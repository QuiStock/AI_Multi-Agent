from __future__ import annotations

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from src.models import get_chat_model

from .tools.faq_tool import faq_search

SYSTEM_PROMPT = """Você é o assistente de FAQ da instituição.
Sua única fonte de informação é a ferramenta faq_search, que consulta a base
de conhecimento. Responda em português, com base APENAS nos trechos retornados.
Se a informação não estiver nos documentos, diga que não encontrou e sugira
entrar em contato com o suporte. Cite a fonte (arquivo) sempre que possível."""


def create_faq_agent() -> CompiledStateGraph:
    model = get_chat_model()
    return create_agent(model, tools=[faq_search], system_prompt=SYSTEM_PROMPT)


faq_app = create_faq_agent
