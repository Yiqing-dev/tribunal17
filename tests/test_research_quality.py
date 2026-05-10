"""Unit tests for subagent_pipeline.research_quality.

Covers:
- Per-dimension scoring (pillar_coverage / evidence_binding / debate_engagement
  / falsifiability / data_freshness / scenario_diversity / industry_context)
- Composite weighting + grade thresholds (A/B/C/D)
- ResearchQualitySummary aggregation across multiple runs
- Edge cases (empty trace, missing fields, NaN-like data)
"""

import json
import tempfile
from pathlib import Path

import pytest

from subagent_pipeline.research_quality import (
    ResearchQualityRecord,
    ResearchQualitySummary,
    build_quality_summary,
    evaluate_run_quality,
    evaluate_trace_quality,
    _grade,
    _score_pillar_coverage,
    _score_evidence_binding,
    _score_debate_engagement,
    _score_falsifiability,
    _score_data_freshness,
    _score_scenario_diversity,
    _score_industry_context,
)


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_trace(**overrides):
    """Build a minimal RunTrace dict with sensible defaults."""
    base = {
        "run_id": "run-test-001",
        "ticker": "603065.SS",
        "ticker_name": "宿迁联盛",
        "trade_date": "2026-05-06",
        "total_nodes": 17,
        "error_count": 0,
        "node_traces": [
            {"node_name": "Market Analyst", "structured_data": {"pillar_score": 2}},
            {"node_name": "Fundamentals Analyst",
             "structured_data": {"pillar_score": 2, "industry_compare": {"industry_name": "化学制品"}}},
            {"node_name": "News Analyst", "structured_data": {"pillar_score": 1}},
            {"node_name": "Social Analyst", "structured_data": {"pillar_score": 2}},
            {"node_name": "Bull Researcher",
             "structured_data": {
                 "supporting_claims": [
                     {"claim_id": "u001", "supports": ["E1"]},
                     {"claim_id": "u002", "supports": ["E2"]},
                     {"claim_id": "u003", "supports": ["E3"]},
                     {"claim_id": "u004", "supports": ["E4"]},
                 ],
                 "dimension_scores": {"basic": 3, "tech": 3},
                 "unresolved_conflicts": ["Q1 trend interpretation"],
             }},
            {"node_name": "Bear Researcher",
             "structured_data": {
                 "supporting_claims": [
                     {"claim_id": "r001", "supports": ["E5"]},
                     {"claim_id": "r002", "supports": ["E6"]},
                 ],
                 "opposing_claims": [
                     {"claim_id": "r003", "opposes": ["E1"]},
                     {"claim_id": "r004", "opposes": ["E2"]},
                 ],
                 "dimension_scores": {"basic": 4, "tech": 4},
                 "unresolved_conflicts": ["Valuation method"],
             }},
            {"node_name": "Scenario Agent",
             "structured_data": {"base_prob": 0.45, "bull_prob": 0.25, "bear_prob": 0.30}},
            {"node_name": "Research Manager",
             "structured_data": {
                 "conclusion": "test",
                 "invalidation_conditions": [
                     "跌破 8.40 元 + RSI < 30",
                     "Q2 净利润 < 1000 万元",
                 ],
             }},
            {"node_name": "Risk Judge",
             "structured_data": {"invalidation_conditions": []}},
        ],
    }
    for k, v in overrides.items():
        base[k] = v
    return base


# ── _grade thresholds ──────────────────────────────────────────────────


def test_grade_thresholds():
    assert _grade(0.95) == "A"
    assert _grade(0.85) == "A"
    assert _grade(0.84) == "B"
    assert _grade(0.70) == "B"
    assert _grade(0.69) == "C"
    assert _grade(0.55) == "C"
    assert _grade(0.54) == "D"
    assert _grade(0.0) == "D"


# ── Per-dimension scoring ──────────────────────────────────────────────


def test_pillar_coverage_full():
    trace = _make_trace()
    assert _score_pillar_coverage(trace) == 1.0


def test_pillar_coverage_partial():
    trace = _make_trace()
    # Drop News Analyst's pillar_score
    for nt in trace["node_traces"]:
        if nt["node_name"] == "News Analyst":
            nt["structured_data"] = {}
    assert _score_pillar_coverage(trace) == 0.75


def test_pillar_coverage_negative_score_excluded():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Market Analyst":
            nt["structured_data"]["pillar_score"] = -1
    assert _score_pillar_coverage(trace) == 0.75


def test_evidence_binding_all_bound():
    trace = _make_trace()
    # All 8 claims have supports/opposes → 1.0
    assert _score_evidence_binding(trace) == 1.0


def test_evidence_binding_partial():
    trace = _make_trace()
    # Strip supports from one bull claim
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Bull Researcher":
            nt["structured_data"]["supporting_claims"][0]["supports"] = []
    # 7/8 bound
    assert _score_evidence_binding(trace) == 7 / 8


def test_evidence_binding_no_claims_returns_zero():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] in ("Bull Researcher", "Bear Researcher"):
            nt["structured_data"] = {}
    assert _score_evidence_binding(trace) == 0.0


def test_debate_engagement_rich():
    trace = _make_trace()
    # 4 + 4 = 8 claims → rich; conflicts present; dims present
    score = _score_debate_engagement(trace)
    assert score == pytest.approx(0.5 + 0.25 + 0.25)


def test_debate_engagement_thin():
    trace = _make_trace()
    # Reduce to 3 total claims → not rich; no conflicts; no dim scores
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Bull Researcher":
            nt["structured_data"]["supporting_claims"] = [{"claim_id": "u001", "supports": ["E1"]}]
            nt["structured_data"]["unresolved_conflicts"] = []
            nt["structured_data"]["dimension_scores"] = {}
        elif nt["node_name"] == "Bear Researcher":
            nt["structured_data"]["supporting_claims"] = [{"claim_id": "r001", "supports": []}]
            nt["structured_data"]["opposing_claims"] = [{"claim_id": "r002", "opposes": []}]
            nt["structured_data"]["unresolved_conflicts"] = []
            nt["structured_data"]["dimension_scores"] = {}
    score = _score_debate_engagement(trace)
    # 0 (rich) + 0.5 (no conflicts soft) + 0.5 (no dims soft) → 0.5*0.25 + 0.5*0.25 = 0.25
    assert score == pytest.approx(0.25)


def test_falsifiability_concrete():
    trace = _make_trace()
    # Both invalidators have concrete numbers → 1.0
    assert _score_falsifiability(trace) == 1.0


def test_falsifiability_vague():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Research Manager":
            nt["structured_data"]["invalidation_conditions"] = [
                "市场转弱时多头逻辑失效",      # vague (no number)
                "若发生不利的政策变化",         # vague
                "跌破 8.40 元",                 # concrete
            ]
    score = _score_falsifiability(trace)
    assert score == pytest.approx(1 / 3)


def test_falsifiability_no_conditions_returns_zero():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] in ("Research Manager", "Risk Judge"):
            nt["structured_data"]["invalidation_conditions"] = []
    assert _score_falsifiability(trace) == 0.0


def test_data_freshness_no_errors():
    trace = _make_trace(total_nodes=17, error_count=0)
    assert _score_data_freshness(trace) == 1.0


def test_data_freshness_with_errors():
    trace = _make_trace(total_nodes=17, error_count=4)
    assert _score_data_freshness(trace) == pytest.approx(13 / 17)


def test_scenario_diversity_balanced():
    trace = _make_trace()
    # 0.45 / 0.25 / 0.30 — well distributed
    assert _score_scenario_diversity(trace) == 1.0


def test_scenario_diversity_degenerate_high():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Scenario Agent":
            nt["structured_data"] = {"base_prob": 0.90, "bull_prob": 0.05, "bear_prob": 0.05}
    assert _score_scenario_diversity(trace) == 0.3


def test_scenario_diversity_mild_collapse():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Scenario Agent":
            nt["structured_data"] = {"base_prob": 0.80, "bull_prob": 0.04, "bear_prob": 0.16}
    assert _score_scenario_diversity(trace) == 0.6


def test_industry_context_present():
    trace = _make_trace()
    assert _score_industry_context(trace) == 1.0


def test_industry_context_missing_name():
    trace = _make_trace()
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Fundamentals Analyst":
            nt["structured_data"]["industry_compare"] = {"pe_percentile_5y": 30.0}
    assert _score_industry_context(trace) == 0.0


# ── Composite + grade integration ──────────────────────────────────────


def test_evaluate_run_quality_full_trace_returns_a_grade(tmp_path):
    trace = _make_trace()
    p = tmp_path / "run-test-001.json"
    p.write_text(json.dumps(trace), encoding="utf-8")

    rec = evaluate_run_quality("run-test-001", storage_dir=str(tmp_path))
    assert rec is not None
    assert rec.run_id == "run-test-001"
    assert rec.ticker == "603065.SS"
    assert rec.composite_grade == "A"
    assert rec.composite_score >= 0.85
    assert rec.weak_dimensions == []


def test_evaluate_trace_quality_scores_in_memory_trace():
    trace = _make_trace()
    rec = evaluate_trace_quality(trace)
    assert rec.run_id == "run-test-001"
    assert rec.composite_grade == "A"
    assert rec.weak_dimensions == []


def test_evaluate_run_quality_missing_returns_none(tmp_path):
    rec = evaluate_run_quality("nonexistent-run", storage_dir=str(tmp_path))
    assert rec is None


def test_evaluate_run_quality_corrupt_json_returns_none(tmp_path):
    p = tmp_path / "run-bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert evaluate_run_quality("run-bad", storage_dir=str(tmp_path)) is None


def test_evaluate_run_quality_weak_dimensions_listed(tmp_path):
    trace = _make_trace()
    # Knock out industry context + falsifiability
    for nt in trace["node_traces"]:
        if nt["node_name"] == "Fundamentals Analyst":
            nt["structured_data"]["industry_compare"] = {}
        if nt["node_name"] == "Research Manager":
            nt["structured_data"]["invalidation_conditions"] = ["市场转弱"]
    p = tmp_path / "run-weak.json"
    p.write_text(json.dumps(trace), encoding="utf-8")

    rec = evaluate_run_quality("run-weak", storage_dir=str(tmp_path))
    assert rec is not None
    assert "industry_context_present" in rec.weak_dimensions
    assert "falsifiability_score" in rec.weak_dimensions


# ── ResearchQualitySummary aggregation ─────────────────────────────────


def test_build_quality_summary_aggregates(tmp_path):
    # Two A-grade runs and one D-grade run
    for i, frac in enumerate([1.0, 1.0, 0.1]):
        trace = _make_trace(run_id=f"run-{i}")
        if frac < 0.5:
            # Force a D by knocking out almost everything
            trace["error_count"] = 17
            for nt in trace["node_traces"]:
                if nt["node_name"] in ("Bull Researcher", "Bear Researcher"):
                    nt["structured_data"] = {}
                if nt["node_name"] == "Scenario Agent":
                    nt["structured_data"] = {"base_prob": 1.0, "bull_prob": 0, "bear_prob": 0}
                if nt["node_name"] == "Research Manager":
                    nt["structured_data"]["invalidation_conditions"] = ["市场转弱"]
                if nt["node_name"] == "Fundamentals Analyst":
                    nt["structured_data"]["industry_compare"] = {}
        p = tmp_path / f"run-{i}.json"
        p.write_text(json.dumps(trace), encoding="utf-8")

    s = build_quality_summary(["run-0", "run-1", "run-2"], storage_dir=str(tmp_path))
    assert s.n == 3
    assert s.grade_dist.get("A", 0) == 2
    assert s.grade_dist.get("D", 0) == 1
    assert s.weakest_dimension  # something is weakest
    md = s.to_markdown()
    assert "研究质量汇总（3 份报告）" in md
    assert "A: 2 份" in md
    assert "D: 1 份" in md


def test_build_quality_summary_skips_missing_runs(tmp_path):
    trace = _make_trace()
    p = tmp_path / "run-only.json"
    p.write_text(json.dumps(trace), encoding="utf-8")

    s = build_quality_summary(["run-only", "run-missing"], storage_dir=str(tmp_path))
    assert s.n == 1
    assert s.records[0].run_id == "run-only"
