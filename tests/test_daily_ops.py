"""Tests for daily operation safeguards: cache TTL, holiday dedup,
ledger index, report rotation, health check.
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.data_cache import DataCache
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.signal_ledger import SignalLedger, SignalRecord
from subagent_pipeline.renderers.report_renderer import rotate_reports
from subagent_pipeline.health_check import check_run_health, check_batch_health
from subagent_pipeline.trace_models import RunTrace, NodeTrace, NodeStatus


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. Cache TTL                                                       ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestCacheTTL:

    def test_evict_old_files(self, tmp_path):
        cache = DataCache(str(tmp_path), auto_evict=False)
        cache.put("api", "601985", "2026-03-01", {"old": True})
        # Backdate the file
        old_file = list(tmp_path.glob("*.json"))[0]
        old_time = time.time() - 10 * 86400  # 10 days ago
        os.utime(old_file, (old_time, old_time))

        removed = cache.evict_older_than(days=7)
        assert removed == 1
        assert not old_file.exists()

    def test_keep_recent_files(self, tmp_path):
        cache = DataCache(str(tmp_path), auto_evict=False)
        cache.put("api", "601985", "2026-04-04", {"recent": True})
        removed = cache.evict_older_than(days=7)
        assert removed == 0

    def test_auto_evict_on_init(self, tmp_path):
        # Create old file manually
        p = tmp_path / "old_cache.json"
        p.write_text('{"payload": null}')
        old_time = time.time() - 10 * 86400
        os.utime(p, (old_time, old_time))

        DataCache(str(tmp_path), auto_evict=True)
        assert not p.exists()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. Holiday Dedup                                                   ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestHolidayDedup:

    def _save_trace(self, store, ticker, trade_date, run_id=None):
        rt = RunTrace(ticker=ticker, trade_date=trade_date)
        if run_id:
            rt.run_id = run_id
        store.save(rt)
        return rt.run_id

    def test_has_run_for_true(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        self._save_trace(store, "601985.SS", "2026-04-03")
        assert store.has_run_for("601985.SS", "2026-04-03") is True

    def test_has_run_for_false(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        self._save_trace(store, "601985.SS", "2026-04-03")
        assert store.has_run_for("601985.SS", "2026-04-04") is False

    def test_different_ticker(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        self._save_trace(store, "601985.SS", "2026-04-03")
        assert store.has_run_for("000710.SZ", "2026-04-03") is False

    def test_list_runs_limit_zero(self, tmp_path):
        """limit=0 should return all runs."""
        store = ReplayStore(storage_dir=str(tmp_path))
        for i in range(5):
            self._save_trace(store, "601985.SS", f"2026-04-0{i+1}")
        runs = store.list_runs(ticker="601985.SS", limit=0)
        assert len(runs) == 5


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  3. Signal Ledger Index                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestLedgerIndex:

    def _rec(self, run_id, ticker="601985.SS", date="2026-04-04"):
        return SignalRecord(
            run_id=run_id, trade_date=date, ticker=ticker,
            action="BUY", confidence=0.8,
        )

    def test_index_built_lazily(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        assert ledger._run_id_index is None  # not built yet
        ledger.append(self._rec("run-001"))
        assert ledger._run_id_index is not None
        assert "run-001" in ledger._run_id_index

    def test_index_prevents_duplicate(self, tmp_path):
        ledger = SignalLedger(path=str(tmp_path / "signals.jsonl"))
        ledger.append(self._rec("run-001"))
        ledger.append(self._rec("run-001"))  # should be skipped
        with open(ledger.path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 1

    def test_index_survives_reinit(self, tmp_path):
        path = str(tmp_path / "signals.jsonl")
        ledger1 = SignalLedger(path=path)
        ledger1.append(self._rec("run-001"))

        # New instance — index rebuilt from file
        ledger2 = SignalLedger(path=path)
        assert ledger2._has_run_id("run-001")
        ledger2.append(self._rec("run-001"))  # should be skipped
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 1


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. Report Rotation                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestReportRotation:

    def test_removes_old_html(self, tmp_path):
        old = tmp_path / "old-report.html"
        old.write_text("<html>old</html>")
        os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))

        recent = tmp_path / "new-report.html"
        recent.write_text("<html>new</html>")

        removed = rotate_reports(str(tmp_path), keep_days=30)
        assert removed == 1
        assert not old.exists()
        assert recent.exists()

    def test_skips_non_report_files(self, tmp_path):
        txt = tmp_path / "notes.txt"
        txt.write_text("keep me")
        os.utime(txt, (time.time() - 100 * 86400, time.time() - 100 * 86400))

        removed = rotate_reports(str(tmp_path), keep_days=30)
        assert removed == 0
        assert txt.exists()

    def test_empty_dir(self, tmp_path):
        assert rotate_reports(str(tmp_path)) == 0


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  5. Health Check                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestHealthCheck:

    def _make_trace(self, store, ticker="601985.SS", date="2026-04-04",
                    action="BUY", confidence=0.75, n_nodes=14):
        rt = RunTrace(ticker=ticker, trade_date=date)
        for i in range(n_nodes):
            nt = NodeTrace(run_id=rt.run_id, node_name=f"Node{i}", seq=i)
            rt.node_traces.append(nt)
        rt.research_action = action
        rt.final_confidence = confidence
        rt.finalize()
        store.save(rt)
        return rt.run_id

    def test_healthy_run(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        rid = self._make_trace(store)
        issues = check_run_health(rid, str(tmp_path))
        assert issues == []

    def test_too_few_nodes(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        rid = self._make_trace(store, n_nodes=3)
        issues = check_run_health(rid, str(tmp_path))
        assert any("nodes" in i for i in issues)

    def test_no_action(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        rt = RunTrace(ticker="601985.SS", trade_date="2026-04-04")
        rt.finalize()
        store.save(rt)
        issues = check_run_health(rt.run_id, str(tmp_path))
        assert any("research_action" in i for i in issues)

    def test_missing_trace(self, tmp_path):
        issues = check_run_health("run-nonexistent", str(tmp_path))
        assert any("not found" in i for i in issues)

    def test_batch_all_same_action(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        rids = []
        for i in range(6):
            rid = self._make_trace(store, ticker=f"00{i:04d}.SZ",
                                   action="BUY", confidence=0.7 + i * 0.01)
            rids.append(rid)
        result = check_batch_health(rids, str(tmp_path),
                                    signal_path=str(tmp_path / "signals.jsonl"))
        assert any("same action" in w.lower() or "all" in w.lower()
                    for w in result["warnings"])

    def test_batch_confidence_clustering(self, tmp_path):
        store = ReplayStore(storage_dir=str(tmp_path))
        rids = []
        for i in range(5):
            rid = self._make_trace(store, ticker=f"00{i:04d}.SZ",
                                   action="BUY", confidence=0.75)
            rids.append(rid)
        result = check_batch_health(rids, str(tmp_path),
                                    signal_path=str(tmp_path / "signals.jsonl"))
        assert any("spread" in w.lower() for w in result["warnings"])
