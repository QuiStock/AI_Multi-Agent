import json
from dataclasses import asdict
from pathlib import Path

from src.agents.faq.ingestion.state.models import (
    IndexedDocumentState,
    IndexStatus,
    Manifest,
)


class ManifestStore:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path

    def load(self) -> Manifest:
        if not self.manifest_path.exists():
            return Manifest()

        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))

        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Failed to load manifest from {self.manifest_path}: {e}"
            ) from e

        documents: dict[str, IndexedDocumentState] = {}

        for doc_id, doc_data in data.get("documents", {}).items():
            documents[doc_id] = IndexedDocumentState(
                doc_id=doc_id,
                source_hash=doc_data["source_hash"],
                pipeline_version=doc_data["pipeline_version"],
                chunk_count=doc_data["chunk_count"],
                status=IndexStatus(doc_data["status"]),
                indexed_at=doc_data.get("indexed_at"),
                error=doc_data.get("error"),
            )

        return Manifest(
            schema_version=data.get(
                "schema_version",
                1,
            ),
            documents=documents,
        )

    def save(self, manifest: Manifest) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "schema_version": manifest.schema_version,
            "documents": {
                doc_id: asdict(doc_state) | {"status": doc_state.status.value}
                for doc_id, doc_state in manifest.documents.items()
            },
        }

        temporary_path = self.manifest_path.with_suffix(
            self.manifest_path.suffix + ".tmp"
        )

        temporary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        temporary_path.replace(self.manifest_path)
