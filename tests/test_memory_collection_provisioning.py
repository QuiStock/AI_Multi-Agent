import pytest

from scripts.provision_memory_collections import validate_collection_names


def test_collection_names_must_be_distinct_and_non_empty() -> None:
    validate_collection_names(["conversations", "jobs", "locks"])

    with pytest.raises(ValueError):
        validate_collection_names(["conversations", "conversations"])

    with pytest.raises(ValueError):
        validate_collection_names(["", "jobs"])
