import os

import pytest

from src.models.gemini import get_embeddings

pytestmark = pytest.mark.integration

REQUIRES_API_KEY = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="GEMINI_API_KEY nao configurada",
)


@REQUIRES_API_KEY
def test_real_embeddings_can_embed_a_query() -> None:
    vector = get_embeddings().embed_query("regra de negocio")

    assert vector
    assert all(isinstance(value, float) for value in vector)


