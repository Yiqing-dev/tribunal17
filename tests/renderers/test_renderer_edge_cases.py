"""Regression tests for renderer edge cases that previously broke output."""

from subagent_pipeline.renderers.views import _strip_internal_tokens, _summarize_display_text
from subagent_pipeline.renderers.research_renderer import _render_trade_plan_card
from subagent_pipeline.renderers.report_renderer import generate_brief_report
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.trace_models import RunTrace, NodeTrace


def test_strip_internal_tokens_preserves_tickers_and_numeric_facts():
    text = "代码 000710，601985 估值偏低，价格 123456 元不是内部ID"
    result = _strip_internal_tokens(text)
    assert "000710" in result
    assert "601985" in result
    assert "123456" in result


def test_render_trade_plan_card_accepts_string_confidence():
    html_num = _render_trade_plan_card({
        "bias": "LONG",
        "entry_setups": [],
        "confidence": "0.8",
    })
    html_label = _render_trade_plan_card({
        "bias": "LONG",
        "entry_setups": [],
        "confidence": "High",
    })

    assert "80%" in html_num
    assert "80%" in html_label


def test_summarize_display_text_skips_markdown_meta_noise():
    text = "# 601985 中国核电\n执行摘要\n- 资金承接改善，等待突破确认。"
    summary = _summarize_display_text(text, max_chars=40)
    assert summary == "资金承接改善，等待突破确认。"


def test_summarize_display_text_drops_claim_adjudication_tokens():
    text = "基于 31 条高置信度 claims 的裁决 [clm-u001 ACCEPT, clm-r011 DEFER]，等待确认。"
    summary = _summarize_display_text(text, max_chars=80)
    assert "clm-" not in summary
    assert "ACCEPT" not in summary
    assert "DEFER" not in summary
    assert "论据" in summary


def test_generate_brief_report_uses_trade_plan_take_profit(tmp_path):
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
