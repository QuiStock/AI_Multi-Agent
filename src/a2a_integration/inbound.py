"""Authenticated synchronous A2A facade over the existing conversation service."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any

from a2a.types import a2a_pb2
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from src import config
from src.agents.product_workflow.filters import MANAGER_ROLE_ID
from src.api.controllers.conversation_controller import ConversationController
from src.api.dependencies import (
    get_conversation_controller,
    get_mongo_client,
    get_postgres_pool,
)
from src.api.errors import InputRejectedError
from src.api.schemas.conversation import ConversationRequest

router = APIRouter(tags=["a2a"])


@dataclass(frozen=True, slots=True)
class A2APrincipal:
    client_id: str
    store_id: int
    external_user_id: str
    email: str
    role_id: int = MANAGER_ROLE_ID


def _bearer(value: str | None) -> str:
    if not value or not value.startswith("Bearer ") or not value[7:].strip():
        raise HTTPException(status_code=401, detail="Credencial A2A inválida")
    return value[7:].strip()


def get_a2a_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_quistock_store_id: Annotated[str | None, Header()] = None,
    x_external_user_id: Annotated[str | None, Header()] = None,
) -> A2APrincipal:
    settings = config.get_settings()
    if (
        not settings.a2a_inbound_service_token
        or not settings.a2a_context_secret
        or settings.a2a_inbound_store_id is None
        or not settings.a2a_inbound_client_id
    ):
        raise HTTPException(status_code=503, detail="A2A não configurado")
    token = _bearer(authorization)
    if not hmac.compare_digest(token, settings.a2a_inbound_service_token):
        raise HTTPException(status_code=401, detail="Credencial A2A inválida")

    if not x_quistock_store_id or not re.fullmatch(r"[0-9]{1,10}", x_quistock_store_id):
        raise HTTPException(status_code=422, detail="store_id A2A inválido")
    store_id = int(x_quistock_store_id)
    if store_id < 1 or store_id > 2_147_483_647:
        raise HTTPException(status_code=422, detail="store_id A2A inválido")
    if store_id != settings.a2a_inbound_store_id:
        raise HTTPException(status_code=403, detail="Loja não autorizada")

    external_user_id = (x_external_user_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", external_user_id):
        raise HTTPException(status_code=422, detail="Identificador externo inválido")

    try:
        pool = get_postgres_pool(request)
        with pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{int(settings.postgres_pool_timeout_seconds * 1000)}ms",),
            )
            cursor.execute(
                "SELECT 1 FROM store WHERE id = %s AND status::text = 'ACTIVE' LIMIT 1",
                (store_id,),
            )
            store_exists = cursor.fetchone() is not None
    except Exception:
        raise HTTPException(status_code=503, detail="Loja indisponível") from None
    if not store_exists:
        raise HTTPException(status_code=403, detail="Loja não autorizada")

    client_id = settings.a2a_inbound_client_id
    identity = _opaque_id("principal", client_id, str(store_id), external_user_id)
    return A2APrincipal(
        client_id=client_id,
        store_id=store_id,
        external_user_id=external_user_id,
        email=f"a2a-{identity[:40]}@integration.invalid",
    )


def get_a2a_response_store() -> Collection[dict[str, Any]]:
    settings = config.get_settings()
    if not settings.mongodb_db:
        raise RuntimeError("MONGODB_DB é obrigatório")
    return get_mongo_client()[settings.mongodb_db][settings.a2a_responses_collection]


def _opaque_id(*parts: str) -> str:
    secret = config.get_settings().a2a_context_secret
    if not secret:
        raise HTTPException(status_code=503, detail="A2A não configurado")
    digest = hmac.new(
        secret.encode("utf-8"),
        "\x00".join(parts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _agent_card() -> a2a_pb2.AgentCard:
    settings = config.get_settings()
    return a2a_pb2.AgentCard(
        name="Quistock",
        description=(
            "Assistente de FAQ e consultas comerciais autorizadas. "
            "Envie X-Quistock-Store-Id e X-External-User-Id em cada mensagem."
        ),
        version="0.1.0",
        supported_interfaces=[
            a2a_pb2.AgentInterface(
                url=settings.a2a_public_url.rstrip("/"),
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
            )
        ],
        capabilities=a2a_pb2.AgentCapabilities(
            streaming=False, push_notifications=False
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            a2a_pb2.AgentSkill(
                id="faq",
                name="FAQ",
                description="Perguntas sobre documentos Quistock",
                tags=["faq"],
            ),
            a2a_pb2.AgentSkill(
                id="product_flow",
                name="Product workflow",
                description=(
                    "Consultas comerciais da loja autorizada para o cliente A2A"
                ),
                tags=["products"],
            ),
            a2a_pb2.AgentSkill(
                id="truck_information",
                name="Truck information",
                description="Consulta simulada de informações sobre caminhões",
                tags=["trucks"],
            ),
        ],
        security_schemes={
            "serviceBearer": a2a_pb2.SecurityScheme(
                http_auth_security_scheme=a2a_pb2.HTTPAuthSecurityScheme(
                    scheme="bearer"
                )
            )
        },
        security_requirements=[
            a2a_pb2.SecurityRequirement(schemes={"serviceBearer": a2a_pb2.StringList()})
        ],
    )


@router.get("/.well-known/agent-card.json")
def agent_card() -> JSONResponse:
    return JSONResponse(content=MessageToDict(_agent_card()))


@router.post("/a2a/message:send")
def send_message(
    request_body: dict[str, Any],
    principal: Annotated[A2APrincipal, Depends(get_a2a_principal)],
    controller: Annotated[ConversationController, Depends(get_conversation_controller)],
    store: Annotated[Collection[dict[str, Any]], Depends(get_a2a_response_store)],
    a2a_version: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    if a2a_version and not a2a_version.startswith("1.0"):
        raise HTTPException(status_code=400, detail="Versão A2A não suportada")
    try:
        envelope = ParseDict(request_body, a2a_pb2.SendMessageRequest())
    except ParseError:
        raise HTTPException(status_code=422, detail="Envelope A2A inválido") from None
    message = envelope.message
    if message.role != a2a_pb2.ROLE_USER or not message.message_id or message.task_id:
        raise HTTPException(status_code=422, detail="Message A2A inválida")
    if not message.parts or any(
        part.WhichOneof("content") != "text" for part in message.parts
    ):
        raise HTTPException(
            status_code=422, detail="Apenas partes de texto são aceitas"
        )
    text = "\n".join(part.text for part in message.parts).strip()
    if not text or len(text) > 4_000:
        raise HTTPException(
            status_code=422, detail="Mensagem deve ter até 4000 caracteres"
        )
    client_id = principal.client_id
    context_id = (
        message.context_id
        or _opaque_id(
            "new-context",
            client_id,
            str(principal.store_id),
            principal.email,
            message.message_id,
        )[:32]
    )
    if len(context_id) > 128 or len(message.message_id) > 128:
        raise HTTPException(status_code=422, detail="Identificador A2A muito longo")

    conversation_id = _opaque_id(
        "context", client_id, str(principal.store_id), principal.email, context_id
    )
    request_id = _opaque_id(
        "message",
        client_id,
        str(principal.store_id),
        principal.email,
        context_id,
        message.message_id,
    )
    payload_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    try:
        store.insert_one(
            {
                "_id": request_id,
                "payload_hash": payload_hash,
                "status": "processing",
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        prior = store.find_one({"_id": request_id})
        if not prior or prior.get("payload_hash") != payload_hash:
            raise HTTPException(
                status_code=409, detail="messageId já usado com outro conteúdo"
            ) from None
        if prior.get("status") == "completed":
            return JSONResponse(
                content=prior["response"], media_type="application/a2a+json"
            )
        raise HTTPException(
            status_code=409,
            detail="Mensagem A2A em processamento",
            headers={"Retry-After": "2"},
        ) from None

    try:
        try:
            result = controller.converse(
                conversation_id=conversation_id,
                request=ConversationRequest(
                    message=text,
                    sent_at=datetime.now(timezone.utc),
                ),
                email=principal.email,
                role_id=principal.role_id,
                request_id=request_id,
                a2a_store_id=principal.store_id,
            )
        except InputRejectedError as exc:
            result = exc.response
        response_message = a2a_pb2.Message(
            message_id=f"{request_id}:reply",
            context_id=context_id,
            role=a2a_pb2.ROLE_AGENT,
            parts=[a2a_pb2.Part(text=result.response)],
        )
        response = MessageToDict(a2a_pb2.SendMessageResponse(message=response_message))
        store.update_one(
            {"_id": request_id, "status": "processing"},
            {"$set": {"status": "completed", "response": response}},
        )
        return JSONResponse(content=response, media_type="application/a2a+json")
    except Exception:
        store.delete_one({"_id": request_id, "status": "processing"})
        raise
