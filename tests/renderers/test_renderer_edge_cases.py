"""Regression tests for renderer edge cases that previously broke output."""

import os

from subagent_pipeline.renderers.views import _strip_internal_tokens, _summarize_display_text
from subagent_pipeline.renderers.research_renderer import _render_trade_plan_card
from subagent_pipeline.renderers import shared_utils
from subagent_pipeline.renderers.shared_utils import (
    _cross_nav_block,
    _html_wrap,
    _nav_bar,
    _render_report_delta_card,
    refresh_report_nav,
)
from subagent_pipeline.renderers.report_renderer import generate_brief_report
from subagent_pipeline.renderers.decision_labels import AI_DISCLAIMER_BANNER, RESEARCH_HEADER_BANNER
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
    assert "观察计划" in html_num
    assert "AI 交易计划" not in html_num


def test_trade_plan_card_uses_shareholder_facing_labels():
    html = _render_trade_plan_card({
        "bias": "LONG",
        "entry_setups": [{"label": "突破观察", "price_zone": [10.2, 10.5], "condition": "放量突破"}],
        "stop_loss": {"price": 9.8, "rule": "跌破支撑"},
        "take_profit": [{"label": "第一目标", "price_zone": [11.2, 11.6]}],
        "time_stop": "5个交易日内未突破则放弃",
        "scenario_actions": {"bear": "重新评估"},
        "confidence": 0.7,
    })

    assert "关注区间" in html
    assert "下行警戒位" in html
    assert "观察期限" in html
    assert "情景应对" in html
    assert "第一参考" in html
    assert "买入设置" not in html
    assert "止损位" not in html


def test_report_banners_use_shareholder_facing_language():
    assert "个股研究参考" in AI_DISCLAIMER_BANNER
    assert "研究报告工厂" not in AI_DISCLAIMER_BANNER
    assert "多智能体" not in AI_DISCLAIMER_BANNER
    assert "个股研究" in RESEARCH_HEADER_BANNER
    assert "不构成投资建议" in RESEARCH_HEADER_BANNER


def test_empty_nav_does_not_emit_cross_nav_sentinel():
    html = _html_wrap("标题", "<main>body</main>", "测试")

    assert _cross_nav_block("") == ""
    assert "cross-nav:start" not in html
    assert "cross-nav:end" not in html


def test_report_delta_card_renders_previous_signal_change():
    class View:
        ticker = "601985"
        run_id = "run-current"
        research_action = "BUY"
        confidence = 0.80
        signal_history = [{
            "trade_date": "2026-04-01",
            "action": "HOLD",
            "confidence": 0.50,
            "run_id": "run-prev-001",
        }]

    html = _render_report_delta_card(View())
    assert "与上次报告相比" in html
    assert "HOLD → BUY" in html
    assert "置信度 +30%" in html
    assert "601985-run-prev-001-snapshot.html" in html


def test_report_delta_card_skips_noop_and_missing_previous_confidence():
    class NoopView:
        ticker = "601985"
        run_id = "run-current"
        research_action = "HOLD"
        confidence = 0.50
        signal_history = [{
            "trade_date": "2026-04-01",
            "action": "HOLD",
            "confidence": 0.50,
            "run_id": "run-prev-001",
        }]

    class MissingConfView:
        ticker = "601985"
        run_id = "run-current"
        research_action = "HOLD"
        confidence = 0.80
        signal_history = [{
            "trade_date": "2026-04-01",
            "action": "HOLD",
            "confidence": -1.0,
            "run_id": "run-prev-001",
        }]

    assert _render_report_delta_card(NoopView()) == ""
    assert _render_report_delta_card(MissingConfView()) == ""


def test_report_delta_card_changed_action_with_missing_previous_confidence_has_no_fake_jump():
    class View:
        ticker = "601985"
        run_id = "run-current"
        research_action = "BUY"
        confidence = 0.80
        signal_history = [{
            "trade_date": "2026-04-01",
            "action": "HOLD",
            "confidence": -1.0,
            "run_id": "run-prev-001",
        }]

    html = _render_report_delta_card(View())
    assert "HOLD → BUY" in html
    assert "置信度 —" in html
    assert "置信度 +80%" not in html


def test_nav_bar_only_links_workbench_when_file_exists(monkeypatch):
    import pathlib

    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    html = _nav_bar("601985", "run-abc123", "snapshot")
    assert "工作台" not in html

    monkeypatch.setattr(pathlib.Path, "exists", lambda self: str(self).endswith("workbench.html"))
    html = _nav_bar("601985", "run-abc123", "snapshot")
    assert "workbench.html" in html
    assert "committee.html" not in html

    monkeypatch.setattr(
        pathlib.Path,
        "exists",
        lambda self: str(self).endswith(("workbench.html", "601985-run-abc123-committee.html")),
    )
    html = _nav_bar("601985", "run-abc123", "snapshot")
    assert "601985-run-abc123-committee.html" in html


def test_nav_bar_uses_output_dir_for_artifact_detection(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    reports.joinpath("workbench.html").write_text("ok", encoding="utf-8")
    reports.joinpath("601985-run-abc123-committee.html").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    html = _nav_bar("601985", "run-abc123", "snapshot", artifact_dir=reports)

    assert "workbench.html" in html
    assert "601985-run-abc123-committee.html" in html


def test_nav_bar_with_output_dir_does_not_fall_back_to_cwd(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd_reports = cwd / "data" / "reports"
    artifact_dir = tmp_path / "actual-reports"
    cwd_reports.mkdir(parents=True)
    artifact_dir.mkdir()
    cwd_reports.joinpath("workbench.html").write_text("stale", encoding="utf-8")
    cwd_reports.joinpath("601985-run-abc123-committee.html").write_text("stale", encoding="utf-8")
    monkeypatch.chdir(cwd)

    html = _nav_bar("601985", "run-abc123", "snapshot", artifact_dir=artifact_dir)

    assert "工作台" not in html
    assert "601985-run-abc123-committee.html" not in html


def test_refresh_report_nav_adds_late_committee_link(tmp_path):
    snapshot = tmp_path / "601985-run-abc123-snapshot.html"
    committee = tmp_path / "601985-run-abc123-committee.html"
    snapshot.write_text(
        '<html><body><div class="container">\n'
        '<nav class="cross-nav"><a href="601985-run-abc123-snapshot.html" class="active">结论</a></nav>'
        '<h1>snapshot</h1></div></body></html>',
        encoding="utf-8",
    )
    committee.write_text(
        '<html><body><div class="debate-shell">\n'
        '<nav class="cross-nav"><a href="601985-run-abc123-committee.html" class="active">辩论</a></nav>'
        '</div></body></html>',
        encoding="utf-8",
    )

    updated = refresh_report_nav("601985", "run-abc123", tmp_path)
    html = snapshot.read_text(encoding="utf-8")

    assert str(snapshot) in updated
    assert str(committee) not in updated
    assert "601985-run-abc123-committee.html" in html
    assert 'class="active">结论</a>' in html
    assert "<!-- cross-nav:start -->" in html


def test_refresh_report_nav_handles_sentinel_legacy_and_missing_anchor(tmp_path, caplog):
    snapshot = tmp_path / "601985-run-abc123-snapshot.html"
    research = tmp_path / "601985-run-abc123-research.html"
    audit = tmp_path / "601985-run-abc123-audit.html"
    committee = tmp_path / "601985-run-abc123-committee.html"
    snapshot.write_text(
        '<html><body><div class="container">\n'
        + _cross_nav_block('<nav class="cross-nav"><a href="old.html">old</a></nav>')
        + '<h1>snapshot</h1></div></body></html>',
        encoding="utf-8",
    )
    research.write_text(
        '<html><body><div class="container">\n'
        '<nav id="old-nav" class="foo cross-nav bar"><a href="old.html">old</a></nav>'
        '<h1>research</h1></div></body></html>',
        encoding="utf-8",
    )
    audit.write_text("<html><body><main>audit</main></body></html>", encoding="utf-8")
    committee.write_text("ok", encoding="utf-8")
    caplog.set_level("WARNING")

    updated = refresh_report_nav("601985", "run-abc123", tmp_path)
    snapshot_html = snapshot.read_text(encoding="utf-8")
    research_html = research.read_text(encoding="utf-8")

    assert str(snapshot) in updated
    assert str(research) in updated
    assert str(audit) not in updated
    assert "old.html" not in snapshot_html
    assert "old.html" not in research_html
    assert "<!-- cross-nav:start -->" in research_html
    assert "no nav anchor found" in caplog.text


def test_refresh_report_nav_legacy_regex_avoids_partial_class_match(tmp_path, caplog):
    snapshot = tmp_path / "601985-run-abc123-snapshot.html"
    committee = tmp_path / "601985-run-abc123-committee.html"
    snapshot.write_text(
        '<html><body><div class="container">\n'
        '<nav class="my-cross-nav-foo"><a href="old.html">old</a></nav>'
        '<h1>snapshot</h1></div></body></html>',
        encoding="utf-8",
    )
    committee.write_text("ok", encoding="utf-8")
    caplog.set_level("INFO")

    updated = refresh_report_nav("601985", "run-abc123", tmp_path)
    html = snapshot.read_text(encoding="utf-8")

    assert str(snapshot) in updated
    assert '<nav class="my-cross-nav-foo">' in html
    assert "old.html" in html
    assert "sentinel missing; inserted nav block" in caplog.text
    assert "legacy block upgraded" not in caplog.text


def test_refresh_report_nav_logs_write_failure(tmp_path, monkeypatch, caplog):
    snapshot = tmp_path / "601985-run-abc123-snapshot.html"
    committee = tmp_path / "601985-run-abc123-committee.html"
    snapshot.write_text(
        '<html><body><div class="container">\n'
        '<nav class="cross-nav"><a href="old.html">old</a></nav>'
        '<h1>snapshot</h1></div></body></html>',
        encoding="utf-8",
    )
    committee.write_text("ok", encoding="utf-8")

    def fail_write(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(shared_utils, "_atomic_write_text", fail_write)
    caplog.set_level("WARNING")

    updated = shared_utils.refresh_report_nav("601985", "run-abc123", tmp_path)

    assert updated == []
    assert "write failed" in caplog.text


def test_refresh_report_nav_preserves_existing_file_permissions(tmp_path):
    snapshot = tmp_path / "601985-run-abc123-snapshot.html"
    committee = tmp_path / "601985-run-abc123-committee.html"
    snapshot.write_text(
        '<html><body><div class="container">\n'
        '<nav class="cross-nav"><a href="old.html">old</a></nav>'
        '<h1>snapshot</h1></div></body></html>',
        encoding="utf-8",
    )
    committee.write_text("ok", encoding="utf-8")
    os.chmod(snapshot, 0o644)

    updated = refresh_report_nav("601985", "run-abc123", tmp_path)

    assert str(snapshot) in updated
    assert (os.stat(snapshot).st_mode & 0o777) == 0o644


def test_atomic_write_uses_umask_for_new_file(tmp_path):
    new_file = tmp_path / "new.html"
    old_umask = os.umask(0o022)
    try:
        shared_utils._atomic_write_text(new_file, "ok")
    finally:
        os.umask(old_umask)

    assert new_file.read_text(encoding="utf-8") == "ok"
    assert (os.stat(new_file).st_mode & 0o777) == 0o644


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
