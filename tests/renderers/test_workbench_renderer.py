import pytest

from subagent_pipeline.renderers.report_renderer import generate_workbench_report
from subagent_pipeline.renderers.workbench_renderer import render_workbench
from subagent_pipeline.renderers.workbench_view import WorkbenchRow, WorkbenchView
from subagent_pipeline.replay_service import ReplayService
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.trace_models import NodeTrace, RunTrace


def _trace(run_id: str, action: str, confidence: float, trade_date: str, ticker: str = "601985") -> RunTrace:
    trace = RunTrace(
        run_id=run_id,
        ticker=ticker,
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


def test_workbench_view_orders_previous_by_trade_date_not_manifest_order(tmp_path):
    store = ReplayStore(storage_dir=str(tmp_path / "replays"))
    store.save(_trace("run-new-date", "BUY", 0.80, "2026-04-08"))
    store.save(_trace("run-old-date", "HOLD", 0.50, "2026-04-01"))

    view = WorkbenchView.build(ReplayService(store=store))

    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.run_id == "run-new-date"
    assert row.previous_run_id == "run-old-date"
    assert row.action_changed is True


def test_generate_workbench_report_writes_product_entry(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-new-002", "BUY", 0.76, "2026-04-09"))
    for suffix in ("snapshot", "research", "audit"):
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir.joinpath(f"601985-run-new-002-{suffix}.html").write_text("ok", encoding="utf-8")

    path = generate_workbench_report(output_dir=str(output_dir), storage_dir=str(storage_dir))
    html = output_dir.joinpath("workbench.html").read_text(encoding="utf-8")

    assert path.endswith("workbench.html")
    assert "个股研究工作台" in html
    assert "中国核电" in html
    assert "可跟踪" in html
    assert "wb-filter-status" in html
    assert "workbench_state.json" in html
    assert "601985-run-new-002-snapshot.html" in html
    assert output_dir.joinpath("report_index.json").exists()
    assert output_dir.joinpath("today_changes.html").exists()
    assert output_dir.joinpath("calibration.html").exists()
    assert output_dir.joinpath("workbench.csv").exists()
    assert output_dir.joinpath("workbench.md").exists()
    assert output_dir.joinpath("workbench_state.json").exists()
    assert not output_dir.joinpath("workbench.pdf").exists()


def test_workbench_omits_missing_tier_links_in_generated_page(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-no-links", "BUY", 0.76, "2026-04-09"))

    generate_workbench_report(output_dir=str(output_dir), storage_dir=str(storage_dir))
    html = output_dir.joinpath("workbench.html").read_text(encoding="utf-8")

    assert "601985-run-no-links-snapshot.html" not in html
    assert 'class="disabled">结论</span>' in html
    assert 'class="disabled">研究</span>' in html
    assert 'class="disabled">审计</span>' in html


def test_generate_workbench_report_scopes_to_daily_watchlist_and_marks_missing(tmp_path):
    storage_dir = tmp_path / "replays"
    output_dir = tmp_path / "reports"
    store = ReplayStore(storage_dir=str(storage_dir))
    store.save(_trace("run-watchlist", "BUY", 0.76, "2026-04-09"))

    generate_workbench_report(
        output_dir=str(output_dir),
        storage_dir=str(storage_dir),
        tickers=["601985", "000858"],
        ticker_names={"000858": "五粮液"},
    )
    html = output_dir.joinpath("workbench.html").read_text(encoding="utf-8")
    csv = output_dir.joinpath("workbench.csv").read_text(encoding="utf-8")

    assert "今日清单 2 个" in html
    assert "待生成 1 个" in html
    assert "601985" in html
    assert "000858.SZ 五粮液" in html
    assert "待生成" in html
    assert "000858.SZ,五粮液" in csv


def test_workbench_watchlist_latest_dedupes_normalized_ticker_variants(tmp_path):
    store = ReplayStore(storage_dir=str(tmp_path / "replays"))
    store.save(_trace("run-old-bare", "BUY", 0.68, "2026-03-12", ticker="603065"))
    store.save(_trace("run-new-suffix", "HOLD", 0.62, "2026-05-07", ticker="603065.SS"))

    view = WorkbenchView.build(ReplayService(store=store), tickers=["603065"])

    assert [row.run_id for row in view.rows] == ["run-new-suffix"]


def test_workbench_kpis_do_not_double_count_review_triggers():
    view = WorkbenchView(rows=[
        WorkbenchRow(
            run_id="run-review",
            ticker="601985",
            status="需复核",
            review_triggers=[{"reason": "高风险触发"}],
        ),
        WorkbenchRow(
            run_id="run-trigger",
            ticker="000858",
            status="可跟踪",
            review_triggers=[{"reason": "中风险观察"}],
        ),
    ])

    html = render_workbench(view)

    assert view.review_count == 1
    assert view.trigger_count == 1
    assert "BUY 标的" in html
    assert "触发待看" in html
    assert '<option value="可跟踪">可跟踪</option>' in html
    assert '<option value="BUY">BUY</option>' in html
    assert html.count('data-trigger="1"') == 1


def test_workbench_missing_confidence_stays_sortable_but_not_extreme():
    row = WorkbenchRow(
        run_id="run-pending",
        ticker="000858.SZ",
        ticker_name="五粮液",
        status="待生成",
        confidence=-1.0,
    )
    html = render_workbench(WorkbenchView(rows=[row]))

    assert 'data-confidence=""' in html
    assert "Number.isFinite(parsed)" in html
