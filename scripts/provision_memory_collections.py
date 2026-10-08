"""Provision new, empty memory collections without deleting existing data."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from pymongo import MongoClient
from qdrant_client import QdrantClient, models

from src import config
from src.memory.summary_job_repository import MongoSummaryJobRepository


def validate_collection_names(names: Sequence[str]) -> None:
    if any(not name.strip() for name in names):
        raise ValueError("Todos os nomes de coleção são obrigatórios")
    if len(set(names)) != len(names):
        raise ValueError("As coleções MongoDB precisam ter nomes distintos")


def ensure_mongo_collection(database: Any, name: str, *, apply: bool) -> int:
    collection = database[name]
    count = int(collection.count_documents({}))
    if apply and count != 0:
        raise RuntimeError(f"A coleção MongoDB não está vazia: {name}")
    if apply:
        collection.create_index(
            [("email", 1), ("status", 1), ("updated_at", -1)],
            name="ix_memory_owner_status_updated",
        )
    return count


def ensure_qdrant_collection(
    client: QdrantClient,
    name: str,
    *,
    vector_size: int,
    apply: bool,
) -> int:
    if vector_size < 1:
        raise ValueError("vector_size precisa ser positivo")
    created = False
    if not client.collection_exists(name):
        if apply:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            created = True
        else:
            return 0
    count = 0 if created else client.count(collection_name=name, exact=True).count
    if apply and count != 0:
        raise RuntimeError(f"A coleção Qdrant não está vazia: {name}")
    if apply:
        for field_name, field_schema in (
            ("email", models.PayloadSchemaType.KEYWORD),
            ("conversation_id", models.PayloadSchemaType.KEYWORD),
            ("memory_type", models.PayloadSchemaType.KEYWORD),
            ("updated_at", models.PayloadSchemaType.DATETIME),
        ):
            client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--vector-size", type=int, required=True)
    args = parser.parse_args()

    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        raise RuntimeError("MONGODB_URI e MONGODB_DB são obrigatórios")
    if not settings.qdrant_url or not settings.qdrant_api_key:
        raise RuntimeError("QDRANT_URL e QDRANT_API_KEY são obrigatórios")

    mongo_names = (
        settings.memory_conversations_collection,
        settings.memory_summary_jobs_collection,
        settings.memory_summary_locks_collection,
    )
    validate_collection_names(mongo_names)
    apply = bool(args.apply)

    mongo_client: MongoClient[Any] = MongoClient(settings.mongodb_uri)
    qdrant_client = config.create_qdrant_client(settings)
    try:
        database = mongo_client[settings.mongodb_db]
        mongo_counts = {
            name: ensure_mongo_collection(database, name, apply=apply)
            for name in mongo_names
        }
        if apply:
            MongoSummaryJobRepository(
                database[settings.memory_summary_jobs_collection],
                max_attempts=settings.summary_job_max_attempts,
            ).ensure_indexes()
        qdrant_count = ensure_qdrant_collection(
            qdrant_client,
            settings.memory_summary_collection,
            vector_size=args.vector_size,
            apply=apply,
        )
        print(
            {
                "mode": "apply" if apply else "check",
                "mongo_counts": mongo_counts,
                "qdrant_count": qdrant_count,
                "qdrant_collection": settings.memory_summary_collection,
            }
        )
    finally:
        qdrant_client.close()
        mongo_client.close()


if __name__ == "__main__":
    main()
