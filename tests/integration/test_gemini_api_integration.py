import os
from typing import Any

import pytest

from src.agents.faq.agent_card import create_faq_agent
from src.models import get_embeddings

pytestmark = pytest.mark.integration

REQUIRES_API_KEY = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="GEMINI_API_KEY nao configurada",
)


@REQUIRES_API_KEY
def test_real_embeddings_index_and_search(pipeline: Any, docs_dir: Any) -> None:
    store = pipeline.ensure(docs_dir, embeddings=get_embeddings())
    assert store is not None
    hits = store.similarity_search("regra de negocio", k=4)
    assert len(hits) >= 1


@REQUIRES_API_KEY
def test_agent_invocation_end_to_end(pipeline: Any, docs_dir: Any) -> None:
    pipeline.point_to(docs_dir)
    agent = create_faq_agent()
    response = agent.invoke(
        {"messages": [{"role": "user", "content": "Qual a regra de negocio do FAQ?"}]}
    )
    answer = response["messages"][-1].content
    assert isinstance(answer, str)
    assert answer.strip()
