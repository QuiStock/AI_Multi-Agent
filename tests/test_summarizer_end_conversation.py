import json
from datetime import datetime, timezone
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.memory.contracts import (
    ConversationSummarySnapshot,
    StoredMessage,
    SummaryCommit,
)
from src.memory.mongo_repository import SummaryUpdateConflictError
from src.memory.worker.summarizer_end_conversation import (
    EndConversationSummaryWorker,
    LLMSummaryUpdater,
)
from src.memory.worker.title_generator import LLMConversationTitleGenerator


def _message(message_id: str, role: str, content: str) -> StoredMessage:
    return StoredMessage(
        message_id=message_id,
        role=role,
        content=content,
        created_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )


def _snapshot(
    *,
    messages: list[StoredMessage],
    summary: str | None = None,
    version: int = 0,
    marker: str | None = None,
    status: str = "active",
    title: str | None = None,
) -> ConversationSummarySnapshot:
    return ConversationSummarySnapshot(
        conversation_id="conversation-1",
        user_id="user-1",
        title=title,
        status=status,
        summary=summary,
        summary_version=version,
        summarized_through_message_id=marker,
        messages=messages,
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )


class FakeRepository:
    def __init__(self, snapshot: ConversationSummarySnapshot) -> None:
        self.snapshot = snapshot
        self.commits: list[tuple[str, str, int]] = []

    def mark_ended(
        self, *, conversation_id: str, user_id: str, ended_at: datetime
    ) -> None:
        assert conversation_id == self.snapshot.conversation_id
        assert user_id == self.snapshot.user_id
        self.snapshot = self.snapshot.model_copy(update={"status": "ended"})

    def get_summary_snapshot(
        self, *, conversation_id: str, user_id: str
    ) -> ConversationSummarySnapshot:
        assert conversation_id == self.snapshot.conversation_id
        assert user_id == self.snapshot.user_id
        return self.snapshot

    def save_summary_if_current(self, commit: SummaryCommit) -> bool:
        if (
            self.snapshot.status != "ended"
            or self.snapshot.summary_version != commit.expected_summary_version
            or self.snapshot.summarized_through_message_id != commit.expected_message_id
        ):
            return False
        self.snapshot = self.snapshot.model_copy(
            update={
                "summary": commit.summary,
                "summary_version": commit.expected_summary_version + 1,
                "summarized_through_message_id": commit.summarized_through_message_id,
            }
        )
        self.commits.append(
            (
                commit.summary,
                commit.summarized_through_message_id,
                commit.expected_summary_version + 1,
            )
        )
        return True

    def save_title_if_missing(
        self,
        *,
        conversation_id: str,
        user_id: str,
        expected_summary_version: int,
        title: str,
    ) -> bool:
        if (
            self.snapshot.conversation_id != conversation_id
            or self.snapshot.user_id != user_id
            or self.snapshot.status != "ended"
            or self.snapshot.summary_version != expected_summary_version
            or self.snapshot.title is not None
        ):
            return False
        self.snapshot = self.snapshot.model_copy(update={"title": title})
        return True


class FakeSummaryUpdater:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, list[StoredMessage]]] = []

    def update(
        self,
        *,
        previous_summary: str | None,
        messages: list[StoredMessage],
    ) -> str:
        self.calls.append((previous_summary, list(messages)))
        return f"summary-{len(self.calls)}"


class FakeTitleGenerator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.summaries: list[str] = []

    def generate(self, *, summary: str) -> str:
        self.summaries.append(summary)
        if self.fail:
            raise RuntimeError("title service unavailable")
        return "Generated title"


class FakeIndexer:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.snapshots: list[ConversationSummarySnapshot] = []

    def upsert(self, snapshot: ConversationSummarySnapshot) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary qdrant failure")
        self.snapshots.append(snapshot)


def _worker(
    repository: FakeRepository,
    updater: FakeSummaryUpdater,
    indexer: FakeIndexer,
    title_generator: FakeTitleGenerator | None = None,
) -> EndConversationSummaryWorker:
    return EndConversationSummaryWorker(
        repository=repository,  # type: ignore[arg-type]
        summary_updater=updater,
        summary_indexer=indexer,
        title_generator=title_generator or FakeTitleGenerator(),
        clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc),
    )


def test_first_close_summarizes_the_full_message_history() -> None:
    messages = [
        _message("m1", "user", "Question"),
        _message("m2", "assistant", "Answer"),
    ]
    repository = FakeRepository(_snapshot(messages=messages))
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer()
    title_generator = FakeTitleGenerator()

    result = _worker(repository, updater, indexer, title_generator).run(
        user_id="user-1",
        conversation_id="conversation-1",
    )

    assert updater.calls == [(None, messages)]
    assert result.summary == "summary-1"
    assert result.summary_version == 1
    assert result.summarized_through_message_id == "m2"
    assert result.title == "Generated title"
    assert title_generator.summaries == ["summary-1"]
    assert len(indexer.snapshots) == 1


def test_reopened_close_updates_only_messages_after_the_marker() -> None:
    messages = [
        _message("m1", "user", "Earlier question"),
        _message("m2", "assistant", "Earlier answer"),
        _message("m3", "user", "New question"),
        _message("m4", "assistant", "New answer"),
    ]
    repository = FakeRepository(
        _snapshot(
            messages=messages,
            title="Existing title",
            summary="previous summary",
            version=3,
            marker="m2",
        )
    )
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer()

    result = _worker(repository, updater, indexer).run(
        user_id="user-1",
        conversation_id="conversation-1",
    )

    assert updater.calls == [("previous summary", messages[2:])]
    assert result.summary == "summary-1"
    assert result.summary_version == 4
    assert result.summarized_through_message_id == "m4"
    assert result.title == "Existing title"


def test_retry_after_index_failure_reuses_saved_summary_without_regenerating() -> None:
    messages = [_message("m1", "user", "Question")]
    repository = FakeRepository(_snapshot(messages=messages))
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer(fail_once=True)
    worker = _worker(repository, updater, indexer)

    with pytest.raises(RuntimeError, match="qdrant"):
        worker.run(user_id="user-1", conversation_id="conversation-1")

    result = worker.run(user_id="user-1", conversation_id="conversation-1")

    assert len(updater.calls) == 1
    assert result.title == "Generated title"
    assert len(repository.commits) == 1
    assert result.summary == "summary-1"
    assert result.summary_version == 1
    assert len(indexer.snapshots) == 1


def test_missing_summary_marker_does_not_resummarize_old_messages() -> None:
    repository = FakeRepository(
        _snapshot(
            messages=[_message("m1", "user", "Question")],
            summary="previous summary",
            version=1,
            marker="deleted-message",
        )
    )
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer()

    with pytest.raises(ValueError, match="marcador"):
        _worker(repository, updater, indexer).run(
            user_id="user-1",
            conversation_id="conversation-1",
        )

    assert updater.calls == []
    assert indexer.snapshots == []


def test_summary_commit_conflict_does_not_index_uncommitted_summary() -> None:
    repository = FakeRepository(
        _snapshot(messages=[_message("m1", "user", "Question")])
    )
    repository.save_summary_if_current = lambda _: False  # type: ignore[method-assign]
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer()

    with pytest.raises(SummaryUpdateConflictError):
        _worker(repository, updater, indexer).run(
            user_id="user-1",
            conversation_id="conversation-1",
        )

    assert len(updater.calls) == 1
    assert indexer.snapshots == []


class FakeStructuredModel:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def invoke(self, messages: list[Any]) -> dict[str, str]:
        human_message = messages[-1]
        assert isinstance(human_message, HumanMessage)
        self.requests.append(json.loads(str(human_message.content)))
        return {"summary": "updated summary"}


class FakeTitleStructuredModel:
    def __init__(self) -> None:
        self.request: dict[str, str] | None = None

    def invoke(self, messages: list[Any]) -> dict[str, str]:
        human_message = messages[-1]
        assert isinstance(human_message, HumanMessage)
        self.request = json.loads(str(human_message.content))
        return {"title": "  Assunto da conversa  "}


def test_llm_updater_supports_initial_and_incremental_modes() -> None:
    model = FakeStructuredModel()
    updater = LLMSummaryUpdater(model=model)
    messages = [_message("m1", "user", "Question")]

    updater.update(previous_summary=None, messages=messages)
    updater.update(previous_summary="previous summary", messages=messages)

    assert model.requests[0]["mode"] == "initial"
    assert model.requests[0]["previous_summary"] is None
    assert model.requests[1]["mode"] == "incremental"
    assert model.requests[1]["previous_summary"] == "previous summary"
    assert model.requests[1]["messages"] == [{"role": "user", "content": "Question"}]


def test_title_generator_uses_summary_and_returns_trimmed_title() -> None:
    model = FakeTitleStructuredModel()
    generator = LLMConversationTitleGenerator(model=model)

    title = generator.generate(summary="Resumo da conversa")

    assert title == "Assunto da conversa"
    assert model.request == {"summary": "Resumo da conversa"}


def test_title_generation_failure_does_not_block_summary_indexing() -> None:
    repository = FakeRepository(
        _snapshot(messages=[_message("m1", "user", "Question")])
    )
    updater = FakeSummaryUpdater()
    indexer = FakeIndexer()
    title_generator = FakeTitleGenerator(fail=True)

    result = _worker(repository, updater, indexer, title_generator).run(
        user_id="user-1",
        conversation_id="conversation-1",
    )

    assert result.summary == "summary-1"
    assert result.title is None
    assert len(indexer.snapshots) == 1
