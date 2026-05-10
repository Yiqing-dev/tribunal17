from subagent_pipeline.backtest import BacktestConfig, BacktestReport, BacktestResult
from subagent_pipeline.calibration import (
    build_calibration_report,
    calibration_summary_for_ticker,
    confidence_bucket,
    format_calibration_feedback,
    load_latest_calibration_report,
    save_calibration_report,
)


def _result(ticker, action, confidence, expected, correct):
    return BacktestResult(
        run_id=f"{ticker}-{action}-{confidence}",
        ticker=ticker,
        trade_date="2026-04-01",
        action=action,
        confidence=confidence,
        direction_expected=expected,
        direction_correct=correct,
        eval_status="completed",
    )


def test_confidence_bucket_thresholds():
    assert confidence_bucket(0.70) == "high"
    assert confidence_bucket(0.55) == "medium"
    assert confidence_bucket(0.30) == "low"
    assert confidence_bucket(-1) == "unknown"


def test_build_calibration_report_groups_by_action_bucket_and_ticker():
    bt = BacktestReport(
        config=BacktestConfig(eval_window_days=5),
        results=[
            _result("601985.SS", "BUY", 0.80, "up", True),
            _result("601985.SS", "SELL", 0.60, "down", False),
            _result("000001.SZ", "BUY", 0.40, "up", True),
            BacktestResult(ticker="000002.SZ", action="HOLD", confidence=0.5, eval_status="pending"),
        ],
    )

    report = build_calibration_report(bt)

    assert report.eval_window_days == 5
    assert report.total_results == 4
    assert report.completed_results == 3
    assert report.overall.decided_n == 3
    assert report.overall.accuracy == 0.6667
    assert report.by_action["BUY"].accuracy == 1.0
    assert report.by_action["SELL"].accuracy == 0.0
    assert report.by_confidence_bucket["high"].decided_n == 1
    assert report.by_ticker["601985.SS"].decided_n == 2


def test_summary_feedback_and_persistence(tmp_path):
    bt = BacktestReport(
        results=[
            _result("601985", "BUY", 0.80, "up", True),
            _result("601985", "BUY", 0.75, "up", False),
        ],
    )
    report = build_calibration_report(bt)
    summary = calibration_summary_for_ticker(report, "601985", action="BUY", confidence=0.80)

    assert summary["ticker"]["key"] == "601985.SS"
    assert summary["action"]["key"] == "BUY"
    feedback = format_calibration_feedback(summary)
    assert "历史校准反馈" in feedback
    assert "当前动作" in feedback

    path = save_calibration_report(report, output_dir=str(tmp_path))
    assert path.exists()
    loaded = load_latest_calibration_report(str(tmp_path))
    assert loaded is not None
    assert loaded.overall.decided_n == report.overall.decided_n

