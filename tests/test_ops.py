from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient, models

from src import config
from src.agents.faq.ingestion.state.models import Manifest
from src.ops.faq import MongoManifestStore, discover_documents
from src.ops.memory import provision


def test_apply_refuses_existing_memory_without_writes():
    database = MagicMock()
    database.__getitem__.return_value.count_documents.return_value = 1
    settings = config.Settings()
    with QdrantClient(":memory:") as client:
        with pytest.raises(ValueError, match="empty"):
            provision(database, client, settings, vector_size=768, apply=True)
        database.__getitem__.return_value.create_index.assert_not_called()
        assert not client.collection_exists(settings.memory_summary_collection)


def test_dimension_mismatch_stops_before_mongo_writes():
    database = MagicMock()
    database.__getitem__.return_value.count_documents.return_value = 0
    settings = config.Settings()
    with QdrantClient(":memory:") as client:
        client.create_collection(
            settings.memory_summary_collection,
            vectors_config=models.VectorParams(
                size=3072, distance=models.Distance.COSINE
            ),
        )
        with pytest.raises(ValueError, match="dimension"):
            provision(database, client, settings, vector_size=768, apply=True)
        database.__getitem__.return_value.create_index.assert_not_called()


def test_check_does_not_create_missing_collections():
    database = MagicMock()
    database.__getitem__.return_value.count_documents.return_value = 0
    settings = config.Settings()
    with QdrantClient(":memory:") as client:
        report = provision(database, client, settings, vector_size=768, apply=False)
        assert report["qdrant_count"] == 0
        assert not client.collection_exists(settings.memory_summary_collection)
        database.__getitem__.return_value.create_index.assert_not_called()


def test_faq_manifest_survives_job_filesystem_replacement(tmp_path: Path):
    collection = MagicMock()
    collection.find_one.return_value = None
    first = MongoManifestStore(tmp_path / "first.json", collection, "faq")
    first.save(Manifest(audience_policy_version="synthetic-policy"))
    saved = collection.update_one.call_args.args[1]["$set"]
    collection.find_one.return_value = saved
    restored = MongoManifestStore(tmp_path / "second.json", collection, "faq").load()
    assert restored.audience_policy_version == "synthetic-policy"


def test_empty_faq_is_not_interpreted_as_delete_all(tmp_path: Path):
    with pytest.raises(ValueError, match="No FAQ"):
        discover_documents(tmp_path)
