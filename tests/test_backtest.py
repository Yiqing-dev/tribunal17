"""Tests for subagent_pipeline.backtest — direction inference, signal evaluation,
summary computation, dataclass round-trips, and dedup logic."""

from __future__ import annotations

import pytest
from subagent_pipeline.backtest import (
    BacktestConfig,
    BacktestReport,
    BacktestResult,
    BacktestSummary,
    compute_summary,
    evaluate_signal,
    infer_direction,
)


# ── infer_direction ──────────────────────────────────────────────────────

class TestInferDirection:
    """Unit tests for action → direction mapping."""

    @pytest.mark.parametrize("action,expected", [
        ("BUY", "up"),
        ("SELL", "down"),
        ("HOLD", "flat"),
        ("VETO", "abstain"),
    ])
    def test_standard_actions(self, action, expected):
        assert infer_direction(action) == expected

    @pytest.mark.parametrize("action,expected", [
        ("buy", "up"),
        ("Sell", "down"),
        ("hold", "flat"),
        ("veto", "abstain"),
    ])
    def test_case_insensitive(self, action, expected):
        assert infer_direction(action) == expected

    @pytest.mark.parametrize("action", ["  BUY  ", " SELL\t", "\tHOLD "])
    def test_whitespace_stripped(self, action):
        assert infer_direction(action) in ("up", "down", "flat")

    @pytest.mark.parametrize("action", ["", "UNKNOWN", "STRONG_BUY", "SHORT", "WAIT"])
    def test_unknown_defaults_to_flat(self, action):
        assert infer_direction(action) == "flat"

    def test_confidence_param_accepted(self):
        """Confidence is accepted but currently unused."""
        assert infer_direction("BUY", confidence=0.9) == "up"
        assert infer_direction("BUY", confidence=0.1) == "up"


# ── evaluate_signal ──────────────────────────────────────────────────────

def _make_bars(prices):
    """Create forward_bars dicts from (close, high, low) tuples."""
    return [{"close": c, "high": h, "low": lo} for c, h, lo in prices]


class TestEvaluateSignal:
    """evaluate_signal with pre-supplied forward_bars (no akshare)."""

    def _eval(self, action="BUY", signal_close=10.0, bars=None, config=None,
              stop_loss=0.0, take_profit=0.0):
        bars = bars or _make_bars([
            (10.5, 10.8, 10.1),
            (11.0, 11.2, 10.4),
            (11.5, 11.5, 10.9),
        ])
        return evaluate_signal(
            run_id="test-001", ticker="601985.SS", ticker_name="中国中冶",
            trade_date="2026-03-10", action=action, confidence=0.75,
            was_vetoed=False, stop_loss=stop_loss, take_profit=take_profit,
            config=config or BacktestConfig(neutral_band_pct=2.0),
            forward_bars=bars, signal_close=signal_close,
        )

    def test_buy_win(self):
        """BUY with +15% return → win."""
        r = self._eval(action="BUY", signal_close=10.0,
                       bars=_make_bars([(11.5, 12.0, 10.5)]))
        assert r.eval_status == "completed"
        assert r.direction_expected == "up"
        assert r.direction_correct is True
        assert r.outcome == "win"
        assert r.stock_return_pct == 15.0

    def test_buy_loss(self):
        """BUY with -5% return → loss."""
        r = self._eval(action="BUY", signal_close=10.0,
                       bars=_make_bars([(9.5, 10.0, 9.0)]))
        assert r.direction_correct is False
        assert r.outcome == "loss"

    def test_buy_neutral(self):
        """BUY with +1% return (within 2% band) → neutral."""
        r = self._eval(action="BUY", signal_close=10.0,
                       bars=_make_bars([(10.1, 10.2, 9.9)]))
        assert r.direction_correct is None
        assert r.outcome == "neutral"

    def test_sell_win(self):
        """SELL with -5% return → win (direction correct)."""
        r = self._eval(action="SELL", signal_close=10.0,
                       bars=_make_bars([(9.5, 9.8, 9.0)]))
        assert r.direction_expected == "down"
        assert r.direction_correct is True
        assert r.outcome == "win"

    def test_sell_loss(self):
        """SELL with +5% return → loss."""
        r = self._eval(action="SELL", signal_close=10.0,
                       bars=_make_bars([(10.5, 11.0, 10.2)]))
        assert r.direction_correct is False
        assert r.outcome == "loss"

    def test_hold_correct(self):
        """HOLD with +1% return (within band) → direction correct."""
        r = self._eval(action="HOLD", signal_close=10.0,
                       bars=_make_bars([(10.1, 10.2, 9.9)]))
        assert r.direction_expected == "flat"
        assert r.direction_correct is True
        assert r.outcome == "neutral"

    def test_hold_wrong(self):
        """HOLD with +5% return → direction wrong (price moved too much)."""
        r = self._eval(action="HOLD", signal_close=10.0,
                       bars=_make_bars([(10.5, 11.0, 10.2)]))
        assert r.direction_correct is False

    def test_veto_abstain(self):
        """VETO → abstain, no direction judgment."""
        r = self._eval(action="VETO", signal_close=10.0,
                       bars=_make_bars([(11.0, 11.5, 10.5)]))
        assert r.direction_expected == "abstain"
        assert r.direction_correct is None
        assert r.outcome == "neutral"

    def test_return_calculations(self):
        """Verify stock_return_pct, max_gain_pct, max_drawdown_pct."""
        bars = _make_bars([
            (10.5, 11.0, 9.5),
            (10.8, 10.8, 10.0),
            (10.2, 10.3, 10.0),
        ])
        r = self._eval(signal_close=10.0, bars=bars)
        assert r.stock_return_pct == 2.0    # (10.2-10)/10*100
        assert r.max_gain_pct == 10.0       # (11.0-10)/10*100
        assert r.max_drawdown_pct == -5.0   # (9.5-10)/10*100

    def test_stop_loss_hit(self):
        """Stop loss triggered when min_low <= stop_loss."""
        r = self._eval(signal_close=10.0, stop_loss=9.6,
                       bars=_make_bars([(9.8, 10.0, 9.5)]))
        assert r.hit_stop_loss is True
        assert r.first_hit == "stop_loss"

    def test_take_profit_hit(self):
        """Take profit triggered when max_high >= take_profit."""
        r = self._eval(signal_close=10.0, take_profit=11.0,
                       bars=_make_bars([(10.5, 11.5, 10.2)]))
        assert r.hit_take_profit is True
        assert r.first_hit == "take_profit"

    def test_both_hit_ambiguous(self):
        """Both SL and TP hit → ambiguous."""
        r = self._eval(signal_close=10.0, stop_loss=9.5, take_profit=11.0,
                       bars=_make_bars([(10.5, 11.5, 9.0)]))
        assert r.hit_stop_loss is True
        assert r.hit_take_profit is True
        assert r.first_hit == "ambiguous"

    def test_neither_hit(self):
        """Neither SL nor TP → neither."""
        r = self._eval(signal_close=10.0, stop_loss=8.0, take_profit=15.0,
                       bars=_make_bars([(10.2, 10.5, 10.0)]))
        assert r.first_hit == "neither"

    def test_insufficient_no_close(self):
        """signal_close=0 and fetch returns 0 → insufficient."""
        from unittest.mock import patch
        with patch("subagent_pipeline.backtest.fetch_signal_day_close", return_value=0.0):
            r = evaluate_signal(
                run_id="x", ticker="601985.SS", ticker_name="T",
                trade_date="2026-03-10", action="BUY", confidence=0.5,
                was_vetoed=False, signal_close=0.0,
                forward_bars=_make_bars([(10,10,10)]),
                config=BacktestConfig(),
            )
        assert r.eval_status == "insufficient"

    def test_insufficient_no_bars(self):
        """Empty forward_bars → insufficient."""
        r = evaluate_signal(
            run_id="x", ticker="601985.SS", ticker_name="T",
            trade_date="2026-03-10", action="BUY", confidence=0.5,
            was_vetoed=False, signal_close=10.0, forward_bars=[],
            config=BacktestConfig(),
        )
        assert r.eval_status == "insufficient"

    def test_custom_neutral_band(self):
        """Wider neutral band changes outcome classification."""
        # +3% return with default 2% band → win
        bars = _make_bars([(10.3, 10.3, 10.0)])
        r1 = self._eval(action="BUY", signal_close=10.0, bars=bars,
                        config=BacktestConfig(neutral_band_pct=2.0))
        assert r1.outcome == "win"

        # Same +3% return with 5% band → neutral
        r2 = self._eval(action="BUY", signal_close=10.0, bars=bars,
                        config=BacktestConfig(neutral_band_pct=5.0))
        assert r2.outcome == "neutral"

    def test_bars_available_count(self):
        """bars_available reflects actual bar count."""
        bars = _make_bars([(10,10,10)] * 7)
        r = self._eval(bars=bars)
        assert r.bars_available == 7


# ── compute_summary ──────────────────────────────────────────────────────

def _completed_result(action="BUY", return_pct=5.0, direction_correct=True,
                      outcome="win", stop_loss_hit=False, take_profit_hit=False):
    """Create a completed BacktestResult for summary testing."""
    return BacktestResult(
        run_id=f"r-{action}-{return_pct}",
        ticker="601985.SS",
        trade_date="2026-03-10",
        action=action,
        confidence=0.7,
        direction_expected=infer_direction(action),
        stock_return_pct=return_pct,
        direction_correct=direction_correct,
        outcome=outcome,
        eval_status="completed",
        hit_stop_loss=stop_loss_hit,
        hit_take_profit=take_profit_hit,
    )


class TestComputeSummary:
    """Tests for compute_summary aggregation logic."""

    def test_empty_results(self):
        s = compute_summary([])
        assert s.total_signals == 0
        assert s.completed == 0
        assert s.direction_accuracy_pct == 0.0
        assert s.win_rate_pct == 0.0

    def test_all_insufficient(self):
        """Only insufficient results → counts populated, no metrics."""
        results = [
            BacktestResult(eval_status="insufficient"),
            BacktestResult(eval_status="insufficient"),
        ]
        s = compute_summary(results)
        assert s.total_signals == 2
        assert s.completed == 0
        assert s.insufficient == 2
        assert s.direction_accuracy_pct == 0.0

    def test_single_buy_win(self):
        s = compute_summary([_completed_result("BUY", 5.0, True, "win")])
        assert s.completed == 1
        assert s.buy_count == 1
        assert s.direction_correct_count == 1
        assert s.direction_accuracy_pct == 100.0
        assert s.win_count == 1
        assert s.win_rate_pct == 100.0
        assert s.avg_stock_return_pct == 5.0
        assert s.avg_buy_return_pct == 5.0

    def test_single_sell_win(self):
        """SELL win: return is -5%, but avg_sell_return_pct inverted to +5%."""
        s = compute_summary([_completed_result("SELL", -5.0, True, "win")])
        assert s.sell_count == 1
        assert s.avg_sell_return_pct == 5.0  # inverted

    def test_mixed_actions(self):
        results = [
            _completed_result("BUY", 5.0, True, "win"),
            _completed_result("BUY", -3.0, False, "loss"),
            _completed_result("SELL", -4.0, True, "win"),
            _completed_result("HOLD", 0.5, True, "neutral"),
            _completed_result("VETO", 2.0, None, "neutral"),
        ]
        s = compute_summary(results)
        assert s.completed == 5
        assert s.buy_count == 2
        assert s.sell_count == 1
        assert s.hold_count == 1
        assert s.veto_count == 1
        # Direction accuracy: only BUY + SELL directional (3 signals), 2 correct + 1 wrong
        # but dir_decided excludes None — BUY(True), BUY(False), SELL(True) → 3 decided
        assert s.direction_correct_count == 2
        assert s.direction_wrong_count == 1
        assert s.direction_accuracy_pct == pytest.approx(66.7, abs=0.1)
        # Win rate: directional only (BUY+SELL), 2 wins + 1 loss
        assert s.win_count == 2
        assert s.loss_count == 1
        assert s.win_rate_pct == pytest.approx(66.7, abs=0.1)

    def test_veto_excluded_from_direction_accuracy(self):
        """VETO (abstain) signals should not affect direction accuracy."""
        results = [
            _completed_result("BUY", 5.0, True, "win"),
            _completed_result("VETO", 5.0, None, "neutral"),
            _completed_result("VETO", -5.0, None, "neutral"),
        ]
        s = compute_summary(results)
        assert s.direction_correct_count == 1
        assert s.direction_wrong_count == 0
        assert s.direction_accuracy_pct == 100.0
        # Win rate: only 1 directional win, 0 losses
        assert s.win_rate_pct == 100.0

    def test_hold_excluded_from_win_rate(self):
        """HOLD (flat) signals should not affect win rate."""
        results = [
            _completed_result("BUY", 5.0, True, "win"),
            _completed_result("HOLD", 0.5, True, "neutral"),
        ]
        s = compute_summary(results)
        assert s.win_count == 1
        assert s.loss_count == 0
        assert s.win_rate_pct == 100.0

    def test_stop_loss_take_profit_counts(self):
        results = [
            _completed_result("BUY", 5.0, True, "win", stop_loss_hit=False, take_profit_hit=True),
            _completed_result("BUY", -5.0, False, "loss", stop_loss_hit=True, take_profit_hit=False),
            _completed_result("BUY", 1.0, None, "neutral"),
        ]
        s = compute_summary(results)
        assert s.stop_loss_hit_count == 1
        assert s.take_profit_hit_count == 1

    def test_action_breakdown(self):
        results = [
            _completed_result("BUY", 5.0, True, "win"),
            _completed_result("BUY", -3.0, False, "loss"),
            _completed_result("SELL", -4.0, True, "win"),
        ]
        s = compute_summary(results)
        assert "BUY" in s.action_breakdown
        assert "SELL" in s.action_breakdown
        assert s.action_breakdown["BUY"]["count"] == 2
        assert s.action_breakdown["BUY"]["win_count"] == 1
        assert s.action_breakdown["BUY"]["loss_count"] == 1
        assert s.action_breakdown["BUY"]["win_rate_pct"] == 50.0
        assert s.action_breakdown["SELL"]["count"] == 1
        assert s.action_breakdown["SELL"]["win_rate_pct"] == 100.0

    def test_scope_and_config_passthrough(self):
        cfg = BacktestConfig(eval_window_days=20, engine_version="v2")
        s = compute_summary([], scope="601985.SS", config=cfg)
        assert s.scope == "601985.SS"
        assert s.eval_window_days == 20
        assert s.engine_version == "v2"

    def test_avg_returns_mixed(self):
        results = [
            _completed_result("BUY", 10.0, True, "win"),
            _completed_result("BUY", -4.0, False, "loss"),
        ]
        s = compute_summary(results)
        assert s.avg_stock_return_pct == 3.0   # (10 + -4) / 2
        assert s.avg_buy_return_pct == 3.0


# ── Dataclass round-trips ────────────────────────────────────────────────

class TestDataclassRoundTrip:
    """Verify to_dict / from_dict preserve data."""

    def test_backtest_result_roundtrip(self):
        r = BacktestResult(
            run_id="rt-001", ticker="601985.SS", ticker_name="中国中冶",
            trade_date="2026-03-10", action="BUY", confidence=0.85,
            direction_expected="up", start_price=10.0, end_close=11.0,
            stock_return_pct=10.0, direction_correct=True, outcome="win",
            eval_status="completed", stop_loss=9.0, take_profit=12.0,
            hit_stop_loss=False, hit_take_profit=False, first_hit="neither",
        )
        d = r.to_dict()
        r2 = BacktestResult.from_dict(d)
        assert r2.run_id == r.run_id
        assert r2.ticker == r.ticker
        assert r2.stock_return_pct == r.stock_return_pct
        assert r2.direction_correct == r.direction_correct
        assert r2.eval_status == r.eval_status

    def test_from_dict_ignores_extra_keys(self):
        d = {"run_id": "x", "ticker": "y", "extra_field": 42}
        r = BacktestResult.from_dict(d)
        assert r.run_id == "x"
        assert not hasattr(r, "extra_field")

    def test_backtest_summary_to_dict(self):
        s = BacktestSummary(
            scope="overall", total_signals=10, completed=8,
            direction_accuracy_pct=75.0, win_rate_pct=60.0,
        )
        d = s.to_dict()
        assert d["scope"] == "overall"
        assert d["total_signals"] == 10
        assert d["win_rate_pct"] == 60.0

    def test_backtest_report_to_dict(self):
        cfg = BacktestConfig(eval_window_days=5, neutral_band_pct=1.5)
        r = BacktestResult(run_id="r1", action="BUY", eval_status="completed")
        report = BacktestReport(
            config=cfg, results=[r],
            overall_summary=BacktestSummary(total_signals=1),
        )
        d = report.to_dict()
        assert d["config"]["eval_window_days"] == 5
        assert d["config"]["neutral_band_pct"] == 1.5
        assert len(d["results"]) == 1
        assert d["overall_summary"]["total_signals"] == 1

    def test_report_summary_alias(self):
        """report.summary is an alias for report.overall_summary."""
        s = BacktestSummary(scope="test")
        report = BacktestReport(overall_summary=s)
        assert report.summary is report.overall_summary
        assert report.summary.scope == "test"


# ── BacktestConfig ───────────────────────────────────────────────────────

class TestBacktestConfig:
    """BacktestConfig is frozen and has sensible defaults."""

    def test_defaults(self):
        c = BacktestConfig()
        assert c.eval_window_days == 10
        assert c.neutral_band_pct == 2.0
        assert c.min_age_days == 1
        assert c.engine_version == "v1"

    def test_frozen(self):
        c = BacktestConfig()
        with pytest.raises(AttributeError):
            c.eval_window_days = 20

    def test_custom_values(self):
        c = BacktestConfig(eval_window_days=20, neutral_band_pct=3.0, min_age_days=5)
        assert c.eval_window_days == 20
        assert c.neutral_band_pct == 3.0
        assert c.min_age_days == 5


# ── Edge cases and boundary behavior ─────────────────────────────────────

class TestEdgeCases:
    """Boundary conditions and edge cases."""

    def test_exact_neutral_boundary_buy(self):
        """Return exactly at +neutral_band → neutral (not >)."""
        bars = _make_bars([(10.2, 10.2, 10.0)])  # +2.0% exactly
        r = evaluate_signal(
            run_id="edge", ticker="601985.SS", ticker_name="T",
            trade_date="2026-03-10", action="BUY", confidence=0.5,
            was_vetoed=False, signal_close=10.0, forward_bars=bars,
            config=BacktestConfig(neutral_band_pct=2.0),
        )
        # +2.0% is NOT > 2.0, so neutral
        assert r.outcome == "neutral"
        assert r.direction_correct is None

    def test_exact_negative_boundary_sell(self):
        """Return exactly at -neutral_band → neutral (not <)."""
        bars = _make_bars([(9.8, 10.0, 9.8)])  # -2.0% exactly
        r = evaluate_signal(
            run_id="edge", ticker="601985.SS", ticker_name="T",
            trade_date="2026-03-10", action="SELL", confidence=0.5,
            was_vetoed=False, signal_close=10.0, forward_bars=bars,
            config=BacktestConfig(neutral_band_pct=2.0),
        )
        assert r.outcome == "neutral"
        assert r.direction_correct is None

    def test_zero_return(self):
        """Exactly 0% return → neutral for all actions."""
        bars = _make_bars([(10.0, 10.0, 10.0)])
        for action in ("BUY", "SELL"):
            r = evaluate_signal(
                run_id="z", ticker="601985.SS", ticker_name="T",
                trade_date="2026-03-10", action=action, confidence=0.5,
                was_vetoed=False, signal_close=10.0, forward_bars=bars,
                config=BacktestConfig(),
            )
            assert r.outcome == "neutral"

    def test_bars_with_zero_values_skipped(self):
        """Bars with close=0 are excluded from metric calculations."""
        bars = [
            {"close": 10.5, "high": 11.0, "low": 10.0},
            {"close": 0, "high": 0, "low": 0},         # bad bar
            {"close": 11.0, "high": 11.5, "low": 10.5},
        ]
        r = evaluate_signal(
            run_id="z", ticker="601985.SS", ticker_name="T",
            trade_date="2026-03-10", action="BUY", confidence=0.5,
            was_vetoed=False, signal_close=10.0, forward_bars=bars,
            config=BacktestConfig(),
        )
        assert r.eval_status == "completed"
        assert r.end_close == 11.0  # last valid close
        assert r.max_high == 11.5
        assert r.min_low == 10.0

    def test_stop_loss_zero_means_disabled(self):
        """stop_loss=0 → never triggers."""
        bars = _make_bars([(5.0, 10.0, 1.0)])  # extreme low
        r = evaluate_signal(
            run_id="z", ticker="601985.SS", ticker_name="T",
            trade_date="2026-03-10", action="BUY", confidence=0.5,
            was_vetoed=False, signal_close=10.0, forward_bars=bars,
            config=BacktestConfig(), stop_loss=0.0, take_profit=0.0,
        )
        assert r.hit_stop_loss is False
        assert r.hit_take_profit is False
        assert r.first_hit == "neither"
