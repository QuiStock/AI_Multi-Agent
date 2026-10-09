"""Update the API and optional summary worker image in the Infra Deployment."""

from __future__ import annotations

import os
import re
from pathlib import Path

IMAGE_REPOSITORY = "ghcr.io/quistock/ai-multi-agent"
CONTAINER_NAMES = {"api-chatbot", "summary-worker"}


def update_image(path: Path, digest: str) -> None:
    """Validate the expected manifest before writing either container image."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Expected a SHA-256 image digest")
    manifest = path.read_text(encoding="utf-8")
    names = re.findall(r"(?m)^        - name: (\S+)[ \t]*$", manifest)
    if (
        "api-chatbot" not in names
        or len(names) != len(set(names))
        or not set(names) <= CONTAINER_NAMES
        or len(re.findall(r"(?m)^          image:", manifest)) != len(names)
    ):
        raise ValueError("Expected API and optional summary-worker containers")
    pattern = (
        r"(?m)^(        - name: (?:api-chatbot|summary-worker)\n"
        r"          image: )"
        r"(?:ghcr\.io/quistock/ai-multi-agent[:@][^\s]+"
        r"|REPLACE_WITH_CHATBOT_ARM64_IMAGE_DIGEST)$"
    )
    image = f"{IMAGE_REPOSITORY}@{digest}"
    updated, count = re.subn(pattern, lambda match: match.group(1) + image, manifest)
    if count != len(names):
        raise ValueError("Expected one chatbot image per named container")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    update_image(
        Path("infra/clusters/us-east1/apps/api-chatbot/deployment.yaml"),
        os.environ["IMAGE_DIGEST"],
    )


if __name__ == "__main__":
    main()
