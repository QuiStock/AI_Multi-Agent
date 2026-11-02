"""Check memory storage; provision only new, empty collections with --apply."""

from __future__ import annotations

import argparse
import json
from typing import Any

from pymongo import MongoClient
from qdrant_client import QdrantClient, models

from src import config
from src.memory.collection_names import validate_collection_names
from src.memory.jobs.summary_job_repository import MongoSummaryJobRepository
from src.memory.summaries.qdrant_summary_indexer import ensure_summary_payload_indexes


def check_vector_collection(client: QdrantClient, name: str, size: int) -> int:
    if size < 1:
        raise ValueError("vector size must be positive")
    if not client.collection_exists(name):
        return 0
    vectors = client.get_collection(name).config.params.vectors
    if not isinstance(vectors, models.VectorParams) or vectors.size != size:
        raise ValueError("Existing vector dimension does not match; migrate separately")
    return int(client.count(name, exact=True).count)


def provision(
    database: Any,
    client: QdrantClient,
    settings: config.Settings,
    *,
    vector_size: int,
    apply: bool,
) -> dict[str, Any]:
    names = [
        settings.memory_conversations_collection,
        settings.memory_summary_jobs_collection,
        settings.memory_summary_locks_collection,
    ]
    validate_collection_names(names)
    counts = {name: int(database[name].count_documents({})) for name in names}
    point_count = check_vector_collection(
        client, settings.memory_summary_collection, vector_size
    )
    # Inspect all targets before performing any write.
    if apply and (any(counts.values()) or point_count):
        raise ValueError("Apply is only allowed for empty memory collections")
    if apply:
        for name in names:
            database[name].create_index(
                [("email", 1), ("status", 1), ("updated_at", -1)],
                name="ix_memory_owner_status_updated",
            )
        MongoSummaryJobRepository(
            database[settings.memory_summary_jobs_collection],
            max_attempts=settings.summary_job_max_attempts,
        ).ensure_indexes()
        if not client.collection_exists(settings.memory_summary_collection):
            client.create_collection(
                settings.memory_summary_collection,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )
        ensure_summary_payload_indexes(client, settings.memory_summary_collection)
    return {
        "mode": "apply" if apply else "check",
        "mongo_counts": counts,
        "qdrant_count": point_count,
        "vector_size": vector_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--vector-size", required=True, type=int)
    args = parser.parse_args()
    settings = config.get_settings()
    if not settings.mongodb_uri or not settings.mongodb_db:
        parser.error("MONGODB_URI and MONGODB_DB are required")
    mongo: MongoClient[Any] = MongoClient(settings.mongodb_uri)
    client = config.create_qdrant_client(settings)
    try:
        report = provision(
            mongo[settings.mongodb_db],
            client,
            settings,
            vector_size=args.vector_size,
            apply=args.apply,
        )
        print(json.dumps(report))
    finally:
        client.close()
        mongo.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print connection strings, tokens or upstream response bodies.
        raise SystemExit(f"Memory operation failed ({type(error).__name__})") from None
