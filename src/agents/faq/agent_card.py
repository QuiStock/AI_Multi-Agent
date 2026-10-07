from __future__ import annotations

from collections.abc import Sequence

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from src.models import get_chat_model

SYSTEM_PROMPT = """Você é o assistente de FAQ da instituição.
Sua única fonte de informação são as ferramentas de FAQ, que consultam a base
de conhecimento. Responda em português, com base APENAS nos trechos retornados.
Se a informação não estiver nos documentos, diga que não encontrou e sugira
entrar em contato com o suporte. Cite a fonte (arquivo) sempre que possível."""


def create_faq_agent(
    tools: Sequence[BaseTool] | None = None,
) -> CompiledStateGraph:
    model = get_chat_model()
    return create_agent(model, tools=list(tools or []), system_prompt=SYSTEM_PROMPT)


faq_app = create_faq_agent
