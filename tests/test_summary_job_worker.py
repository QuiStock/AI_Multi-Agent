from __future__ import annotations

from datetime import datetime, timezone

from src.memory.worker.summary_job_worker import RedisSummaryJobWorker


class FakeRedis:
    def __init__(self) -> None:
        self.acks: list[str] = []
        self.requeued: list[dict[str, str]] = []

    def xack(self, stream: str, group: str, entry_id: str) -> None:
        assert stream == "summary-stream"
        assert group == "summary-workers"
        self.acks.append(entry_id)

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        assert stream == "summary-stream"
        self.requeued.append(fields)
        return "2-0"


class FakeJobs:
    def __init__(self, *, claimed: bool = True, retry: bool = False) -> None:
        self.claimed = claimed
        self.retry = retry
        self.processing: list[str] = []
        self.completed: list[str] = []
        self.failed: list[str] = []

    def mark_processing(self, *, job_id: str, updated_at: datetime) -> bool:
        self.processing.append(job_id)
        return self.claimed

    def mark_completed(self, *, job_id: str, updated_at: datetime) -> None:
        self.completed.append(job_id)

    def mark_failed(
        self,
        *,
        job_id: str,
        updated_at: datetime,
        error: str,
        max_attempts: int,
    ) -> str:
        self.failed.append(job_id)
        return "queued" if self.retry else "failed"


class FakeSummaryWorker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def run(self, *, conversation_id: str, user_id: str) -> None:
        self.calls.append((conversation_id, user_id))
        if self.fail:
            raise RuntimeError("summary failed")


def _worker(
    *,
    jobs: FakeJobs,
    summary: FakeSummaryWorker,
    redis: FakeRedis,
) -> RedisSummaryJobWorker:
    return RedisSummaryJobWorker(
        client=redis,  # type: ignore[arg-type]
        stream_name="summary-stream",
        group_name="summary-workers",
        consumer_name="worker-1",
        job_repository=jobs,  # type: ignore[arg-type]
        summary_worker=summary,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc),
    )


def _fields() -> dict[str, str]:
    return {
        "job_id": "job-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
    }


def test_worker_acknowledges_only_after_summary_success() -> None:
    redis = FakeRedis()
    jobs = FakeJobs()
    summary = FakeSummaryWorker()

    _worker(jobs=jobs, summary=summary, redis=redis).process_entry(
        entry_id="1-0",
        fields=_fields(),
    )

    assert summary.calls == [("conversation-1", "user-1")]
    assert jobs.completed == ["job-1"]
    assert redis.acks == ["1-0"]
    assert redis.requeued == []


def test_worker_requeues_retryable_failure_and_acknowledges_original_entry() -> None:
    redis = FakeRedis()
    jobs = FakeJobs(retry=True)
    summary = FakeSummaryWorker(fail=True)

    _worker(jobs=jobs, summary=summary, redis=redis).process_entry(
        entry_id="1-0",
        fields=_fields(),
    )

    assert jobs.failed == ["job-1"]
    assert redis.acks == ["1-0"]
    assert redis.requeued == [_fields()]


def test_worker_acknowledges_duplicate_without_running_summary_again() -> None:
    redis = FakeRedis()
    jobs = FakeJobs(claimed=False)
    summary = FakeSummaryWorker()

    _worker(jobs=jobs, summary=summary, redis=redis).process_entry(
        entry_id="1-0",
        fields=_fields(),
    )

    assert summary.calls == []
    assert redis.acks == ["1-0"]
