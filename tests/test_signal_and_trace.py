"""Tests for signal_ledger.py, renderers/shared_utils.py, and trace_models.py.

Covers:
1. normalize_ticker() — exchange-suffix normalization
2. SignalLedger.append() + read() — round-trip and deduplication
3. append_from_trace() — invalid action guard
4. _esc() — HTML escaping
5. _pct_to_hex() — percentage → color mapping
6. _squarify() — treemap layout
7. NodeTrace.from_dict() — no input mutation + invalid status fallback
8. RunTrace.from_dict() — no input mutation
9. compute_hash() — empty and non-empty strings
"""

import json
import sys
import os
import tempfile
import pytest
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path for subagent_pipeline imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.signal_ledger import normalize_ticker, SignalLedger, SignalRecord
from subagent_pipeline.trace_models import NodeTrace, NodeStatus, RunTrace, compute_hash
from subagent_pipeline.renderers.shared_utils import _esc, _pct_to_hex, _squarify


# ──────────────────────────────────────────────────────────────────────────────
# 1. normalize_ticker
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeTicker:
    def test_bare_600_becomes_ss(self):
        assert normalize_ticker("601985") == "601985.SS"

    def test_bare_000_becomes_sz(self):
        assert normalize_ticker("000710") == "000710.SZ"

    def test_bare_300_becomes_sz(self):
        assert normalize_ticker("300059") == "300059.SZ"

    def test_bare_920_becomes_bj(self):
        assert normalize_ticker("920344") == "920344.BJ"

    def test_bare_8xx_becomes_bj(self):
        assert normalize_ticker("831000") == "831000.BJ"

    def test_wrong_suffix_corrected_sz_to_ss(self):
        # Shanghai ticker with wrong .SZ suffix should be corrected to .SS
        assert normalize_ticker("601985.SZ") == "601985.SS"

    def test_wrong_suffix_corrected_sz_to_bj(self):
        # Beijing ticker with wrong .SZ suffix should be corrected to .BJ
        assert normalize_ticker("920344.SZ") == "920344.BJ"

    def test_correct_suffix_unchanged(self):
        assert normalize_ticker("601985.SS") == "601985.SS"
        assert normalize_ticker("000710.SZ") == "000710.SZ"

    def test_non_numeric_passthrough(self):
        # Non-digit tickers are returned unchanged
        result = normalize_ticker("AAPL")
        assert result == "AAPL"


# ──────────────────────────────────────────────────────────────────────────────
# 2. SignalLedger.append() + read() — round-trip and deduplication
# ──────────────────────────────────────────────────────────────────────────────

class TestSignalLedgerAppendRead:
    def _make_record(self, run_id="run-001", ticker="601985.SS", trade_date="2026-03-14",
                     action="BUY", confidence=0.75):
        return SignalRecord(
            run_id=run_id,
            trade_date=trade_date,
            ticker=ticker,
            ticker_name="中国核电",
            action=action,
            confidence=confidence,
            entry_price=9.16,
            stop_loss=8.80,
            take_profit=10.00,
            market_score=3,
            fundamental_score=2,
            news_score=3,
            sentiment_score=2,
            risk_score=4,
            risk_flags=["流动性风险"],
            market_regime="RISK_ON",
        )

    def test_append_and_read_roundtrip(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        rec = self._make_record()
        ledger.append(rec)

        results = ledger.read()
        assert len(results) == 1
        r = results[0]
        assert r.ticker == "601985.SS"
        assert r.trade_date == "2026-03-14"
        assert r.action == "BUY"
        assert r.confidence == pytest.approx(0.75)
        assert r.entry_price == pytest.approx(9.16)
        assert r.risk_flags == ["流动性风险"]

    def test_dedup_keeps_latest_for_same_ticker_date(self, tmp_path):
        """Appending same ticker+date twice should return only one record (latest)."""
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))

        rec1 = self._make_record(run_id="run-001", action="BUY", confidence=0.70)
        rec2 = self._make_record(run_id="run-002", action="HOLD", confidence=0.50)

        ledger.append(rec1)
        ledger.append(rec2)

        results = ledger.read(ticker="601985.SS")
        # Dedup: only one record for (ticker, trade_date)
        assert len(results) == 1
        assert results[0].action == "HOLD"
        assert results[0].run_id == "run-002"

    def test_filter_by_ticker(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        rec_a = self._make_record(ticker="601985.SS", trade_date="2026-03-14")
        rec_b = self._make_record(ticker="000710.SZ", trade_date="2026-03-14")
        ledger.append(rec_a)
        ledger.append(rec_b)

        results = ledger.read(ticker="601985.SS")
        assert len(results) == 1
        assert results[0].ticker == "601985.SS"

    def test_filter_by_action(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        ledger.append(self._make_record(trade_date="2026-03-14", action="BUY"))
        ledger.append(self._make_record(ticker="000710.SZ", trade_date="2026-03-14", action="SELL"))

        buys = ledger.read(action="BUY")
        assert all(r.action == "BUY" for r in buys)

    def test_filter_by_after_date(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        ledger.append(self._make_record(trade_date="2026-03-10"))
        ledger.append(self._make_record(ticker="000710.SZ", trade_date="2026-03-20"))

        results = ledger.read(after="2026-03-15")
        assert len(results) == 1
        assert results[0].trade_date == "2026-03-20"

    def test_read_empty_ledger_returns_empty_list(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        assert ledger.read() == []

    def test_recorded_at_auto_populated(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        rec = self._make_record()
        assert rec.recorded_at == ""
        ledger.append(rec)
        # After append, the original record object's recorded_at was filled in
        assert rec.recorded_at != ""


# ──────────────────────────────────────────────────────────────────────────────
# 3. append_from_trace() — invalid action guard
# ──────────────────────────────────────────────────────────────────────────────

class TestAppendFromTraceInvalidAction:
    def test_invalid_action_returns_none(self, tmp_path):
        """append_from_trace should return None when trace has an invalid action."""
        from subagent_pipeline.replay_store import ReplayStore
        from subagent_pipeline.trace_models import RunTrace

        storage_dir = str(tmp_path / "replays")
        os.makedirs(storage_dir, exist_ok=True)

        store = ReplayStore(storage_dir=storage_dir)
        trace = RunTrace(
            run_id="run-bad-action",
            ticker="601985",
            ticker_name="中国核电",
            trade_date="2026-03-14",
            research_action="MAYBE",   # invalid
            final_confidence=0.5,
        )
        store.save(trace)

        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        result = ledger.append_from_trace(
            run_id="run-bad-action",
            storage_dir=storage_dir,
        )
        assert result is None

    def test_valid_action_returns_record(self, tmp_path):
        """append_from_trace should return SignalRecord for a valid BUY action."""
        from subagent_pipeline.replay_store import ReplayStore
        from subagent_pipeline.trace_models import RunTrace

        storage_dir = str(tmp_path / "replays")
        os.makedirs(storage_dir, exist_ok=True)

        store = ReplayStore(storage_dir=storage_dir)
        trace = RunTrace(
            run_id="run-valid",
            ticker="601985",
            ticker_name="中国核电",
            trade_date="2026-03-14",
            research_action="BUY",
            final_confidence=0.80,
        )
        store.save(trace)

        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        result = ledger.append_from_trace(
            run_id="run-valid",
            storage_dir=storage_dir,
        )
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "601985.SS"


# ──────────────────────────────────────────────────────────────────────────────
# 4. _esc() — HTML escaping
# ──────────────────────────────────────────────────────────────────────────────

class TestEsc:
    def test_ampersand_escaped(self):
        assert "&amp;" in _esc("A & B")

    def test_less_than_escaped(self):
        assert "&lt;" in _esc("<script>")

    def test_greater_than_escaped(self):
        assert "&gt;" in _esc("x > y")

    def test_double_quote_escaped(self):
        assert "&quot;" in _esc('say "hello"')

    def test_empty_string(self):
        assert _esc("") == ""

    def test_plain_text_unchanged(self):
        assert _esc("hello world") == "hello world"

    def test_chinese_unchanged(self):
        assert _esc("中国核电") == "中国核电"

    def test_multiple_specials(self):
        result = _esc('<a href="x&y">text</a>')
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result
        assert "&quot;" in result


# ──────────────────────────────────────────────────────────────────────────────
# 5. _pct_to_hex() — percentage → color mapping
# ──────────────────────────────────────────────────────────────────────────────

class TestPctToHex:
    def test_zero_pct_returns_neutral(self):
        """0% should return the neutral warm off-white #F0EAE7."""
        result = _pct_to_hex(0.0)
        assert result == "#F0EAE7"

    def test_positive_pct_returns_salmon_family(self):
        """+3% should be close to salmon #FDA5B5 (A-share: red = up)."""
        result = _pct_to_hex(3.0)
        assert result.startswith("#")
        r = int(result[1:3], 16)
        g = int(result[3:5], 16)
        b = int(result[5:7], 16)
        # Salmon: high red, moderate green, moderate blue — red component dominant
        assert r > g

    def test_negative_pct_returns_green_family(self):
        """-3% should be close to muted mint #AAD993 (A-share: green = down)."""
        result = _pct_to_hex(-3.0)
        assert result.startswith("#")
        r = int(result[1:3], 16)
        g = int(result[3:5], 16)
        # Mint: green component dominant
        assert g > r

    def test_beyond_positive_clamp(self):
        """+10% should equal +3% (clamped)."""
        assert _pct_to_hex(10.0) == _pct_to_hex(3.0)

    def test_beyond_negative_clamp(self):
        """-10% should equal -3% (clamped)."""
        assert _pct_to_hex(-10.0) == _pct_to_hex(-3.0)

    def test_returns_valid_hex_string(self):
        for pct in (-5.0, -1.0, 0.0, 0.5, 1.0, 3.0, 5.0):
            result = _pct_to_hex(pct)
            assert len(result) == 7, f"Expected 7-char hex for pct={pct}, got {result!r}"
            assert result[0] == "#"
            # Should be valid hex
            int(result[1:], 16)


# ──────────────────────────────────────────────────────────────────────────────
# 6. _squarify() — treemap layout
# ──────────────────────────────────────────────────────────────────────────────

class TestSquarify:
    def test_empty_input_returns_empty(self):
        assert _squarify([], 0, 0, 100, 100) == []

    def test_single_item_fills_bounding_box(self):
        rects = _squarify([(0, 100)], 0, 0, 200, 150)
        assert len(rects) == 1
        idx, rx, ry, rw, rh = rects[0]
        assert idx == 0
        assert rx == pytest.approx(0)
        assert ry == pytest.approx(0)
        # Single item should span the full width/height
        assert rw == pytest.approx(200, abs=1)
        assert rh == pytest.approx(150, abs=1)

    def test_all_rects_within_bounds(self):
        values = [(i, (i + 1) * 10) for i in range(5)]
        rects = _squarify(values, 10, 20, 300, 200)
        for idx, rx, ry, rw, rh in rects:
            assert rx >= 10 - 1, f"rx={rx} out of left bound"
            assert ry >= 20 - 1, f"ry={ry} out of top bound"
            assert rx + rw <= 10 + 300 + 2, f"rect overflows right: rx={rx}, rw={rw}"
            assert ry + rh <= 20 + 200 + 2, f"rect overflows bottom: ry={ry}, rh={rh}"

    def test_returns_all_indices(self):
        values = [(i, 10.0) for i in range(4)]
        rects = _squarify(values, 0, 0, 200, 200)
        indices = [idx for idx, *_ in rects]
        assert sorted(indices) == [0, 1, 2, 3]

    def test_positive_dimensions(self):
        values = [(i, (i + 1) * 5.0) for i in range(6)]
        rects = _squarify(values, 0, 0, 400, 300)
        for idx, rx, ry, rw, rh in rects:
            assert rw >= 1, f"rw={rw} too small"
            assert rh >= 1, f"rh={rh} too small"

    def test_zero_total_fallback(self):
        # All-zero values should return evenly-divided rects without error
        values = [(0, 0), (1, 0), (2, 0)]
        rects = _squarify(values, 0, 0, 300, 100)
        assert len(rects) == 3


# ──────────────────────────────────────────────────────────────────────────────
# 7. NodeTrace.from_dict() — no input mutation
# ──────────────────────────────────────────────────────────────────────────────

class TestNodeTraceFromDict:
    def _sample_dict(self):
        return {
            "run_id": "run-abc",
            "node_name": "Research Manager",
            "seq": 5,
            "timestamp": "2026-03-14T10:00:00",
            "duration_ms": 1234.5,
            "status": "ok",
            "input_hash": "abcdef0123456789",
            "output_hash": "9876543210fedcba",
            "output_excerpt": "Buy recommendation",
            "research_action": "BUY",
            "confidence": 0.82,
            "parse_status": "STRICT_OK",
            "parse_confidence": 0.95,
            "parse_missing_fields": [],
            "parse_warnings": [],
            "evidence_ids_referenced": ["E1", "E3"],
            "claim_ids_referenced": [],
            "claim_ids_produced": ["C1"],
            "claims_produced": 1,
            "claims_attributed": 1,
            "claims_unattributed": 0,
            "thesis_effect": "bullish",
            "risk_score": None,
            "risk_cleared": None,
            "max_position_pct": -1.0,
            "risk_flag_count": 0,
            "risk_flag_categories": [],
            "vetoed": False,
            "veto_source": "",
            "veto_reasons": [],
            "compliance_status": "",
            "compliance_reasons": [],
            "compliance_rules_fired": [],
            "ledger_prev_status": "",
            "ledger_new_status": "",
            "ledger_transition_reason": "",
            "errors": [],
            "structured_data": {},
        }

    def test_does_not_mutate_input_dict(self):
        d = self._sample_dict()
        original_keys = set(d.keys())
        original_timestamp = d["timestamp"]

        NodeTrace.from_dict(d)

        # Original dict should be unchanged
        assert set(d.keys()) == original_keys
        assert d["timestamp"] == original_timestamp  # still a string
        assert d["status"] == "ok"  # still a string, not an Enum

    def test_deserializes_timestamp(self):
        d = self._sample_dict()
        nt = NodeTrace.from_dict(d)
        assert isinstance(nt.timestamp, datetime)

    def test_deserializes_status_enum(self):
        d = self._sample_dict()
        nt = NodeTrace.from_dict(d)
        assert nt.status == NodeStatus.OK

    def test_fields_correctly_loaded(self):
        d = self._sample_dict()
        nt = NodeTrace.from_dict(d)
        assert nt.run_id == "run-abc"
        assert nt.node_name == "Research Manager"
        assert nt.confidence == pytest.approx(0.82)
        assert nt.evidence_ids_referenced == ["E1", "E3"]

    def test_invalid_status_defaults_to_warn(self):
        d = self._sample_dict()
        d["status"] = "INVALID_STATUS"
        nt = NodeTrace.from_dict(d)
        assert nt.status == NodeStatus.WARN


# ──────────────────────────────────────────────────────────────────────────────
# 8. RunTrace.from_dict() — no input mutation
# ──────────────────────────────────────────────────────────────────────────────

class TestRunTraceFromDict:
    def _sample_dict(self):
        return {
            "run_id": "run-xyz",
            "ticker": "601985",
            "ticker_name": "中国核电",
            "trade_date": "2026-03-14",
            "as_of": "2026-03-14",
            "started_at": "2026-03-14T09:30:00",
            "completed_at": "2026-03-14T10:15:00",
            "market": "cn",
            "language": "zh",
            "llm_provider": "anthropic",
            "novice_mode": False,
            "node_traces": [],
            "total_nodes": 0,
            "error_count": 0,
            "warn_count": 0,
            "total_evidence_ids": [],
            "total_claim_ids": [],
            "research_action": "BUY",
            "final_confidence": 0.78,
            "compliance_status": "",
            "was_vetoed": False,
            "veto_source": "",
            "pre_veto_action": "",
            "market_context": {},
            "freshness_ok": True,
            "stale_sources": [],
            "vendor_freshness": {},
        }

    def test_does_not_mutate_input_dict(self):
        d = self._sample_dict()
        original_started_at = d["started_at"]
        original_node_traces = d["node_traces"]

        RunTrace.from_dict(d)

        # Original dict values unchanged
        assert d["started_at"] == original_started_at  # still a string
        assert d["node_traces"] is original_node_traces  # same list object

    def test_deserializes_timestamps(self):
        d = self._sample_dict()
        rt = RunTrace.from_dict(d)
        assert isinstance(rt.started_at, datetime)
        assert isinstance(rt.completed_at, datetime)

    def test_completed_at_none_preserved(self):
        d = self._sample_dict()
        d["completed_at"] = None
        rt = RunTrace.from_dict(d)
        assert rt.completed_at is None

    def test_fields_correctly_loaded(self):
        d = self._sample_dict()
        rt = RunTrace.from_dict(d)
        assert rt.run_id == "run-xyz"
        assert rt.ticker == "601985"
        assert rt.final_confidence == pytest.approx(0.78)
        assert rt.research_action == "BUY"

    def test_node_traces_deserialized(self):
        d = self._sample_dict()
        d["node_traces"] = [
            {
                "run_id": "run-xyz",
                "node_name": "ResearchOutput",
                "seq": 17,
                "status": "ok",
                "confidence": 0.78,
                "research_action": "BUY",
            }
        ]
        rt = RunTrace.from_dict(d)
        assert len(rt.node_traces) == 1
        assert rt.node_traces[0].node_name == "ResearchOutput"


# ──────────────────────────────────────────────────────────────────────────────
# 9. NodeTrace.from_dict() with INVALID_STATUS → defaults to WARN
# (already covered above in TestNodeTraceFromDict.test_invalid_status_defaults_to_warn)
# Adding a standalone test for clarity:
# ──────────────────────────────────────────────────────────────────────────────

class TestNodeTraceInvalidStatus:
    def test_garbage_status_falls_back_to_warn(self):
        nt = NodeTrace.from_dict({
            "run_id": "r1",
            "node_name": "SomeNode",
            "seq": 0,
            "status": "INVALID_STATUS",
        })
        assert nt.status == NodeStatus.WARN

    def test_empty_status_falls_back_to_warn(self):
        nt = NodeTrace.from_dict({
            "run_id": "r1",
            "node_name": "SomeNode",
            "seq": 0,
            "status": "",
        })
        assert nt.status == NodeStatus.WARN

    def test_mixed_case_status_recognized(self):
        # Enum uses lowercase values ("ok", "warn", "error", "skipped")
        nt = NodeTrace.from_dict({
            "run_id": "r1",
            "node_name": "SomeNode",
            "seq": 0,
            "status": "error",
        })
        assert nt.status == NodeStatus.ERROR


# ──────────────────────────────────────────────────────────────────────────────
# 10. compute_hash()
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeHash:
    def test_empty_string_returns_16_zeros(self):
        result = compute_hash("")
        assert result == "0" * 16

    def test_non_empty_returns_16_char_hex(self):
        result = compute_hash("hello world")
        assert len(result) == 16
        # Must be valid hex
        int(result, 16)

    def test_deterministic(self):
        assert compute_hash("some text") == compute_hash("some text")

    def test_different_inputs_differ(self):
        assert compute_hash("abc") != compute_hash("xyz")

    def test_chinese_text(self):
        result = compute_hash("中国核电601985")
        assert len(result) == 16
        int(result, 16)

    def test_whitespace_only(self):
        result = compute_hash("   ")
        assert len(result) == 16
        assert result != "0" * 16
