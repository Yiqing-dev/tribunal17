"""Tests for TradePlan protocol, parser, and rendering.

Covers:
1. Protocol dataclass (TradePlan, EntrySetup, StopLoss, TakeProfit)
2. Bridge parser (parse_trade_plan_json)
3. Bridge structured_data wiring
4. Report renderer (_render_trade_plan_card)
5. View integration (ResearchView.trade_plan, StockDivergenceRow.trade_plan)
"""

import json
import pytest

try:
    from tradingagents.agents.protocol import TradePlan  # noqa: F401
    _HAS_TA = True
except ImportError:
    _HAS_TA = False

try:
    import dashboard  # noqa: F401
    _HAS_DASH = True
except ImportError:
    _HAS_DASH = False


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

SAMPLE_TRADE_PLAN = {
    "bias": "LONG",
    "entry_setups": [
        {
            "type": "breakout",
            "label": "突破买点",
            "price_zone": [12.40, 12.75],
            "condition": "放量突破近20日高点",
            "strength": "high",
        },
        {
            "type": "pullback",
            "label": "回踩买点",
            "price_zone": [11.80, 12.00],
            "condition": "回踩5日/14日均线企稳",
            "strength": "medium",
        },
    ],
    "stop_loss": {"price": 11.35, "rule": "跌破14日均线且放量转弱"},
    "take_profit": [
        {"label": "第一目标位", "price_zone": [13.60, 13.90]},
        {"label": "第二目标位", "price_zone": [14.50, 15.00]},
    ],
    "invalidators": [
        "板块强度跌出前20%",
        "市场环境转为RISK_OFF",
        "核心利好证伪",
    ],
    "holding_horizon": "short_swing",
    "confidence": 0.72,
}


def _wrap_in_llm_output(plan_dict: dict, label: str = "TRADE_PLAN_JSON") -> str:
    """Wrap a trade plan dict as if it came from LLM output."""
    inner = json.dumps({"trade_plan": plan_dict}, ensure_ascii=False, indent=2)
    return f"Some analysis text...\n\n{label}\n```json\n{inner}\n```\n\nMore text..."


# ────────────────────────────────────────────────────────────────────
# 1. Protocol tests
# ────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TA, reason="tradingagents package not installed")
class TestTradePlanProtocol:
    """Test TradePlan dataclass and serialization."""

    def test_default_values(self):
        from tradingagents.agents.protocol import TradePlan
        tp = TradePlan()
        assert tp.bias == "WAIT"
        assert tp.entry_setups == []
        assert tp.stop_loss is None
        assert tp.take_profit == []
        assert tp.invalidators == []
        assert tp.confidence == 0.5

    def test_to_dict(self):
        from tradingagents.agents.protocol import TradePlan, EntrySetup, StopLoss, TakeProfit
        tp = TradePlan(
            bias="LONG",
            entry_setups=[EntrySetup(type="breakout", label="突破", price_zone=[10, 11])],
            stop_loss=StopLoss(price=9.5, rule="跌破支撑"),
            take_profit=[TakeProfit(label="目标1", price_zone=[12, 13])],
            invalidators=["条件A"],
            holding_horizon="short_swing",
            confidence=0.8,
        )
        d = tp.to_dict()
        assert d["bias"] == "LONG"
        assert len(d["entry_setups"]) == 1
        assert d["entry_setups"][0]["type"] == "breakout"
        assert d["stop_loss"]["price"] == 9.5
        assert d["take_profit"][0]["label"] == "目标1"
        assert d["invalidators"] == ["条件A"]
        assert d["confidence"] == 0.8

    def test_to_dict_no_stop_loss(self):
        from tradingagents.agents.protocol import TradePlan
        tp = TradePlan(bias="WAIT")
        d = tp.to_dict()
        assert d["stop_loss"] is None

    def test_from_dict(self):
        from tradingagents.agents.protocol import TradePlan
        tp = TradePlan.from_dict(SAMPLE_TRADE_PLAN)
        assert tp.bias == "LONG"
        assert len(tp.entry_setups) == 2
        assert tp.entry_setups[0].label == "突破买点"
        assert tp.entry_setups[0].price_zone == [12.40, 12.75]
        assert tp.stop_loss.price == 11.35
        assert tp.stop_loss.rule == "跌破14日均线且放量转弱"
        assert len(tp.take_profit) == 2
        assert tp.take_profit[1].price_zone == [14.50, 15.00]
        assert len(tp.invalidators) == 3
        assert tp.holding_horizon == "short_swing"
        assert tp.confidence == 0.72

    def test_from_dict_empty(self):
        from tradingagents.agents.protocol import TradePlan
        tp = TradePlan.from_dict({})
        assert tp.bias == "WAIT"
        assert tp.entry_setups == []
        assert tp.stop_loss is None

    def test_from_dict_none(self):
        from tradingagents.agents.protocol import TradePlan
        tp = TradePlan.from_dict(None)
        assert tp.bias == "WAIT"

    def test_roundtrip(self):
        from tradingagents.agents.protocol import TradePlan
        tp1 = TradePlan.from_dict(SAMPLE_TRADE_PLAN)
        d = tp1.to_dict()
        tp2 = TradePlan.from_dict(d)
        assert tp2.bias == tp1.bias
        assert len(tp2.entry_setups) == len(tp1.entry_setups)
        assert tp2.stop_loss.price == tp1.stop_loss.price
        assert tp2.confidence == tp1.confidence


# ────────────────────────────────────────────────────────────────────
# 2. Parser tests
# ────────────────────────────────────────────────────────────────────

class TestParseTradePlan:
    """Test parse_trade_plan_json in bridge.py."""

    def test_wrapped_format(self):
        from subagent_pipeline.bridge import parse_trade_plan_json
        text = _wrap_in_llm_output(SAMPLE_TRADE_PLAN)
        result = parse_trade_plan_json(text)
        assert result["bias"] == "LONG"
        assert len(result["entry_setups"]) == 2
        assert result["stop_loss"]["price"] == 11.35

    def test_direct_format(self):
        """JSON block with bias/entry_setups directly (no trade_plan wrapper)."""
        from subagent_pipeline.bridge import parse_trade_plan_json
        inner = json.dumps(SAMPLE_TRADE_PLAN, ensure_ascii=False, indent=2)
        text = f"```json\n{inner}\n```"
        result = parse_trade_plan_json(text)
        assert result["bias"] == "LONG"

    def test_no_match(self):
        from subagent_pipeline.bridge import parse_trade_plan_json
        assert parse_trade_plan_json("no json here") == {}
        assert parse_trade_plan_json("") == {}

    def test_trailing_comma_fix(self):
        from subagent_pipeline.bridge import parse_trade_plan_json
        text = '''TRADE_PLAN_JSON
```json
{
  "trade_plan": {
    "bias": "WAIT",
    "entry_setups": [],
    "stop_loss": null,
    "take_profit": [],
    "invalidators": ["test",],
    "holding_horizon": "",
    "confidence": 0.3,
  }
}
```'''
        result = parse_trade_plan_json(text)
        assert result["bias"] == "WAIT"
        assert result["confidence"] == 0.3

    def test_avoid_bias(self):
        from subagent_pipeline.bridge import parse_trade_plan_json
        plan = {
            "bias": "AVOID",
            "entry_setups": [],
            "stop_loss": None,
            "take_profit": [],
            "invalidators": ["风控否决，不建议参与"],
            "holding_horizon": "",
            "confidence": 0.15,
        }
        text = _wrap_in_llm_output(plan)
        result = parse_trade_plan_json(text)
        assert result["bias"] == "AVOID"
        assert result["entry_setups"] == []

    def test_coexists_with_tradecard(self):
        """Both TRADECARD_JSON and TRADE_PLAN_JSON in same output."""
        from subagent_pipeline.bridge import parse_trade_plan_json, parse_tradecard_json
        text = '''
TRADECARD_JSON
```json
{"symbol": "601985", "side": "BUY", "rationale": "test", "pillars": {}, "risk_score": 7, "manager_score": 6, "confidence": "High"}
```

TRADE_PLAN_JSON
```json
{"trade_plan": {"bias": "LONG", "entry_setups": [{"type": "breakout", "label": "突破", "price_zone": [12, 13], "condition": "放量", "strength": "high"}], "stop_loss": {"price": 11, "rule": "跌破"}, "take_profit": [], "invalidators": [], "holding_horizon": "short_swing", "confidence": 0.8}}
```
'''
        tc = parse_tradecard_json(text)
        tp = parse_trade_plan_json(text)
        assert tc["symbol"] == "601985"
        assert tp["bias"] == "LONG"


# ────────────────────────────────────────────────────────────────────
# 3. Bridge structured_data wiring
# ────────────────────────────────────────────────────────────────────

class TestBridgeWiring:
    """Test that trade_plan is populated in NodeTrace structured_data."""

    def test_research_output_with_trade_plan(self):
        from subagent_pipeline.bridge import build_node_trace
        text = '''
TRADECARD_JSON
```json
{"symbol": "601985", "side": "BUY", "rationale": "test", "pillars": {}, "risk_score": 7, "manager_score": 6, "confidence": "High"}
```

TRADE_PLAN_JSON
```json
{"trade_plan": {"bias": "LONG", "entry_setups": [{"type": "breakout", "label": "突破买点", "price_zone": [12.40, 12.75], "condition": "放量", "strength": "high"}], "stop_loss": {"price": 11.35, "rule": "跌破均线"}, "take_profit": [{"label": "第一目标", "price_zone": [13.60, 13.90]}], "invalidators": ["条件A"], "holding_horizon": "short_swing", "confidence": 0.72}}
```

FINAL TRANSACTION PROPOSAL: **BUY**
'''
        nt = build_node_trace("research_output", text, "test-run")
        sd = nt.structured_data
        assert "tradecard" in sd
        assert "trade_plan" in sd
        assert sd["trade_plan"]["bias"] == "LONG"
        assert sd["trade_plan"]["stop_loss"]["price"] == 11.35

    def test_research_output_without_trade_plan(self):
        from subagent_pipeline.bridge import build_node_trace
        text = '''
TRADECARD_JSON
```json
{"symbol": "601985", "side": "HOLD", "rationale": "test", "pillars": {}, "risk_score": 5, "manager_score": 3, "confidence": "Low"}
```

FINAL TRANSACTION PROPOSAL: **HOLD**
'''
        nt = build_node_trace("research_output", text, "test-run")
        sd = nt.structured_data
        assert "tradecard" in sd
        assert "trade_plan" not in sd  # not generated

    def test_research_output_trade_plan_only(self):
        from subagent_pipeline.bridge import build_node_trace
        text = '''
TRADE_PLAN_JSON
```json
{"trade_plan": {"bias": "AVOID", "entry_setups": [], "stop_loss": null, "take_profit": [], "invalidators": ["VETO"], "holding_horizon": "", "confidence": 0.1}}
```
'''
        nt = build_node_trace("research_output", text, "test-run")
        sd = nt.structured_data
        assert "trade_plan" in sd
        assert sd["trade_plan"]["bias"] == "AVOID"


# ────────────────────────────────────────────────────────────────────
# 4. Renderer tests
# ────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_DASH, reason="dashboard package not installed")
class TestRenderTradePlanCard:
    """Test _render_trade_plan_card in report_renderer."""

    def test_full_plan(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card(SAMPLE_TRADE_PLAN)
        assert "AI 交易计划" in html
        assert "LONG" in html
        assert "偏多" in html
        assert "突破买点" in html
        assert "回踩买点" in html
        assert "12.40" in html
        assert "12.75" in html
        assert "11.35" in html
        assert "13.60" in html
        assert "14.50" in html
        assert "板块强度跌出前20%" in html
        assert "市场环境转为RISK_OFF" in html
        assert "短线波段" in html

    def test_wait_bias(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({"bias": "WAIT", "entry_setups": [], "confidence": 0.3})
        assert "等待" in html
        assert "WAIT" in html
        assert "不建议入场" in html

    def test_avoid_bias(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "AVOID",
            "entry_setups": [],
            "invalidators": ["风控否决"],
            "confidence": 0.1,
        })
        assert "回避" in html
        assert "风控否决" in html

    def test_no_stop_loss(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({"bias": "LONG", "entry_setups": [], "confidence": 0.5})
        assert "止损位" not in html

    def test_stop_loss_shown(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [],
            "stop_loss": {"price": 9.50, "rule": "跌破支撑"},
            "confidence": 0.6,
        })
        assert "9.50" in html
        assert "跌破支撑" in html

    def test_targets_shown(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [],
            "take_profit": [
                {"label": "目标1", "price_zone": [15.0, 15.5]},
            ],
            "confidence": 0.7,
        })
        assert "目标1" in html
        assert "15.00" in html
        assert "15.50" in html

    def test_high_strength_color(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [{"type": "breakout", "label": "突破", "price_zone": [10, 11],
                              "condition": "放量", "strength": "high"}],
            "confidence": 0.8,
        })
        assert "var(--green)" in html

    def test_medium_term_horizon(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG", "entry_setups": [],
            "holding_horizon": "medium_term", "confidence": 0.6,
        })
        assert "中期持有" in html

    def test_xss_escape(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [{"type": "x", "label": "<script>alert(1)</script>",
                              "price_zone": [1, 2], "condition": "test", "strength": "low"}],
            "invalidators": ['<img onerror="hack">'],
            "confidence": 0.5,
        })
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_string_confidence_numeric(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [],
            "confidence": "0.8",
        })
        assert "80%" in html

    def test_string_confidence_label(self):
        from dashboard.report_renderer import _render_trade_plan_card
        html = _render_trade_plan_card({
            "bias": "LONG",
            "entry_setups": [],
            "confidence": "High",
        })
        assert "80%" in html


# ────────────────────────────────────────────────────────────────────
# 5. View integration
# ────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_DASH, reason="dashboard package not installed")
class TestViewIntegration:
    """Test trade_plan field exists in ResearchView and StockDivergenceRow."""

    def test_research_view_has_trade_plan(self):
        from dashboard.views import ResearchView
        v = ResearchView()
        assert v.trade_plan == {}
        v.trade_plan = SAMPLE_TRADE_PLAN
        assert v.trade_plan["bias"] == "LONG"

    def test_stock_divergence_row_has_trade_plan(self):
        from dashboard.views import StockDivergenceRow
        r = StockDivergenceRow()
        assert r.trade_plan == {}
        r.trade_plan = SAMPLE_TRADE_PLAN
        assert r.trade_plan["bias"] == "LONG"

    def test_trade_plan_in_research_render(self):
        """Trade plan card appears in render_research output."""
        from dashboard.views import ResearchView
        from dashboard.report_renderer import render_research
        v = ResearchView(
            run_id="test",
            ticker="601985.SS",
            ticker_name="中国核电",
            trade_date="2026-03-13",
            research_action="BUY",
            action_label="建议关注",
            action_class="buy",
            action_explanation="测试",
            confidence=0.72,
            trade_plan=SAMPLE_TRADE_PLAN,
        )
        html = render_research(v, skip_vendors=True)
        assert "AI 交易计划" in html
        assert "突破买点" in html
        assert "11.35" in html

    def test_no_trade_plan_no_card(self):
        """Without trade_plan, no card rendered."""
        from dashboard.views import ResearchView
        from dashboard.report_renderer import render_research
        v = ResearchView(
            run_id="test",
            ticker="601985.SS",
            trade_date="2026-03-13",
            research_action="HOLD",
            action_label="观望",
            action_class="hold",
            action_explanation="测试",
            confidence=0.3,
        )
        html = render_research(v, skip_vendors=True)
        assert "AI 交易计划" not in html


# ────────────────────────────────────────────────────────────────────
# 6. Prompt integration
# ────────────────────────────────────────────────────────────────────

class TestPromptIntegration:
    """Test that research_output prompt includes TRADE_PLAN_JSON template."""

    def test_prompt_contains_trade_plan_template(self):
        from subagent_pipeline.prompts import research_output
        prompt = research_output(
            company_name="中国核电",
            investment_plan="BUY with 72% confidence",
            ticker="601985",
        )
        assert "TRADE_PLAN_JSON" in prompt
        assert "bias" in prompt
        assert "entry_setups" in prompt
        assert "stop_loss" in prompt
        assert "take_profit" in prompt
        assert "invalidators" in prompt
        assert "holding_horizon" in prompt

    def test_prompt_has_generation_rules(self):
        from subagent_pipeline.prompts import research_output
        prompt = research_output(
            company_name="中国核电",
            investment_plan="HOLD",
            ticker="601985",
        )
        assert "bias comes from PM direction" in prompt
        assert "RISK_OFF" in prompt
        assert "risk_cleared=FALSE" in prompt


class TestBriefReport:
    def test_trade_plan_only_take_profit_is_included(self, tmp_path):
        from subagent_pipeline.trace_models import RunTrace, NodeTrace
        from subagent_pipeline.replay_store import ReplayStore
        from subagent_pipeline.renderers.report_renderer import generate_brief_report

        storage_dir = tmp_path / "replays"
        store = ReplayStore(storage_dir=str(storage_dir))

        trace = RunTrace(
            run_id="run-brief-001",
            ticker="601985",
            ticker_name="中国核电",
            trade_date="2026-04-22",
            research_action="BUY",
            final_confidence=0.8,
        )
        node = NodeTrace(run_id="run-brief-001", node_name="ResearchOutput", seq=17)
        node.structured_data = {
            "trade_plan": {
                "bias": "LONG",
                "entry_setups": [],
                "stop_loss": {"price": 11.35, "rule": "跌破均线"},
                "take_profit": [
                    {"label": "第一目标", "price_zone": [13.60, 13.90]},
                ],
                "invalidators": ["条件A"],
                "holding_horizon": "short_swing",
                "confidence": 0.72,
            }
        }
        trace.node_traces = [node]
        trace.finalize()
        store.save(trace)

        md = generate_brief_report(["run-brief-001"], storage_dir=str(storage_dir))
        assert "止损 `11.35`" in md
        assert "目标 `13.75`" in md
