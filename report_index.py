"""Report index helpers for product workbench pages.

The replay manifest is append-only, so write order can diverge from report
chronology after backfills.  This module centralizes chronology sorting and
the static artifact index used by workbench-style pages.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .replay_service import ReplayService
from .trace_models import _now_cst

_UNSAFE_PATH_RE = re.compile(r"[^A-Za-z0-9._\-]")


def safe_filename(part: str) -> str:
    """Sanitize a string for report file names."""
    return _UNSAFE_PATH_RE.sub("_", str(part or ""))


def short_run_id(run_id: str) -> str:
    """Return the file-name run id fragment used by tier reports."""
    return str(run_id or "").replace("run-", "")[:12]


def run_sort_key(entry: Dict[str, Any]) -> tuple:
    """Chronological key for manifest entries.

    ISO dates/timestamps sort lexicographically, so missing values naturally
    fall behind real values.  ``run_id`` is the last tie-breaker for stable
    deterministic output.
    """
    return (
        str(entry.get("trade_date") or ""),
        str(entry.get("started_at") or ""),
        str(entry.get("run_id") or ""),
    )


def sort_run_entries(entries: Iterable[Dict[str, Any]], *, newest_first: bool = True) -> List[Dict[str, Any]]:
    """Return manifest entries sorted by report date, not append order."""
    return sorted((dict(e) for e in entries), key=run_sort_key, reverse=newest_first)


def group_entries_by_ticker(entries: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group already-sorted entries by ticker while preserving order."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        ticker = str(entry.get("ticker") or "")
        if ticker:
            grouped.setdefault(ticker, []).append(entry)
    return grouped


def previous_entry_for_run(entries_for_ticker: List[Dict[str, Any]], current_run_id: str) -> Optional[Dict[str, Any]]:
    """Find the previous chronological run for ``current_run_id``.

    ``entries_for_ticker`` must be newest-first.  The previous report is the
    next older item after the current run.
    """
    found_current = False
    for entry in entries_for_ticker:
        if entry.get("run_id") == current_run_id:
            found_current = True
            continue
        if found_current:
            return entry
    return None


def latest_entries_per_ticker(entries: List[Dict[str, Any]], *, limit: int = 120) -> List[Dict[str, Any]]:
    """Pick the newest entry for each ticker from a newest-first list."""
    selected: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        ticker = entry.get("ticker", "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        selected.append(entry)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def report_links_for_run(
    ticker: str,
    run_id: str,
    *,
    output_dir: Optional[str | Path] = None,
    include_missing: bool = True,
) -> Dict[str, str]:
    """Return existing tier links for a run.

    When ``output_dir`` is provided and ``include_missing`` is false, missing
    artifacts are omitted to avoid static 404 links in the workbench.
    """
    safe_t = safe_filename(ticker)
    short = short_run_id(run_id)
    candidates = {
        "snapshot": f"{safe_t}-run-{short}-snapshot.html",
        "research": f"{safe_t}-run-{short}-research.html",
        "audit": f"{safe_t}-run-{short}-audit.html",
    }
    if output_dir is None or include_missing:
        return candidates
    root = Path(output_dir)
    return {k: v for k, v in candidates.items() if (root / v).exists()}


def build_report_index(
    service: ReplayService,
    *,
    output_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Build a compact static index for generated reports."""
    entries = sort_run_entries(service.store.list_runs(limit=0), newest_first=True)
    by_ticker = group_entries_by_ticker(entries)
    previous_by_run_id: Dict[str, str] = {}
    for ticker_entries in by_ticker.values():
        for entry in ticker_entries:
            prev = previous_entry_for_run(ticker_entries, str(entry.get("run_id") or ""))
            if prev:
                previous_by_run_id[str(entry.get("run_id") or "")] = str(prev.get("run_id") or "")

    reports: List[Dict[str, Any]] = []
    for entry in entries:
        run_id = str(entry.get("run_id") or "")
        if not run_id:
            continue
        trace = service.load_run(run_id)
        ticker = str(entry.get("ticker") or getattr(trace, "ticker", "") or "")
        reports.append({
            "run_id": run_id,
            "ticker": ticker,
            "ticker_name": getattr(trace, "ticker_name", "") if trace else "",
            "trade_date": str(entry.get("trade_date") or getattr(trace, "trade_date", "") or ""),
            "started_at": str(entry.get("started_at") or ""),
            "action": (getattr(trace, "research_action", "") if trace else entry.get("research_action", "")) or "",
            "confidence": getattr(trace, "final_confidence", -1.0) if trace else -1.0,
            "was_vetoed": bool(getattr(trace, "was_vetoed", False)) if trace else bool(entry.get("was_vetoed", False)),
            "previous_run_id": previous_by_run_id.get(run_id, ""),
            "links": report_links_for_run(
                ticker,
                run_id,
                output_dir=output_dir,
                include_missing=output_dir is None,
            ),
        })

    latest_by_ticker = {
        ticker: rows[0].get("run_id", "")
        for ticker, rows in by_ticker.items()
        if rows
    }
    return {
        "schema_version": 1,
        "generated_at": _now_cst().isoformat(),
        "total_reports": len(entries),
        "total_tickers": len(latest_by_ticker),
        "latest_by_ticker": latest_by_ticker,
        "previous_by_run_id": previous_by_run_id,
        "reports": reports,
    }


def save_report_index(index: Dict[str, Any], output_dir: str | Path = "data/reports") -> Path:
    """Persist ``report_index.json`` with an atomic replace."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report_index.json"
    content = json.dumps(index, ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".report-index-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
