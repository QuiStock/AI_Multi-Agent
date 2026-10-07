from pathlib import Path

import pytest

from src.agents.faq.ingestion.audience import audience_for_path


def test_audience_is_resolved_from_the_first_directory() -> None:
    root = Path("/faq/docs")

    assert audience_for_path(root, root / "shared" / "policy.md") == "shared"
    assert audience_for_path(root, root / "employee" / "triage.md") == "employee"
    assert audience_for_path(root, root / "manager" / "approval.md") == "manager"


@pytest.mark.parametrize(
    "relative_path",
    [
        "policy.md",
        "unknown/policy.md",
    ],
)
def test_unknown_audience_paths_are_rejected(relative_path: str) -> None:
    root = Path("/faq/docs")

    with pytest.raises(ValueError):
        audience_for_path(root, root / relative_path)
