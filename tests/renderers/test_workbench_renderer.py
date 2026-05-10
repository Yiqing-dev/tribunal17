import pytest

from subagent_pipeline.renderers.report_renderer import generate_workbench_report
from subagent_pipeline.renderers.workbench_view import WorkbenchView
from subagent_pipeline.replay_service import ReplayService
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.trace_models import NodeTrace, RunTrace


def _trace(run_id: str, action: str, confidence: float, trade_date: str) -> RunTrace:
    trace = RunTrace(
        run_id=run_id,
        ticker="601985",
        ticker_name="中国核电",
        trade_date=trade_date,
    )
    trace.node_traces = [
        NodeTrace(
            run_id=run_id,
            node_name="Fundamentals Analyst",
            seq=2,
            structured_data={
                "stock_profile": {"label_cn": "蓝筹白马"},
                "industry_compare": {
                    "relative_valuation_label": "fair",
                    "relative_quality_label": "quality_premium",
                },
                "data_quality_flags": [],
            },
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Research Manager",
            seq=12,
            research_action=action,
            confidence=confidence,
            structured_data={"conclusion": "核电装机与电价稳定，等待突破确认。"},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Risk Judge",
            seq=16,
            risk_score=8,
            risk_cleared=True,
            structured_data={"risk_flags": []},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="ResearchOutput",
            seq=17,
            structured_data={
                "trade_plan": {
                    "bias": "LONG" if action == "BUY" else "WAIT",
                    "confirmations": ["收盘价站上关键压力区且成交额放大"],
                    "review_triggers": ["跌破20日均线或财报披露"],
                    "invalidators": ["跌破关键支撑位"],
                    "confidence": confidence,
                }
            },
        ),
    ]
    trace.finalize()
    return trace


def test_workbench_view_uses_latest_run_and_previous_delta(tmp_path):
    store = ReplayStore(storage_dir=str(tmp_path / "replays"))
    store.save(_trace("run-old-001", "HOLD", 0.50, "2026-04-01"))
    store.save(_trace("run-new-001", "BUY", 0.80, "2026-04-08"))

    view = WorkbenchView.build(ReplayService(store=store))

    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.run_id == "run-new-001"
    assert row.previous_run_id == "run-old-001"
    assert row.action_changed is True
    assert row.confidence_delta == pytest.approx(0.30)
    assert row.status in {"可跟踪", "需复核"}
    assert "snapshot.html" in row.report_links["snapshot"]


def test_generate_workbench_report_writes_product_entry(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-new-002", "BUY", 0.76, "2026-04-09"))

    path = generate_workbench_report(output_dir=str(output_dir), storage_dir=str(storage_dir))
    html = output_dir.joinpath("workbench.html").read_text(encoding="utf-8")

    assert path.endswith("workbench.html")
    assert "个股研究工作台" in html
    assert "中国核电" in html
    assert "可跟踪" in html
    assert "601985-run-new-002-snapshot.html" in html
