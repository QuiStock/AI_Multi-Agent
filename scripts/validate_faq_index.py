from __future__ import annotations

from collections import Counter
from typing import Any

from qdrant_client import QdrantClient

from src import config
from src.agents.faq.ingestion.audience import VALID_AUDIENCES


def validate_collection(
    client: QdrantClient,
    collection_name: str,
) -> dict[str, int]:
    """Validate audience payloads before switching the active collection."""
    if not client.collection_exists(collection_name):
        raise RuntimeError(f"A collection FAQ não existe: {collection_name}")

    collection_info = client.get_collection(collection_name)
    payload_schema = getattr(collection_info, "payload_schema", {})
    if "audience" not in payload_schema:
        raise RuntimeError("A collection não possui índice payload para audience.")

    counts: Counter[str] = Counter()
    offset: Any = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=offset,
            with_payload=["audience"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            audience = payload.get("audience")
            if audience not in VALID_AUDIENCES:
                raise RuntimeError("A collection contém ponto sem audiência válida.")
            counts[str(audience)] += 1

        if offset is None:
            break

    return dict(counts)


def main() -> None:
    settings = config.get_settings()
    client = config.create_qdrant_client(settings)
    counts = validate_collection(
        client,
        settings.faq_vectorstore_collection,
    )
    print(f"FAQ validada: collection={settings.faq_vectorstore_collection}")
    print(f"pontos_por_audiencia={counts}")


if __name__ == "__main__":
    main()
