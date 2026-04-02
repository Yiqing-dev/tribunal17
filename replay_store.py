"""
Replay Store — append-only persistence for RunTrace objects.

Storage format: one JSONL file per run, indexed by a manifest file.
Directory structure:
    data/replays/
        manifest.jsonl        ← one line per run (run_id, ticker, date, status)
        run-abc123def456.jsonl ← full RunTrace for that run
"""

import fcntl
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from .trace_models import RunTrace
from .signal_ledger import normalize_ticker

logger = logging.getLogger(__name__)

_DEFAULT_DIR = "data/replays"


class ReplayStore:
    """Persists and retrieves RunTrace objects."""

    def __init__(self, storage_dir: str = _DEFAULT_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.storage_dir / "manifest.jsonl"

    # ── Write ────────────────────────────────────────────────────────────

    def save(self, trace: RunTrace) -> Path:
        """Persist a finalized RunTrace. Returns the path written.

        Uses write-to-temp-then-rename for crash safety: if the process
        dies mid-write, the original file (if any) remains intact.
        """
        trace_path = self.storage_dir / f"{trace.run_id}.json"

        # Atomic write: temp file in same dir → os.replace (atomic on POSIX)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.storage_dir), suffix=".tmp", prefix=".trace-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(trace.to_dict(), f, ensure_ascii=False, indent=2)
            # os.replace can raise PermissionError on Windows when the
            # target file is momentarily locked by antivirus or indexer.
            # Retry up to 3 times with a brief delay.
            for attempt in range(3):
                try:
                    os.replace(tmp_path, str(trace_path))
                    break
                except PermissionError:
                    if attempt < 2:
                        logger.warning(
                            "PermissionError replacing %s, retrying (%d/3)",
                            trace_path, attempt + 1,
                        )
                        time.sleep(0.2 * (attempt + 1))
                    else:
                        raise
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Append to manifest (with advisory file lock for concurrency safety)
        manifest_entry = {
            "run_id": trace.run_id,
            "ticker": trace.ticker,
            "trade_date": trace.trade_date,
            "started_at": trace.started_at.isoformat() if trace.started_at else "",
            "total_nodes": trace.total_nodes,
            "error_count": trace.error_count,
            "research_action": trace.research_action,
            "was_vetoed": trace.was_vetoed,
            "veto_source": trace.veto_source,
            "compliance_status": trace.compliance_status,
        }
        line = json.dumps(manifest_entry, ensure_ascii=False) + "\n"
        with open(self._manifest_path, "a", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass  # platform without flock — proceed unprotected
            try:
                f.write(line)
            finally:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass

        logger.info(f"Saved replay trace: {trace_path}")
        return trace_path

    # ── Read ─────────────────────────────────────────────────────────────

    def load(self, run_id: str) -> Optional[RunTrace]:
        """Load a RunTrace by run_id. Returns None if not found."""
        trace_path = self.storage_dir / f"{run_id}.json"
        if not trace_path.exists():
            logger.warning(f"Replay trace not found: {trace_path}")
            return None

        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, FileNotFoundError, OSError) as e:
            logger.warning("Failed to load replay trace %s: %s", trace_path, e)
            return None
        return RunTrace.from_dict(data)

    def list_runs(self, ticker: str = None, limit: int = 50) -> List[dict]:
        """List recent runs from the manifest. Optionally filter by ticker."""
        if not self._manifest_path.exists():
            return []

        entries = []
        with open(self._manifest_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if ticker and normalize_ticker(entry.get("ticker", "")) != normalize_ticker(ticker):
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    logger.warning("Skipping corrupted manifest line: %s", line[:120])
                    continue

        # Return most recent first
        entries.reverse()
        return entries[:limit]

    def delete(self, run_id: str) -> bool:
        """Delete a trace file. Does NOT rewrite manifest (append-only)."""
        trace_path = self.storage_dir / f"{run_id}.json"
        if trace_path.exists():
            trace_path.unlink()
            return True
        return False

    def reconcile(self) -> int:
        """Find trace files missing from manifest and append entries.

        Repairs split-brain state where trace was written but manifest
        append failed (e.g., crash between the two operations in save()).
        """
        known_ids: set = set()
        if self._manifest_path.exists():
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        known_ids.add(json.loads(line).get("run_id", ""))
                    except json.JSONDecodeError:
                        pass

        repaired = 0
        skip_prefixes = ("market_context", "recap")
        for p in sorted(self.storage_dir.glob("*.json")):
            run_id = p.stem
            if run_id in known_ids or any(run_id.startswith(sp) for sp in skip_prefixes):
                continue
            try:
                trace = self.load(run_id)
                if trace is None:
                    continue
                entry = {
                    "run_id": trace.run_id,
                    "ticker": trace.ticker,
                    "trade_date": trace.trade_date,
                    "started_at": trace.started_at.isoformat() if trace.started_at else "",
                    "total_nodes": trace.total_nodes,
                    "error_count": trace.error_count,
                    "research_action": trace.research_action,
                    "was_vetoed": trace.was_vetoed,
                    "veto_source": trace.veto_source,
                    "compliance_status": trace.compliance_status,
                }
                line = json.dumps(entry, ensure_ascii=False) + "\n"
                with open(self._manifest_path, "a", encoding="utf-8") as f:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except OSError:
                        pass
                    try:
                        f.write(line)
                    finally:
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
                repaired += 1
                logger.info("Reconciled orphan trace: %s", run_id)
            except Exception as e:
                logger.warning("Failed to reconcile %s: %s", run_id, e)
        return repaired
