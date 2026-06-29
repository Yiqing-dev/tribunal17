"""review_renderer adapter (A3): a populated DiscussionReview must render with
real values, not the all-placeholder fallback (the renderer was contract-broken
against DiscussionReview's nested shape, and never wired in).

Imports only subagent_pipeline, so it runs in-repo (no dashboard/tradingagents).
"""
from subagent_pipeline.discussion_tracker import (
    DiscussionReview, DebateQualityScore, EvidenceUtilization, PromptSuggestion,
)
from subagent_pipeline.renderers.review_renderer import (
    discussion_review_to_render_dict, render_review_page,
)


def _review() -> DiscussionReview:
    dq = DebateQualityScore(
        bull_claims_count=6, bull_confidence=0.8,
        bear_claims_count=4, bear_confidence=0.6,
        balance_score=0.7,
        addressed_dimensions=["基本面", "技术", "估值"],   # 3 of 5 → cov_frac 0.6
        missed_dimensions=["资金", "催化"],
        pm_consumption_rate=0.5, risk_challenge_rate=0.6,
        debate_grade="B",
    )
    eu = EvidenceUtilization(total_evidence=10, cited_by_bull=5, utilization_rate=0.7)
    return DiscussionReview(
        run_id="run-abc123def456", ticker="601985.SS", trade_date="2026-06-26",
        debate_quality=dq, evidence_utilization=eu,
        prompt_suggestions=[PromptSuggestion(
            agent="bull", category="coverage", description="补充资金面分析",
            severity="warning", example="加入北向资金数据")],
    )


def test_adapter_maps_nested_to_flat():
    d = discussion_review_to_render_dict(_review(), ticker_name="中国核电")
    assert d["grade"] == "B"                                  # not default C
    assert d["overall_score"] == 78.0                         # grade B → 78 (derived from grade)
    assert d["ticker_name"] == "中国核电"
    assert d["bull"]["claims_count"] == 6 and d["bear"]["claims_count"] == 4
    assert len(d["coverage"]) == 5
    assert sum(c["value"] for c in d["coverage"]) == 300      # 3 dims × 100
    assert d["pm_consumption"]["bull_total"] == 6
    # PromptSuggestion severity warning → renderer's medium scale
    assert d["suggestions"] and d["suggestions"][0]["severity"] == "medium"


def test_rendered_page_has_no_placeholders():
    html = render_review_page(discussion_review_to_render_dict(_review(), ticker_name="中国核电"))
    assert "中国核电" in html
    assert ">B<" in html                 # real grade badge, not default-only
    assert "78" in html                  # grade-derived overall score (B→78), not 0/100
    assert "多方 (Bull)" in html
    assert "补充资金面分析" in html        # the suggestion rendered


def test_empty_review_falls_back_gracefully():
    # No debate_quality → safe defaults, no crash.
    d = discussion_review_to_render_dict(DiscussionReview(run_id="r", ticker="600519.SS"))
    assert d["grade"] == "C" and d["overall_score"] == 0.0
    assert len(d["coverage"]) == 5 and d["bull"]["claims_count"] == 0
