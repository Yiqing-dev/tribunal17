"""Daily review refresh for the product workbench."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .report_index import (
    group_entries_by_ticker,
    latest_entries_per_ticker,
    previous_entry_for_run,
    sort_run_entries,
)
from .replay_service import ReplayService
from .replay_store import ReplayStore
from .review_triggers import ReviewTrigger, evaluate_review_triggers
from .trace_models import _now_cst


PriceProvider = Callable[[str], float]


@dataclass
class MonitorAlert:
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""
    current_price: float = 0.0
    triggers: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MonitorReport:
    generated_at: str = ""
    total_checked: int = 0
    alert_count: int = 0
    alerts: List[MonitorAlert] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_checked": self.total_checked,
            "alert_count": self.alert_count,
            "alerts": [a.to_dict() for a in self.alerts],
        }


def run_review_monitor_once(
    *,
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    limit: int = 120,
    price_by_ticker: Optional[Dict[str, float]] = None,
    price_provider: Optional[PriceProvider] = None,
) -> MonitorReport:
    """Evaluate latest reports against current trigger inputs and persist alerts."""
    store = ReplayStore(storage_dir=storage_dir)
    service = ReplayService(store=store)
    entries = sort_run_entries(store.list_runs(limit=0), newest_first=True)
    latest = latest_entries_per_ticker(entries, limit=limit)
    by_ticker = group_entries_by_ticker(entries)

    report = MonitorReport(generated_at=_now_cst().isoformat())
    as_of = _now_cst().strftime("%Y-%m-%d")
    for entry in latest:
        run_id = str(entry.get("run_id") or "")
        trace = service.load_run(run_id)
        if trace is None:
            continue
        report.total_checked += 1
        prev_entry = previous_entry_for_run(by_ticker.get(trace.ticker, []), run_id)
        prev_trace = service.load_run(prev_entry.get("run_id", "")) if prev_entry else None
        price = _resolve_price(trace.ticker, price_by_ticker=price_by_ticker, price_provider=price_provider)
        triggers = evaluate_review_triggers(
            trace,
            prev_trace,
            current_price=price,
            as_of_date=as_of,
        )
        material = [t for t in triggers if t.severity in ("critical", "high")]
        if material:
            report.alerts.append(MonitorAlert(
                run_id=trace.run_id,
                ticker=trace.ticker,
                ticker_name=trace.ticker_name,
                trade_date=trace.trade_date,
                current_price=price,
                triggers=[t.to_dict() for t in material],
            ))
    report.alert_count = len(report.alerts)
    save_monitor_report(report, output_dir=output_dir)
    return report


def save_monitor_report(report: MonitorReport, output_dir: str = "data/reports") -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "review_alerts.json"
    content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".review-alerts-")
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


def _resolve_price(
    ticker: str,
    *,
    price_by_ticker: Optional[Dict[str, float]],
    price_provider: Optional[PriceProvider],
) -> float:
    if price_by_ticker and ticker in price_by_ticker:
        try:
            return float(price_by_ticker[ticker])
        except (TypeError, ValueError):
            return 0.0
    if price_provider is not None:
        try:
            return float(price_provider(ticker) or 0)
        except Exception:
            return 0.0
    return 0.0
