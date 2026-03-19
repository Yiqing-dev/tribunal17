"""Tests for opinion_tracker — daily cross-ticker opinion drift analysis."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from subagent_pipeline.opinion_tracker import (
    DailySnapshot,
    OpinionDrift,
    WatchlistReport,
    build_watchlist_report,
    compute_drift,
    extract_snapshot,
    latest_drift,
    track_ticker,
    _claims_match,
    _diff_claims,
    _normalize_ticker,
    _assess_magnitude,
    _assess_direction,
)
from subagent_pipeline.trace_models import NodeTrace, RunTrace, NodeStatus
from subagent_pipeline.replay_store import ReplayStore


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_trace(
    ticker="601985",
    ticker_name="中国核电",
    trade_date="2026-03-17",
    action="BUY",
    confidence=0.72,
    market_score=2,
    fundamental_score=1,
    news_score=2,
    sentiment_score=1,
    risk_score=4,
    risk_cleared=True,
    risk_flags=None,
    bull_claims=None,
    bear_claims=None,
    bull_confidence=0.75,
    bear_confidence=0.60,
    base_prob=0.55,
    bull_prob=0.30,
    bear_prob=0.15,
    pm_conclusion="建议逢低买入",
    thesis_effect="strengthened",
    stop_loss=8.5,
    take_profit=10.5,
    was_vetoed=False,
    market_regime="RISK_ON",
    run_id=None,
) -> RunTrace:
    """Build a mock RunTrace with controlled structured_data."""
    if risk_flags is None:
        risk_flags = ["估值风险"]
    if bull_claims is None:
        bull_claims = [
            {"text": "核电审批重启加速", "confidence": 0.8, "dimension": "catalysts"},
            {"text": "ROE连续改善", "confidence": 0.7, "dimension": "fundamentals"},
        ]
    if bear_claims is None:
        bear_claims = [
            {"text": "电价下行风险", "confidence": 0.6, "dimension": "fundamentals"},
        ]

    rt = RunTrace(
        ticker=ticker,
        ticker_name=ticker_name,
        trade_date=trade_date,
        research_action=action,
        final_confidence=confidence,
        was_vetoed=was_vetoed,
        market_context={"regime": market_regime},
    )
    if run_id:
        rt.run_id = run_id

    # Analyst nodes
    analyst_nodes = [
        ("Market Analyst", "market_analyst", market_score),
        ("Fundamentals Analyst", "fundamentals_analyst", fundamental_score),
        ("News Analyst", "news_analyst", news_score),
        ("Social Analyst", "sentiment_analyst", sentiment_score),
    ]
    for i, (name, _, score) in enumerate(analyst_nodes):
        nt = NodeTrace(
            run_id=rt.run_id,
            node_name=name,
            seq=i,
            structured_data={"pillar_score": score},
        )
        rt.node_traces.append(nt)

    # Bull researcher
    bull_supporting = [
        {
            "claim_id": f"clm-b{j:03d}",
            "text": c["text"],
            "dimension": c.get("dimension", ""),
            "confidence": c["confidence"],
            "supports": [],
        }
        for j, c in enumerate(bull_claims)
    ]
    nt_bull = NodeTrace(
        run_id=rt.run_id,
        node_name="Bull Researcher",
        seq=4,
        structured_data={
            "thesis": "多头主论点",
            "direction": "bullish",
            "overall_confidence": bull_confidence,
            "supporting_claims": bull_supporting,
        },
    )
    rt.node_traces.append(nt_bull)

    # Bear researcher
    bear_supporting = [
        {
            "claim_id": f"clm-r{j:03d}",
            "text": c["text"],
            "dimension": c.get("dimension", ""),
            "confidence": c["confidence"],
            "supports": [],
        }
        for j, c in enumerate(bear_claims)
    ]
    nt_bear = NodeTrace(
        run_id=rt.run_id,
        node_name="Bear Researcher",
        seq=5,
        structured_data={
            "thesis": "空头主论点",
            "direction": "bearish",
            "overall_confidence": bear_confidence,
            "supporting_claims": bear_supporting,
        },
    )
    rt.node_traces.append(nt_bear)

    # Scenario agent
    nt_scenario = NodeTrace(
        run_id=rt.run_id,
        node_name="Scenario Agent",
        seq=6,
        structured_data={
            "base_prob": base_prob,
            "bull_prob": bull_prob,
            "bear_prob": bear_prob,
        },
    )
    rt.node_traces.append(nt_scenario)

    # Research Manager
    nt_pm = NodeTrace(
        run_id=rt.run_id,
        node_name="Research Manager",
        seq=7,
        research_action=action,
        confidence=confidence,
        thesis_effect=thesis_effect,
        structured_data={"conclusion": pm_conclusion},
    )
    rt.node_traces.append(nt_pm)

    # Risk Judge
    nt_risk = NodeTrace(
        run_id=rt.run_id,
        node_name="Risk Judge",
        seq=8,
        risk_score=risk_score,
        risk_cleared=risk_cleared,
        risk_flag_categories=risk_flags,
        risk_flag_count=len(risk_flags),
        structured_data={},
    )
    rt.node_traces.append(nt_risk)

    # ResearchOutput
    nt_output = NodeTrace(
        run_id=rt.run_id,
        node_name="ResearchOutput",
        seq=9,
        structured_data={
            "tradecard": {
                "pillars": {
                    "market_score": market_score,
                    "fundamental_score": fundamental_score,
                    "news_score": news_score,
                    "sentiment_score": sentiment_score,
                },
                "risk_score": risk_score,
            },
            "trade_plan": {
                "stop_loss": {"price": stop_loss},
                "take_profit": [{"price_zone": [take_profit, take_profit + 0.5]}],
            },
        },
    )
    rt.node_traces.append(nt_output)

    return rt


def _store_with_traces(traces):
    """Create a temp ReplayStore and save traces into it."""
    tmp = tempfile.mkdtemp()
    store = ReplayStore(storage_dir=tmp)
    for t in traces:
        t.finalize()
        store.save(t)
    return tmp


# ── Test extract_snapshot ───────────────────────────────────────────────


class TestExtractSnapshot:
    def test_basic_extraction(self):
        trace = _make_trace()
        snap = extract_snapshot(trace)

        assert snap.ticker == "601985.SS"
        assert snap.ticker_name == "中国核电"
        assert snap.action == "BUY"
        assert snap.confidence == 0.72
        assert snap.market_score == 2
        assert snap.fundamental_score == 1
        assert snap.news_score == 2
        assert snap.sentiment_score == 1
        assert snap.risk_score == 4
        assert snap.risk_cleared is True
        assert "估值风险" in snap.risk_flags

    def test_bull_bear_claims(self):
        trace = _make_trace()
        snap = extract_snapshot(trace)

        assert len(snap.bull_claims) == 2
        assert snap.bull_claims[0]["text"] == "核电审批重启加速"
        assert snap.bull_overall_confidence == 0.75
        assert len(snap.bear_claims) == 1
        assert snap.bear_overall_confidence == 0.60

    def test_scenario_probs(self):
        trace = _make_trace(base_prob=0.5, bull_prob=0.3, bear_prob=0.2)
        snap = extract_snapshot(trace)

        assert snap.base_prob == 0.5
        assert snap.bull_prob == 0.3
        assert snap.bear_prob == 0.2

    def test_pm_synthesis(self):
        trace = _make_trace(pm_conclusion="逢低吸纳", thesis_effect="unchanged")
        snap = extract_snapshot(trace)

        assert snap.pm_conclusion == "逢低吸纳"
        assert snap.thesis_effect == "unchanged"

    def test_trade_plan_prices(self):
        trace = _make_trace(stop_loss=8.5, take_profit=10.5)
        snap = extract_snapshot(trace)

        assert snap.stop_loss == 8.5
        assert snap.take_profit == 10.75  # midpoint of [10.5, 11.0]

    def test_vetoed_trace(self):
        trace = _make_trace(action="VETO", was_vetoed=True)
        snap = extract_snapshot(trace)

        assert snap.action == "VETO"
        assert snap.was_vetoed is True

    def test_sentinel_confidence(self):
        trace = _make_trace(confidence=-1.0)
        snap = extract_snapshot(trace)
        assert snap.confidence == -1.0

    def test_ticker_normalization_ss(self):
        trace = _make_trace(ticker="601985")
        snap = extract_snapshot(trace)
        assert snap.ticker == "601985.SS"

    def test_ticker_normalization_sz(self):
        trace = _make_trace(ticker="000710")
        snap = extract_snapshot(trace)
        assert snap.ticker == "000710.SZ"

    def test_ticker_already_suffixed(self):
        trace = _make_trace(ticker="601985.SS")
        snap = extract_snapshot(trace)
        assert snap.ticker == "601985.SS"

    def test_market_regime(self):
        trace = _make_trace(market_regime="RISK_OFF")
        snap = extract_snapshot(trace)
        assert snap.market_regime == "RISK_OFF"

    def test_empty_node_traces(self):
        rt = RunTrace(ticker="601985", trade_date="2026-03-17")
        snap = extract_snapshot(rt)
        assert snap.ticker == "601985.SS"
        assert snap.market_score == -1
        assert snap.bull_claims == []

    def test_to_dict_roundtrip(self):
        trace = _make_trace()
        snap = extract_snapshot(trace)
        d = snap.to_dict()
        snap2 = DailySnapshot.from_dict(d)
        assert snap2.action == snap.action
        assert snap2.confidence == snap.confidence
        assert snap2.bull_claims == snap.bull_claims


# ── Test compute_drift ──────────────────────────────────────────────────


class TestComputeDrift:
    def test_stable_drift(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="HOLD", confidence=0.55,
            market_score=1, fundamental_score=1, news_score=1, sentiment_score=1,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="HOLD", confidence=0.55,
            market_score=1, fundamental_score=1, news_score=1, sentiment_score=1,
        )
        d = compute_drift(s1, s2)

        assert not d.action_changed
        assert d.confidence_delta == 0.0
        assert d.drift_magnitude == "stable"
        assert d.drift_direction == "unchanged"

    def test_action_flip(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="HOLD", confidence=0.55,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="BUY", confidence=0.72,
        )
        d = compute_drift(s1, s2)

        assert d.action_changed
        assert d.action_prev == "HOLD"
        assert d.action_curr == "BUY"
        assert d.drift_magnitude == "major"
        assert d.drift_direction == "bullish_shift"

    def test_bearish_shift(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="BUY", confidence=0.70,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="SELL", confidence=0.40,
        )
        d = compute_drift(s1, s2)

        assert d.drift_direction == "bearish_shift"
        assert d.drift_magnitude == "major"

    def test_confidence_delta(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="BUY", confidence=0.55,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="BUY", confidence=0.72,
        )
        d = compute_drift(s1, s2)

        assert abs(d.confidence_delta - 0.17) < 0.01
        assert d.drift_magnitude == "major"  # >= 0.15
        assert d.drift_direction == "bullish_shift"

    def test_minor_confidence_shift(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="HOLD", confidence=0.50,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="HOLD", confidence=0.58,
        )
        d = compute_drift(s1, s2)

        assert d.drift_magnitude == "minor"

    def test_pillar_score_delta(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="HOLD", confidence=0.50,
            market_score=0, news_score=1,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="HOLD", confidence=0.50,
            market_score=2, news_score=1,
        )
        d = compute_drift(s1, s2)

        assert d.market_score_delta == 2
        assert d.news_score_delta == 0
        assert d.drift_magnitude == "major"  # pillar delta >= 2

    def test_sentinel_confidence_ignored(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            action="HOLD", confidence=-1.0,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            action="HOLD", confidence=0.60,
        )
        d = compute_drift(s1, s2)
        assert d.confidence_delta == 0.0

    def test_sentinel_score_ignored(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            market_score=-1,
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            market_score=2,
        )
        d = compute_drift(s1, s2)
        assert d.market_score_delta == 0

    def test_risk_flags_diff(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            risk_flags=["估值风险", "流动性风险"],
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            risk_flags=["估值风险", "政策风险"],
        )
        d = compute_drift(s1, s2)

        assert d.risk_flags_added == ["政策风险"]
        assert d.risk_flags_removed == ["流动性风险"]

    def test_regime_change(self):
        s1 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-14",
            market_regime="RISK_ON",
        )
        s2 = DailySnapshot(
            ticker="601985.SS", trade_date="2026-03-17",
            market_regime="RISK_OFF",
        )
        d = compute_drift(s1, s2)
        assert d.regime_changed


# ── Test claim matching ─────────────────────────────────────────────────


class TestClaimMatching:
    def test_exact_match(self):
        assert _claims_match("核电审批加速", "核电审批加速")

    def test_substring_match(self):
        assert _claims_match("核电审批加速", "核电审批加速，利好中国核电")

    def test_no_match(self):
        assert not _claims_match("核电审批加速", "电价下行风险")

    def test_empty_strings(self):
        assert not _claims_match("", "核电")
        assert not _claims_match("", "")

    def test_diff_claims_all_new(self):
        prev = [{"text": "old claim"}]
        curr = [{"text": "completely new claim"}]
        added, dropped = _diff_claims(prev, curr)
        assert "completely new claim" in added
        assert "old claim" in dropped

    def test_diff_claims_all_same(self):
        claims = [{"text": "same claim"}, {"text": "another same"}]
        added, dropped = _diff_claims(claims, claims)
        assert added == []
        assert dropped == []

    def test_diff_claims_partial_overlap(self):
        prev = [{"text": "核电审批加速"}, {"text": "ROE改善"}]
        curr = [{"text": "核电审批加速"}, {"text": "新增论据"}]
        added, dropped = _diff_claims(prev, curr)
        assert "新增论据" in added
        assert "ROE改善" in dropped


# ── Test WatchlistReport ────────────────────────────────────────────────


class TestWatchlistReport:
    def test_build_report_with_traces(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="HOLD", confidence=0.55, run_id="run-day1",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="BUY", confidence=0.72, run_id="run-day2",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )

        assert "601985.SS" in report.snapshots
        snaps = report.snapshots["601985.SS"]
        assert len(snaps) == 2
        assert snaps[0].trade_date == "2026-03-14"
        assert snaps[1].trade_date == "2026-03-17"

        drifts = report.drifts["601985.SS"]
        assert len(drifts) == 1
        assert drifts[0].action_changed
        assert drifts[0].action_prev == "HOLD"
        assert drifts[0].action_curr == "BUY"

    def test_action_flips_collected(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="HOLD", confidence=0.50, run_id="run-a",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="BUY", confidence=0.72, run_id="run-b",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        assert len(report.action_flips) == 1
        assert report.action_flips[0]["from_action"] == "HOLD"
        assert report.action_flips[0]["to_action"] == "BUY"

    def test_confidence_moves_collected(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="BUY", confidence=0.50, run_id="run-c",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="BUY", confidence=0.70, run_id="run-d",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        assert len(report.biggest_confidence_moves) == 1
        assert abs(report.biggest_confidence_moves[0]["delta"] - 0.20) < 0.01

    def test_multi_ticker(self):
        traces = [
            _make_trace(ticker="601985", trade_date="2026-03-14", run_id="r1"),
            _make_trace(ticker="601985", trade_date="2026-03-17", run_id="r2"),
            _make_trace(ticker="000710", trade_date="2026-03-14", run_id="r3"),
            _make_trace(ticker="000710", trade_date="2026-03-17", run_id="r4"),
        ]
        storage = _store_with_traces(traces)

        report = build_watchlist_report(
            tickers=["601985.SS", "000710.SZ"],
            storage_dir=storage,
        )
        assert "601985.SS" in report.snapshots
        assert "000710.SZ" in report.snapshots

    def test_date_range_filter(self):
        traces = [
            _make_trace(ticker="601985", trade_date="2026-03-14", run_id="r1"),
            _make_trace(ticker="601985", trade_date="2026-03-17", run_id="r2"),
            _make_trace(ticker="601985", trade_date="2026-03-19", run_id="r3"),
        ]
        storage = _store_with_traces(traces)

        report = build_watchlist_report(
            tickers=["601985.SS"],
            date_from="2026-03-16",
            date_to="2026-03-18",
            storage_dir=storage,
        )
        snaps = report.snapshots.get("601985.SS", [])
        assert len(snaps) == 1
        assert snaps[0].trade_date == "2026-03-17"

    def test_current_state(self):
        traces = [
            _make_trace(
                ticker="601985", trade_date="2026-03-14",
                action="HOLD", run_id="r1",
            ),
            _make_trace(
                ticker="601985", trade_date="2026-03-17",
                action="BUY", run_id="r2",
            ),
        ]
        storage = _store_with_traces(traces)

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        assert report.current_state["601985.SS"].action == "BUY"

    def test_empty_store(self):
        tmp = tempfile.mkdtemp()
        store = ReplayStore(storage_dir=tmp)

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=tmp,
        )
        assert report.snapshots.get("601985.SS", []) == []

    def test_risk_flags_highlight(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            risk_flags=["估值风险"], run_id="r1",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            risk_flags=["估值风险", "政策风险"], run_id="r2",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        assert len(report.new_risk_flags) == 1
        assert "政策风险" in report.new_risk_flags[0]["flags"]


# ── Test Markdown output ────────────────────────────────────────────────


class TestMarkdown:
    def test_markdown_has_header(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="HOLD", confidence=0.55, run_id="r1",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="BUY", confidence=0.72, run_id="r2",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        md = report.to_markdown()

        assert "# 观点跟踪报告" in md
        assert "601985.SS" in md
        assert "HOLD -> BUY" in md

    def test_markdown_stable_no_drift_detail(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="HOLD", confidence=0.55, run_id="r1",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="HOLD", confidence=0.55, run_id="r2",
        )
        storage = _store_with_traces([t1, t2])

        report = build_watchlist_report(
            tickers=["601985.SS"],
            storage_dir=storage,
        )
        md = report.to_markdown()

        # Stable drift should not produce detail block
        assert "重大" not in md
        assert "变动)" not in md

    def test_to_dict_roundtrip(self):
        report = WatchlistReport(
            date_from="2026-03-14",
            date_to="2026-03-19",
            tickers=["601985.SS"],
        )
        d = report.to_dict()
        assert d["date_from"] == "2026-03-14"
        assert d["tickers"] == ["601985.SS"]


# ── Test convenience functions ──────────────────────────────────────────


class TestConvenience:
    def test_track_ticker(self):
        traces = [
            _make_trace(ticker="601985", trade_date=f"2026-03-{d:02d}", run_id=f"r{d}")
            for d in range(14, 20)
        ]
        storage = _store_with_traces(traces)

        snaps, drifts = track_ticker("601985.SS", storage_dir=storage)
        assert len(snaps) == 6
        assert len(drifts) == 5

    def test_track_ticker_limit(self):
        traces = [
            _make_trace(ticker="601985", trade_date=f"2026-03-{d:02d}", run_id=f"r{d}")
            for d in range(14, 20)
        ]
        storage = _store_with_traces(traces)

        snaps, drifts = track_ticker("601985.SS", storage_dir=storage, limit=3)
        assert len(snaps) == 3
        assert len(drifts) == 2

    def test_latest_drift(self):
        t1 = _make_trace(
            ticker="601985", trade_date="2026-03-14",
            action="HOLD", run_id="r1",
        )
        t2 = _make_trace(
            ticker="601985", trade_date="2026-03-17",
            action="BUY", run_id="r2",
        )
        storage = _store_with_traces([t1, t2])

        d = latest_drift("601985.SS", storage_dir=storage)
        assert d is not None
        assert d.action_curr == "BUY"
        assert d.action_prev == "HOLD"

    def test_latest_drift_no_data(self):
        tmp = tempfile.mkdtemp()
        d = latest_drift("601985.SS", storage_dir=tmp)
        assert d is None

    def test_latest_drift_single_snapshot(self):
        t1 = _make_trace(ticker="601985", trade_date="2026-03-14", run_id="r1")
        storage = _store_with_traces([t1])

        d = latest_drift("601985.SS", storage_dir=storage)
        assert d is None


# ── Test normalize_ticker ───────────────────────────────────────────────


class TestNormalizeTicker:
    def test_ss(self):
        assert _normalize_ticker("601985") == "601985.SS"

    def test_sz(self):
        assert _normalize_ticker("000710") == "000710.SZ"

    def test_sz_300(self):
        assert _normalize_ticker("300750") == "300750.SZ"

    def test_bj(self):
        assert _normalize_ticker("830799") == "830799.BJ"

    def test_already_suffixed(self):
        assert _normalize_ticker("601985.SS") == "601985.SS"


# ── Test magnitude/direction assessment ─────────────────────────────────


class TestAssessment:
    def _drift(self, **kw) -> OpinionDrift:
        return OpinionDrift(**kw)

    def test_major_action_change(self):
        d = self._drift(action_prev="HOLD", action_curr="BUY", action_changed=True)
        assert _assess_magnitude(d) == "major"

    def test_major_confidence(self):
        d = self._drift(confidence_delta=0.20)
        assert _assess_magnitude(d) == "major"

    def test_minor_confidence(self):
        d = self._drift(confidence_delta=0.08)
        assert _assess_magnitude(d) == "minor"

    def test_minor_risk_flags(self):
        d = self._drift(risk_flags_added=["new_flag"])
        assert _assess_magnitude(d) == "minor"

    def test_stable(self):
        d = self._drift()
        assert _assess_magnitude(d) == "stable"

    def test_bullish_shift_action(self):
        d = self._drift(action_prev="HOLD", action_curr="BUY")
        assert _assess_direction(d) == "bullish_shift"

    def test_bearish_shift_action(self):
        d = self._drift(action_prev="BUY", action_curr="SELL")
        assert _assess_direction(d) == "bearish_shift"

    def test_bullish_shift_confidence(self):
        d = self._drift(action_prev="HOLD", action_curr="HOLD", confidence_delta=0.10)
        assert _assess_direction(d) == "bullish_shift"

    def test_unchanged(self):
        d = self._drift(action_prev="HOLD", action_curr="HOLD", confidence_delta=0.02)
        assert _assess_direction(d) == "unchanged"


# ── Test save_json ──────────────────────────────────────────────────────


class TestSaveJson:
    def test_save_and_load(self):
        report = WatchlistReport(
            date_from="2026-03-14",
            date_to="2026-03-19",
            tickers=["601985.SS"],
        )
        tmp = tempfile.mkdtemp()
        path = report.save_json(output_dir=tmp)

        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["tickers"] == ["601985.SS"]
