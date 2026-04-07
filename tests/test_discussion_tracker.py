"""Tests for discussion_tracker — debate quality analysis and semantic detection.

Covers:
- _has_rebuttal_language: rebuttal pattern detection
- _extract_key_phrases: key phrase extraction (numeric + vocabulary)
- _estimate_pm_consumption_semantic: topic-based PM consumption
- _scan_dimensions: dimension coverage detection
- _compute_balance: debate balance scoring
- generate_discussion_review: integration with RunTrace
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional

from subagent_pipeline.discussion_tracker import (
    _has_rebuttal_language,
    _extract_key_phrases,
    _estimate_pm_consumption_semantic,
    _scan_dimensions,
    _compute_balance,
    _FINANCIAL_TERMS,
    DIMENSIONS,
    DebateQualityScore,
    EvidenceUtilization,
    DiscussionReview,
    generate_discussion_review,
)


# ── _has_rebuttal_language ─────────────────────────────────────────


class TestHasRebuttalLanguage:
    def test_disagree_chinese(self):
        assert _has_rebuttal_language("本报告不同意PM的持有建议")

    def test_pm_overoptimistic(self):
        assert _has_rebuttal_language("PM过于乐观，未充分考虑下行风险")

    def test_position_too_high(self):
        assert _has_rebuttal_language("当前仓位过高，应当降低至5%")

    def test_adjust_position_down(self):
        assert _has_rebuttal_language("建议下调仓位至3%以控制风险")

    def test_plain_analysis_no_rebuttal(self):
        assert not _has_rebuttal_language("本股票基本面稳健，估值合理")

    def test_english_disagree(self):
        assert _has_rebuttal_language("I disagree with the PM's BUY call")

    def test_empty_string(self):
        assert not _has_rebuttal_language("")


# ── _extract_key_phrases ──────────────────────────────────────────


class TestExtractKeyPhrases:
    def test_numeric_adjacent_chinese(self):
        claims = [{"text": "毛利率53.32%，ROE提升至12%"}]
        phrases = _extract_key_phrases(claims, "")
        assert "毛利率" in phrases or "毛利" in phrases

    def test_numeric_adjacent_english(self):
        claims = [{"text": "ROE = 12.5%, PB仅2.58倍"}]
        phrases = _extract_key_phrases(claims, "")
        assert "ROE" in phrases

    def test_dimension_label(self):
        claims = [{"text": "基本面偏弱", "dimension": "基本面风险"}]
        phrases = _extract_key_phrases(claims, "")
        assert "基本面" in phrases

    def test_financial_vocabulary_without_numbers(self):
        claims = [{"text": "主力资金持续净流出，质押风险加剧"}]
        phrases = _extract_key_phrases(claims, "")
        assert "主力" in phrases
        assert "质押" in phrases
        assert "净流出" in phrases

    def test_empty_claims(self):
        assert _extract_key_phrases([], "") == []

    def test_deduplication(self):
        claims = [{"text": "ROE 12%"}, {"text": "ROE 15%"}]
        phrases = _extract_key_phrases(claims, "")
        assert phrases.count("ROE") == 1

    def test_excerpt_numeric_extraction(self):
        phrases = _extract_key_phrases([], "PE 37.46倍 PB 6.05")
        assert "PE" in phrases
        assert "PB" in phrases


# ── _estimate_pm_consumption_semantic ─────────────────────────────


class TestEstimatePmConsumption:
    def _make_node(self, excerpt=""):
        node = MagicMock()
        node.output_excerpt = excerpt
        return node

    def test_high_consumption(self):
        pm = self._make_node("基本面改善，毛利率稳定，ROE回升，净流出缩窄，催化剂即将到来")
        claims = [{"text": "基本面健康度7分，毛利率53%，ROE改善中，催化剂是年报"}]
        rate = _estimate_pm_consumption_semantic(pm, claims, [], "", "")
        assert rate >= 0.5

    def test_low_consumption(self):
        pm = self._make_node("本股票处于横盘整理阶段")
        claims = [{"text": "基本面健康度7分，毛利率53%，ROE改善中，催化剂是年报"}]
        rate = _estimate_pm_consumption_semantic(pm, claims, [], "", "")
        assert rate < 0.5

    def test_empty_pm(self):
        pm = self._make_node("")
        claims = [{"text": "ROE 12%, 毛利率稳定"}]
        rate = _estimate_pm_consumption_semantic(pm, claims, [], "", "")
        assert rate == 0.0

    def test_no_financial_terms_falls_back_to_dimensions(self):
        pm = self._make_node("基本面良好，技术面偏弱，资金面中性")
        # Claims with no _FINANCIAL_TERMS
        claims = [{"text": "股价走势平稳，无特殊信号"}]
        rate = _estimate_pm_consumption_semantic(pm, claims, [], "", "")
        # Falls back to dimension coverage: 3/5
        assert rate == pytest.approx(0.6, abs=0.01)


# ── _scan_dimensions ─────────────────────────────────────────────


class TestScanDimensions:
    def test_all_five(self):
        claims = [{"text": "基本面健康，估值合理，技术面看多，资金面流入，催化剂明确"}]
        dims = _scan_dimensions(claims)
        assert set(dims) == set(DIMENSIONS)

    def test_partial_coverage(self):
        dims = _scan_dimensions([], excerpt="基本面偏弱，估值过高")
        assert "基本面" in dims
        assert "估值" in dims
        assert "技术" not in dims

    def test_empty(self):
        assert _scan_dimensions([], "") == []


# ── _compute_balance ─────────────────────────────────────────────


class TestComputeBalance:
    def test_perfectly_balanced(self):
        score = _compute_balance(10, 10, 0.7, 0.7)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_heavily_skewed_count(self):
        score = _compute_balance(10, 1, 0.8, 0.8)
        assert score < 0.5  # count_balance=0.1, conf_balance=1.0 → 0.46

    def test_zero_claims(self):
        assert _compute_balance(0, 0, 0.0, 0.0) == 0.0

    def test_confidence_gap(self):
        score_balanced = _compute_balance(5, 5, 0.5, 0.5)
        score_skewed = _compute_balance(5, 5, 0.9, 0.1)
        assert score_balanced > score_skewed


# ── _FINANCIAL_TERMS constant ────────────────────────────────────


class TestFinancialTerms:
    def test_contains_dimensions(self):
        for dim in DIMENSIONS:
            assert dim in _FINANCIAL_TERMS or any(
                dim in t for t in _FINANCIAL_TERMS
            ), f"Dimension '{dim}' not in _FINANCIAL_TERMS"

    def test_contains_common_metrics(self):
        for term in ["PE", "PB", "ROE", "毛利", "净利"]:
            assert term in _FINANCIAL_TERMS


# ── generate_discussion_review integration ───────────────────────


class TestGenerateDiscussionReview:
    def test_returns_review_with_all_fields(self, tmp_path):
        """Minimal integration: mock a RunTrace and verify review structure."""
        from subagent_pipeline.trace_models import RunTrace, NodeTrace, NodeStatus

        trace = RunTrace(
            run_id="run-test-001",
            ticker="688114.SS",
            trade_date="2026-04-07",
        )
        # Add bull node
        bull = NodeTrace(
            run_id="run-test-001", node_name="Bull Researcher", seq=5,
            output_excerpt="基本面健康度 7/10, ROE改善, 毛利率53%, 催化剂是CGI交易",
            claims_produced=3, confidence=0.65,
        )
        bull.structured_data = {
            "overall_confidence": 0.65,
            "supporting_claims": [
                {"text": "毛利率53%维持高位", "confidence": 0.8, "dimension": "基本面"},
                {"text": "PB=2.58历史低位", "confidence": 0.7, "dimension": "估值"},
                {"text": "CGI交易催化", "confidence": 0.6, "dimension": "催化"},
            ],
        }
        # Add bear node
        bear = NodeTrace(
            run_id="run-test-001", node_name="Bear Researcher", seq=6,
            output_excerpt="技术面下降通道, 资金面净流出, 估值风险",
            claims_produced=3, confidence=0.70,
        )
        bear.structured_data = {
            "overall_confidence": 0.70,
            "supporting_claims": [
                {"text": "技术面死叉确认", "confidence": 0.8, "dimension": "技术"},
                {"text": "主力净流出持续", "confidence": 0.75, "dimension": "资金"},
                {"text": "ROE为负不支撑估值", "confidence": 0.7, "dimension": "估值"},
            ],
        }
        # Add PM node
        pm = NodeTrace(
            run_id="run-test-001", node_name="Research Manager", seq=9,
            output_excerpt="综合研判：基本面减亏趋势明确但技术面下降通道未破，毛利率稳健但ROE为负，资金面偏空。建议HOLD。",
            confidence=0.55,
        )
        pm.structured_data = {"overall_confidence": 0.55}
        pm.research_action = "HOLD"

        # Add risk debaters
        for name, rec in [("Aggressive Debator", "BUY"),
                          ("Conservative Debator", "HOLD"),
                          ("Neutral Debator", "HOLD")]:
            rn = NodeTrace(
                run_id="run-test-001", node_name=name, seq=12,
                output_excerpt=f"建议{rec}，PM过于保守" if rec == "BUY" else f"建议{rec}",
            )
            rn.structured_data = {"recommendation": rec}
            rn.research_action = rec
            trace.node_traces.append(rn)

        trace.node_traces.extend([bull, bear, pm])
        trace.research_action = "HOLD"
        trace.final_confidence = 0.55

        # Save trace
        from subagent_pipeline.replay_store import ReplayStore
        store = ReplayStore(storage_dir=str(tmp_path))
        store.save(trace)

        # Generate review
        review = generate_discussion_review("run-test-001", storage_dir=str(tmp_path))

        assert isinstance(review, DiscussionReview)
        assert review.run_id == "run-test-001"
        assert review.ticker == "688114.SS"
        assert review.debate_quality is not None
        assert review.evidence_utilization is not None
        assert isinstance(review.prompt_suggestions, list)

        dq = review.debate_quality
        assert dq.bull_claims_count >= 3
        assert dq.bear_claims_count >= 3
        assert dq.balance_score > 0.5
        assert dq.pm_consumption_rate > 0  # PM mentions debate topics
        assert dq.risk_challenge_rate > 0  # Aggressive debater says BUY != HOLD
        assert dq.debate_grade in ("A", "B", "C", "D")

    def test_missing_run_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Run not found"):
            generate_discussion_review("run-nonexistent", storage_dir=str(tmp_path))
