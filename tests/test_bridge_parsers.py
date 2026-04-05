"""Tests for critical bridge.py parsing functions.

Covers:
1. parse_pillar_score() — normal, two-digit (clamped), missing, no-score text
2. build_evidence_block() — [E#] ID generation from analyst reports
3. parse_claims() — bullish/bearish, claim_id format (clm-u vs clm-r)
4. Chinese negation detection — _parse_research_manager fallback path
5. parse_risk_output() — valid block, missing block, invalid risk_flags JSON
6. assemble_market_context() — sector_momentum flow value cleaning
7. format_market_context_block() — list-of-dicts sector_leaders
"""

import re
import pytest


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. parse_pillar_score                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

class TestParsePillarScore:
    """Tests for parse_pillar_score()."""

    def test_normal_score_zero(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "pillar_score = 0\nsome other text"
        assert parse_pillar_score(text) == 0

    def test_normal_score_two(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "Analysis complete.\npillar_score = 2\n"
        assert parse_pillar_score(text) == 2

    def test_normal_score_four(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "pillar_score=4"
        assert parse_pillar_score(text) == 4

    def test_normal_score_with_spaces(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "pillar_score   =   3"
        assert parse_pillar_score(text) == 3

    def test_two_digit_score_clamped_to_four(self):
        """Scores > 4 (e.g. agent uses 0-10 scale) must be clamped to 4."""
        from subagent_pipeline.bridge import parse_pillar_score
        assert parse_pillar_score("pillar_score = 10") == 4
        assert parse_pillar_score("pillar_score = 7") == 4
        assert parse_pillar_score("pillar_score = 5") == 4

    def test_score_exactly_four_not_clamped(self):
        from subagent_pipeline.bridge import parse_pillar_score
        assert parse_pillar_score("pillar_score = 4") == 4

    def test_missing_pillar_score_returns_none(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "This analysis has no structured output."
        assert parse_pillar_score(text) is None

    def test_empty_string_returns_none(self):
        from subagent_pipeline.bridge import parse_pillar_score
        assert parse_pillar_score("") is None

    def test_text_with_unrelated_numbers_returns_none(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = "ROE = 12%, PE = 15x, score_value = 3"
        assert parse_pillar_score(text) is None

    def test_pillar_score_in_multiline_report(self):
        from subagent_pipeline.bridge import parse_pillar_score
        text = (
            "## 技术面分析\n"
            "MACD 金叉形成，趋势向上。\n"
            "RSI: 58\n"
            "pillar_score = 3\n"
            "综合来看持乐观态度。\n"
        )
        assert parse_pillar_score(text) == 3


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. build_evidence_block                                            ║
# ╚══════════════════════════════════════════════════════════════════════╝

SAMPLE_MARKET_REPORT = """
## 技术面分析
pillar_score = 3
CLAIM 1: MACD 金叉，趋势向好
EVIDENCE: 技术面报告-MACD指标
CONFIDENCE: 0.75
FACT: 20日均线支撑有效，价格高于均线5%
"""

SAMPLE_FUNDAMENTALS_REPORT = """
## 基本面分析
pillar_score = 2
ROE: 12.5%
净利润: 15.3亿
CLAIM 1: 盈利能力稳健，毛利率保持高位
EVIDENCE: 基本面报告-财务数据
CONFIDENCE: 0.70
"""

SAMPLE_NEWS_REPORT = """
## 新闻分析
pillar_score = 2
FACT: 公司发布正面盈利预告，超出市场预期
近期无重大负面事件。
"""

SAMPLE_SENTIMENT_REPORT = """
## 情绪分析
pillar_score = 1
整体市场情绪偏中性，主力资金净流入较小。
"""


class TestBuildEvidenceBlock:
    """Tests for build_evidence_block()."""

    def test_generates_e_id_markers(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(
            market_report=SAMPLE_MARKET_REPORT,
            fundamentals_report=SAMPLE_FUNDAMENTALS_REPORT,
        )
        assert "[E1]" in block
        assert "[E2]" in block

    def test_returns_nonempty_for_valid_reports(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(
            market_report=SAMPLE_MARKET_REPORT,
            fundamentals_report=SAMPLE_FUNDAMENTALS_REPORT,
            news_report=SAMPLE_NEWS_REPORT,
            sentiment_report=SAMPLE_SENTIMENT_REPORT,
        )
        assert len(block) > 0

    def test_e_ids_are_sequential(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(
            market_report=SAMPLE_MARKET_REPORT,
            fundamentals_report=SAMPLE_FUNDAMENTALS_REPORT,
            news_report=SAMPLE_NEWS_REPORT,
            sentiment_report=SAMPLE_SENTIMENT_REPORT,
        )
        ids = [int(m) for m in re.findall(r'\[E(\d+)\]', block)]
        assert ids == list(range(1, len(ids) + 1)), "E# IDs must be sequential starting at 1"

    def test_source_labels_present(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(
            market_report=SAMPLE_MARKET_REPORT,
            fundamentals_report=SAMPLE_FUNDAMENTALS_REPORT,
        )
        assert "技术面报告" in block
        assert "基本面报告" in block

    def test_empty_reports_returns_empty_string(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(
            market_report="",
            fundamentals_report="",
            news_report="",
            sentiment_report="",
        )
        assert block == ""

    def test_partial_reports_only_populates_present_sources(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(market_report=SAMPLE_MARKET_REPORT)
        assert "技术面报告" in block
        assert "基本面报告" not in block

    def test_max_32_items_across_all_reports(self):
        """Should not exceed 32 evidence items total (8 per report × 4 reports)."""
        from subagent_pipeline.bridge import build_evidence_block
        # Create reports with lots of FACT lines to stress the limit
        many_facts = "\n".join(
            f"pillar_score = 2\nFACT: 重要数据点{i}: 数值为{i * 10}\n" for i in range(1, 20)
        )
        block = build_evidence_block(
            market_report=many_facts,
            fundamentals_report=many_facts,
            news_report=many_facts,
            sentiment_report=many_facts,
        )
        ids = re.findall(r'\[E(\d+)\]', block)
        assert len(ids) <= 32, f"Got {len(ids)} items, expected ≤ 32"

    def test_contains_evidence_bundle_header(self):
        from subagent_pipeline.bridge import build_evidence_block
        block = build_evidence_block(market_report=SAMPLE_MARKET_REPORT)
        assert "EVIDENCE BUNDLE" in block


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  3. parse_claims — bullish and bearish                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

BULL_RESEARCHER_OUTPUT = """\
## 多头研究员分析

CLAIM 1: 技术面突破关键压力位，上行动能强劲
EVIDENCE: [E1, E3]
CONFIDENCE: 0.80
INVALIDATION: 收盘价跌破20日均线

CLAIM 2: 基本面业绩超预期，ROE持续提升
EVIDENCE: [E2, E4]
CONFIDENCE: 0.75
INVALIDATION: 下季度业绩大幅低于预期

BUY confidence: 8/10
"""

BEAR_RESEARCHER_OUTPUT = """\
## 空头研究员分析

CLAIM 1: 估值偏高，PE超过行业均值30%
EVIDENCE: [E2]
CONFIDENCE: 0.72
INVALIDATION: 业绩大幅超预期导致估值合理化

CLAIM 2: 主力资金持续净流出，情绪转弱
EVIDENCE: [E5]
CONFIDENCE: 0.65
INVALIDATION: 外资大量买入扭转资金面

SELL confidence: 7/10
"""


class TestParseClaims:
    """Tests for parse_claims()."""

    def test_bullish_claim_ids_use_clm_u_prefix(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        for claim in claims:
            assert claim["claim_id"].startswith("clm-u"), (
                f"Bullish claim_id should start with 'clm-u', got '{claim['claim_id']}'"
            )

    def test_bearish_claim_ids_use_clm_r_prefix(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BEAR_RESEARCHER_OUTPUT, direction="bearish")
        for claim in claims:
            assert claim["claim_id"].startswith("clm-r"), (
                f"Bearish claim_id should start with 'clm-r', got '{claim['claim_id']}'"
            )

    def test_bullish_ids_not_clm_b(self):
        """Regression: bullish IDs were incorrectly prefixed 'clm-b' in old code."""
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        for claim in claims:
            assert not claim["claim_id"].startswith("clm-b"), (
                f"Bullish claim_id must NOT start with 'clm-b', got '{claim['claim_id']}'"
            )

    def test_bearish_ids_not_clm_b(self):
        """Regression: bearish IDs were incorrectly prefixed 'clm-b' in old code."""
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BEAR_RESEARCHER_OUTPUT, direction="bearish")
        for claim in claims:
            assert not claim["claim_id"].startswith("clm-b"), (
                f"Bearish claim_id must NOT start with 'clm-b', got '{claim['claim_id']}'"
            )

    def test_bullish_claim_count(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        assert len(claims) == 2

    def test_bearish_claim_count(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BEAR_RESEARCHER_OUTPUT, direction="bearish")
        assert len(claims) == 2

    def test_claim_direction_field_bullish(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        for c in claims:
            assert c["direction"] == "bullish"

    def test_claim_direction_field_bearish(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BEAR_RESEARCHER_OUTPUT, direction="bearish")
        for c in claims:
            assert c["direction"] == "bearish"

    def test_claim_ids_are_sequential(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        for i, claim in enumerate(claims, start=1):
            assert claim["claim_id"] == f"clm-u{i:03d}"

    def test_evidence_ids_parsed_from_brackets(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        assert claims[0]["supports"] == ["E1", "E3"]
        assert claims[1]["supports"] == ["E2", "E4"]

    def test_confidence_parsed(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        assert abs(claims[0]["confidence"] - 0.80) < 0.01
        assert abs(claims[1]["confidence"] - 0.75) < 0.01

    def test_confidence_normalized_from_1_to_10_scale(self):
        """If agent uses 1-10 scale, confidence should be divided by 10.

        Note: parse_claims splits on '\nCLAIM' so the input text must have
        a leading newline for the first CLAIM block to be detected.
        """
        from subagent_pipeline.bridge import parse_claims
        # Leading '\n' ensures the CLAIM splitter (splits on \nCLAIM) finds this block
        text = "\nCLAIM 1: 上涨趋势明确\nEVIDENCE: [E1]\nCONFIDENCE: 8.0\n"
        claims = parse_claims(text, direction="bullish")
        assert len(claims) == 1
        assert claims[0]["confidence"] <= 1.0, "Confidence >1.0 should be normalized"
        assert abs(claims[0]["confidence"] - 0.80) < 0.01

    def test_invalidation_extracted(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT, direction="bullish")
        assert "20日均线" in claims[0]["invalidation"]

    def test_empty_text_returns_empty_list(self):
        from subagent_pipeline.bridge import parse_claims
        assert parse_claims("", direction="bullish") == []

    def test_no_claim_blocks_returns_empty_list(self):
        from subagent_pipeline.bridge import parse_claims
        text = "这是一段没有CLAIM结构的普通文本，ROE = 12%。"
        assert parse_claims(text, direction="bullish") == []

    def test_default_direction_is_bullish(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(BULL_RESEARCHER_OUTPUT)  # no direction arg
        assert all(c["direction"] == "bullish" for c in claims)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. Chinese negation detection in _parse_research_manager fallback  ║
# ╚══════════════════════════════════════════════════════════════════════╝

class TestResearchManagerNegationDetection:
    """Test that negated Chinese buying/selling phrases do NOT trigger the wrong action.

    The PM fallback (when SYNTHESIS_OUTPUT block is missing) uses a 5-char
    window negation check.  'BUY' must not be triggered by '不建议买入', and
    'SELL' must not be triggered by '不要卖出'.
    """

    def _run_pm_parse(self, text: str) -> str:
        """Run _parse_research_manager on text and return the resolved research_action."""
        from subagent_pipeline.bridge import build_node_trace
        nt = build_node_trace("research_manager", text, run_id="test-neg-001")
        return nt.research_action

    def test_negated_buy_does_not_trigger_buy(self):
        """'不建议买入' should NOT produce BUY."""
        # No SYNTHESIS_OUTPUT block → forces fallback path
        text = (
            "综合来看，该股风险较高，不建议买入，建议等待更好时机。"
            "当前持仓者可选择继续持有。"
        )
        action = self._run_pm_parse(text)
        assert action != "BUY", (
            f"'不建议买入' must NOT trigger BUY, got '{action}'"
        )

    def test_negated_sell_does_not_trigger_sell(self):
        """'不要卖出' should NOT produce SELL."""
        text = (
            "目前形势稳健，不要卖出，维持现有仓位。"
            "短期内回调空间有限。"
        )
        action = self._run_pm_parse(text)
        assert action != "SELL", (
            f"'不要卖出' must NOT trigger SELL, got '{action}'"
        )

    def test_negated_buy_resolves_to_hold(self):
        """'不建议买入' with no other strong signals should resolve to HOLD."""
        text = (
            "综合评估：不建议买入，市场环境不明朗。"
            "观望为宜。"
        )
        action = self._run_pm_parse(text)
        assert action == "HOLD", f"Expected HOLD, got '{action}'"

    def test_positive_buy_triggers_buy(self):
        """Positive '建议买入' (no negation) should produce BUY."""
        text = (
            "综合评估，公司基本面扎实，建议买入。"
            "目标价格为15元。"
        )
        action = self._run_pm_parse(text)
        assert action == "BUY", f"Expected BUY for '建议买入', got '{action}'"

    def test_synthesis_output_overrides_fallback(self):
        """When SYNTHESIS_OUTPUT is present, it takes priority over fallback text matching."""
        text = (
            "SYNTHESIS_OUTPUT:\n"
            "research_action = SELL\n"
            "confidence = 0.72\n"
            "conclusion = 技术面破位，建议减仓\n"
            "\n"
            "正文中包含'建议买入'等干扰词。"
        )
        action = self._run_pm_parse(text)
        assert action == "SELL", (
            f"SYNTHESIS_OUTPUT should override text matching, got '{action}'"
        )

    def test_negation_with_different_negators(self):
        """Multiple Chinese negation words: 不宜, 切勿, 避免."""
        from subagent_pipeline.bridge import build_node_trace

        negation_phrases = [
            "不宜买入此股",
            "切勿买入，风险过高",
            "避免买入，板块景气下行",
        ]
        for phrase in negation_phrases:
            nt = build_node_trace("research_manager", phrase, run_id="test-neg-002")
            assert nt.research_action != "BUY", (
                f"Phrase '{phrase}' should not trigger BUY, got '{nt.research_action}'"
            )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  5. parse_risk_output                                               ║
# ╚══════════════════════════════════════════════════════════════════════╝

VALID_RISK_OUTPUT = """\
分析完毕，风险评估如下：

RISK_OUTPUT:
risk_score = 6
risk_cleared = TRUE
research_action = BUY
max_position_pct = 15
confidence = 0.68
risk_flags = [
  {"category": "流动性风险", "severity": "medium", "description": "日均成交量偏低", "evidence": "E3"},
  {"category": "估值风险", "severity": "low", "description": "PE略高于均值", "evidence": "E2"}
]
"""

RISK_OUTPUT_MISSING_BLOCK = """\
综合分析后，认为该股风险可控，但需注意流动性。
建议仓位不超过10%。
"""

RISK_OUTPUT_INVALID_FLAGS_JSON = """\
RISK_OUTPUT:
risk_score = 7
risk_cleared = FALSE
risk_flags = [{"category": "流动性", "severity": "high", "description": "缺失控制字符\x00无效"}
]
"""


class TestParseRiskOutput:
    """Tests for parse_risk_output()."""

    def test_valid_block_parses_risk_score(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        assert result.get("risk_score") == 6

    def test_valid_block_parses_risk_cleared_true(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        assert result.get("risk_cleared") is True

    def test_valid_block_parses_research_action(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        assert result.get("research_action") == "BUY"

    def test_valid_block_parses_max_position_pct(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        assert result.get("max_position_pct") == 15

    def test_valid_block_parses_confidence(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        assert abs(float(result.get("confidence", 0)) - 0.68) < 0.01

    def test_valid_block_parses_risk_flags_as_list(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        flags = result.get("risk_flags", [])
        assert isinstance(flags, list)
        assert len(flags) == 2

    def test_valid_block_risk_flag_category(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(VALID_RISK_OUTPUT)
        categories = [f.get("category") for f in result.get("risk_flags", [])]
        assert "流动性风险" in categories

    def test_missing_block_returns_empty_dict(self):
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(RISK_OUTPUT_MISSING_BLOCK)
        assert result == {}

    def test_invalid_risk_flags_json_defaults_to_empty_list(self):
        """When risk_flags JSON is malformed, should default to [] and set parse_failed flag."""
        from subagent_pipeline.bridge import parse_risk_output
        result = parse_risk_output(RISK_OUTPUT_INVALID_FLAGS_JSON)
        flags = result.get("risk_flags", [])
        assert isinstance(flags, list), "risk_flags must be a list even on parse failure"
        # Either empty (failed gracefully) or the parse_failed flag is set
        if len(flags) == 0:
            assert result.get("_risk_flags_parse_failed") is True

    def test_risk_cleared_false_string_normalized(self):
        from subagent_pipeline.bridge import parse_risk_output
        text = "RISK_OUTPUT:\nrisk_score = 8\nrisk_cleared = FALSE\n"
        result = parse_risk_output(text)
        assert result.get("risk_cleared") is False

    def test_json_format_risk_output(self):
        """RISK_OUTPUT can also be a JSON object."""
        from subagent_pipeline.bridge import parse_risk_output
        text = (
            "RISK_OUTPUT:\n"
            '{"risk_score": 5, "risk_cleared": "TRUE", "research_action": "HOLD", '
            '"max_position_pct": 10, "confidence": 0.60, "risk_flags": []}\n'
        )
        result = parse_risk_output(text)
        assert result.get("risk_score") == 5
        assert result.get("risk_cleared") is True
        assert result.get("research_action") == "HOLD"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  6. assemble_market_context — sector_momentum flow cleaning         ║
# ╚══════════════════════════════════════════════════════════════════════╝

class TestAssembleMarketContextFlowCleaning:
    """Tests for sector_momentum flow value cleaning in assemble_market_context()."""

    def _make_sector_with_flow(self, flow_value: str) -> dict:
        """Helper: build minimal sector dict with a single momentum entry."""
        return {
            "sector_momentum": [
                {"name": "电子", "direction": "in", "flow": flow_value}
            ]
        }

    def test_flow_string_with_plus_sign_and_yi(self):
        """'+33.92亿' should be cleaned to '33.92'."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = self._make_sector_with_flow("+33.92亿")
        ctx = assemble_market_context({}, {}, sector)
        momentum = ctx.get("sector_momentum", [])
        assert len(momentum) == 1
        assert momentum[0]["flow"] == "33.92", (
            f"Expected '33.92', got '{momentum[0]['flow']}'"
        )

    def test_flow_string_with_minus_sign(self):
        """-12.5亿 should clean to '-12.5'."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = self._make_sector_with_flow("-12.5亿")
        ctx = assemble_market_context({}, {}, sector)
        momentum = ctx.get("sector_momentum", [])
        assert momentum[0]["flow"] == "-12.5", (
            f"Expected '-12.5', got '{momentum[0]['flow']}'"
        )

    def test_flow_numeric_string_passes_through(self):
        """A clean numeric string should pass through unchanged."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = self._make_sector_with_flow("25.7")
        ctx = assemble_market_context({}, {}, sector)
        momentum = ctx.get("sector_momentum", [])
        # Float conversion and back to string may add .0 — accept both
        flow = momentum[0]["flow"]
        assert float(flow) == pytest.approx(25.7)

    def test_flow_with_wan_yi_suffix_cleaned(self):
        """Flow values like '5.2万亿' should have non-numeric chars stripped."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = self._make_sector_with_flow("5.2万亿")
        ctx = assemble_market_context({}, {}, sector)
        momentum = ctx.get("sector_momentum", [])
        flow = momentum[0]["flow"]
        assert float(flow) == pytest.approx(5.2)

    def test_flow_already_numeric_int_unchanged(self):
        """When flow is already an integer (not a string), it should not be touched."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = {
            "sector_momentum": [
                {"name": "银行", "direction": "out", "flow": 45}
            ]
        }
        ctx = assemble_market_context({}, {}, sector)
        momentum = ctx.get("sector_momentum", [])
        # Non-string flows should remain unchanged
        assert momentum[0]["flow"] == 45

    def test_multiple_momentum_entries_all_cleaned(self):
        """All entries in sector_momentum list should be cleaned."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = {
            "sector_momentum": [
                {"name": "电子", "direction": "in", "flow": "+33.92亿"},
                {"name": "银行", "direction": "out", "flow": "-8.1亿"},
                {"name": "医药", "direction": "in", "flow": "12.3"},
            ]
        }
        ctx = assemble_market_context({}, {}, sector)
        flows = [m["flow"] for m in ctx.get("sector_momentum", [])]
        assert float(flows[0]) == pytest.approx(33.92)
        assert float(flows[1]) == pytest.approx(-8.1)
        assert float(flows[2]) == pytest.approx(12.3)

    def test_regime_normalized_to_uppercase(self):
        from subagent_pipeline.bridge import assemble_market_context
        macro = {"regime": "risk_on"}
        ctx = assemble_market_context(macro, {}, {})
        assert ctx["regime"] == "RISK_ON"

    def test_breadth_state_normalized_to_uppercase(self):
        from subagent_pipeline.bridge import assemble_market_context
        breadth = {"breadth_state": "healthy"}
        ctx = assemble_market_context({}, breadth, {})
        assert ctx["breadth_state"] == "HEALTHY"

    def test_trade_date_stored(self):
        from subagent_pipeline.bridge import assemble_market_context
        ctx = assemble_market_context({}, {}, {}, trade_date="2026-04-02")
        assert ctx["trade_date"] == "2026-04-02"

    def test_sector_leaders_string_split_to_list(self):
        """When sector_leaders is a comma-separated string, it should be split."""
        from subagent_pipeline.bridge import assemble_market_context
        sector = {"sector_leaders": "电子, 新能源, 军工"}
        ctx = assemble_market_context({}, {}, sector)
        leaders = ctx["sector_leaders"]
        assert isinstance(leaders, list)
        assert len(leaders) == 3

    def test_position_cap_multiplier_string_converted_to_float(self):
        from subagent_pipeline.bridge import assemble_market_context
        macro = {"position_cap_multiplier": "0.9"}
        ctx = assemble_market_context(macro, {}, {})
        assert isinstance(ctx["position_cap_multiplier"], float)
        assert ctx["position_cap_multiplier"] == pytest.approx(0.9)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  7. format_market_context_block — list-of-dicts sector_leaders      ║
# ╚══════════════════════════════════════════════════════════════════════╝

class TestFormatMarketContextBlock:
    """Tests for format_market_context_block()."""

    def test_list_of_dicts_sector_leaders_does_not_crash(self):
        """Regression: sector_leaders as list of dicts (with 'name' key) used to crash."""
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "RISK_ON",
            "market_weather": "晴",
            "position_cap_multiplier": 0.8,
            "style_bias": "成长",
            "breadth_state": "HEALTHY",
            "advance_decline_ratio": "2:1",
            "breadth_trend": "上升",
            "sector_leaders": [
                {"name": "电子", "direction": "in"},
                {"name": "新能源", "direction": "in"},
            ],
            "avoid_sectors": ["银行"],
            "rotation_phase": "扩散期",
            "risk_alerts": "NONE",
        }
        # Should not raise any exception
        block = format_market_context_block(ctx)
        assert isinstance(block, str)
        assert len(block) > 0

    def test_list_of_dicts_sector_leaders_rendered_as_names(self):
        """Dict sector_leaders should show name values in output, not raw dict repr."""
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "NEUTRAL",
            "market_weather": "",
            "position_cap_multiplier": 0.8,
            "style_bias": "均衡",
            "breadth_state": "NARROW",
            "advance_decline_ratio": "",
            "breadth_trend": "",
            "sector_leaders": [
                {"name": "电子", "flow": 33.9},
                {"name": "军工", "flow": 12.1},
            ],
            "avoid_sectors": [],
            "rotation_phase": "",
            "risk_alerts": "NONE",
        }
        block = format_market_context_block(ctx)
        assert "电子" in block
        assert "军工" in block
        # Should NOT contain raw dict representation
        assert "{'name'" not in block
        assert '{"name"' not in block

    def test_string_list_sector_leaders_rendered_correctly(self):
        """Regular string list for sector_leaders should work normally."""
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "RISK_ON",
            "market_weather": "晴",
            "position_cap_multiplier": 1.0,
            "style_bias": "成长",
            "breadth_state": "HEALTHY",
            "advance_decline_ratio": "3:1",
            "breadth_trend": "强势",
            "sector_leaders": ["电子", "新能源", "军工"],
            "avoid_sectors": ["银行", "地产"],
            "rotation_phase": "初始期",
            "risk_alerts": "无重大风险",
        }
        block = format_market_context_block(ctx)
        assert "电子" in block
        assert "新能源" in block
        assert "军工" in block

    def test_empty_dict_returns_empty_string(self):
        from subagent_pipeline.bridge import format_market_context_block
        block = format_market_context_block({})
        assert block == ""

    def test_regime_appears_in_output(self):
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "RISK_OFF",
            "market_weather": "",
            "position_cap_multiplier": 0.5,
            "style_bias": "防御",
            "breadth_state": "WEAK",
            "advance_decline_ratio": "1:3",
            "breadth_trend": "下降",
            "sector_leaders": [],
            "avoid_sectors": [],
            "rotation_phase": "",
            "risk_alerts": "高风险",
        }
        block = format_market_context_block(ctx)
        assert "RISK_OFF" in block

    def test_empty_sector_leaders_renders_none_label(self):
        """Empty sector_leaders should render as '无' not an empty string."""
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "NEUTRAL",
            "market_weather": "",
            "position_cap_multiplier": 0.8,
            "style_bias": "均衡",
            "breadth_state": "NARROW",
            "advance_decline_ratio": "",
            "breadth_trend": "",
            "sector_leaders": [],
            "avoid_sectors": [],
            "rotation_phase": "",
            "risk_alerts": "NONE",
        }
        block = format_market_context_block(ctx)
        assert "无" in block


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Audit-fix tests: bracket parser, confidence normalization,         ║
# ║  strict_date_check, negation window 12 chars                       ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestCatalystBracketParser:
    """Tests for string-aware bracket matching in parse_catalyst_json."""

    def test_simple_array(self):
        from subagent_pipeline.bridge import parse_catalyst_json
        text = 'CATALYST_OUTPUT:\n[{"name": "test", "impact": "high"}]'
        result = parse_catalyst_json(text)
        assert len(result) == 1
        assert result[0]["name"] == "test"

    def test_brackets_inside_strings_ignored(self):
        from subagent_pipeline.bridge import parse_catalyst_json
        text = 'CATALYST_OUTPUT:\n[{"name": "Price at [100, 105]", "impact": "high"}]'
        result = parse_catalyst_json(text)
        assert len(result) == 1
        assert "[100, 105]" in result[0]["name"]

    def test_nested_arrays(self):
        from subagent_pipeline.bridge import parse_catalyst_json
        text = 'CATALYST_OUTPUT:\n[{"tags": ["a", "b"], "impact": "high"}]'
        result = parse_catalyst_json(text)
        assert len(result) == 1
        assert result[0]["tags"] == ["a", "b"]

    def test_empty_output(self):
        from subagent_pipeline.bridge import parse_catalyst_json
        assert parse_catalyst_json("no output here") == []


class TestConfidenceNormalization:
    """Tests for the >= 10 boundary fix in parse_claims."""

    def _make_claim_text(self, confidence):
        # parse_claims splits on "\nCLAIM:" — needs preceding newline
        return f"Preamble\nCLAIM: Test claim\nEVIDENCE: [E1]\nCONFIDENCE: {confidence}"

    def test_confidence_10_normalized(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(self._make_claim_text(10))
        assert len(claims) >= 1
        # 10 >= 10 → divided by 100 → 0.1
        assert claims[0]["confidence"] == pytest.approx(0.1, abs=0.01)

    def test_confidence_75_normalized(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(self._make_claim_text(75))
        assert len(claims) >= 1
        assert claims[0]["confidence"] == pytest.approx(0.75, abs=0.01)

    def test_confidence_0_8_unchanged(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(self._make_claim_text(0.8))
        assert len(claims) >= 1
        assert claims[0]["confidence"] == pytest.approx(0.8, abs=0.01)

    def test_confidence_5_normalized_as_1_10_scale(self):
        from subagent_pipeline.bridge import parse_claims
        claims = parse_claims(self._make_claim_text(5))
        assert len(claims) >= 1
        # 5 > 1.0 but < 10 → divide by 10 → 0.5
        assert claims[0]["confidence"] == pytest.approx(0.5, abs=0.01)


class TestStrictDateCheck:
    """Tests for strict_date_check in assemble_market_context."""

    def test_strict_raises_on_stale(self):
        from subagent_pipeline.bridge import assemble_market_context, StaleMarketDataError
        macro = {"regime": "RISK_ON"}
        breadth = {"breadth_state": "BROAD"}
        sector = {}
        # Raw text with wrong date
        raw = {"macro": "日期: 2026-01-01\nregime=RISK_ON", "breadth": "", "sector": ""}
        with pytest.raises(StaleMarketDataError):
            assemble_market_context(
                macro, breadth, sector,
                trade_date="2026-04-04",
                raw_texts=raw,
                strict_date_check=True,
            )

    def test_non_strict_logs_warning(self):
        from subagent_pipeline.bridge import assemble_market_context
        macro = {"regime": "RISK_ON"}
        breadth = {"breadth_state": "BROAD"}
        sector = {}
        raw = {"macro": "日期: 2026-01-01\nregime=RISK_ON", "breadth": "", "sector": ""}
        # Should not raise — warning only
        result = assemble_market_context(
            macro, breadth, sector,
            trade_date="2026-04-04",
            raw_texts=raw,
            strict_date_check=False,
        )
        assert result["regime"] == "RISK_ON"


class TestNegationWindow:
    """Tests for the 12-char Chinese negation window."""

    def test_short_negation_detected(self):
        from subagent_pipeline.bridge import _has_positive
        # "不建议买入" — negation within 5 chars
        assert _has_positive("不建议买入", "买入") is False

    def test_long_prefix_negation_detected(self):
        from subagent_pipeline.bridge import _has_positive
        # "坚决不建议买入" — negation at 7 chars before keyword
        # Old 5-char window would miss this; 12-char window catches it
        assert _has_positive("坚决不建议买入", "买入") is False

    def test_positive_no_negation(self):
        from subagent_pipeline.bridge import _has_positive
        assert _has_positive("建议买入该股票", "买入") is True

    def test_cautious_buy_is_positive(self):
        from subagent_pipeline.bridge import _has_positive
        # "谨慎买入" = buy cautiously, NOT negation
        assert _has_positive("谨慎买入", "买入") is True
