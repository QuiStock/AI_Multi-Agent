import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.agents.faq.ingestion.state.models import IndexStatus, Manifest


class ChangeStatus(str, Enum):
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    DELETED = "deleted"
    NEW = "new"


@dataclass(frozen=True)
class FileSnapshot:
    doc_id: str
    path: Path
    source_hash: str


@dataclass(frozen=True)
class DetectedChange:
    status: ChangeStatus
    doc_id: str
    path: Path | None = None
    source_hash: str | None = None


class ChangeDetector:
    def detect(
        self,
        root: Path,
        files: list[Path],
        manifest: Manifest,
        pipeline_version: str,
    ) -> list[DetectedChange]:
        changes: list[DetectedChange] = []

        # Create a set of current document IDs from the manifest
        current_doc_ids: set[str] = set()

        for file_path in files:
            doc_id = str(file_path.relative_to(root).as_posix())
            source_hash = self.calculate_hash(file_path)

            current_doc_ids.add(doc_id)

            previous_state = manifest.documents.get(doc_id)

            if previous_state is None:
                changes.append(
                    DetectedChange(
                        status=ChangeStatus.NEW,
                        doc_id=doc_id,
                        path=file_path,
                        source_hash=source_hash,
                    )
                )
                continue

            source_changed = previous_state.source_hash != source_hash

            pipeline_changed = previous_state.pipeline_version != pipeline_version

            previous_failed = previous_state.status == IndexStatus.FAILED

            if source_changed or pipeline_changed or previous_failed:
                status = ChangeStatus.MODIFIED
            else:
                status = ChangeStatus.UNCHANGED

            changes.append(
                DetectedChange(
                    status=status,
                    doc_id=doc_id,
                    path=file_path,
                    source_hash=source_hash,
                )
            )
        changes.extend(
            DetectedChange(
                status=ChangeStatus.DELETED,
                doc_id=doc_id,
            )
            for doc_id in manifest.documents
            if doc_id not in current_doc_ids
        )
        return changes

    @staticmethod
    def calculate_hash(file_path: Path, block_size: int = 1024 * 1024) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as f:
            while chunk := f.read(block_size):
                hasher.update(chunk)
        return hasher.hexdigest()
