"""Tests for web_collector: parsers, integration helpers, and prompt generators."""

import pytest

from subagent_pipeline.web_collector import (
    global_macro_prompt,
    market_snapshot_web_fallback_prompt,
    ticker_web_enhancement_prompt,
    concept_board_web_prompt,
    top10_shareholders_web_prompt,
    parse_global_macro_output,
    parse_snapshot_recovery,
    parse_ticker_web_output,
    parse_concept_board_output,
    parse_top10_shareholders_output,
    merge_global_macro_into_context,
    format_global_macro_block,
    apply_snapshot_recovery,
    apply_concept_board_recovery,
    format_top10_shareholders_md,
)


# ── Prompt generation ────────────────────────────────────────────────


class TestPromptGeneration:
    def test_global_macro_prompt_basic(self):
        p = global_macro_prompt("2026-03-20")
        assert "Global Macro Intelligence Agent" in p
        assert "2026-03-20" in p
        assert "GLOBAL_MACRO_OUTPUT:" in p

    def test_global_macro_prompt_with_snapshot(self):
        p = global_macro_prompt("2026-03-20", market_snapshot_md="上证 3957")
        assert "上证 3957" in p
        assert "已知 A 股数据" in p

    def test_snapshot_fallback_prompt(self):
        p = market_snapshot_web_fallback_prompt("2026-03-20", missing_fields=["breadth", "sector_flow"])
        assert "SNAPSHOT_RECOVERY:" in p
        assert "breadth" in p
        assert "sector_flow" in p

    def test_snapshot_fallback_no_missing(self):
        p = market_snapshot_web_fallback_prompt("2026-03-20")
        assert "SNAPSHOT_RECOVERY:" in p

    def test_ticker_web_prompt(self):
        p = ticker_web_enhancement_prompt("601985", "中国核电", "2026-03-20")
        assert "601985" in p
        assert "中国核电" in p
        assert "TICKER_WEB_OUTPUT:" in p


# ── GLOBAL_MACRO_OUTPUT parser ───────────────────────────────────────


SAMPLE_GLOBAL_MACRO = """
Some preamble text about the search...

```
GLOBAL_MACRO_OUTPUT:
overnight_markets = US markets closed mixed; S&P -0.3%, Nasdaq +0.1%
geopolitical_risk = Iran tensions; oil prices volatile
cross_market_catalysts = Tesla $2.9B solar deal boosts Chinese solar stocks
sector_implications = Solar/renewable energy sectors benefit; defense stocks mixed
foreign_sentiment = Goldman maintains overweight on China A-shares
macro_narrative = 隔夜美股窄幅波动，地缘局势紧张但未升级，特斯拉太阳能大单利好光伏板块。
```
"""


class TestParseGlobalMacro:
    def test_full_parse(self):
        r = parse_global_macro_output(SAMPLE_GLOBAL_MACRO)
        assert "S&P" in r["overnight_markets"]
        assert "Iran" in r["geopolitical_risk"]
        assert "Tesla" in r["cross_market_catalysts"]
        assert "Solar" in r["sector_implications"]
        assert "Goldman" in r["foreign_sentiment"]
        assert "光伏" in r["macro_narrative"]

    def test_partial_output(self):
        text = """
GLOBAL_MACRO_OUTPUT:
overnight_markets = US up 1%
macro_narrative = 美股上涨
"""
        r = parse_global_macro_output(text)
        assert r["overnight_markets"] == "US up 1%"
        assert r["macro_narrative"] == "美股上涨"
        assert r["geopolitical_risk"] == ""

    def test_empty_text(self):
        r = parse_global_macro_output("")
        assert all(v == "" for v in r.values())

    def test_no_block_marker(self):
        text = "overnight_markets = test value"
        r = parse_global_macro_output(text)
        assert r["overnight_markets"] == "test value"


# ── SNAPSHOT_RECOVERY parser ─────────────────────────────────────────


SAMPLE_RECOVERY = """
```
SNAPSHOT_RECOVERY:
advance_count = 2,345
decline_count = 2,100
limit_up_count = 78
limit_down_count = 12
top_sectors_up = 光伏 +3.2%, AI算力 +2.8%
top_sectors_down = 银行 -1.5%, 地产 -2.1%
index_sse = 3957.05
index_szse = 11987.32
index_chinext = 2345.67
source = eastmoney.com
```
"""


class TestParseSnapshotRecovery:
    def test_full_parse(self):
        r = parse_snapshot_recovery(SAMPLE_RECOVERY)
        assert r["advance_count"] == "2,345"
        assert r["limit_up_count"] == "78"
        assert r["index_sse"] == "3957.05"
        assert r["source"] == "eastmoney.com"

    def test_unknown_excluded(self):
        text = """
SNAPSHOT_RECOVERY:
advance_count = UNKNOWN
decline_count = 2100
"""
        r = parse_snapshot_recovery(text)
        assert "advance_count" not in r
        assert r["decline_count"] == "2100"

    def test_empty(self):
        assert parse_snapshot_recovery("") == {}


# ── TICKER_WEB_OUTPUT parser ─────────────────────────────────────────


SAMPLE_TICKER = """
```
TICKER_WEB_OUTPUT:
international_coverage = Goldman rates BUY with TP 15.0
global_context = Leading nuclear operator in China
recent_deals = Partnership with French EDF on Hinkley Point
sector_global_trend = Global nuclear renaissance underway
```
"""


class TestParseTickerWeb:
    def test_full_parse(self):
        r = parse_ticker_web_output(SAMPLE_TICKER)
        assert "Goldman" in r["international_coverage"]
        assert "nuclear" in r["global_context"]
        assert "EDF" in r["recent_deals"]
        assert "renaissance" in r["sector_global_trend"]

    def test_empty(self):
        r = parse_ticker_web_output("")
        assert all(v == "" for v in r.values())


# ── merge_global_macro_into_context ──────────────────────────────────


class TestMergeGlobalMacro:
    def test_merge_adds_global_macro_key(self):
        ctx = {"regime": "RISK_OFF", "risk_alerts": ""}
        gm = {"overnight_markets": "US up", "geopolitical_risk": "NONE"}
        result = merge_global_macro_into_context(ctx, gm)
        assert "global_macro" in result
        assert result["global_macro"]["overnight_markets"] == "US up"

    def test_geo_risk_appended(self):
        ctx = {"risk_alerts": "existing alert"}
        gm = {"geopolitical_risk": "Iran war escalation"}
        result = merge_global_macro_into_context(ctx, gm)
        assert "existing alert" in result["risk_alerts"]
        assert "Iran war" in result["risk_alerts"]

    def test_geo_risk_none_not_appended(self):
        ctx = {"risk_alerts": "existing"}
        gm = {"geopolitical_risk": "NONE"}
        result = merge_global_macro_into_context(ctx, gm)
        assert result["risk_alerts"] == "existing"

    def test_empty_global_macro(self):
        ctx = {"regime": "NEUTRAL"}
        result = merge_global_macro_into_context(ctx, {})
        assert "global_macro" not in result

    def test_none_global_macro(self):
        ctx = {"regime": "NEUTRAL"}
        result = merge_global_macro_into_context(ctx, None)
        assert result == ctx


# ── format_global_macro_block ────────────────────────────────────────


class TestFormatGlobalMacroBlock:
    def test_format_full(self):
        gm = {
            "overnight_markets": "US up 1%",
            "geopolitical_risk": "Iran tensions",
            "cross_market_catalysts": "Tesla deal",
            "sector_implications": "Solar up",
            "foreign_sentiment": "Bullish",
            "macro_narrative": "综合利好",
        }
        block = format_global_macro_block(gm)
        assert "国际宏观情报:" in block
        assert "隔夜外盘:" in block
        assert "地缘风险:" in block
        assert "综合研判:" in block

    def test_empty_dict(self):
        assert format_global_macro_block({}) == ""

    def test_none_values(self):
        assert format_global_macro_block({"overnight_markets": ""}) == ""

    def test_none_fields_skipped(self):
        gm = {"overnight_markets": "US flat", "geopolitical_risk": "NONE"}
        block = format_global_macro_block(gm)
        assert "隔夜外盘:" in block
        assert "地缘风险:" not in block


# ── apply_snapshot_recovery ──────────────────────────────────────────


class TestApplySnapshotRecovery:
    def test_fills_zero_fields(self):
        class FakeSnapshot:
            advance_count = 0
            decline_count = 0
            limit_up_count = 0
            limit_down_count = 0

        snap = FakeSnapshot()
        apply_snapshot_recovery(snap, {"advance_count": "2345", "decline_count": "2100"})
        assert snap.advance_count == 2345
        assert snap.decline_count == 2100
        assert snap.limit_up_count == 0  # not in recovery

    def test_never_overwrites_existing(self):
        class FakeSnapshot:
            advance_count = 999
            decline_count = 0
            limit_up_count = 0
            limit_down_count = 0

        snap = FakeSnapshot()
        apply_snapshot_recovery(snap, {"advance_count": "100"})
        assert snap.advance_count == 999  # kept existing

    def test_empty_recovery(self):
        class FakeSnapshot:
            advance_count = 0
            decline_count = 0
            limit_up_count = 0
            limit_down_count = 0

        snap = FakeSnapshot()
        apply_snapshot_recovery(snap, {})
        assert snap.advance_count == 0

    def test_none_recovery(self):
        class FakeSnapshot:
            advance_count = 0
            decline_count = 0
            limit_up_count = 0
            limit_down_count = 0

        snap = FakeSnapshot()
        apply_snapshot_recovery(snap, None)  # should not raise


# ── assemble_market_context with global_macro ────────────────────────


class TestAssembleWithGlobalMacro:
    """Test that bridge.assemble_market_context accepts and merges global_macro."""

    def test_without_global_macro(self):
        from subagent_pipeline.bridge import assemble_market_context
        ctx = assemble_market_context(
            macro={"regime": "NEUTRAL"},
            breadth={"breadth_state": "NARROW"},
            sector={},
            trade_date="2026-03-20",
        )
        assert "global_macro" not in ctx

    def test_with_global_macro(self):
        from subagent_pipeline.bridge import assemble_market_context
        gm = {"overnight_markets": "US up", "geopolitical_risk": "Iran war"}
        ctx = assemble_market_context(
            macro={"regime": "RISK_OFF"},
            breadth={"breadth_state": "DETERIORATING"},
            sector={},
            trade_date="2026-03-20",
            global_macro=gm,
        )
        assert "global_macro" in ctx
        assert ctx["global_macro"]["overnight_markets"] == "US up"
        assert "Iran war" in ctx.get("risk_alerts", "")


# ── format_market_context_block with global_macro ────────────────────


class TestFormatContextBlockWithGlobalMacro:
    def test_includes_global_macro_section(self):
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "RISK_OFF",
            "market_weather": "阴",
            "position_cap_multiplier": 0.6,
            "style_bias": "防御",
            "breadth_state": "DETERIORATING",
            "advance_decline_ratio": "1:2",
            "breadth_trend": "下行",
            "sector_leaders": ["AI算力"],
            "avoid_sectors": ["银行"],
            "rotation_phase": "防御",
            "risk_alerts": "地缘风险",
            "global_macro": {
                "overnight_markets": "US down 2%",
                "macro_narrative": "美股大跌",
            },
        }
        block = format_market_context_block(ctx)
        assert "国际宏观情报:" in block
        assert "隔夜外盘: US down 2%" in block
        assert "综合研判: 美股大跌" in block

    def test_no_global_macro_no_section(self):
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "NEUTRAL",
            "sector_leaders": [],
            "avoid_sectors": [],
        }
        block = format_market_context_block(ctx)
        assert "国际宏观情报" not in block


# ── Concept board web fallback ────────────────────────────────────


class TestConceptBoardWebFallback:
    def test_prompt_generation(self):
        p = concept_board_web_prompt("2026-03-24")
        assert "概念板块" in p
        assert "2026-03-24" in p
        assert "CONCEPT_BOARD_OUTPUT:" in p

    def test_parse_valid_output(self):
        text = """Here are the results.

```
CONCEPT_BOARD_OUTPUT:
concept_count = 3
concepts = [{"name": "AI算力", "change_pct": 5.2, "market_cap_yi": 15000}, {"name": "光伏", "change_pct": 3.1, "market_cap_yi": 8000}, {"name": "锂电池", "change_pct": -1.5, "market_cap_yi": 20000}]
source = https://data.eastmoney.com/bkzj/gn.html
```"""
        concepts = parse_concept_board_output(text)
        assert len(concepts) == 3
        assert concepts[0]["name"] == "AI算力"
        assert concepts[0]["change_pct"] == 5.2
        # market_cap_yi * 1e8 = total_market_cap
        assert concepts[0]["total_market_cap"] == 15000 * 1e8

    def test_parse_empty(self):
        assert parse_concept_board_output("no data found") == []

    def test_parse_invalid_json(self):
        text = "CONCEPT_BOARD_OUTPUT:\nconcepts = not json at all"
        assert parse_concept_board_output(text) == []

    def test_parse_zero_concepts(self):
        text = "CONCEPT_BOARD_OUTPUT:\nconcept_count = 0\nconcepts = []"
        assert parse_concept_board_output(text) == []

    def test_apply_to_snapshot_fills_empty(self):
        class FakeSnapshot:
            concept_fund_flow = None
        snap = FakeSnapshot()
        concepts = [{"name": "AI", "change_pct": 3.0, "total_market_cap": 1e12}]
        apply_concept_board_recovery(snap, concepts)
        assert snap.concept_fund_flow == concepts

    def test_apply_to_snapshot_no_overwrite(self):
        class FakeSnapshot:
            concept_fund_flow = [{"name": "existing"}]
        snap = FakeSnapshot()
        apply_concept_board_recovery(snap, [{"name": "new"}])
        assert snap.concept_fund_flow == [{"name": "existing"}]

    def test_apply_empty_list(self):
        class FakeSnapshot:
            concept_fund_flow = None
        snap = FakeSnapshot()
        apply_concept_board_recovery(snap, [])
        assert snap.concept_fund_flow is None


# ── Top 10 shareholders web fallback ──────────────────────────────


class TestTop10ShareholdersWebFallback:
    def test_prompt_generation(self):
        p = top10_shareholders_web_prompt("601985", "中国核电")
        assert "十大流通股东" in p
        assert "601985" in p
        assert "中国核电" in p
        assert "TOP10_SHAREHOLDERS_OUTPUT:" in p

    def test_parse_valid_output(self):
        text = """Found the data.

```
TOP10_SHAREHOLDERS_OUTPUT:
report_date = 2025-12-31
ticker = 601985
shareholder_count = 3
shareholders = [{"name": "中核集团", "shares_wan": 120000, "pct": 62.5, "change_wan": 0}, {"name": "社保基金", "shares_wan": 5000, "pct": 2.6, "change_wan": 200}, {"name": "某私募", "shares_wan": 3000, "pct": 1.56, "change_wan": -100}]
source = https://emweb.securities.eastmoney.com
```"""
        data = parse_top10_shareholders_output(text)
        assert data["report_date"] == "2025-12-31"
        assert len(data["shareholders"]) == 3
        assert data["shareholders"][0]["name"] == "中核集团"
        assert data["shareholders"][0]["shares_wan"] == 120000
        assert data["shareholders"][1]["change_wan"] == 200
        assert data["shareholders"][2]["change_wan"] == -100

    def test_parse_empty(self):
        data = parse_top10_shareholders_output("no data")
        assert data["shareholders"] == []
        assert data["report_date"] == ""

    def test_parse_invalid_json(self):
        text = "TOP10_SHAREHOLDERS_OUTPUT:\nshareholders = broken json"
        data = parse_top10_shareholders_output(text)
        assert data["shareholders"] == []

    def test_format_markdown(self):
        data = {
            "report_date": "2025-12-31",
            "shareholders": [
                {"name": "中核集团", "shares_wan": 120000, "pct": 62.5, "change_wan": 0},
                {"name": "社保基金", "shares_wan": 5000, "pct": 2.6, "change_wan": 200},
            ],
        }
        md = format_top10_shareholders_md(data)
        assert "十大流通股东" in md
        assert "2025-12-31" in md
        assert "中核集团" in md
        assert "+200" in md
        assert "62.50" in md

    def test_format_empty(self):
        assert format_top10_shareholders_md({}) == ""
        assert format_top10_shareholders_md({"shareholders": []}) == ""

    def test_format_negative_change(self):
        data = {
            "report_date": "2025-12-31",
            "shareholders": [
                {"name": "减持方", "shares_wan": 1000, "pct": 0.5, "change_wan": -500},
            ],
        }
        md = format_top10_shareholders_md(data)
        assert "-500" in md
