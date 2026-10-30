"""Checks for Mongo memory collection names."""


def validate_collection_names(names: list[str]) -> None:
    """Require collection names to be distinct and non-empty."""
    if any(not name for name in names):
        raise ValueError("collection names must be non-empty")
    if len(names) != len(set(names)):
        raise ValueError("collection names must be distinct")
