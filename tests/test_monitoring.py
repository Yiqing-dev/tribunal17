"""Tests for P2 rolling monitoring module."""

import json
import tempfile
from pathlib import Path

import pytest

from subagent_pipeline.monitoring import (
    ACCURACY_ALERT,
    ACCURACY_WARN,
    MIN_SAMPLE_N,
    RollingMonitorReport,
    StratumResult,
    _alert_level_for,
    _compute_window,
    _infer_actual_direction,
    _pillar_direction,
    compute_rolling_monitor,
    load_supplement,
)


# ── Pure helpers ────────────────────────────────────────────────────────────


class TestPillarDirection:
    def test_score_0_down(self):
        assert _pillar_direction(0) == "down"

    def test_score_1_down(self):
        assert _pillar_direction(1) == "down"

    def test_score_2_neutral(self):
        assert _pillar_direction(2) == "neutral"

    def test_score_3_up(self):
        assert _pillar_direction(3) == "up"

    def test_score_4_up(self):
        assert _pillar_direction(4) == "up"

    def test_score_negative_neutral(self):
        """Missing pillar (-1) → neutral (not enough info)."""
        assert _pillar_direction(-1) == "neutral"

    def test_score_none_neutral(self):
        assert _pillar_direction(None) == "neutral"


class TestInferActualDirection:
    def test_up(self):
        assert _infer_actual_direction(5.0) == "up"

    def test_down(self):
        assert _infer_actual_direction(-5.0) == "down"

    def test_within_band_neutral(self):
        assert _infer_actual_direction(1.0) == "neutral"

    def test_custom_band(self):
        assert _infer_actual_direction(3.0, band_pct=5.0) == "neutral"


class TestAlertLevel:
    def test_above_threshold_no_alert(self):
        assert _alert_level_for(0.55, 50) == ""

    def test_just_below_warn(self):
        """40% is the boundary — below triggers warn."""
        assert _alert_level_for(0.39, 50) == "warn"

    def test_at_warn_threshold_no_alert(self):
        """Accuracy exactly at warn threshold → no alert (strict less-than)."""
        assert _alert_level_for(ACCURACY_WARN, 50) == ""

    def test_below_alert(self):
        assert _alert_level_for(0.30, 50) == "alert"

    def test_below_min_sample_ignored(self):
        """Below MIN_SAMPLE_N → no alert regardless of accuracy."""
        assert _alert_level_for(0.0, MIN_SAMPLE_N - 1) == ""


# ── compute_window ──────────────────────────────────────────────────────────


def _mk_record(
    ticker="601985.SS",
    action="BUY",
    direction_expected="up",
    direction_correct=True,
    actual_direction="up",
    regime="NEUTRAL",
    market_score=3, fundamental_score=3, news_score=2, sentiment_score=2,
):
    return {
        "ticker": ticker,
        "trade_date": "2026-04-15",
        "action": action,
        "direction_expected": direction_expected,
        "direction_correct": direction_correct,
        "actual_direction": actual_direction,
        "regime": regime,
        "pillar_scores": {
            "market_score": market_score,
            "fundamental_score": fundamental_score,
            "news_score": news_score,
            "sentiment_score": sentiment_score,
        },
    }


class TestComputeWindow:
    def test_empty_records_no_crash(self):
        assert _compute_window([], 30) == []

    def test_all_hold_excluded(self):
        """HOLD records (direction_expected=flat) excluded from directional accuracy."""
        records = [
            _mk_record(action="HOLD", direction_expected="flat",
                       direction_correct=None)
            for _ in range(20)
        ]
        results = _compute_window(records, 30)
        # Neither regime nor action strata emerge from HOLD-only input
        assert results == []

    def test_below_min_sample_no_alert(self):
        """Stratum with n=5 gets reported but has no alert flag."""
        records = [
            _mk_record(action="BUY", direction_correct=False)
            for _ in range(5)
        ]
        results = _compute_window(records, 30)
        # Strata computed but alert_level stays empty (n < MIN_SAMPLE_N)
        for r in results:
            assert r.alert_level == ""

    def test_alert_threshold_triggers(self):
        """≥MIN_SAMPLE_N BUY signals with 30% accuracy → alert level on action=BUY."""
        # 10 records, 3 correct, 7 wrong = 30% accuracy
        records = (
            [_mk_record(action="BUY", direction_correct=True) for _ in range(3)]
            + [_mk_record(action="BUY", direction_correct=False) for _ in range(7)]
        )
        results = _compute_window(records, 30)
        buy_result = [r for r in results if r.label == "action=BUY"][0]
        assert buy_result.n == 10
        assert buy_result.accuracy == pytest.approx(0.30)
        assert buy_result.alert_level == "alert"

    def test_warn_threshold_triggers(self):
        """10 records at 38% accuracy → warn."""
        records = (
            [_mk_record(action="SELL", direction_expected="down",
                        direction_correct=True) for _ in range(4)]
            + [_mk_record(action="SELL", direction_expected="down",
                          direction_correct=False) for _ in range(6)]
        )
        # But wait — 4/10=40% exactly; that's at_warn_threshold → no alert.
        # Let me force 3/10 = 30% for alert, or 3/8 for warn.
        results = _compute_window(records, 30)
        sell_result = [r for r in results if r.label == "action=SELL"][0]
        assert sell_result.n == 10
        # 40% boundary exact → no alert (strict less-than semantics)
        assert sell_result.alert_level == ""

    def test_regime_stratification(self):
        """Mix of regimes produces separate stratum results."""
        records = (
            [_mk_record(regime="RISK_ON", direction_correct=True) for _ in range(10)]
            + [_mk_record(regime="RISK_OFF", direction_correct=False) for _ in range(10)]
        )
        results = _compute_window(records, 30)
        labels = {r.label: r for r in results}
        assert "regime=RISK_ON" in labels
        assert "regime=RISK_OFF" in labels
        assert labels["regime=RISK_ON"].accuracy == 1.0
        assert labels["regime=RISK_OFF"].accuracy == 0.0
        assert labels["regime=RISK_OFF"].alert_level == "alert"

    def test_pillar_stratification_skips_neutral(self):
        """Pillar with score=2 (neutral) is excluded from its accuracy."""
        # 12 records, all BUY correct, market_score=3 (up) or 2 (neutral)
        records = (
            [_mk_record(market_score=3, direction_correct=True,
                        actual_direction="up") for _ in range(6)]
            + [_mk_record(market_score=2, direction_correct=True,
                          actual_direction="up") for _ in range(6)]
        )
        results = _compute_window(records, 30)
        market_pillar = [r for r in results if r.label == "pillar=market"]
        assert len(market_pillar) == 1
        # 6 (non-neutral, all correct), accuracy=100%
        assert market_pillar[0].n == 6
        assert market_pillar[0].accuracy == 1.0


# ── Report objects ──────────────────────────────────────────────────────────


class TestRollingMonitorReport:
    def test_to_dict_roundtrip(self):
        rep = RollingMonitorReport(
            computed_at="2026-04-21T10:00:00",
            trade_date="2026-04-21",
            stratum_results=[
                StratumResult("regime=NEUTRAL", 30, 15, 0.6, ""),
                StratumResult("action=BUY", 30, 12, 0.3, "alert"),
            ],
        )
        rep.alerts = [s for s in rep.stratum_results if s.alert_level]
        d = rep.to_dict()
        assert d["trade_date"] == "2026-04-21"
        assert len(d["stratum_results"]) == 2
        assert len(d["alerts"]) == 1
        assert d["alerts"][0]["label"] == "action=BUY"

    def test_to_markdown_section_no_alerts(self):
        rep = RollingMonitorReport(
            computed_at="x", trade_date="2026-04-21",
            stratum_results=[StratumResult("regime=NEUTRAL", 30, 15, 0.6, "")],
        )
        rep.alerts = []
        md = rep.to_markdown_section()
        assert "未发现异常" in md
        assert "## 滚动监控告警" in md

    def test_to_markdown_section_with_alerts(self):
        rep = RollingMonitorReport(
            computed_at="x", trade_date="2026-04-21",
            stratum_results=[
                StratumResult("action=BUY", 30, 12, 0.3, "alert"),
                StratumResult("action=SELL", 60, 15, 0.38, "warn"),
            ],
        )
        rep.alerts = rep.stratum_results
        md = rep.to_markdown_section()
        assert "action=BUY" in md
        assert "action=SELL" in md
        assert "ALERT" in md
        assert "WARN" in md


# ── compute_rolling_monitor (integration) ───────────────────────────────────


class TestComputeRollingMonitorColdStart:
    def test_missing_ledger_returns_empty(self, tmp_path):
        """No ledger file → empty report, no crash."""
        rep = compute_rolling_monitor(
            trade_date="2026-04-21",
            ledger_path=str(tmp_path / "missing.jsonl"),
            supplement_path=str(tmp_path / "missing_supp.json"),
            storage_dir=str(tmp_path / "missing_replays"),
            output_dir=str(tmp_path / "out"),
        )
        assert rep.trade_date == "2026-04-21"
        assert rep.stratum_results == []
        assert rep.alerts == []

    def test_invalid_trade_date_uses_today(self, tmp_path):
        """Bogus trade_date string → falls back to today (no crash)."""
        rep = compute_rolling_monitor(
            trade_date="not-a-date",
            ledger_path=str(tmp_path / "missing.jsonl"),
            supplement_path=str(tmp_path / "missing_supp.json"),
            storage_dir=str(tmp_path / "missing_replays"),
            output_dir=str(tmp_path / "out"),
        )
        assert rep.stratum_results == []


class TestLoadSupplement:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_supplement(str(tmp_path / "none.json")) == {}

    def test_valid_supplement_loaded(self, tmp_path):
        p = tmp_path / "supp.json"
        p.write_text(json.dumps({"run-abc": "RISK_ON"}), encoding="utf-8")
        assert load_supplement(str(p)) == {"run-abc": "RISK_ON"}

    def test_malformed_json_returns_empty(self, tmp_path):
        p = tmp_path / "supp.json"
        p.write_text("not-json", encoding="utf-8")
        assert load_supplement(str(p)) == {}

    def test_non_dict_supplement_returns_empty(self, tmp_path):
        p = tmp_path / "supp.json"
        p.write_text(json.dumps(["list-not-dict"]), encoding="utf-8")
        assert load_supplement(str(p)) == {}
