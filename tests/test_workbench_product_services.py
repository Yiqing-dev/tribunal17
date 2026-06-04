import json
import io

from subagent_pipeline.renderers.calibration_renderer import generate_calibration_page
from subagent_pipeline.renderers.audit_view import AuditView
from subagent_pipeline.renderers.workbench_renderer import render_workbench_csv
from subagent_pipeline.renderers.workbench_renderer import generate_workbench_report
from subagent_pipeline.replay_service import ReplayService
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.trace_models import NodeTrace, RunTrace
from subagent_pipeline.workbench_monitor import run_review_monitor_once
from subagent_pipeline.workbench_server import PayloadTooLarge, WorkbenchRequestHandler
from subagent_pipeline.workbench_state import (
    load_workbench_state,
    merge_workbench_state,
    save_workbench_state,
)


def _trace(run_id: str, action: str, confidence: float, trade_date: str, stop_loss: float = 0.0) -> RunTrace:
    trace = RunTrace(
        run_id=run_id,
        ticker="601985",
        ticker_name="中国核电",
        trade_date=trade_date,
    )
    trace.node_traces = [
        NodeTrace(
            run_id=run_id,
            node_name="Research Manager",
            seq=12,
            research_action=action,
            confidence=confidence,
            structured_data={"conclusion": "等待突破确认"},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Risk Judge",
            seq=16,
            risk_score=5,
            risk_cleared=True,
            structured_data={"risk_flags": []},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="ResearchOutput",
            seq=17,
            research_action=action,
            confidence=confidence,
            structured_data={
                "trade_plan": {
                    "bias": "LONG",
                    "stop_loss": {"price": stop_loss, "rule": "跌破均线"} if stop_loss else None,
                    "review_triggers": ["跌破20日均线或财报披露"],
                    "time_stop": "5个交易日内未突破则放弃",
                    "confidence": confidence,
                }
            },
        ),
    ]
    trace.finalize()
    return trace


def test_workbench_state_persists_and_sanitizes(tmp_path):
    save_workbench_state({"run-a": {"favorite": True, "note": "abc", "bad": "x"}}, tmp_path)
    merged = merge_workbench_state({"run-a": {"read": True}, "run-b": {"ignore": 1}}, tmp_path)

    assert merged["run-a"]["favorite"] is True
    assert merged["run-a"]["read"] is True
    assert "bad" not in merged["run-a"]
    assert load_workbench_state(tmp_path)["run-b"]["ignore"] is True


def test_audit_view_signal_history_uses_date_order_and_missing_confidence_sentinel(tmp_path):
    storage_dir = tmp_path / "replays"
    store = ReplayStore(storage_dir=str(storage_dir))
    old = _trace("run-old", "HOLD", 0.50, "2026-04-01")
    new = _trace("run-new", "BUY", 0.72, "2026-04-08")
    missing = _trace("run-missing", "HOLD", -1.0, "2026-03-25")
    store.save(new)
    store.save(missing)
    store.save(old)

    view = AuditView.build(ReplayService(store=store), "run-new")

    assert view.signal_history[0]["run_id"] == "run-old"
    assert view.signal_history[1]["run_id"] == "run-missing"
    assert view.signal_history[1]["confidence"] == -1.0


def test_monitor_once_writes_alerts_with_current_price(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-old", "HOLD", 0.50, "2026-04-01"))
    store.save(_trace("run-new", "BUY", 0.72, "2026-04-08", stop_loss=10.2))

    report = run_review_monitor_once(
        output_dir=str(output_dir),
        storage_dir=str(storage_dir),
        price_by_ticker={"601985": 10.1},
    )

    assert report.alert_count == 1
    alert_json = json.loads(output_dir.joinpath("review_alerts.json").read_text(encoding="utf-8"))
    assert alert_json["alerts"][0]["ticker"] == "601985"
    assert any(t["kind"] == "stop_loss" for t in alert_json["alerts"][0]["triggers"])


def test_workbench_csv_has_bom(tmp_path):
    storage_dir = tmp_path / "replays"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-new", "BUY", 0.72, "2026-04-08"))
    from subagent_pipeline.renderers.workbench_view import WorkbenchView

    view = WorkbenchView.build(ReplayService(store=store), output_dir=str(tmp_path / "reports"))
    csv_text = render_workbench_csv(view)

    assert csv_text.startswith("\ufeff")


def test_calibration_page_auto_build_gracefully_handles_missing_ledger(tmp_path):
    path = generate_calibration_page(
        output_dir=str(tmp_path / "reports"),
        monitoring_dir=str(tmp_path / "monitoring"),
        ledger_path=str(tmp_path / "missing.jsonl"),
        auto_build=True,
    )
    html = (tmp_path / "reports" / "calibration.html").read_text(encoding="utf-8")

    assert path.endswith("calibration.html")
    assert "暂无校准数据" in html


def test_workbench_html_contains_server_action_buttons(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-new", "BUY", 0.72, "2026-04-08"))

    generate_workbench_report(output_dir=str(output_dir), storage_dir=str(storage_dir))
    html = output_dir.joinpath("workbench.html").read_text(encoding="utf-8")

    assert "/api/workbench/state" in html
    assert "wb-run-review" in html
    assert "/api/workbench/review/run" in html
    assert "/api/workbench/monitor/run" not in html
    assert "wb-run-calibration" in html
    assert "workbench.pdf" not in html


def test_workbench_server_handler_imports():
    assert WorkbenchRequestHandler.__name__ == "WorkbenchRequestHandler"


def test_workbench_server_read_json_rejects_oversized_body():
    handler = object.__new__(WorkbenchRequestHandler)
    handler.max_json_bytes = 8
    handler.headers = {"Content-Length": "9"}
    handler.rfile = io.BytesIO(b'{"x": 1}')

    try:
        handler._read_json()
    except PayloadTooLarge:
        pass
    else:
        raise AssertionError("expected PayloadTooLarge")
