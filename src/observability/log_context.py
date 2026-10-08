"""Context propagated from an active trace/span to Python log records."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogContext:
    trace_id: str
    conversation_id: str
    span_id: str
    agent_id: str | None = None


_CURRENT_LOG_CONTEXT: ContextVar[LogContext | None] = ContextVar(
    "observability_log_context",
    default=None,
)


def get_log_context() -> LogContext | None:
    return _CURRENT_LOG_CONTEXT.get()


def set_log_context(context: LogContext) -> None:
    _CURRENT_LOG_CONTEXT.set(context)


@contextmanager
def bind_trace_context(
    *,
    trace_id: str,
    conversation_id: str,
) -> Iterator[None]:
    token: Token[LogContext | None] = _CURRENT_LOG_CONTEXT.set(
        LogContext(
            trace_id=trace_id,
            conversation_id=conversation_id,
            span_id=trace_id,
        )
    )
    try:
        yield
    finally:
        _CURRENT_LOG_CONTEXT.reset(token)
