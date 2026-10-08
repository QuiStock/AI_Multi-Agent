from __future__ import annotations

from datetime import datetime, timezone
from math import inf, nan

import pytest

from src.observability.metrics import (
    ModelPricing,
    _distribution,
    _number,
    _rate,
    _text,
    _token_count,
    calculate_application_cost,
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
        "observed_trace_count": 1,
        "trace_signal_count": 2,
        "signal_coverage": 1.0,
        "rate": 0.5,
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
    assert result["fallback"]["signal_coverage"] == 0.0
    assert result["fallback"]["rate"] is None

    empty = calculate_metrics([])
    assert empty["traces"]["error_rate"] is None
    assert empty["cost"]["estimated_total_usd"] == 0.0
    assert empty["cost"]["cost_per_completed_trace_usd"] is None


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
    assert result["turn_completion"]["good_count"] == 2
    assert result["turn_completion"]["bad_count"] == 1
    assert result["turn_latency"]["good_count"] == 1
    assert result["turn_latency"]["bad_count"] == 2
    assert result["turn_latency"]["p95_ms"] == 20_001
    assert result["turn_latency"]["status"] == "breached"
    assert result["models"]["gpt-6-luna"]["good_count"] == 1
    assert result["models"]["gpt-6-luna"]["bad_count"] == 1
    assert result["models"]["unknown"]["total_count"] == 0

    empty = calculate_slo_metrics(
        [],
        window_started_at=NOW,
        window_ended_at=NOW,
        environment=None,
    )
    assert empty["turn_completion"]["status"] == "no_data"
    assert empty["turn_latency"]["p95_ms"] is None
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
