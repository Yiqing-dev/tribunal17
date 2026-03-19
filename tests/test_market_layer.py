"""Tests for market layer: agents, heatmap, pages, drawer, export (P1-P5).

78 tests covering:
- P1: Market agent prompts, parsers, assemble_market_context, config
- P2: HeatmapNode, HeatmapData, size/color scores, sector aggregation
- P3: MarketView, decision_labels, render_market_page, render_divergence_pool with heatmap
- P4: Drawer HTML, heatmap JS, tooltip
- P5: Static export, generate_market_report
"""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ╔══════════════════════════════════════════════════════════════════╗
# ║  P1: Market Agents + market_context                            ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestMarketPrompts:
    """Test market agent prompt generation."""

    def test_macro_analyst_prompt(self):
        from subagent_pipeline.prompts import macro_analyst
        prompt = macro_analyst("2026-03-13", "## 指数\n上证 3200")
        assert "Macro Analyst" in prompt
        assert "RISK_ON" in prompt
        assert "MACRO_OUTPUT" in prompt
        assert "position_cap_multiplier" in prompt

    def test_market_breadth_agent_prompt(self):
        from subagent_pipeline.prompts import market_breadth_agent
        prompt = market_breadth_agent("2026-03-13")
        assert "Breadth" in prompt
        assert "BREADTH_OUTPUT" in prompt
        assert "HEALTHY" in prompt

    def test_sector_rotation_agent_prompt(self):
        from subagent_pipeline.prompts import sector_rotation_agent
        prompt = sector_rotation_agent("2026-03-13")
        assert "Sector Rotation" in prompt
        assert "SECTOR_OUTPUT" in prompt
        assert "sector_leaders" in prompt

    def test_market_analyst_with_context_block(self):
        from subagent_pipeline.prompts import market_analyst
        prompt = market_analyst("601985", "2026-03-13", market_context_block="regime=RISK_ON")
        assert "市场环境" in prompt
        assert "regime" in prompt

    def test_market_analyst_without_context_block(self):
        from subagent_pipeline.prompts import market_analyst
        prompt = market_analyst("601985", "2026-03-13")
        assert "市场环境" not in prompt

    def test_research_manager_with_context_block(self):
        from subagent_pipeline.prompts import research_manager
        prompt = research_manager("601985", "debate input", market_context_block="regime=RISK_OFF")
        assert "市场环境" in prompt
        assert "市场大方向" in prompt

    def test_risk_manager_with_context_block(self):
        from subagent_pipeline.prompts import risk_manager
        prompt = risk_manager("中国核电", "plan", market_context_block="position_cap_multiplier=0.5")
        assert "仓位约束" in prompt
        assert "avoid_sectors" in prompt

    def test_market_input_block(self):
        from subagent_pipeline.shared import market_input_block
        block = market_input_block("2026-03-13")
        assert "Market-Level" in block
        assert "2026-03-13" in block


class TestMarketParsers:
    """Test market agent output parsers."""

    def test_parse_macro_output_kv(self):
        from subagent_pipeline.bridge import parse_macro_output
        text = """Analysis here...
MACRO_OUTPUT:
regime = RISK_ON
market_weather = 指数运行在MA20上方，市场情绪偏暖
position_cap_multiplier = 1.0
style_bias = 成长
risk_alerts = NONE
client_summary = 市场处于进攻状态
"""
        result = parse_macro_output(text)
        assert result["regime"] == "RISK_ON"
        assert result["position_cap_multiplier"] == 1.0
        assert "成长" in str(result["style_bias"])

    def test_parse_macro_output_json(self):
        from subagent_pipeline.bridge import parse_macro_output
        text = """Analysis...
MACRO_OUTPUT:
```json
{"regime": "RISK_OFF", "position_cap_multiplier": 0.5, "market_weather": "大盘破位", "style_bias": "价值", "risk_alerts": "地缘风险", "client_summary": "防御模式"}
```
"""
        result = parse_macro_output(text)
        assert result["regime"] == "RISK_OFF"
        assert result["position_cap_multiplier"] == 0.5

    def test_parse_macro_output_empty(self):
        from subagent_pipeline.bridge import parse_macro_output
        result = parse_macro_output("no output here")
        assert result == {}

    def test_parse_breadth_output(self):
        from subagent_pipeline.bridge import parse_breadth_output
        text = """BREADTH_OUTPUT:
breadth_state = HEALTHY
advance_decline_ratio = 1.45
breadth_trend = improving
risk_note = 暂无明显风险
"""
        result = parse_breadth_output(text)
        assert result["breadth_state"] == "HEALTHY"
        assert result["advance_decline_ratio"] == 1.45

    def test_parse_sector_output_with_arrays(self):
        from subagent_pipeline.bridge import parse_sector_output
        text = """SECTOR_OUTPUT:
sector_leaders = [核电, 半导体, 新能源]
avoid_sectors = [房地产, 白酒]
rotation_phase = mid
sector_momentum = [{"name": "核电", "flow": "5.2", "direction": "in"}]
"""
        result = parse_sector_output(text)
        assert isinstance(result["sector_leaders"], list)
        assert "核电" in result["sector_leaders"]
        assert isinstance(result["avoid_sectors"], list)
        assert result["rotation_phase"] == "mid"

    def test_parse_sector_output_json(self):
        from subagent_pipeline.bridge import parse_sector_output
        text = """SECTOR_OUTPUT:
```json
{"sector_leaders": ["AI", "核电"], "avoid_sectors": ["地产"], "rotation_phase": "early", "sector_momentum": []}
```
"""
        result = parse_sector_output(text)
        assert "AI" in result["sector_leaders"]


class TestAssembleMarketContext:
    """Test market context assembly."""

    def test_assemble_basic(self):
        from subagent_pipeline.bridge import assemble_market_context
        macro = {"regime": "RISK_ON", "position_cap_multiplier": 1.0,
                 "market_weather": "好天气", "style_bias": "成长"}
        breadth = {"breadth_state": "HEALTHY", "advance_decline_ratio": 1.5}
        sector = {"sector_leaders": ["核电", "AI"], "avoid_sectors": ["地产"],
                  "rotation_phase": "mid"}
        ctx = assemble_market_context(macro, breadth, sector, "2026-03-13")
        assert ctx["regime"] == "RISK_ON"
        assert ctx["breadth_state"] == "HEALTHY"
        assert "核电" in ctx["sector_leaders"]
        assert ctx["position_cap_multiplier"] == 1.0
        assert ctx["trade_date"] == "2026-03-13"

    def test_assemble_defaults(self):
        from subagent_pipeline.bridge import assemble_market_context
        ctx = assemble_market_context({}, {}, {})
        assert ctx["regime"] == "NEUTRAL"
        assert ctx["breadth_state"] == "NARROW"
        assert ctx["position_cap_multiplier"] == 0.8

    def test_assemble_string_pcm(self):
        from subagent_pipeline.bridge import assemble_market_context
        ctx = assemble_market_context({"position_cap_multiplier": "0.6"}, {}, {})
        assert ctx["position_cap_multiplier"] == 0.6

    def test_assemble_string_sectors(self):
        from subagent_pipeline.bridge import assemble_market_context
        ctx = assemble_market_context({}, {}, {"sector_leaders": "核电, 半导体, AI"})
        assert ctx["sector_leaders"] == ["核电", "半导体", "AI"]

    def test_format_market_context_block(self):
        from subagent_pipeline.bridge import format_market_context_block
        ctx = {
            "regime": "RISK_ON", "market_weather": "阳光", "position_cap_multiplier": 1.0,
            "style_bias": "成长", "breadth_state": "HEALTHY", "advance_decline_ratio": "1.5",
            "breadth_trend": "improving", "sector_leaders": ["核电"], "avoid_sectors": ["地产"],
            "rotation_phase": "mid", "risk_alerts": "NONE",
        }
        block = format_market_context_block(ctx)
        assert "RISK_ON" in block
        assert "核电" in block
        assert "地产" in block

    def test_format_empty_context(self):
        from subagent_pipeline.bridge import format_market_context_block
        assert format_market_context_block({}) == ""
        assert format_market_context_block(None) == ""


class TestMarketConfig:
    """Test config additions for market agents."""

    def test_models_include_market_agents(self):
        from subagent_pipeline.config import PIPELINE_CONFIG
        models = PIPELINE_CONFIG["models"]
        assert "macro_analyst" in models
        assert "market_breadth_agent" in models
        assert "sector_rotation_agent" in models

    def test_pipeline_stages_include_market(self):
        from subagent_pipeline.config import PIPELINE_STAGES
        market_stage = [s for s in PIPELINE_STAGES if s["stage"] == 0.8]
        assert len(market_stage) == 1
        assert market_stage[0]["run_once_per_day"] is True
        assert "macro_analyst" in market_stage[0]["agents"]

    def test_agent_node_map_market(self):
        from subagent_pipeline.bridge import AGENT_NODE_MAP
        assert AGENT_NODE_MAP["macro_analyst"] == "Macro Analyst"
        assert AGENT_NODE_MAP["market_breadth_agent"] == "Market Breadth"
        assert AGENT_NODE_MAP["sector_rotation_agent"] == "Sector Rotation"


class TestMarketStructuredData:
    """Test that market agents populate structured_data correctly."""

    def test_macro_node_trace(self):
        from subagent_pipeline.bridge import build_node_trace
        text = """Analysis...
MACRO_OUTPUT:
regime = RISK_ON
market_weather = 暖
position_cap_multiplier = 1.0
style_bias = 成长
risk_alerts = NONE
client_summary = 好
"""
        nt = build_node_trace("macro_analyst", text, "run-test")
        assert nt.node_name == "Macro Analyst"
        assert nt.structured_data["regime"] == "RISK_ON"

    def test_breadth_node_trace(self):
        from subagent_pipeline.bridge import build_node_trace
        text = """BREADTH_OUTPUT:
breadth_state = DETERIORATING
advance_decline_ratio = 0.6
breadth_trend = deteriorating
risk_note = 注意
"""
        nt = build_node_trace("market_breadth_agent", text, "run-test")
        assert nt.structured_data["breadth_state"] == "DETERIORATING"

    def test_sector_node_trace(self):
        from subagent_pipeline.bridge import build_node_trace
        text = """SECTOR_OUTPUT:
sector_leaders = [AI, 核电]
avoid_sectors = [地产]
rotation_phase = late
"""
        nt = build_node_trace("sector_rotation_agent", text, "run-test")
        assert isinstance(nt.structured_data["sector_leaders"], list)

    def test_market_agent_fallback(self):
        from subagent_pipeline.bridge import build_node_trace
        nt = build_node_trace("macro_analyst", "no structured output", "run-test")
        assert nt.parse_status == "fallback_used"


# ╔══════════════════════════════════════════════════════════════════╗
# ║  P2: Heatmap Data                                              ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestHeatmapScores:
    """Test size and color score computation."""

    def test_compute_size_score_range(self):
        from subagent_pipeline.heatmap import compute_size_score
        # All values should be 0-1
        caps = [10, 100, 1000, 5000]
        for c in caps:
            s = compute_size_score(c, caps)
            assert 0 <= s <= 1

    def test_compute_size_score_single(self):
        from subagent_pipeline.heatmap import compute_size_score
        assert compute_size_score(100, [100]) == 0.5

    def test_compute_size_score_extremes(self):
        from subagent_pipeline.heatmap import compute_size_score
        caps = [10, 10000]
        assert compute_size_score(10, caps) == 0.0
        assert compute_size_score(10000, caps) == 1.0

    def test_compute_color_score_buy_high(self):
        from subagent_pipeline.heatmap import compute_color_score
        score = compute_color_score("BUY", 0.9, "PASS")
        assert score > 0.8

    def test_compute_color_score_sell(self):
        from subagent_pipeline.heatmap import compute_color_score
        score = compute_color_score("SELL", 0.7, "PASS")
        assert score < -0.2

    def test_compute_color_score_veto(self):
        from subagent_pipeline.heatmap import compute_color_score
        score = compute_color_score("VETO", 0.9, "VETO")
        assert score < -0.6

    def test_compute_color_score_hold(self):
        from subagent_pipeline.heatmap import compute_color_score
        score = compute_color_score("HOLD", 0.5, "PASS")
        assert -0.2 <= score <= 0.4

    def test_color_score_to_hex(self):
        from subagent_pipeline.heatmap import color_score_to_hex
        assert color_score_to_hex(0.9) == "#1a7f37"
        assert color_score_to_hex(0.5) == "#3fb950"
        assert color_score_to_hex(0.0) == "#d29922"
        assert color_score_to_hex(-0.4) == "#da3633"
        assert color_score_to_hex(-0.8) == "#8b1325"


class TestHeatmapNode:
    """Test HeatmapNode dataclass."""

    def test_defaults(self):
        from subagent_pipeline.heatmap import HeatmapNode
        n = HeatmapNode()
        assert n.market_wind == ""
        assert n.bull_claims_top3 == []

    def test_with_values(self):
        from subagent_pipeline.heatmap import HeatmapNode
        n = HeatmapNode(
            id="601985.SS", ticker="601985.SS", name="中国核电",
            action="BUY", confidence=0.72, market_wind="顺风",
        )
        assert n.name == "中国核电"
        assert n.market_wind == "顺风"


class TestHeatmapData:
    """Test HeatmapData construction and serialization."""

    def _make_pool_view(self):
        """Create a minimal DivergencePoolView for testing."""
        from subagent_pipeline.renderers.views import StockDivergenceRow, DivergencePoolView
        rows = [
            StockDivergenceRow(
                run_id="run-001", ticker="601985.SS", ticker_name="中国核电",
                trade_date="2026-03-13", action="BUY", action_label="建议关注",
                action_class="buy", confidence=0.72, risk_cleared=True,
                bull_claims=[{"text": "核电审批加速", "confidence": 0.85}],
                bear_claims=[{"text": "电价下行", "confidence": 0.65}],
                risk_flags=[{"category": "估值风险", "severity": "medium"}],
                market_cap="800",
            ),
            StockDivergenceRow(
                run_id="run-002", ticker="300627.SZ", ticker_name="华测导航",
                trade_date="2026-03-13", action="HOLD", action_label="维持观察",
                action_class="hold", confidence=0.55, risk_cleared=True,
                market_cap="200",
            ),
        ]
        return DivergencePoolView(
            trade_date="2026-03-13", rows=rows, total_stocks=2,
            buy_count=1, hold_count=1,
        )

    def test_build_from_pool(self):
        from subagent_pipeline.heatmap import HeatmapData
        pool = self._make_pool_view()
        ctx = {"regime": "RISK_ON", "sector_leaders": ["核电"], "avoid_sectors": ["地产"]}
        spots = {"601985": {"name": "中国核电", "price": 8.5, "pct_change": 2.31, "market_cap": 2000e8}}
        hm = HeatmapData.build_from_pool(pool, market_context=ctx, spot_data=spots)
        assert len(hm.nodes) == 2
        assert hm.nodes[0].action == "BUY"

    def test_to_dict(self):
        from subagent_pipeline.heatmap import HeatmapData
        pool = self._make_pool_view()
        hm = HeatmapData.build_from_pool(pool)
        d = hm.to_dict()
        assert "nodes" in d
        assert "sectors" in d
        assert len(d["nodes"]) == 2

    def test_market_wind_assignment(self):
        from subagent_pipeline.heatmap import HeatmapData
        pool = self._make_pool_view()
        ctx = {"regime": "RISK_ON", "sector_leaders": [], "avoid_sectors": []}
        hm = HeatmapData.build_from_pool(pool, market_context=ctx)
        # BUY in RISK_ON → 顺风
        assert hm.nodes[0].market_wind == "顺风"

    def test_sector_status(self):
        from subagent_pipeline.heatmap import HeatmapData
        pool = self._make_pool_view()
        ctx = {"regime": "NEUTRAL", "sector_leaders": ["核电"], "avoid_sectors": []}
        spots = {"601985": {"sector": "核电"}}
        hm = HeatmapData.build_from_pool(pool, market_context=ctx, spot_data=spots)
        assert hm.nodes[0].sector_status == "主线板块"


class TestSectorAggregation:
    """Test sector aggregation logic."""

    def test_build_sector_aggregates(self):
        from subagent_pipeline.heatmap import HeatmapNode, build_sector_aggregates
        nodes = [
            HeatmapNode(sector="核电", market_cap=800, pct_change=2.0, action="BUY"),
            HeatmapNode(sector="核电", market_cap=500, pct_change=1.5, action="HOLD"),
            HeatmapNode(sector="半导体", market_cap=300, pct_change=-1.0, action="SELL"),
        ]
        sectors = build_sector_aggregates(nodes)
        assert len(sectors) == 2
        nuke = [s for s in sectors if s["name"] == "核电"][0]
        assert nuke["count"] == 2
        assert nuke["buy_count"] == 1
        assert nuke["hold_count"] == 1

    def test_empty_nodes(self):
        from subagent_pipeline.heatmap import build_sector_aggregates
        assert build_sector_aggregates([]) == []


# ╔══════════════════════════════════════════════════════════════════╗
# ║  P3: MarketView + Decision Labels + Rendering                 ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestDecisionLabels:
    """Test new market-level labels."""

    def test_regime_labels(self):
        from subagent_pipeline.renderers.decision_labels import get_regime_label, get_regime_class
        assert get_regime_label("RISK_ON") == "进攻"
        assert get_regime_class("RISK_ON") == "buy"
        assert get_regime_label("RISK_OFF") == "防御"
        assert get_regime_class("RISK_OFF") == "sell"

    def test_breadth_labels(self):
        from subagent_pipeline.renderers.decision_labels import get_breadth_label, get_breadth_class
        assert get_breadth_label("HEALTHY") == "健康"
        assert get_breadth_class("DETERIORATING") == "sell"

    def test_node_name_labels_market(self):
        from subagent_pipeline.renderers.decision_labels import NODE_NAME_LABELS
        assert NODE_NAME_LABELS["Macro Analyst"] == "宏观分析师"
        assert NODE_NAME_LABELS["Market Breadth"] == "市场宽度分析"
        assert NODE_NAME_LABELS["Sector Rotation"] == "板块轮动分析"


class TestMarketView:
    """Test MarketView construction."""

    def test_build_basic(self):
        from subagent_pipeline.renderers.views import MarketView
        ctx = {
            "trade_date": "2026-03-13",
            "regime": "RISK_ON",
            "position_cap_multiplier": 1.0,
            "style_bias": "成长",
            "client_summary": "市场偏暖",
            "breadth_state": "HEALTHY",
            "sector_leaders": ["核电"],
            "avoid_sectors": ["地产"],
            "rotation_phase": "mid",
        }
        view = MarketView.build(market_context=ctx)
        assert view.regime == "RISK_ON"
        assert view.regime_label == "进攻"
        assert view.regime_class == "buy"
        assert view.breadth_label == "健康"
        assert "核电" in view.sector_leaders

    def test_build_empty(self):
        from subagent_pipeline.renderers.views import MarketView
        view = MarketView.build(market_context={})
        assert view.regime == "NEUTRAL"
        assert view.regime_label == "中性"


class TestRenderMarketPage:
    """Test market page rendering."""

    def test_render_contains_key_elements(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import render_market_page
        ctx = {
            "trade_date": "2026-03-13", "regime": "RISK_ON",
            "position_cap_multiplier": 1.0, "client_summary": "市场偏暖",
            "breadth_state": "HEALTHY", "sector_leaders": ["核电"],
            "avoid_sectors": ["地产"], "market_weather": "阳光明媚",
        }
        view = MarketView.build(market_context=ctx)
        html = render_market_page(view)
        assert "<!DOCTYPE html>" in html
        assert "市场指挥台" in html
        assert "进攻" in html
        assert "核电" in html
        assert "地产" in html
        assert "仓位乘数" in html

    def test_render_no_external_links(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import render_market_page
        view = MarketView.build(market_context={"trade_date": "2026-03-13"})
        html = render_market_page(view)
        # Should be fully self-contained
        assert '<link href=' not in html
        assert '<script src=' not in html

    def test_render_responsive_css(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import render_market_page
        view = MarketView.build(market_context={"trade_date": "2026-03-13"})
        html = render_market_page(view)
        assert "@media" in html
        assert "768px" in html


class TestRenderPoolWithHeatmap:
    """Test render_divergence_pool with heatmap data."""

    def _make_pool_and_heatmap(self):
        from subagent_pipeline.renderers.views import StockDivergenceRow, DivergencePoolView
        from subagent_pipeline.heatmap import HeatmapData
        rows = [
            StockDivergenceRow(
                run_id="run-001", ticker="601985.SS", ticker_name="中国核电",
                action="BUY", action_label="建议关注", action_class="buy",
                confidence=0.72, risk_cleared=True, trade_date="2026-03-13",
                bull_claims=[{"text": "核电审批加速", "confidence": 0.85}],
                market_cap="800",
            ),
        ]
        pool = DivergencePoolView(
            trade_date="2026-03-13", rows=rows, total_stocks=1, buy_count=1,
        )
        hm = HeatmapData.build_from_pool(pool)
        return pool, hm

    def test_pool_with_heatmap(self):
        from subagent_pipeline.renderers.report_renderer import render_divergence_pool
        pool, hm = self._make_pool_and_heatmap()
        ctx = {"regime": "RISK_ON", "client_summary": "市场偏暖"}
        html = render_divergence_pool(pool, heatmap_data=hm, market_context=ctx)
        assert "热力图" in html
        assert "hm-node" in html

    def test_pool_without_heatmap(self):
        from subagent_pipeline.renderers.report_renderer import render_divergence_pool
        pool, _ = self._make_pool_and_heatmap()
        html = render_divergence_pool(pool)
        assert "热力图" not in html

    def test_pool_with_market_banner(self):
        from subagent_pipeline.renderers.report_renderer import render_divergence_pool
        pool, _ = self._make_pool_and_heatmap()
        ctx = {"regime": "RISK_ON", "client_summary": "市场偏暖"}
        html = render_divergence_pool(pool, market_context=ctx)
        assert "market-summary-banner" in html
        assert "进攻" in html


# ╔══════════════════════════════════════════════════════════════════╗
# ║  P4: Drawer + Bottom Sheet                                    ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestDrawer:
    """Test drawer and tooltip rendering."""

    def test_drawer_html_structure(self):
        from subagent_pipeline.renderers.report_renderer import _render_detail_drawer
        html = _render_detail_drawer()
        assert "detail-drawer" in html
        assert "drawer-overlay" in html
        assert "drawer-close" in html
        assert "drawerTitle" in html
        assert "drawerPct" in html
        assert "drawerAction" in html
        assert "drawerSector" in html

    def test_heatmap_js_structure(self):
        from subagent_pipeline.renderers.report_renderer import _render_heatmap_js
        data = {
            "nodes": [
                {"id": "601985.SS", "name": "中国核电", "action": "BUY",
                 "confidence": 0.72, "pct_change": 2.31, "action_label": "建议关注",
                 "market_wind": "顺风", "sector_status": "主线板块",
                 "bull_claims_top3": [{"text": "核电审批", "confidence": 0.85}],
                 "bear_claims_top3": [], "risk_flags": [], "detail_ref": "run-001"},
            ],
        }
        js = _render_heatmap_js(data)
        assert "openDrawer" in js
        assert "closeDrawer" in js
        assert "mouseenter" in js  # tooltip
        assert "hm-tooltip" in js

    def test_drawer_mobile_css(self):
        from subagent_pipeline.renderers.report_renderer import _MARKET_CSS
        assert "767px" in _MARKET_CSS
        assert "translateY" in _MARKET_CSS
        assert "border-radius: 14px 14px 0 0" in _MARKET_CSS


# ╔══════════════════════════════════════════════════════════════════╗
# ║  P5: Static Export                                             ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestStaticExport:
    """Test static HTML export generation."""

    def test_generate_market_report(self, tmp_path):
        from subagent_pipeline.renderers.report_renderer import generate_market_report
        ctx = {
            "trade_date": "2026-03-13", "regime": "RISK_ON",
            "client_summary": "市场偏暖", "breadth_state": "HEALTHY",
            "sector_leaders": ["核电"], "avoid_sectors": [],
        }
        path = generate_market_report(
            market_context=ctx,
            output_dir=str(tmp_path),
            trade_date="2026-03-13",
        )
        assert path is not None
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "市场总览" in content

    def test_generate_market_report_none(self, tmp_path):
        from subagent_pipeline.renderers.report_renderer import generate_market_report
        path = generate_market_report(
            market_context={},
            output_dir=str(tmp_path),
        )
        assert path is None

    def test_market_report_self_contained(self, tmp_path):
        from subagent_pipeline.renderers.report_renderer import generate_market_report
        ctx = {"trade_date": "2026-03-13", "regime": "NEUTRAL", "client_summary": "中性"}
        path = generate_market_report(market_context=ctx, output_dir=str(tmp_path))
        content = Path(path).read_text(encoding="utf-8")
        assert '<link href=' not in content
        assert '<script src=' not in content


# ╔══════════════════════════════════════════════════════════════════╗
# ║  SVG Treemap Algorithm                                         ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestSquarify:
    """Test the squarified treemap layout algorithm."""

    def test_basic_layout(self):
        from subagent_pipeline.renderers.report_renderer import _squarify
        values = [(0, 60), (1, 30), (2, 10)]
        rects = _squarify(values, 0, 0, 400, 300)
        assert len(rects) == 3
        # All rects should be within bounds
        for idx, x, y, w, h in rects:
            assert x >= 0
            assert y >= 0
            assert w > 0
            assert h > 0

    def test_single_value(self):
        from subagent_pipeline.renderers.report_renderer import _squarify
        rects = _squarify([(0, 100)], 0, 0, 400, 300)
        assert len(rects) == 1

    def test_empty_values(self):
        from subagent_pipeline.renderers.report_renderer import _squarify
        rects = _squarify([], 0, 0, 400, 300)
        assert rects == []

    def test_equal_values(self):
        from subagent_pipeline.renderers.report_renderer import _squarify
        values = [(i, 25) for i in range(4)]
        rects = _squarify(values, 0, 0, 200, 200)
        assert len(rects) == 4


class TestSVGHeatmap:
    """Test SVG heatmap rendering."""

    def test_render_basic(self):
        from subagent_pipeline.renderers.report_renderer import _render_svg_heatmap
        data = {
            "nodes": [
                {"name": "A", "market_cap": 100, "color_score": 0.8, "pct_change": 2.0,
                 "ticker": "000001", "detail_ref": "r1"},
                {"name": "B", "market_cap": 50, "color_score": -0.5, "pct_change": -1.0,
                 "ticker": "000002", "detail_ref": "r2"},
            ],
        }
        svg = _render_svg_heatmap(data)
        assert "<svg" in svg
        assert "hm-node" in svg
        assert "data-ticker" in svg

    def test_render_empty(self):
        from subagent_pipeline.renderers.report_renderer import _render_svg_heatmap
        result = _render_svg_heatmap({"nodes": []})
        assert result == ""


# ╔══════════════════════════════════════════════════════════════════╗
# ║  MarketSnapshot (akshare_collector)                            ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestMarketSnapshot:
    """Test MarketSnapshot dataclass and markdown builder."""

    def test_snapshot_defaults(self):
        from subagent_pipeline.akshare_collector import MarketSnapshot
        ms = MarketSnapshot(trade_date="2026-03-13")
        assert ms.advance_count == 0
        assert ms.stock_spots == {}

    def test_build_market_markdown(self):
        from subagent_pipeline.akshare_collector import MarketSnapshot, _build_market_markdown
        ms = MarketSnapshot(
            trade_date="2026-03-13",
            advance_count=2500,
            decline_count=2000,
            limit_up_count=30,
            limit_down_count=5,
            total_stocks=5000,
            index_data={
                "sh000001": {"name": "上证指数", "close": 3200.0, "change_pct": 0.5, "volume": 1e10},
            },
        )
        md = _build_market_markdown(ms)
        assert "上证指数" in md
        assert "2500" in md
        assert "2026-03-13" in md


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Market Route                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestMarketRoute:
    """Test market route helper."""

    def test_load_market_context(self, tmp_path):
        from dashboard.routes.market import _load_market_context
        # Write a test context file
        ctx = {"regime": "RISK_ON", "trade_date": "2026-03-13"}
        ctx_path = tmp_path / "market_context_2026-03-13.json"
        ctx_path.write_text(json.dumps(ctx), encoding="utf-8")
        loaded = _load_market_context(str(tmp_path), "2026-03-13")
        assert loaded["regime"] == "RISK_ON"

    def test_load_market_context_latest(self, tmp_path):
        from dashboard.routes.market import _load_market_context
        ctx = {"regime": "NEUTRAL"}
        (tmp_path / "market_context_2026-03-12.json").write_text(json.dumps(ctx))
        loaded = _load_market_context(str(tmp_path))
        assert loaded["regime"] == "NEUTRAL"

    def test_load_market_context_empty(self, tmp_path):
        from dashboard.routes.market import _load_market_context
        loaded = _load_market_context(str(tmp_path))
        assert loaded == {}


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Integration / Edge Cases                                      ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestEdgeCases:
    """Edge case tests for completeness."""

    def test_color_score_boundary_values(self):
        from subagent_pipeline.heatmap import compute_color_score
        # Exact boundary: BUY with confidence=0 → should still be >=0.4
        assert compute_color_score("BUY", 0.0, "PASS") >= 0.4
        # SELL with confidence=1.0 → should be <= -0.2
        assert compute_color_score("SELL", 1.0, "PASS") <= -0.2

    def test_size_score_zero_cap(self):
        from subagent_pipeline.heatmap import compute_size_score
        assert compute_size_score(0, [0, 100]) == 0.5  # fallback

    def test_heatmap_data_empty_pool(self):
        from subagent_pipeline.renderers.views import DivergencePoolView
        from subagent_pipeline.heatmap import HeatmapData
        pool = DivergencePoolView(trade_date="2026-03-13")
        hm = HeatmapData.build_from_pool(pool)
        assert hm.nodes == []

    def test_market_view_with_snapshot(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.akshare_collector import MarketSnapshot
        ms = MarketSnapshot(
            trade_date="2026-03-13",
            advance_count=2500, decline_count=2000,
            limit_up_count=30, limit_down_count=5,
            index_data={"sh000001": {"name": "上证指数", "close": 3200.0, "change_pct": 0.5}},
        )
        ctx = {"regime": "RISK_ON", "breadth_state": "HEALTHY"}
        view = MarketView.build(market_context=ctx, market_snapshot=ms)
        assert view.advance_count == 2500
        assert "上证指数" in str(view.index_sparklines)

    def test_render_market_page_with_risk_alerts(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import render_market_page
        ctx = {"trade_date": "2026-03-13", "regime": "RISK_OFF",
               "risk_alerts": "地缘风险升级", "client_summary": "防御模式"}
        view = MarketView.build(market_context=ctx)
        html = render_market_page(view)
        assert "地缘风险升级" in html
        assert "alert-strip" in html

    def test_render_index_cards(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import _render_idx_battle_cards
        view = MarketView(
            index_sparklines={
                "sh000001": {"name": "上证指数", "close": 3200.0, "change_pct": 1.5},
            }
        )
        html = _render_idx_battle_cards(view)
        assert "上证指数" in html
        assert "+1.50%" in html

    def test_render_hero(self):
        from subagent_pipeline.renderers.views import MarketView
        from subagent_pipeline.renderers.report_renderer import _render_mkt_hero
        view = MarketView(regime_label="进攻", regime_class="buy",
                          position_cap=1.0, style_bias="成长")
        html = _render_mkt_hero(view)
        assert "进攻" in html
        assert "仓位乘数" in html
