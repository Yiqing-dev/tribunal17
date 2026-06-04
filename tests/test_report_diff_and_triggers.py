from subagent_pipeline.report_diff import compare_reports
from subagent_pipeline.review_triggers import (
    _current_price,
    _due_date_from_time_stop,
    evaluate_review_triggers,
    primary_review_trigger,
)
from subagent_pipeline.trace_models import NodeTrace, RunTrace


def _trace(run_id, action, confidence, trade_date, *, conclusion, bull_claims=None, risks=None, plan=None, price=0):
    trace = RunTrace(
        run_id=run_id,
        ticker="601985",
        ticker_name="中国核电",
        trade_date=trade_date,
    )
    trace.node_traces = [
        NodeTrace(
            run_id=run_id,
            node_name="Bull Researcher",
            seq=4,
            structured_data={
                "supporting_claims": [{"text": c, "confidence": 0.7} for c in (bull_claims or [])],
            },
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Research Manager",
            seq=12,
            research_action=action,
            confidence=confidence,
            structured_data={"conclusion": conclusion},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Risk Judge",
            seq=16,
            risk_score=6,
            risk_cleared=True,
            risk_flag_categories=[r.get("category", "") for r in (risks or [])],
            risk_flag_count=len(risks or []),
            structured_data={"risk_flags": risks or []},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="ResearchOutput",
            seq=17,
            research_action=action,
            confidence=confidence,
            structured_data={"trade_plan": plan or {}},
        ),
        NodeTrace(
            run_id=run_id,
            node_name="Market Analyst",
            seq=1,
            structured_data={"price_history": [price] if price else []},
        ),
    ]
    trace.finalize()
    return trace


def test_report_diff_captures_deep_report_changes():
    prev = _trace(
        "run-prev",
        "HOLD",
        0.50,
        "2026-04-01",
        conclusion="等待突破确认",
        bull_claims=["电价稳定支撑现金流"],
        risks=[{"category": "估值", "severity": "medium", "description": "估值不便宜"}],
        plan={"invalidators": ["跌破关键支撑"]},
    )
    curr = _trace(
        "run-curr",
        "BUY",
        0.72,
        "2026-04-08",
        conclusion="放量突破后转为积极跟踪",
        bull_claims=["电价稳定支撑现金流", "新项目投产提升利润"],
        risks=[{"category": "政策", "severity": "high", "description": "电价政策变化"}],
        plan={
            "invalidators": ["跌破20日均线"],
            "review_triggers": ["跌破20日均线或财报披露"],
            "stop_loss": {"price": 10.2, "rule": "跌破均线"},
        },
    )

    diff = compare_reports(prev, curr)

    assert diff.action_changed is True
    assert diff.confidence_delta == 0.22
    assert diff.thesis_changed is True
    assert diff.bull_claims_added == ["新项目投产提升利润"]
    assert diff.risk_flags_added
    assert diff.invalidators_added == ["跌破20日均线"]
    assert diff.review_triggers_added == ["跌破20日均线或财报披露"]
    assert diff.severity == "major"
    assert any("结论 HOLD → BUY" in x for x in diff.summary)


def test_review_triggers_detect_action_risk_and_stop_loss():
    prev = _trace(
        "run-prev",
        "HOLD",
        0.50,
        "2026-04-01",
        conclusion="等待突破确认",
        bull_claims=[],
        risks=[],
        plan={},
    )
    curr = _trace(
        "run-curr",
        "BUY",
        0.72,
        "2026-04-08",
        conclusion="放量突破后转为积极跟踪",
        bull_claims=[],
        risks=[{"category": "政策", "severity": "high", "description": "电价政策变化"}],
        plan={
            "stop_loss": {"price": 10.2, "rule": "跌破均线"},
            "review_triggers": ["跌破20日均线或财报披露"],
            "time_stop": "5个交易日内未突破则放弃",
        },
        price=10.3,
    )

    triggers = evaluate_review_triggers(curr, prev, quality_grade="B")
    kinds = {t.kind for t in triggers}

    assert {"action_change", "risk_added", "high_risk", "stop_loss_near", "planned_review", "time_stop"} <= kinds
    assert primary_review_trigger(triggers).severity == "high"


def test_report_diff_treats_near_duplicate_claims_as_unchanged():
    prev = _trace(
        "run-prev",
        "HOLD",
        0.50,
        "2026-04-01",
        conclusion="电价稳定支撑现金流，等待突破确认。",
        bull_claims=["电价稳定支撑现金流"],
        risks=[],
        plan={},
    )
    curr = _trace(
        "run-curr",
        "HOLD",
        0.51,
        "2026-04-08",
        conclusion="维持电价稳定支撑现金流，等待突破确认",
        bull_claims=["电价稳定，支撑现金流"],
        risks=[],
        plan={},
    )

    diff = compare_reports(prev, curr)

    assert diff.thesis_changed is False
    assert diff.bull_claims_added == []
    assert diff.bull_claims_dropped == []


def test_report_diff_short_substring_is_not_enough_to_hide_change():
    prev = _trace(
        "run-prev",
        "HOLD",
        0.50,
        "2026-04-01",
        conclusion="等待突破确认",
        bull_claims=["盈利"],
        risks=[],
        plan={},
    )
    curr = _trace(
        "run-curr",
        "HOLD",
        0.51,
        "2026-04-08",
        conclusion="等待突破确认",
        bull_claims=["盈利下降"],
        risks=[],
        plan={},
    )

    diff = compare_reports(prev, curr)

    assert diff.bull_claims_added == ["盈利下降"]


def test_review_trigger_price_fallback_uses_market_current_price():
    trace = _trace(
        "run-curr",
        "BUY",
        0.72,
        "2026-04-08",
        conclusion="等待突破确认",
        bull_claims=[],
        risks=[],
        plan={},
        price=0,
    )
    trace.node_traces[-1].structured_data = {"current_price": 10.25}

    assert _current_price(trace) == 10.25


def test_time_stop_due_date_uses_real_trading_calendar():
    # "N个交易日" now advances N REAL trading days via the CN calendar (skips
    # weekends + holidays) — an accurate due date, not a ×7/5 fake. 2026-04-08
    # + 5 trading days = 2026-04-15 (Apr 11-12 weekend skipped).
    assert _due_date_from_time_stop("2026-04-08", "5个交易日内未突破则放弃") == "2026-04-15"
    # 天/日 stay literal calendar days.
    assert _due_date_from_time_stop("2026-04-08", "5天内未突破则放弃") == "2026-04-13"
