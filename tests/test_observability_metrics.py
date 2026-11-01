from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import inf, nan

import pytest

from src import config
from src.api.schemas.observability import (
    ApplicationCostMetricsResponse,
    CumulativeCostSeriesPointResponse,
    LatencySeriesPointResponse,
    ObservabilityMetricsBoardResponse,
    ObservabilityMetricsResponse,
    TraceDetailResponse,
)
from src.api.services.observability_service import ObservabilityService
from src.config import Settings
from src.observability.metrics import (
    ModelPricing,
    _distribution,
    _number,
    _rate,
    _text,
    _token_count,
    calculate_application_cost,
    calculate_cost_projections,
    calculate_metrics,
    calculate_slo_metrics,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
PRICING = {"gpt-6-luna": ModelPricing(0.10, 0.50)}


def test_model_pricing_rejects_negative_and_non_finite_rates() -> None:
    for rate in (-0.01, inf, nan):
        with pytest.raises(ValueError, match="preços"):
            ModelPricing(rate, 0.5)


def test_calculate_metrics_aggregates_latency_usage_costs_fallbacks_and_tools() -> None:
    traces = [
        {
            "status": "completed",
            "duration_ms": None,
            "fallback_used": True,
            "spans": [
                {"kind": "turn", "duration_ms": 120},
                {
                    "kind": "llm",
                    "name": "answer",
                    "model": "gpt-6-luna",
                    "status": "completed",
                    "duration_ms": 80,
                    "input_tokens": 1_000,
                    "output_tokens": 100,
                },
                {
                    "kind": "tool",
                    "name": "lookup",
                    "status": "error",
                    "duration_ms": 20,
                },
                None,
            ],
        },
        {
            "status": "error",
            "duration_ms": 200,
            "fallback_used": False,
            "spans": [
                {
                    "kind": "llm",
                    "model": "unpriced-model",
                    "status": "error",
                    "duration_ms": 30,
                    "input_tokens": 50,
                    "output_tokens": None,
                },
                {
                    "kind": "retriever",
                    "name": "faq",
                    "status": "completed",
                    "duration_ms": True,
                },
            ],
        },
    ]

    result = calculate_metrics(traces, model_pricing=PRICING)

    assert result["traces"] == {
        "count": 2,
        "completed_count": 1,
        "error_count": 1,
        "error_rate": 0.5,
        "latency": {
            "sample_count": 2,
            "average_ms": 160.0,
            "p95_ms": 200.0,
            "max_ms": 200.0,
        },
    }
    assert result["spans"] == {
        "count": 4,
        "error_count": 2,
        "error_rate": 0.5,
    }
    assert result["models"]["gpt-6-luna"]["estimated_cost_usd"] == 0.00015
    assert result["models"]["gpt-6-luna"]["calls_with_complete_usage"] == 1
    assert result["models"]["unpriced-model"]["calls_with_partial_usage"] == 1
    assert result["models"]["unpriced-model"]["estimated_cost_usd"] is None
    assert result["components"]["tool:lookup"]["error_count"] == 1
    assert result["components"]["retriever:faq"]["latency"]["sample_count"] == 0
    assert result["cost"]["estimated_total_usd"] is None
    assert result["cost"]["priced_calls"] == 1
    assert result["cost"]["unpriced_calls"] == 1
    assert result["cost"]["cost_per_completed_trace_usd"] == 0.00015
    assert result["fallback"] == {
        "qwen_call_count": 0,
        "qwen_trace_count": 0,
        "rate": 0.0,
    }


def test_metrics_handle_missing_spans_invalid_values_and_no_samples() -> None:
    result = calculate_metrics(
        [
            {"status": "running", "duration_ms": True, "spans": None},
            {
                "status": "completed",
                "spans": [
                    {"kind": "turn", "duration_ms": inf},
                    {
                        "kind": "llm",
                        "model": "",
                        "status": "running",
                        "input_tokens": True,
                        "output_tokens": "unknown",
                    },
                ],
            },
        ]
    )

    assert result["traces"]["latency"]["sample_count"] == 0
    assert result["traces"]["latency"]["average_ms"] is None
    assert result["spans"]["error_rate"] == 0.0
    assert result["tokens"]["input_tokens"] is None
    assert result["tokens"]["output_tokens"] is None
    assert result["models"]["unknown"]["calls_without_usage"] == 1
    assert result["fallback"]["qwen_call_count"] == 0
    assert result["fallback"]["rate"] == 0.0

    empty = calculate_metrics([])
    assert empty["traces"]["error_rate"] is None
    assert empty["cost"]["estimated_total_usd"] == 0.0
    assert empty["cost"]["cost_per_completed_trace_usd"] is None


def test_metrics_build_daily_board_and_time_series_from_traces() -> None:
    result = calculate_metrics(
        [
            {
                "started_at": datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
                "status": "completed",
                "duration_ms": 100,
                "spans": [
                    {
                        "kind": "llm",
                        "model": "gpt-6-luna",
                        "status": "completed",
                        "input_tokens": 100,
                        "output_tokens": 20,
                    },
                    {
                        "kind": "node",
                        "name": "router",
                        "status": "completed",
                        "duration_ms": 40,
                    },
                ],
            },
            {
                "started_at": datetime(2026, 10, 8, 18, tzinfo=timezone.utc),
                "status": "completed",
                "duration_ms": 300,
                "spans": [
                    {
                        "kind": "llm",
                        "model": "gpt-6-luna",
                        "status": "completed",
                        "input_tokens": 200,
                        "output_tokens": 20,
                    },
                    {
                        "kind": "node",
                        "name": "router",
                        "status": "completed",
                        "duration_ms": 60,
                    },
                ],
            },
            {
                "started_at": datetime(2026, 10, 9, 1, tzinfo=timezone.utc),
                "status": "error",
                "duration_ms": 21_000,
                "spans": [],
            },
        ],
        model_pricing=PRICING,
    )

    assert result["board"] == {
        "slo_ok": False,
        "most_used_model": "gpt-6-luna",
        "agent_latency": [{"name": "router", "average_ms": 50.0}],
    }
    assert result["latency_series"] == [
        {"date": datetime(2026, 10, 8).date(), "duration_ms": 200.0, "sample_count": 2},
        {
            "date": datetime(2026, 10, 9).date(),
            "duration_ms": 21_000.0,
            "sample_count": 1,
        },
    ]
    assert result["cumulative_cost_series"] == [
        {"date": datetime(2026, 10, 8).date(), "cumulative_cost_usd": 0.00005},
        {"date": datetime(2026, 10, 9).date(), "cumulative_cost_usd": 0.00005},
    ]
    ObservabilityMetricsBoardResponse.model_validate(result["board"])
    for point in result["latency_series"]:
        LatencySeriesPointResponse.model_validate(point)
    for point in result["cumulative_cost_series"]:
        CumulativeCostSeriesPointResponse.model_validate(point)


def test_board_reports_no_data_and_does_not_mark_missing_durations_as_good() -> None:
    empty = calculate_metrics([])
    assert empty["board"]["slo_ok"] is None
    assert empty["latency_series"] == []
    assert empty["cumulative_cost_series"] == []

    missing_duration = calculate_metrics(
        [
            {
                "started_at": NOW,
                "status": "completed",
                "duration_ms": None,
                "spans": [],
            }
        ]
    )
    assert missing_duration["board"]["slo_ok"] is False
    assert missing_duration["latency_series"] == [
        {"date": NOW.date(), "duration_ms": None, "sample_count": 0}
    ]


def test_qwen_fallback_counts_model_calls_and_turns() -> None:
    result = calculate_metrics(
        [
            {
                "status": "completed",
                "spans": [
                    {
                        "kind": "llm",
                        "model": "qwen/qwen3.8-27b",
                        "status": "completed",
                        "input_tokens": 1000,
                        "output_tokens": 100,
                    },
                    {
                        "kind": "llm",
                        "model": "qwen/qwen3.8-27b",
                        "status": "error",
                        "input_tokens": 1000,
                        "output_tokens": 100,
                    },
                    {"kind": "llm", "model": "gpt-6-luna", "status": "completed"},
                ],
            },
            {
                "status": "completed",
                "spans": [
                    {"kind": "llm", "model": "gpt-6-luna", "status": "completed"},
                ],
            },
        ],
        model_pricing={
            "qwen/qwen3.8-27b": ModelPricing(0.80, 4.00),
        },
    )

    assert result["fallback"] == {
        "qwen_call_count": 2,
        "qwen_trace_count": 1,
        "rate": 0.5,
    }
    assert result["models"]["qwen/qwen3.8-27b"]["estimated_cost_usd"] == 0.0024


def test_slo_metrics_count_missing_durations_as_bad_and_group_model_results() -> None:
    result = calculate_slo_metrics(
        [
            {
                "status": "completed",
                "duration_ms": 10_000,
                "spans": [
                    {"kind": "llm", "model": "gpt-6-luna", "status": "completed"},
                ],
            },
            {
                "status": "error",
                "spans": [
                    {"kind": "llm", "model": "gpt-6-luna", "status": "error"},
                    {"kind": "llm", "model": "", "status": "running"},
                    "invalid span",
                ],
            },
            {"status": "completed", "duration_ms": 20_001, "spans": []},
            {"status": "running", "duration_ms": 1},
        ],
        window_started_at=NOW,
        window_ended_at=NOW,
        environment="production",
    )

    assert result["window"]["environment"] == "production"
    assert result["window"]["duration_days"] == 0
    assert result["period_slo_ok"] is False
    assert result["turn_completion"]["good_count"] == 2
    assert result["turn_completion"]["bad_count"] == 1
    assert result["turn_latency"]["good_count"] == 1
    assert result["turn_latency"]["bad_count"] == 2
    assert result["turn_latency"]["p95_ms"] == 20_001
    assert result["turn_latency"]["status"] == "breached"
    assert result["models"]["gpt-6-luna"]["good_count"] == 1
    assert result["models"]["gpt-6-luna"]["bad_count"] == 1
    assert result["models"]["unknown"]["total_count"] == 0


def test_completion_slo_accepts_exactly_five_percent_errors() -> None:
    traces = [
        {
            "trace_id": f"trace-{index}",
            "status": "error" if index == 0 else "completed",
            "duration_ms": 1_000,
            "spans": [],
        }
        for index in range(20)
    ]

    result = calculate_slo_metrics(
        traces,
        window_started_at=NOW,
        window_ended_at=NOW,
        environment=None,
    )

    assert result["turn_completion"]["target_rate"] == 0.95
    assert result["turn_completion"]["actual_rate"] == 0.95
    assert result["turn_completion"]["status"] == "met"
    assert result["period_slo_ok"] is True


def test_slo_model_success_includes_jev_usage_events() -> None:
    result = calculate_slo_metrics(
        [
            {
                "trace_id": "trace-ok",
                "status": "completed",
                "duration_ms": 1_000,
                "spans": [],
            },
            {
                "trace_id": "trace-error",
                "status": "error",
                "duration_ms": 1_000,
                "spans": [],
            },
            {
                "trace_id": "trace-running",
                "status": "running",
                "duration_ms": 1_000,
                "spans": [],
            },
        ],
        usage_events=[
            {
                "source": "judge_jev",
                "trace_id": "trace-ok",
                "model": "jev-latest",
                "status": "completed",
            },
            {
                "source": "judge_jev",
                "trace_id": "trace-error",
                "model": "jev-latest",
                "status": "error",
            },
            {
                "source": "lab",
                "trace_id": "trace-ok",
                "model": "jev-latest",
                "status": "completed",
            },
            {
                "source": "judge_jev",
                "trace_id": "trace-running",
                "model": "jev-latest",
                "status": "completed",
            },
        ],
        window_started_at=NOW,
        window_ended_at=NOW,
        environment=None,
    )

    assert result["models"]["jev-latest"]["good_count"] == 1
    assert result["models"]["jev-latest"]["bad_count"] == 1
    assert result["models"]["jev-latest"]["target_rate"] == 0.95

    empty = calculate_slo_metrics(
        [],
        window_started_at=NOW,
        window_ended_at=NOW,
        environment=None,
    )
    assert empty["turn_completion"]["status"] == "no_data"
    assert empty["turn_latency"]["p95_ms"] is None
    assert empty["period_slo_ok"] is None
    assert empty["models"] == {}


def test_application_cost_splits_sources_and_marks_incomplete_costs() -> None:
    result = calculate_application_cost(
        [
            {
                "spans": [
                    {
                        "kind": "llm",
                        "model": "gpt-6-luna",
                        "status": "completed",
                        "input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                    },
                    {"kind": "tool", "name": "lookup"},
                ]
            },
            {"spans": "invalid"},
        ],
        [
            {
                "source": "lab",
                "model": "gpt-6-luna",
                "status": "completed",
                "input_tokens": 10,
                "output_tokens": 2,
            },
            {
                "source": "faq_embedding_index",
                "model": "gemini-embedding",
                "status": "completed",
                "input_tokens": 500,
                "output_tokens": 0,
            },
            {
                "source": "memory_embedding_query",
                "model": "other-model",
                "status": "error",
                "input_tokens": 20,
                "output_tokens": None,
            },
            {
                "source": "summary_generation",
                "model": "unknown",
                "status": "error",
                "input_tokens": None,
                "output_tokens": None,
            },
            {"source": "unknown-source", "model": "ignored"},
            {
                "source": "agent_turn",
                "model": "gpt-6-luna",
                "input_tokens": 99,
                "output_tokens": 99,
            },
        ],
        model_pricing=PRICING,
        embedding_model="gemini-embedding",
        embedding_input_usd_per_million_tokens=0,
        embedding_tier="free",
    )

    assert result["embedding_tier"] == "free"
    assert result["conversation_count"] == 0
    assert result["resolution_count"] == 0
    assert result["priced_calls"] == 3
    assert result["unpriced_calls"] == 2
    assert result["estimated_total_usd"] is None
    origins = {origin["source"]: origin for origin in result["origins"]}
    assert set(origins) == {
        "agent_turn",
        "faq_embedding_index",
        "lab",
        "memory_embedding_query",
        "summary_generation",
    }
    assert origins["agent_turn"]["estimated_cost_usd"] == 0.6
    assert origins["faq_embedding_index"]["estimated_cost_usd"] == 0.0
    assert origins["memory_embedding_query"]["estimated_cost_usd"] is None
    assert origins["summary_generation"]["calls_without_usage"] == 1
    assert origins["summary_generation"]["calls_missing_both"] == 1
    assert result["conversation_variable_cost_usd"] == 0
    assert result["operational_cost_usd"] is None


def test_cost_projection_uses_observed_conversations_and_no_error_turns() -> None:
    traces = [
        {
            "conversation_id": "conversation-1",
            "status": "completed",
            "logs": [
                {
                    "event": "router_decision_completed",
                    "attributes": {"route": "faq"},
                },
                {
                    "event": "conversation_turn_completed",
                    "attributes": {"status": "success"},
                },
            ],
            "spans": [
                {
                    "kind": "llm",
                    "model": "gpt-6-luna",
                    "status": "completed",
                    "input_tokens": 100,
                    "output_tokens": 0,
                }
            ],
        },
        {
            "conversation_id": "conversation-2",
            "status": "completed",
            "logs": [
                {
                    "event": "router_decision_completed",
                    "attributes": {"route": "clarification_required"},
                },
                {
                    "event": "conversation_turn_completed",
                    "attributes": {"status": "clarification_required"},
                },
            ],
            "spans": [
                {
                    "kind": "llm",
                    "model": "gpt-6-luna",
                    "status": "completed",
                    "input_tokens": 100,
                    "output_tokens": 0,
                }
            ],
        },
        {
            "conversation_id": "conversation-2",
            "status": "completed",
            "logs": [
                {
                    "event": "conversation_turn_completed",
                    "attributes": {"status": "rejected"},
                }
            ],
            "spans": [],
        },
        {
            "conversation_id": "conversation-3",
            "status": "error",
            "logs": [
                {
                    "event": "conversation_turn_completed",
                    "attributes": {"status": "error"},
                }
            ],
            "spans": [],
        },
    ]
    application_cost = calculate_application_cost(
        traces,
        [],
        model_pricing=PRICING,
        embedding_model="gemini-embedding",
        embedding_input_usd_per_million_tokens=0,
        embedding_tier="free",
    )

    assert application_cost["estimated_total_usd"] == 0.00002
    assert application_cost["conversation_count"] == 3
    assert application_cost["resolution_count"] == 3
    projections = calculate_cost_projections(
        conversation_variable_cost_usd=application_cost[
            "conversation_variable_cost_usd"
        ],
        conversation_count=application_cost["conversation_count"],
        resolution_count=application_cost["resolution_count"],
    )
    assert projections["conversation_count"] == 3
    assert projections["resolution_count"] == 3
    assert projections["cost_per_conversation_usd"] == 0.00000667
    assert projections["cost_per_resolution_usd"] == 0.00000667
    assert projections["weekly_cost_100_users_usd"] == pytest.approx(
        0.0033333333333333335
    )
    assert projections["weekly_cost_1000_users_usd"] == pytest.approx(
        0.03333333333333333
    )
    assert projections["weekly_cost_1000_users_usd"] == pytest.approx(
        projections["weekly_cost_100_users_usd"] * 10
    )
    ObservabilityMetricsBoardResponse.model_validate(
        {
            "slo_ok": True,
            "most_used_model": "gpt-6-luna",
            "agent_latency": [],
            **projections,
        }
    )
    ApplicationCostMetricsResponse.model_validate(
        {
            **application_cost,
            "coverage_start_at": NOW,
            "coverage_complete": True,
        }
    )

    incomplete = calculate_cost_projections(
        conversation_variable_cost_usd=None,
        conversation_count=3,
        resolution_count=1,
    )
    assert incomplete["cost_per_resolution_usd"] is None
    assert incomplete["cost_per_conversation_usd"] is None
    assert incomplete["weekly_cost_100_users_usd"] is None
    assert incomplete["weekly_cost_1000_users_usd"] is None


def test_observability_service_populates_the_complete_cost_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = {
        "trace_id": "trace-1",
        "conversation_id": "conversation-1",
        "started_at": NOW,
        "status": "completed",
        "duration_ms": 250,
        "logs": [
            {
                "event": "router_decision_completed",
                "attributes": {"route": "faq"},
            },
            {
                "event": "conversation_turn_completed",
                "attributes": {"status": "success"},
            },
        ],
        "spans": [
            {
                "kind": "turn",
                "status": "completed",
                "duration_ms": 250,
            },
            {
                "kind": "llm",
                "model": "gpt-6-luna",
                "status": "completed",
                "input_tokens": 100,
                "output_tokens": 0,
            },
            {
                "kind": "llm",
                "name": "Judge JEV",
                "model": "jev-resolved-version",
                "status": "completed",
                "input_tokens": 1_000,
                "output_tokens": 12,
                "duration_ms": 82.0,
                "attributes": {"usage_source": "judge_jev"},
            },
        ],
    }

    class TraceSource:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def iter_traces(
            self, *, started_from: datetime, started_to: datetime, **filters: object
        ) -> list[dict[str, object]]:
            self.calls.append(
                {
                    "started_from": started_from,
                    "started_to": started_to,
                    **filters,
                }
            )
            return [trace] if started_from <= trace["started_at"] <= started_to else []

    class UsageSource:
        def iter_usage(
            self, *, started_from: datetime, started_to: datetime
        ) -> list[dict[str, object]]:
            event = {
                "source": "judge_jev",
                "model": "jev-resolved-version",
                "status": "completed",
                "input_tokens": 1_000,
                "output_tokens": 12,
                "trace_id": "trace-1",
                "conversation_id": "conversation-1",
                "duration_ms": 82.0,
                "timestamp": NOW,
            }
            return [event] if started_from <= event["timestamp"] <= started_to else []

        def get_metering_started_at(self) -> datetime:
            return NOW - timedelta(days=1)

    monkeypatch.setattr(config, "OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: Settings(
            gemini_embedding_model="gemini-embedding",
            gemini_embedding_tier="free",
            typesafe_jev_model="jev-latest",
        ),
    )
    trace_source = TraceSource()

    class ConversationSource:
        def list_conversation_ids_for_email(self, *, email: str) -> list[str]:
            assert email == "operator@example.test"
            return ["conversation-1"]

    service = ObservabilityService(
        trace_source,  # type: ignore[arg-type]
        ConversationSource(),  # type: ignore[arg-type]
        UsageSource(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(ObservabilityService, "_utc_now", staticmethod(lambda: NOW))

    result = service.calculate_metrics(started_from=NOW, started_to=NOW)
    other_period = service.calculate_metrics(
        started_from=NOW - timedelta(hours=12),
        started_to=NOW - timedelta(hours=1),
    )
    filtered_period = service.calculate_metrics(
        started_from=NOW - timedelta(days=2),
        started_to=NOW,
        consumer_id="operator@example.test",
        conversation_id="conversation-1",
        environment="qa",
        status="error",
    )

    assert result["board"]["conversation_count"] == 1
    assert result["board"]["resolution_count"] == 1
    assert result["board"]["cost_per_conversation_usd"] == 0.000052
    assert result["board"]["cost_per_resolution_usd"] == 0.000052
    assert result["board"]["projection_window_days"] == 1
    assert result["board"]["weekly_cost_100_users_usd"] == pytest.approx(0.026)
    assert result["board"]["weekly_cost_1000_users_usd"] == pytest.approx(0.26)
    assert other_period["board"]["cost_per_conversation_usd"] == 0.000052
    assert other_period["board"]["weekly_cost_100_users_usd"] == pytest.approx(0.026)
    assert other_period["board"]["weekly_cost_1000_users_usd"] == pytest.approx(0.26)
    assert result["board"]["slo_ok"] is True
    assert other_period["board"]["slo_ok"] is None
    assert other_period["slos"]["turn_completion"]["status"] == "no_data"
    assert filtered_period["slos"]["window"]["started_at"] == NOW - timedelta(days=2)
    assert filtered_period["slos"]["window"]["ended_at"] == NOW
    assert filtered_period["slos"]["window"]["duration_days"] == 2
    assert filtered_period["slos"]["window"]["environment"] == "qa"
    assert filtered_period["slos"]["period_slo_ok"] is True
    slo_query = trace_source.calls[-1]
    assert slo_query["conversation_id"] == "conversation-1"
    assert slo_query["conversation_ids"] == ["conversation-1"]
    assert slo_query["environment"] == "qa"
    assert "status" not in slo_query
    assert result["models"]["jev-resolved-version"]["calls"] == 1
    assert result["models"]["jev-resolved-version"]["latency"]["average_ms"] == 82.0
    assert result["models"]["jev-resolved-version"]["estimated_cost_usd"] == 0.000042
    assert result["slos"]["models"]["jev-resolved-version"]["good_count"] == 1
    assert result["application_cost"]["origins"][-1]["source"] == "judge_jev"
    assert result["application_cost"]["coverage_complete"] is True
    ObservabilityMetricsResponse.model_validate(result)


def test_trace_detail_adds_span_cost_only_when_usage_is_available(monkeypatch) -> None:
    monkeypatch.setattr(config, "OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: Settings(
            gemini_embedding_model="gemini-embedding",
            gemini_embedding_tier="free",
            typesafe_jev_model="jev-latest",
        ),
    )

    trace = {
        "trace_id": "trace-1",
        "conversation_id": "conversation-1",
        "environment": "qa",
        "started_at": NOW,
        "status": "completed",
        "duration_ms": 150,
        "spans": [
            {
                "span_id": "llm-1",
                "name": "chat completion",
                "kind": "llm",
                "model": "gpt-6-luna",
                "status": "completed",
                "started_at": NOW,
                "duration_ms": 100,
                "input_tokens": 1_000,
                "output_tokens": 100,
            },
            {
                "span_id": "node-1",
                "name": "router",
                "kind": "node",
                "status": "completed",
                "started_at": NOW,
                "duration_ms": 50,
            },
        ],
        "logs": [],
    }

    class TraceSource:
        def get_trace(self, trace_id: str) -> dict[str, object] | None:
            assert trace_id == "trace-1"
            return trace

    class UsageSource:
        def iter_trace_usage(self, trace_id: str) -> list[dict[str, object]]:
            assert trace_id == "trace-1"
            return [
                {
                    "source": "judge_jev",
                    "model": "jev-latest",
                    "status": "completed",
                    "input_tokens": 1_000,
                    "output_tokens": 8,
                    "timestamp": NOW,
                    "duration_ms": 75,
                }
            ]

    service = ObservabilityService(
        TraceSource(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        UsageSource(),  # type: ignore[arg-type]
    )

    result = service.get_trace(trace_id="trace-1")

    assert result is not None
    assert result["spans"][0]["estimated_cost_usd"] == 0.00015
    assert "estimated_cost_usd" not in result["spans"][1]
    assert result["usage_events"][0]["source"] == "judge_jev"
    assert result["usage_events"][0]["estimated_cost_usd"] == 0.000042
    validated = TraceDetailResponse.model_validate(result)
    assert validated.spans[1].input_tokens is None
    assert validated.spans[1].estimated_cost_usd is None
    assert len(validated.usage_events) == 1


def test_metric_helpers_validate_and_calculate_edges() -> None:
    assert _distribution([])["max_ms"] is None
    assert _distribution([1, 2, 100]) == {
        "sample_count": 3,
        "average_ms": 34.333,
        "p95_ms": 100.0,
        "max_ms": 100.0,
    }
    assert _rate(1, 0) is None
    assert _number(True) is None
    assert _number(inf) is None
    assert _number(-1) is None
    assert _number(1.5) == 1.5
    assert _token_count(True) is None
    assert _token_count(-1) is None
    assert _token_count(4) == 4
    assert _text("  ", "fallback") == "fallback"
    assert _text(" model ", "fallback") == "model"
