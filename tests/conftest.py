from collections.abc import Iterator
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import pytest


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Use per-test directories compatible with the local OneDrive checkout."""

    root = Path.cwd() / "tmp" / "pytest-fixtures"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid4().hex
    directory.mkdir()

    try:
        yield directory
    finally:
        rmtree(directory, ignore_errors=True)
