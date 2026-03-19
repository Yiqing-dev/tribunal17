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

    # Price at signal time
    entry_price: float = 0.0       # Close on signal date

    # Trade plan targets
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # Pillar scores (0/1/2)
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
        """Append a single signal record."""
        if not record.recorded_at:
            record.recorded_at = datetime.now().isoformat()
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

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
        ticker = trace.ticker
        bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        if ticker == bare and bare.isdigit():
            if bare.startswith("6"):
                ticker = f"{bare}.SS"
            elif bare.startswith(("0", "3")):
                ticker = f"{bare}.SZ"
            elif bare.startswith(("8", "4", "9")):
                ticker = f"{bare}.BJ"
            else:
                ticker = f"{bare}.SZ"

        record = SignalRecord(
            run_id=run_id,
            trade_date=trace.trade_date,
            ticker=ticker,
            ticker_name=trace.ticker_name,
            action=trace.research_action,
            confidence=trace.final_confidence,
            was_vetoed=trace.was_vetoed,
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
        records = []
        for rid in run_ids:
            from .replay_store import ReplayStore
            store = ReplayStore(storage_dir=storage_dir)
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

        records = []
        seen_keys = set()  # (ticker, trade_date) for dedup

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Dedup: keep last record per ticker+date
                key = (d.get("ticker", ""), d.get("trade_date", ""))
                if key in seen_keys:
                    # Replace previous
                    records = [r for r in records if (r.ticker, r.trade_date) != key]
                seen_keys.add(key)

                rec = SignalRecord.from_dict(d)

                if ticker and rec.ticker != ticker:
                    continue
                if action and rec.action.upper() != action.upper():
                    continue
                if after and rec.trade_date < after:
                    continue
                if before and rec.trade_date > before:
                    continue

                records.append(rec)

        # Most recent first
        records.sort(key=lambda r: r.trade_date, reverse=True)

        if limit > 0:
            records = records[:limit]
        return records

    def count(self) -> int:
        """Total number of unique signals."""
        return len(self.read())

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
