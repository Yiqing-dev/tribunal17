"""Confidence and direction calibration for stock research signals.

This module consumes existing backtest outputs or runs against SignalLedger.
It does not change signal generation by itself; bridge/report code can load
the resulting summaries and surface them as prompt feedback or audit context.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .signal_ledger import normalize_ticker


@dataclass
class CalibrationCell:
    """Accuracy stats for one calibration slice."""

    key: str = ""
    n: int = 0
    decided_n: int = 0
    correct_n: int = 0
    accuracy: float = 0.0
    avg_confidence: float = 0.0
    calibration_gap: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationReport:
    """Aggregated calibration report."""

    computed_at: str = ""
    eval_window_days: int = 10
    total_results: int = 0
    completed_results: int = 0
    overall: CalibrationCell = field(default_factory=lambda: CalibrationCell(key="overall"))
    by_action: Dict[str, CalibrationCell] = field(default_factory=dict)
    by_confidence_bucket: Dict[str, CalibrationCell] = field(default_factory=dict)
    by_ticker: Dict[str, CalibrationCell] = field(default_factory=dict)
    by_regime: Dict[str, CalibrationCell] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "computed_at": self.computed_at,
            "eval_window_days": self.eval_window_days,
            "total_results": self.total_results,
            "completed_results": self.completed_results,
            "overall": self.overall.to_dict(),
            "by_action": {k: v.to_dict() for k, v in self.by_action.items()},
            "by_confidence_bucket": {k: v.to_dict() for k, v in self.by_confidence_bucket.items()},
            "by_ticker": {k: v.to_dict() for k, v in self.by_ticker.items()},
            "by_regime": {k: v.to_dict() for k, v in self.by_regime.items()},
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CalibrationReport":
        def _cell(obj: Dict[str, Any], key: str = "") -> CalibrationCell:
            data = dict(obj or {})
            data.setdefault("key", key)
            return CalibrationCell(**{k: v for k, v in data.items() if k in CalibrationCell.__dataclass_fields__})

        return cls(
            computed_at=d.get("computed_at", ""),
            eval_window_days=int(d.get("eval_window_days", 10) or 10),
            total_results=int(d.get("total_results", 0) or 0),
            completed_results=int(d.get("completed_results", 0) or 0),
            overall=_cell(d.get("overall", {}), "overall"),
            by_action={k: _cell(v, k) for k, v in (d.get("by_action") or {}).items()},
            by_confidence_bucket={
                k: _cell(v, k) for k, v in (d.get("by_confidence_bucket") or {}).items()
            },
            by_ticker={k: _cell(v, k) for k, v in (d.get("by_ticker") or {}).items()},
            by_regime={k: _cell(v, k) for k, v in (d.get("by_regime") or {}).items()},
            notes=list(d.get("notes") or []),
        )


def confidence_bucket(confidence: float) -> str:
    """Bucket confidence on the same thresholds used in prompts/UI."""
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if c < 0:
        return "unknown"
    if c >= 0.70:
        return "high"
    if c >= 0.55:
        return "medium"
    return "low"


def _cell_from_results(key: str, rows: List[Any]) -> CalibrationCell:
    decided = [
        r for r in rows
        if getattr(r, "direction_expected", "") in ("up", "down")
        and getattr(r, "direction_correct", None) is not None
    ]
    confs = [
        float(getattr(r, "confidence", -1))
        for r in decided
        if isinstance(getattr(r, "confidence", -1), (int, float))
        and getattr(r, "confidence", -1) >= 0
    ]
    correct_n = sum(1 for r in decided if bool(getattr(r, "direction_correct", False)))
    decided_n = len(decided)
    accuracy = correct_n / decided_n if decided_n else 0.0
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    return CalibrationCell(
        key=key,
        n=len(rows),
        decided_n=decided_n,
        correct_n=correct_n,
        accuracy=round(accuracy, 4),
        avg_confidence=round(avg_conf, 4),
        calibration_gap=round(avg_conf - accuracy, 4) if decided_n else 0.0,
    )


def build_calibration_report(
    backtest_report,
    *,
    ledger_records: Optional[List[Any]] = None,
) -> CalibrationReport:
    """Build calibration slices from a BacktestReport-like object."""
    results = list(getattr(backtest_report, "results", []) or [])
    completed = [r for r in results if getattr(r, "eval_status", "") == "completed"]
    cfg = getattr(backtest_report, "config", None)
    eval_window = int(getattr(cfg, "eval_window_days", 10) or 10)

    report = CalibrationReport(
        computed_at=datetime.now().isoformat(),
        eval_window_days=eval_window,
        total_results=len(results),
        completed_results=len(completed),
    )
    report.overall = _cell_from_results("overall", completed)

    def _group_by(fn):
        groups: Dict[str, List[Any]] = {}
        for r in completed:
            key = fn(r) or "UNKNOWN"
            groups.setdefault(str(key), []).append(r)
        return groups

    report.by_action = {
        k: _cell_from_results(k, rows)
        for k, rows in _group_by(lambda r: getattr(r, "action", "").upper()).items()
    }
    report.by_confidence_bucket = {
        k: _cell_from_results(k, rows)
        for k, rows in _group_by(lambda r: confidence_bucket(getattr(r, "confidence", -1))).items()
    }
    report.by_ticker = {
        normalize_ticker(k): _cell_from_results(normalize_ticker(k), rows)
        for k, rows in _group_by(lambda r: normalize_ticker(getattr(r, "ticker", ""))).items()
    }

    if ledger_records:
        regime_by_key = {
            (normalize_ticker(getattr(rec, "ticker", "")), getattr(rec, "trade_date", "")): getattr(rec, "market_regime", "")
            for rec in ledger_records
        }
        report.by_regime = {
            k: _cell_from_results(k, rows)
            for k, rows in _group_by(
                lambda r: (regime_by_key.get((normalize_ticker(getattr(r, "ticker", "")), getattr(r, "trade_date", "")), "") or "UNKNOWN").upper()
            ).items()
        }

    if report.overall.decided_n < 10:
        report.notes.append("样本数不足，校准结果仅作提示")
    elif report.overall.calibration_gap >= 0.15:
        report.notes.append("整体置信度偏高，建议降低高置信度结论")
    elif report.overall.calibration_gap <= -0.15:
        report.notes.append("整体置信度偏低，可能低估有效信号")

    return report


def build_calibration_report_from_ledger(
    ledger_path: str = "data/signals/signals.jsonl",
    *,
    config=None,
    after: str = "",
    before: str = "",
):
    """Run a ledger backtest and return a calibration report."""
    from .backtest import BacktestConfig, run_backtest_from_ledger
    from .signal_ledger import SignalLedger

    cfg = config or BacktestConfig()
    bt = run_backtest_from_ledger(
        ledger_path=ledger_path,
        config=cfg,
        after=after or None,
        before=before or None,
    )
    ledger_records = SignalLedger(path=ledger_path).read(after=after or None, before=before or None)
    return build_calibration_report(bt, ledger_records=ledger_records)


def save_calibration_report(report: CalibrationReport, output_dir: str = "data/monitoring") -> Path:
    """Persist a calibration report as JSON using an atomic write."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_slug = datetime.now().strftime("%Y%m%d")
    path = out / f"calibration-{date_slug}.json"
    content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".cal-")
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


def load_latest_calibration_report(directory: str = "data/monitoring") -> Optional[CalibrationReport]:
    """Load the newest ``calibration-*.json`` file from a directory."""
    root = Path(directory)
    if not root.exists():
        return None
    files = sorted(root.glob("calibration-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            return CalibrationReport.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return None


def calibration_summary_for_ticker(
    report: Optional[CalibrationReport],
    ticker: str,
    *,
    action: str = "",
    confidence: float = -1.0,
) -> Dict[str, Any]:
    """Extract the slices most relevant to a single report."""
    if report is None:
        return {}
    nticker = normalize_ticker(ticker)
    bucket = confidence_bucket(confidence)
    out = {
        "eval_window_days": report.eval_window_days,
        "overall": report.overall.to_dict(),
        "ticker": report.by_ticker.get(nticker, CalibrationCell(key=nticker)).to_dict(),
        "confidence_bucket": report.by_confidence_bucket.get(bucket, CalibrationCell(key=bucket)).to_dict(),
        "notes": list(report.notes),
    }
    if action:
        key = action.upper()
        out["action"] = report.by_action.get(key, CalibrationCell(key=key)).to_dict()
    return out


def format_calibration_feedback(summary: Dict[str, Any]) -> str:
    """Render calibration summary for prompt injection."""
    if not summary:
        return ""

    def _line(label: str, cell: Dict[str, Any]) -> str:
        n = int(cell.get("decided_n", 0) or 0)
        if n <= 0:
            return f"- {label}: 样本不足"
        acc = float(cell.get("accuracy", 0) or 0)
        gap = float(cell.get("calibration_gap", 0) or 0)
        return f"- {label}: n={n}, 准确率={acc:.0%}, 置信度偏差={gap:+.0%}"

    lines = ["【历史校准反馈】"]
    lines.append(_line("整体", summary.get("overall") or {}))
    lines.append(_line("本标的", summary.get("ticker") or {}))
    lines.append(_line("当前置信度层", summary.get("confidence_bucket") or {}))
    if summary.get("action"):
        lines.append(_line("当前动作", summary.get("action") or {}))
    notes = summary.get("notes") or []
    if notes:
        lines.append("【校准提示】" + "；".join(str(n) for n in notes[:3]))
    return "\n".join(lines)
