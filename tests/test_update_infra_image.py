"""Deployment releases update both processes without partially writing a file."""

from pathlib import Path

import pytest

from scripts.update_infra_image import update_image

DIGEST = "sha256:" + "a" * 64
REPOSITORY = "ghcr.io/quistock/ai-multi-agent"


def manifest(*, worker: bool = True) -> str:
    value = (
        "apiVersion: apps/v1\nkind: Deployment\nspec:\n"
        "  template:\n    spec:\n      containers:\n"
        "        - name: api-chatbot\n"
        f"          image: {REPOSITORY}:v0.2.0\n"
        "          ports:\n            - name: http\n"
        "              containerPort: 8000\n"
    )
    if worker:
        value += (
            "        - name: summary-worker\n"
            f"          image: {REPOSITORY}@sha256:{'b' * 64}\n"
            '          command: ["python", "-m", '
            '"src.memory.worker.run_summary_worker"]\n'
        )
    return value


@pytest.mark.parametrize("worker", [False, True])
def test_release_updates_all_processes_and_preserves_other_configuration(
    tmp_path: Path, worker: bool
) -> None:
    path = tmp_path / "deployment.yaml"
    original = manifest(worker=worker)
    path.write_text(original, encoding="utf-8")
    update_image(path, DIGEST)
    expected = original.replace(f"{REPOSITORY}:v0.2.0", f"{REPOSITORY}@{DIGEST}")
    expected = expected.replace(f"sha256:{'b' * 64}", DIGEST)
    assert path.read_text(encoding="utf-8") == expected


def test_initial_placeholder_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "deployment.yaml"
    path.write_text(
        manifest(worker=False).replace(
            f"{REPOSITORY}:v0.2.0", "REPLACE_WITH_CHATBOT_ARM64_IMAGE_DIGEST"
        ),
        encoding="utf-8",
    )
    update_image(path, DIGEST)
    assert f"image: {REPOSITORY}@{DIGEST}" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("digest", ["latest", "sha256:abc", "sha256:" + "A" * 64])
def test_invalid_digest_does_not_write_manifest(tmp_path: Path, digest: str) -> None:
    path = tmp_path / "deployment.yaml"
    path.write_text(manifest(), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="SHA-256"):
        update_image(path, digest)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "invalid",
    [
        manifest().replace("summary-worker", "unrelated-worker"),
        manifest().replace("summary-worker", "api-chatbot"),
        manifest().replace("api-chatbot", "unrelated-api"),
        manifest().replace(f"{REPOSITORY}@", "ghcr.io/other/worker@"),
        manifest().replace("          image:", "          unexpected:"),
        manifest().replace("        - name: summary-worker\n", ""),
    ],
)
def test_unexpected_manifest_does_not_partially_update_api(
    tmp_path: Path, invalid: str
) -> None:
    path = tmp_path / "deployment.yaml"
    path.write_text(invalid, encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        update_image(path, DIGEST)
    assert path.read_bytes() == original
