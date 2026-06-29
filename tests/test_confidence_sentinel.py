"""Regression tests for the -1.0 confidence-sentinel render-layer gate
(N-RSH-01 / N-RMKT / N-DEB-04 / N-FND).

`format_confidence_pct` is the single render-layer gate: it turns the -1.0
"unset" sentinel into "—" (never "-100%") and clamps in-range values to [0,1]
(never "7500%"). Aggregates exclude the sentinel before averaging.
"""
from subagent_pipeline.renderers.shared_utils import format_confidence_pct


# ── The gate itself (pure, no heavy imports) ──
def test_sentinel_returns_dash():
    assert format_confidence_pct(-1.0) == "—"


def test_none_returns_dash():
    assert format_confidence_pct(None) == "—"


def test_in_range_value():
    assert format_confidence_pct(0.62) == "62%"


def test_raw_scale_normalizes():
    assert format_confidence_pct(75) == "75%"      # >=10 → ÷100


def test_absurd_value_is_clamped_not_7500pct():
    assert format_confidence_pct(7500) == "100%"   # 7500→÷100=75→clamp 1.0


def test_zero_is_zero_not_dash():
    assert format_confidence_pct(0.0) == "0%"


def test_custom_missing_token():
    assert format_confidence_pct(-1.0, missing="N/A") == "N/A"


# ── Pool average excludes the sentinel (N-RMKT) ──
def test_pool_avg_excludes_sentinel():
    from subagent_pipeline.renderers.pool_view import (
        DivergencePoolView, StockDivergenceRow,
    )
    v = DivergencePoolView(rows=[
        StockDivergenceRow(confidence=-1.0),
        StockDivergenceRow(confidence=0.8),
    ])
    assert abs(v.avg_confidence - 0.8) < 1e-9


def test_pool_avg_all_sentinel_is_sentinel():
    from subagent_pipeline.renderers.pool_view import (
        DivergencePoolView, StockDivergenceRow,
    )
    v = DivergencePoolView(rows=[StockDivergenceRow(confidence=-1.0)])
    assert v.avg_confidence == -1.0


# ── Committee verdict: missing risk node is "not assessed", not 0/10 (N-DEB-04) ──
def test_verdict_default_risk_unassessed():
    from subagent_pipeline.renderers.debate_view import VerdictView
    vd = VerdictView()
    assert vd.risk_score == -1
    assert vd.risk_assessed is False


# ── Legacy trace: out-of-range confidence normalizes, not clamp-to-1.0 (N-FND) ──
def test_legacy_overrange_confidence_normalizes():
    from subagent_pipeline.trace_models import RunTrace
    rt = RunTrace.from_dict({"run_id": "t", "final_confidence": 75.0, "node_traces": []})
    assert abs(rt.final_confidence - 0.75) < 1e-9


def test_legacy_sentinel_confidence_preserved():
    from subagent_pipeline.trace_models import RunTrace
    rt = RunTrace.from_dict({"run_id": "t", "final_confidence": -1.0, "node_traces": []})
    assert rt.final_confidence == -1.0
