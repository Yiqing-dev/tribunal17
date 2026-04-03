"""Signal Ledger — lightweight append-only log for daily signal accumulation.

Each pipeline run appends one record per ticker. The ledger is a JSONL file
(one JSON object per line), optimized for fast append and sequential read.

Usage:
    from subagent_pipeline.signal_ledger import SignalLedger

    ledger = SignalLedger()                       # default: data/signals/signals.jsonl
    ledger.append(run_id, ticker, ...)            # after pipeline completes
    ledger.append_from_trace(run_id, store)       # auto-extract from RunTrace

    signals = ledger.read()                       # all signals
    signals = ledger.read(ticker="601985.SS")     # filter by ticker
    signals = ledger.read(after="2026-03-01")     # filter by date

    ledger.summary()                              # print stats
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "data/signals/signals.jsonl"


def normalize_ticker(ticker: str) -> str:
    """Ensure ticker has the correct exchange suffix.

    Canonical source for ticker normalization across the codebase.
    Rules: 6xx→.SS (Shanghai), 0xx/3xx→.SZ (Shenzhen), 8xx/4xx/9xx→.BJ (Beijing).
    Always strips and re-applies the suffix to fix wrong ones (e.g., 920344.SZ → 920344.BJ).
    """
    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if not bare.isdigit():
        return ticker
    if bare.startswith("6"):
        correct = f"{bare}.SS"
    elif bare.startswith(("0", "3")):
        correct = f"{bare}.SZ"
    elif bare.startswith(("8", "4", "9")):
        correct = f"{bare}.BJ"
    else:
        correct = f"{bare}.SZ"
    return correct


def _flock_exclusive(f) -> None:
    """Acquire POSIX exclusive advisory lock (non-blocking falls back to blocking)."""
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    except OSError:
        pass  # platform without flock — proceed unprotected


def _flock_release(f) -> None:
    """Release POSIX advisory lock."""
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@dataclass
class SignalRecord:
    """One signal entry in the ledger."""
    # Identity
    run_id: str = ""
    trade_date: str = ""            # Signal date (YYYY-MM-DD)
    ticker: str = ""                # e.g. "601985.SS"
    ticker_name: str = ""           # e.g. "中国核电"

    # Decision
    action: str = ""                # BUY / HOLD / SELL / VETO
    confidence: float = -1.0
    was_vetoed: bool = False
    veto_source: str = ""           # "agent_veto" | "risk_gate" | ""
    pre_veto_action: str = ""       # Original action before risk gate forced VETO

    # Price at signal time
    entry_price: float = 0.0       # Close on signal date

    # Trade plan targets
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # Pillar scores (0-4)
    market_score: int = -1
    fundamental_score: int = -1
    news_score: int = -1
    sentiment_score: int = -1

    # Risk
    risk_score: int = -1
    risk_flags: List[str] = field(default_factory=list)

    # Context
    market_regime: str = ""         # RISK_ON / NEUTRAL / RISK_OFF
    position_cap_multiplier: float = 1.0

    # Metadata
    recorded_at: str = ""           # ISO timestamp when appended

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "SignalRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SignalLedger:
    """Append-only signal log backed by a JSONL file."""

    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Write ─────────────────────────────────────────────────────────────

    def append(self, record: SignalRecord) -> None:
        """Append a single signal record.

        Uses atomic write-to-temp-then-append with file locking to
        prevent concurrent writers from interleaving or losing lines.
        """
        if not record.recorded_at:
            record.recorded_at = datetime.now().isoformat()
        line = json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False) + "\n"

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), suffix=".tmp", prefix=".signal-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                tmp_f.write(line)

            # Append under exclusive lock
            with open(self.path, "a", encoding="utf-8") as f:
                _flock_exclusive(f)
                try:
                    with open(tmp_path, "r", encoding="utf-8") as tmp_f:
                        f.write(tmp_f.read())
                finally:
                    _flock_release(f)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def append_from_trace(
        self,
        run_id: str,
        storage_dir: str = "data/replays",
        entry_price: float = 0.0,
        market_regime: str = "",
        position_cap_multiplier: float = 1.0,
    ) -> Optional[SignalRecord]:
        """Extract signal from a RunTrace and append to ledger.

        Returns the SignalRecord or None if trace not found.
        """
        from .replay_store import ReplayStore

        store = ReplayStore(storage_dir=storage_dir)
        trace = store.load(run_id)
        if trace is None:
            logger.warning(f"Trace not found: {run_id}")
            return None

        # Validate action (consistent with backfill_ledger whitelist)
        _action = (trace.research_action or "").upper().strip()
        if _action not in ("BUY", "HOLD", "SELL", "VETO"):
            logger.warning("Skipping trace %s: invalid action '%s'", run_id, trace.research_action)
            return None

        # Extract trade plan prices and pillar scores
        sl, tp = 0.0, 0.0
        pillars = {}
        risk_score = -1
        risk_flags = []

        for nt in trace.node_traces:
            sd = nt.structured_data or {}

            # ResearchOutput: tradecard + trade_plan
            if nt.node_name == "ResearchOutput":
                tc = sd.get("tradecard", {})
                if tc:
                    p = tc.get("pillars", {})
                    pillars = {
                        "market_score": p.get("market_score", -1),
                        "fundamental_score": p.get("fundamental_score", -1),
                        # TRADECARD spec uses "macro_score"; ledger field is
                        # "news_score".  Accept either key, preferring news_score
                        # if present to avoid silent field mismatch.
                        "news_score": p.get("news_score", p.get("macro_score", -1)),
                        "sentiment_score": p.get("sentiment_score", -1),
                    }
                    risk_score = tc.get("risk_score", -1)

                tplan = sd.get("trade_plan", {})
                if tplan:
                    sl_obj = tplan.get("stop_loss", {})
                    if isinstance(sl_obj, dict):
                        sl = float(sl_obj.get("price", 0) or 0)
                    elif isinstance(sl_obj, (int, float)):
                        sl = float(sl_obj)
                    tp_list = tplan.get("take_profit", [])
                    if tp_list and isinstance(tp_list, list):
                        first = tp_list[0]
                        if isinstance(first, dict):
                            zone = first.get("price_zone", [])
                            if zone and len(zone) >= 2:
                                tp = (float(zone[0]) + float(zone[1])) / 2
                            elif zone:
                                tp = float(zone[0])

            # Risk Judge: flags
            if nt.node_name == "Risk Judge":
                flags = sd.get("risk_flags", [])
                if isinstance(flags, list):
                    for f in flags:
                        if isinstance(f, dict):
                            risk_flags.append(f.get("category", str(f)))
                        elif isinstance(f, str):
                            risk_flags.append(f)

        # Normalize ticker
        ticker = normalize_ticker(trace.ticker)

        record = SignalRecord(
            run_id=run_id,
            trade_date=trace.trade_date,
            ticker=ticker,
            ticker_name=trace.ticker_name,
            action=trace.research_action,
            confidence=trace.final_confidence,
            was_vetoed=trace.was_vetoed,
            veto_source=getattr(trace, "veto_source", ""),
            pre_veto_action=getattr(trace, "pre_veto_action", ""),
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            market_score=pillars.get("market_score", -1),
            fundamental_score=pillars.get("fundamental_score", -1),
            news_score=pillars.get("news_score", -1),
            sentiment_score=pillars.get("sentiment_score", -1),
            risk_score=risk_score if isinstance(risk_score, int) else -1,
            risk_flags=risk_flags,
            market_regime=market_regime,
            position_cap_multiplier=position_cap_multiplier,
        )
        self.append(record)
        logger.info(f"Appended signal: {ticker} {trace.trade_date} {trace.research_action}")
        return record

    def append_batch_from_traces(
        self,
        run_ids: List[str],
        storage_dir: str = "data/replays",
        market_regime: str = "",
        position_cap_multiplier: float = 1.0,
        spot_data: Optional[Dict] = None,
    ) -> List[SignalRecord]:
        """Append signals for multiple run_ids. Auto-fills entry_price from spot_data."""
        spot_data = spot_data or {}
        from .replay_store import ReplayStore
        store = ReplayStore(storage_dir=storage_dir)
        records = []
        for rid in run_ids:
            trace = store.load(rid)
            if trace is None:
                continue
            bare = trace.ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
            spot = spot_data.get(bare, {})
            price = float(spot.get("price", 0) or 0)

            rec = self.append_from_trace(
                run_id=rid,
                storage_dir=storage_dir,
                entry_price=price,
                market_regime=market_regime,
                position_cap_multiplier=position_cap_multiplier,
            )
            if rec:
                records.append(rec)
        return records

    # ── Read ──────────────────────────────────────────────────────────────

    def read(
        self,
        ticker: str = None,
        action: str = None,
        after: str = None,
        before: str = None,
        limit: int = 0,
    ) -> List[SignalRecord]:
        """Read signals with optional filters.

        Args:
            ticker: Filter by ticker (e.g. "601985.SS")
            action: Filter by action (e.g. "BUY")
            after: Only signals on or after this date (YYYY-MM-DD)
            before: Only signals on or before this date (YYYY-MM-DD)
            limit: Max records to return (0 = unlimited)
        """
        if not self.path.exists():
            return []

        dedup: dict = {}  # (ticker, trade_date) → SignalRecord

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                try:
                    rec = SignalRecord.from_dict(d)
                except (TypeError, ValueError):
                    logger.warning("Skipping malformed signal record: %s", d)
                    continue

                if ticker and normalize_ticker(rec.ticker) != normalize_ticker(ticker):
                    continue
                if action and rec.action.upper() != action.upper():
                    continue
                if after and rec.trade_date < after:
                    continue
                if before and rec.trade_date > before:
                    continue

                # Dedup: keep last record per ticker+date (O(1) dict replace)
                dedup[(rec.ticker, rec.trade_date)] = rec

        records = list(dedup.values())
        # Most recent first
        records.sort(key=lambda r: r.trade_date, reverse=True)

        if limit > 0:
            records = records[:limit]
        return records

    def count(self) -> int:
        """Total number of unique signals.

        Uses a fast line-counting approach instead of fully parsing every record.
        Falls back to full read() for dedup accuracy when the file exists.
        """
        if not self.path.exists():
            return 0
        n = 0
        seen: set = set()
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (d.get("ticker", ""), d.get("trade_date", ""))
                seen.add(key)
        return len(seen)

    # ── Summary ───────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        """Compute summary statistics from the ledger."""
        records = self.read()
        if not records:
            return {"total": 0}

        from collections import Counter
        actions = Counter(r.action.upper() for r in records)
        tickers = Counter(r.ticker for r in records)
        dates = sorted(set(r.trade_date for r in records))

        return {
            "total": len(records),
            "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else "",
            "unique_dates": len(dates),
            "unique_tickers": len(tickers),
            "actions": dict(actions),
            "tickers": dict(tickers),
        }

    def print_summary(self) -> None:
        """Print human-readable summary."""
        s = self.summary()
        if s["total"] == 0:
            print("Signal ledger is empty.")
            return
        print(f"信号总数: {s['total']}")
        print(f"日期范围: {s['date_range']} ({s['unique_dates']} 交易日)")
        print(f"股票数量: {s['unique_tickers']}")
        print(f"信号分布: {s['actions']}")

    # ── Export ────────────────────────────────────────────────────────────

    def to_markdown(self, limit: int = 50) -> str:
        """Export ledger as markdown table."""
        records = self.read(limit=limit)
        if not records:
            return "_(无信号记录)_"

        from .renderers.decision_labels import get_signal_emoji, get_action_label

        lines = [
            "| 日期 | 股票 | 信号 | 置信度 | 入场价 | 止损 | 止盈 |",
            "|------|------|------|--------|--------|------|------|",
        ]
        for r in records:
            emoji = get_signal_emoji(r.action)
            label = get_action_label(r.action)
            conf = f"{r.confidence:.0%}" if r.confidence >= 0 else "—"
            price = f"{r.entry_price:.2f}" if r.entry_price > 0 else "—"
            sl = f"{r.stop_loss:.2f}" if r.stop_loss > 0 else "—"
            tp = f"{r.take_profit:.2f}" if r.take_profit > 0 else "—"
            lines.append(
                f"| {r.trade_date} | {r.ticker_name or r.ticker} "
                f"| {emoji} {label} | {conf} | {price} | {sl} | {tp} |"
            )
        return "\n".join(lines)


# ── Convenience: backfill from existing replays ──────────────────────────

def backfill_ledger(
    storage_dir: str = "data/replays",
    ledger_path: str = _DEFAULT_PATH,
) -> int:
    """Scan all existing RunTrace files and backfill the signal ledger.

    Useful for initializing the ledger from historical data.
    Returns number of signals appended.
    """
    from .replay_store import ReplayStore

    store = ReplayStore(storage_dir=storage_dir)
    runs = store.list_runs(limit=1000)
    ledger = SignalLedger(path=ledger_path)

    count = 0
    for entry in runs:
        run_id = entry.get("run_id", "")
        action = entry.get("research_action", "")
        if not action or action.upper() not in ("BUY", "HOLD", "SELL", "VETO"):
            continue

        rec = ledger.append_from_trace(run_id=run_id, storage_dir=storage_dir)
        if rec:
            count += 1

    logger.info(f"Backfilled {count} signals into {ledger_path}")
    return count


# ── Ledger repair utility ─────────────────────────────────────────────────


def repair_ledger(
    ledger_path: str = _DEFAULT_PATH,
    replay_dir: str = "data/replays",
    dry_run: bool = True,
) -> Dict:
    """Repair known data quality issues in the signal ledger.

    Fixes:
      - Date repair: trade_date starting with "2025-" → look up correct date from replay
      - Name repair: empty ticker_name → backfill from replay or static mapping
      - Suffix repair: re-normalize ticker suffix (e.g., 920344.SZ → 920344.BJ)

    Args:
        dry_run: If True, return a report dict without modifying the file.
                 If False, atomically rewrite the ledger.

    Returns:
        Dict with counts of each repair type and list of affected run_ids.
    """
    from .replay_store import ReplayStore

    store = ReplayStore(storage_dir=replay_dir)
    report: Dict = {
        "date_fixes": 0,
        "name_fixes": 0,
        "suffix_fixes": 0,
        "total_records": 0,
        "affected_run_ids": [],
    }

    if not os.path.exists(ledger_path):
        return report

    with open(ledger_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    repaired_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            repaired_lines.append(line)
            continue

        report["total_records"] += 1
        changed = False
        run_id = d.get("run_id", "")

        # 1. Date repair: "2025-" dates are likely off-by-one-year
        trade_date = d.get("trade_date", "")
        if trade_date.startswith("2025-"):
            try:
                trace = store.load(run_id)
                if trace and trace.trade_date and not trace.trade_date.startswith("2025-"):
                    d["trade_date"] = trace.trade_date
                    changed = True
                    report["date_fixes"] += 1
            except Exception:
                pass

        # 2. Name repair: empty ticker_name
        if not d.get("ticker_name"):
            try:
                trace = store.load(run_id)
                if trace and getattr(trace, "ticker_name", ""):
                    d["ticker_name"] = trace.ticker_name
                    changed = True
                    report["name_fixes"] += 1
            except Exception:
                pass

        # 3. Suffix repair: re-normalize ticker
        ticker = d.get("ticker", "")
        if ticker:
            fixed = normalize_ticker(ticker)
            if fixed != ticker:
                d["ticker"] = fixed
                changed = True
                report["suffix_fixes"] += 1

        if changed:
            report["affected_run_ids"].append(run_id)

        repaired_lines.append(json.dumps(d, ensure_ascii=False))

    if not dry_run:
        # Atomic write: temp file → rename (with file lock)
        dir_name = os.path.dirname(ledger_path) or "."
        fd, tmp_path = tempfile.mkstemp(suffix=".jsonl", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                _flock_exclusive(tmp_f)
                try:
                    for rl in repaired_lines:
                        tmp_f.write(rl + "\n")
                finally:
                    _flock_release(tmp_f)
            os.replace(tmp_path, ledger_path)
            logger.info(f"Repaired ledger: {report}")
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    return report
