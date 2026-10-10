"""Authenticated synchronous A2A facade over the existing conversation service."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated, Any

import jwt
from a2a.types import a2a_pb2
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from src import config
from src.api.controllers.conversation_controller import ConversationController
from src.api.dependencies import (
    get_conversation_controller,
    get_mongo_client,
    get_postgres_pool,
)
from src.api.errors import InputRejectedError
from src.api.schemas.conversation import ConversationRequest
from src.auth.account_repository import PostgresAccountRepository
from src.auth.errors import (
    AccountLookupError,
    AuthenticationConfigurationError,
    InvalidCredentialError,
)
from src.auth.models import AuthenticatedPrincipal
from src.auth.service import AuthenticationService
from src.auth.token import JWTEmailDecoder

router = APIRouter(tags=["a2a"])


def _bearer(value: str | None) -> str:
    if not value or not value.startswith("Bearer ") or not value[7:].strip():
        raise HTTPException(status_code=401, detail="Credencial A2A inválida")
    return value[7:].strip()


def get_a2a_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_quistock_user_authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedPrincipal:
    settings = config.get_settings()
    if not settings.a2a_inbound_service_token or not settings.a2a_context_secret:
        raise HTTPException(status_code=503, detail="A2A não configurado")
    token = _bearer(authorization)
    if not hmac.compare_digest(token, settings.a2a_inbound_service_token):
        raise HTTPException(status_code=401, detail="Credencial A2A inválida")
    user_token = _bearer(x_quistock_user_authorization)
    try:
        if not settings.jwt_secret:
            raise AuthenticationConfigurationError("JWT secret is not configured")
        jwt.decode(
            user_token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["email", "exp"], "verify_aud": False},
        )
        service = AuthenticationService(
            JWTEmailDecoder(settings.jwt_secret),
            PostgresAccountRepository(
                get_postgres_pool(request),
                statement_timeout_ms=int(settings.postgres_pool_timeout_seconds * 1000),
            ),
        )
        return service.authenticate(user_token)
    except (
        InvalidCredentialError,
        AuthenticationConfigurationError,
        jwt.InvalidTokenError,
    ):
        raise HTTPException(status_code=401, detail="Delegação inválida") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Acesso não permitido") from None
    except AccountLookupError:
        raise HTTPException(status_code=503, detail="Identidade indisponível") from None


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
        description="Assistente de FAQ e consultas comerciais autorizadas.",
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
                description="Consultas comerciais no escopo do usuário delegado",
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
    principal: Annotated[AuthenticatedPrincipal, Depends(get_a2a_principal)],
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
    client_id = config.get_settings().a2a_inbound_client_id
    context_id = message.context_id or _opaque_id(
        "new-context", client_id, principal.email, message.message_id
    )[:32]
    if len(context_id) > 128 or len(message.message_id) > 128:
        raise HTTPException(status_code=422, detail="Identificador A2A muito longo")

    conversation_id = _opaque_id("context", client_id, principal.email, context_id)
    request_id = _opaque_id(
        "message", client_id, principal.email, context_id, message.message_id
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
