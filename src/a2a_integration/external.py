"""One configured A2A peer, with an in-process mock for development."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from a2a.types import a2a_pb2
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from langchain_core.messages import HumanMessage

from src.config import Settings
from src.graphs.state import Evidence, GraphState

logger = logging.getLogger(__name__)
PEER_ID = "truck_info_agent"
SKILL_ID = "truck_specs"


class ExternalA2AError(RuntimeError):
    """The configured peer cannot provide a usable direct message."""


class ExternalA2AExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _mock_reply(self, context_id: str) -> a2a_pb2.Message:
        return a2a_pb2.Message(
            message_id=str(uuid4()),
            context_id=context_id,
            role=a2a_pb2.ROLE_AGENT,
            parts=[
                a2a_pb2.Part(
                    text=(
                        "Resposta simulada do sistema de caminhões: o catálogo "
                        "definitivo ainda não está conectado. Não há dado "
                        "técnico verificado para esta consulta."
                    )
                )
            ],
        )

    def _remote_reply(
        self, question: str, context_id: str, message_id: str
    ) -> a2a_pb2.Message:
        card_url = self.settings.a2a_truck_card_url
        endpoint = self.settings.a2a_truck_endpoint_url
        token = self.settings.a2a_truck_service_token
        if not card_url or not endpoint or not token:
            raise ExternalA2AError("Peer A2A não configurado")
        if self.settings.app_environment == "production" and any(
            urlparse(url).scheme != "https" for url in (card_url, endpoint)
        ):
            raise ExternalA2AError("Peer A2A de produção exige HTTPS")

        with httpx.Client(
            timeout=self.settings.a2a_timeout_seconds, follow_redirects=False
        ) as client:
            card_response = client.get(card_url)
            card_response.raise_for_status()
            card = ParseDict(card_response.json(), a2a_pb2.AgentCard())
            if not any(
                interface.protocol_binding == "HTTP+JSON"
                and interface.protocol_version.startswith("1.0")
                and interface.url.rstrip("/") == endpoint.rstrip("/")
                for interface in card.supported_interfaces
            ):
                raise ExternalA2AError("Interface A2A não autorizada")
            if not any(skill.id == SKILL_ID for skill in card.skills):
                raise ExternalA2AError("Skill A2A não anunciada")

            request = a2a_pb2.SendMessageRequest(
                message=a2a_pb2.Message(
                    message_id=message_id,
                    context_id=context_id,
                    role=a2a_pb2.ROLE_USER,
                    parts=[a2a_pb2.Part(text=question)],
                )
            )
            response = client.post(
                f"{endpoint.rstrip('/')}/message:send",
                json=MessageToDict(request),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/a2a+json",
                    "Accept": "application/a2a+json",
                    "A2A-Version": "1.0",
                },
            )
            response.raise_for_status()
            parsed = ParseDict(response.json(), a2a_pb2.SendMessageResponse())
            if parsed.WhichOneof("payload") != "message":
                raise ExternalA2AError("O peer retornou uma Task não suportada")
            return parsed.message

    def invoke(self, state: GraphState) -> dict[str, Any]:
        decision = state.get("routing_decision", {})
        if decision.get("peer_id") != PEER_ID or decision.get("skill_id") != SKILL_ID:
            return {"error_code": "A2A_PEER_NOT_ALLOWED"}
        question = next(
            (
                message.content
                for message in reversed(state.get("messages", []))
                if isinstance(message, HumanMessage)
                and isinstance(message.content, str)
            ),
            "",
        ).strip()
        if not question:
            return {"error_code": "A2A_EMPTY_MESSAGE"}
        request = state.get("request", {})
        context_id = request.get("conversation_id", "")
        message_id = request.get("request_id", "")

        try:
            if self.settings.a2a_truck_mode == "mock":
                if self.settings.app_environment == "production":
                    raise ExternalA2AError("Mock A2A desabilitado em produção")
                reply = self._mock_reply(context_id)
            else:
                reply = self._remote_reply(question, context_id, message_id)
            if reply.role != a2a_pb2.ROLE_AGENT or not reply.message_id:
                raise ExternalA2AError("Mensagem A2A inválida")
            answer = "\n".join(
                part.text
                for part in reply.parts
                if part.WhichOneof("content") == "text"
            ).strip()
            if not answer:
                raise ExternalA2AError("Resposta A2A sem texto")
        except ExternalA2AError, httpx.HTTPError, ParseError, ValueError, KeyError:
            logger.warning("external_a2a_unavailable", extra={"peer_id": PEER_ID})
            return {"error_code": "A2A_PEER_UNAVAILABLE"}

        evidence: Evidence = {
            "evidence_id": f"a2a:{PEER_ID}:{reply.message_id}",
            "source_type": "a2a_agent",
            "source_id": reply.message_id,
            "content": answer,
            "metadata": {
                "peer_id": PEER_ID,
                "skill_id": SKILL_ID,
                "trust_level": "peer_assertion",
                "mock": str(self.settings.a2a_truck_mode == "mock").lower(),
            },
        }
        return {
            "answer": f"Segundo o sistema externo de caminhões: {answer}",
            "evidences": [evidence],
        }
