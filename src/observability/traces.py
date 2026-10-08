"""Collect one conversation-turn trace from LangChain callback events."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel

from src.observability.log_context import LogContext, set_log_context

SpanKind = Literal["turn", "graph", "node", "chain", "llm", "tool", "retriever"]
SpanStatus = Literal["running", "completed", "error", "interrupted"]
TraceStatus = Literal["running", "completed", "error"]
FinalTraceStatus = Literal["completed", "error"]
_TOOL_RESULT_STATUSES = {"success", "partial", "error"}
_TOOL_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(slots=True)
class TraceSpan:
    """A single timed operation inside a trace; content is intentionally omitted."""

    span_id: str
    parent_span_id: str | None
    name: str
    kind: SpanKind
    started_at: datetime
    status: SpanStatus = "running"
    ended_at: datetime | None = None
    duration_ms: float | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(slots=True)
class TraceRecord:
    """Correlation envelope for one request/turn through the agent graph."""

    trace_id: str
    conversation_id: str
    environment: str
    started_at: datetime
    status: TraceStatus = "running"
    ended_at: datetime | None = None
    duration_ms: float | None = None
    spans: list[TraceSpan] = field(default_factory=list)


class TraceRecorder(BaseCallbackHandler):
    """Collect graph, node, model, tool, and retriever spans for one turn.

    Create one recorder per graph invocation, pass it through RunnableConfig's
    ``callbacks`` field, then call ``finish_trace`` and ``to_document`` after
    the invocation. Callback failures must never break the conversation.
    """

    raise_error = False
    # ContextVar updates must happen in the graph's execution context so log
    # records emitted by a node inherit the span that just started.
    run_inline = True

    def __init__(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        environment: str,
        event_publisher: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        super().__init__()
        self._event_publisher = event_publisher
        now = datetime.now(timezone.utc)
        self._trace = TraceRecord(
            trace_id=trace_id,
            conversation_id=conversation_id,
            environment=environment,
            started_at=now,
        )
        self._lock = RLock()
        self._started_monotonic: dict[str, float] = {}
        self._spans_by_id: dict[str, TraceSpan] = {}

        root_span = TraceSpan(
            span_id=trace_id,
            parent_span_id=None,
            name="conversation.turn",
            kind="turn",
            started_at=now,
        )
        self._trace.spans.append(root_span)
        self._spans_by_id[root_span.span_id] = root_span
        self._started_monotonic[root_span.span_id] = perf_counter()
        self._publish_span_event("started", root_span)

    @property
    def trace_id(self) -> str:
        return self._trace.trace_id

    def finish_trace(self, *, status: FinalTraceStatus) -> None:
        """Close the turn span and mark any callback spans left open as interrupted."""
        finalized_spans: list[TraceSpan] = []
        with self._lock:
            if self._trace.ended_at is not None:
                return

            self._trace.status = status
            self._finish_span_locked(self.trace_id, status=status)
            finalized_spans.append(self._spans_by_id[self.trace_id])
            self._trace.ended_at = self._trace.spans[0].ended_at
            self._trace.duration_ms = self._trace.spans[0].duration_ms

            for span_id, span in self._spans_by_id.items():
                if span_id == self.trace_id or span.ended_at is not None:
                    continue
                self._finish_span_locked(span_id, status="interrupted")
                finalized_spans.append(span)

        for span in finalized_spans:
            self._publish_span_event(span.status, span)

    def to_document(self) -> dict[str, Any]:
        """Return a Mongo-serializable snapshot for the repository layer."""
        with self._lock:
            return asdict(self._trace)

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        safe_metadata = self._safe_metadata(metadata)
        node_name = safe_metadata.get("langgraph_node")
        name = (
            str(node_name) if node_name else self._serialized_name(serialized, "chain")
        )
        kind: SpanKind = (
            "node" if node_name else "graph" if parent_run_id is None else "chain"
        )
        self._start_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            name=name,
            kind=kind,
            metadata=safe_metadata,
        )

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._finish_span(run_id=run_id, status="completed")

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._finish_span(
            run_id=run_id,
            status="error",
            error_type=type(error).__name__,
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        safe_metadata = self._safe_metadata(metadata)
        model = self._model_name(serialized, safe_metadata)
        self._start_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            name=model or "chat_model",
            kind="llm",
            model=model,
            metadata=safe_metadata,
        )

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        safe_metadata = self._safe_metadata(metadata)
        model = self._model_name(serialized, safe_metadata)
        self._start_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            name=model or "llm",
            kind="llm",
            model=model,
            metadata=safe_metadata,
        )

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        input_tokens, output_tokens = self._token_usage(response)
        self._finish_span(
            run_id=run_id,
            status="completed",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._finish_span(
            run_id=run_id,
            status="error",
            error_type=type(error).__name__,
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            name=self._serialized_name(serialized, "tool"),
            kind="tool",
            metadata=self._safe_metadata(metadata),
        )

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            summary = self._tool_result_summary(output)
        except Exception:
            # A malformed tool output must not interfere with the conversation.
            summary = {"tool_status": "success"}
        tool_status = summary.get("tool_status")
        has_error = tool_status == "error"
        self._finish_span(
            run_id=run_id,
            status="error" if has_error else "completed",
            error_type="ToolResultError" if has_error else None,
            span_attributes=summary,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        summary: dict[str, str | int | float | bool] = {"tool_status": "error"}
        try:
            error_code = self._safe_tool_error_code(getattr(error, "code", None))
        except Exception:
            error_code = None
        if error_code is not None:
            summary["tool_error_code"] = error_code
        self._finish_span(
            run_id=run_id,
            status="error",
            error_type=type(error).__name__,
            span_attributes=summary,
        )

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start_span(
            run_id=run_id,
            parent_run_id=parent_run_id,
            name=self._serialized_name(serialized, "retriever"),
            kind="retriever",
            metadata=self._safe_metadata(metadata),
        )

    def on_retriever_end(self, documents: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish_span(run_id=run_id, status="completed")

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._finish_span(
            run_id=run_id,
            status="error",
            error_type=type(error).__name__,
        )

    def _start_span(  # noqa: PLR0913
        self,
        *,
        run_id: UUID,
        parent_run_id: UUID | None,
        name: str,
        kind: SpanKind,
        metadata: dict[str, str | int | float | bool],
        model: str | None = None,
    ) -> None:
        span_id = str(run_id)
        parent_span_id = str(parent_run_id) if parent_run_id else self.trace_id
        with self._lock:
            if span_id in self._spans_by_id:
                return

            attributes = dict(metadata)
            parent_span = self._spans_by_id.get(parent_span_id)
            agent_id = attributes.get("agent_id")
            if not isinstance(agent_id, str) and parent_span is not None:
                agent_id = parent_span.attributes.get("agent_id")
                if isinstance(agent_id, str):
                    attributes["agent_id"] = agent_id

            span = TraceSpan(
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                kind=kind,
                started_at=datetime.now(timezone.utc),
                model=model,
                attributes=attributes,
            )
            self._trace.spans.append(span)
            self._spans_by_id[span_id] = span
            self._started_monotonic[span_id] = perf_counter()

        set_log_context(
            LogContext(
                trace_id=self.trace_id,
                conversation_id=self._trace.conversation_id,
                span_id=span_id,
                agent_id=agent_id if isinstance(agent_id, str) else None,
            )
        )
        self._publish_span_event("started", span)

    def _finish_span(  # noqa: PLR0913
        self,
        *,
        run_id: UUID,
        status: Literal["completed", "error"],
        error_type: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        span_attributes: Mapping[str, str | int | float | bool] | None = None,
    ) -> None:
        with self._lock:
            span_id = str(run_id)
            span = self._spans_by_id.get(span_id)
            if span is None:
                return
            parent_span_id = span.parent_span_id or self.trace_id
            parent_span = self._spans_by_id.get(parent_span_id)
            parent_agent_id = (
                parent_span.attributes.get("agent_id") if parent_span else None
            )
            span.error_type = error_type
            span.input_tokens = input_tokens
            span.output_tokens = output_tokens
            if span_attributes is not None:
                span.attributes.update(
                    self._safe_tool_summary_attributes(span_attributes)
                )
            self._finish_span_locked(span_id, status=status)

        set_log_context(
            LogContext(
                trace_id=self.trace_id,
                conversation_id=self._trace.conversation_id,
                span_id=parent_span_id,
                agent_id=(
                    parent_agent_id if isinstance(parent_agent_id, str) else None
                ),
            )
        )
        self._publish_span_event(status, span)

    def _publish_span_event(self, phase: str, span: TraceSpan) -> None:
        if self._event_publisher is None:
            return
        event_timestamp = span.started_at if phase == "started" else span.ended_at
        try:
            self._event_publisher(
                {
                    "event_type": "span",
                    "phase": phase,
                    "trace_id": self.trace_id,
                    "conversation_id": self._trace.conversation_id,
                    "timestamp": event_timestamp or datetime.now(timezone.utc),
                    "data": {
                        "span_id": span.span_id,
                        "parent_span_id": span.parent_span_id,
                        "name": span.name,
                        "kind": span.kind,
                        "status": span.status,
                        "duration_ms": span.duration_ms,
                        "model": span.model,
                        "input_tokens": span.input_tokens,
                        "output_tokens": span.output_tokens,
                        "error_type": span.error_type,
                        "attributes": dict(span.attributes),
                    },
                }
            )
        except Exception:
            # Live monitoring must never interfere with graph execution.
            return

    def _finish_span_locked(self, span_id: str, *, status: SpanStatus) -> None:
        span = self._spans_by_id.get(span_id)
        started = self._started_monotonic.pop(span_id, None)
        if span is None or started is None or span.ended_at is not None:
            return
        span.ended_at = datetime.now(timezone.utc)
        span.duration_ms = round((perf_counter() - started) * 1000, 3)
        span.status = status

    @staticmethod
    def _safe_metadata(
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, str | int | float | bool]:
        if not isinstance(metadata, Mapping):
            return {}
        allowed_keys = {"langgraph_node", "agent_id", "prompt_version"}
        return {
            key: value
            for key, value in metadata.items()
            if key in allowed_keys and isinstance(value, (str, int, float, bool))
        }

    @staticmethod
    def _serialized_name(serialized: Mapping[str, Any] | None, fallback: str) -> str:
        if not isinstance(serialized, Mapping):
            return fallback
        name = serialized.get("name")
        if isinstance(name, str) and name:
            return name
        identifier = serialized.get("id")
        if isinstance(identifier, (list, tuple)) and identifier:
            identifier = identifier[-1]
        return identifier if isinstance(identifier, str) and identifier else fallback

    @classmethod
    def _model_name(
        cls,
        serialized: Mapping[str, Any] | None,
        metadata: Mapping[str, Any],
    ) -> str | None:
        kwargs = serialized.get("kwargs") if isinstance(serialized, Mapping) else None
        for source in (metadata, kwargs, serialized):
            if not isinstance(source, Mapping):
                continue
            for key in ("ls_model_name", "model_name", "model", "model_id"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _token_usage(response: LLMResult) -> tuple[int | None, int | None]:
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None)
                if isinstance(usage, Mapping):
                    return (
                        TraceRecorder._first_int(
                            usage,
                            ("input_tokens", "prompt_tokens", "prompt_token_count"),
                        ),
                        TraceRecorder._first_int(
                            usage,
                            (
                                "output_tokens",
                                "completion_tokens",
                                "candidates_token_count",
                            ),
                        ),
                    )

        llm_output = response.llm_output
        if isinstance(llm_output, Mapping):
            usage = llm_output.get("token_usage") or llm_output.get("usage")
            if isinstance(usage, Mapping):
                return (
                    TraceRecorder._first_int(
                        usage,
                        ("input_tokens", "prompt_tokens", "prompt_token_count"),
                    ),
                    TraceRecorder._first_int(
                        usage,
                        (
                            "output_tokens",
                            "completion_tokens",
                            "candidates_token_count",
                        ),
                    ),
                )
        return None, None

    @staticmethod
    def _first_int(
        values: Mapping[str, Any],
        keys: tuple[str, ...],
    ) -> int | None:
        for key in keys:
            value = values.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    @classmethod
    def _tool_result_summary(
        cls,
        output: Any,
    ) -> dict[str, str | int | float | bool]:
        """Extract allowlisted aggregates; never copy tool content to a span."""
        payload = cls._tool_output_mapping(output)
        if payload is None:
            return {"tool_status": "success"}

        summary: dict[str, str | int | float | bool] = {}
        status = payload.get("status")
        if isinstance(status, str) and status in _TOOL_RESULT_STATUSES:
            summary["tool_status"] = status

        error = cls._mapping_value(payload.get("error"))
        error_code = cls._safe_tool_error_code(
            error.get("code") if error is not None else payload.get("error_code")
        )
        if error_code is not None:
            summary["tool_error_code"] = error_code
            summary.setdefault("tool_status", "error")

        results_count = cls._tool_results_count(payload)
        if results_count is not None:
            summary["tool_results_count"] = results_count

        evidence_count = cls._tool_evidence_count(payload)
        if evidence_count is not None:
            summary["tool_evidence_count"] = evidence_count

        summary.setdefault("tool_status", "success")
        return cls._safe_tool_summary_attributes(summary)

    @classmethod
    def _tool_output_mapping(cls, output: Any) -> Mapping[str, Any] | None:
        if isinstance(output, Mapping):
            return output
        if isinstance(output, BaseModel):
            dumped = output.model_dump(mode="python")
            return dumped if isinstance(dumped, Mapping) else None
        if isinstance(output, str):
            try:
                decoded = json.loads(output)
            except json.JSONDecodeError, TypeError, ValueError:
                return None
            return decoded if isinstance(decoded, Mapping) else None

        # LangChain may wrap a tool's serialized value in a ToolMessage.
        content = getattr(output, "content", None)
        if content is not None and content is not output:
            return cls._tool_output_mapping(content)
        return None

    @staticmethod
    def _mapping_value(value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, BaseModel):
            dumped = value.model_dump(mode="python")
            return dumped if isinstance(dumped, Mapping) else None
        return None

    @classmethod
    def _tool_results_count(cls, payload: Mapping[str, Any]) -> int | None:
        direct_count = cls._first_sequence_count(
            payload,
            ("results", "resultados"),
        )
        if direct_count is not None:
            return direct_count

        data = cls._mapping_value(payload.get("data"))
        if data is not None:
            nested_count = cls._first_sequence_count(
                data,
                ("results", "candidates", "cards"),
            )
            if nested_count is not None:
                return nested_count
            if cls._mapping_value(data.get("card")) is not None:
                return 1
        return None

    @classmethod
    def _tool_evidence_count(cls, payload: Mapping[str, Any]) -> int | None:
        for key in ("evidence", "evidences", "evidencias"):
            value = payload.get(key)
            if isinstance(value, (list, tuple)):
                return len(value)

        # FAQ's legacy `resultados` array contains only retrieved evidence.
        legacy_results = payload.get("resultados")
        if isinstance(legacy_results, (list, tuple)):
            return len(legacy_results)
        return None

    @staticmethod
    def _first_sequence_count(
        values: Mapping[str, Any],
        keys: tuple[str, ...],
    ) -> int | None:
        for key in keys:
            value = values.get(key)
            if isinstance(value, (list, tuple)):
                return len(value)
        return None

    @staticmethod
    def _safe_tool_error_code(value: Any) -> str | None:
        if (
            isinstance(value, str)
            and _TOOL_ERROR_CODE_PATTERN.fullmatch(value) is not None
        ):
            return value
        return None

    @staticmethod
    def _safe_tool_summary_attributes(
        attributes: Mapping[str, Any],
    ) -> dict[str, str | int | float | bool]:
        safe: dict[str, str | int | float | bool] = {}
        status = attributes.get("tool_status")
        if isinstance(status, str) and status in _TOOL_RESULT_STATUSES:
            safe["tool_status"] = status

        error_code = TraceRecorder._safe_tool_error_code(
            attributes.get("tool_error_code")
        )
        if error_code is not None:
            safe["tool_error_code"] = error_code

        for key in ("tool_results_count", "tool_evidence_count"):
            count = attributes.get(key)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                safe[key] = count

        return safe
