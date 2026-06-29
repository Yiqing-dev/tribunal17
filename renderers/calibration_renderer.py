"""Static calibration dashboard renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from ..calibration import (
    CalibrationCell,
    CalibrationReport,
    build_calibration_report_from_ledger,
    load_latest_calibration_report,
    save_calibration_report,
)
from .shared_utils import _esc, _html_wrap, format_confidence_pct


_CAL_CSS = """
.cal-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:.2rem 0 1rem}
.cal-head h1{margin:0;font-size:1.75rem;letter-spacing:0}
.cal-sub{color:var(--muted);font-size:.84rem;margin-top:.2rem}
.cal-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}
.cal-kpi{border:1px solid rgba(255,255,255,.07);border-radius:8px;background:rgba(255,255,255,.025);padding:.8rem .9rem}
.cal-kpi .v{font-size:1.35rem;font-weight:800;color:var(--white);line-height:1}
.cal-kpi .l{font-size:.72rem;color:var(--muted);margin-top:.2rem}
.cal-section{margin-top:1rem}
.cal-table{width:100%;border-collapse:collapse;font-size:.84rem;border:1px solid rgba(255,255,255,.07);border-radius:8px;overflow:hidden}
.cal-table th,.cal-table td{padding:.55rem .65rem;border-bottom:1px solid rgba(255,255,255,.06);text-align:left}
.cal-table th{color:var(--muted);font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;background:rgba(255,255,255,.035)}
.cal-table td.num{text-align:right;font-family:var(--mono)}
.cal-note{color:var(--muted);font-size:.82rem;line-height:1.6;margin:.6rem 0}
.cal-empty{padding:2rem;text-align:center;color:var(--muted);border:1px solid rgba(255,255,255,.07);border-radius:8px;background:rgba(255,255,255,.025)}
@media(max-width:860px){.cal-head{align-items:flex-start;flex-direction:column}.cal-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cal-table{font-size:.76rem}}
"""


def render_calibration_page(report: CalibrationReport | None) -> str:
    """Render the latest calibration report, if available."""
    if report is None:
        body = """
        <div class="cal-head">
          <div>
            <h1>历史校准</h1>
            <div class="cal-sub">方向准确率 · 置信度分桶 · 策略画像偏差</div>
          </div>
          <div class="cal-sub"><a href="workbench.html" style="color:var(--blue);text-decoration:none">返回工作台</a></div>
        </div>
        <div class="cal-empty">暂无校准数据。运行信号回测并保存 calibration-*.json 后，这里会自动展示。</div>
        """
        return _html_wrap("历史校准", body, "历史校准", extra_css=_CAL_CSS)

    overall = report.overall
    body = f"""
    <div class="cal-head">
      <div>
        <h1>历史校准</h1>
        <div class="cal-sub">方向准确率 · 置信度分桶 · 策略画像偏差</div>
      </div>
      <div class="cal-sub"><a href="workbench.html" style="color:var(--blue);text-decoration:none">返回工作台</a></div>
    </div>
    <div class="cal-grid">
      <div class="cal-kpi"><div class="v">{report.completed_results}</div><div class="l">已完成样本</div></div>
      <div class="cal-kpi"><div class="v">{overall.accuracy:.0%}</div><div class="l">整体方向准确率</div></div>
      <div class="cal-kpi"><div class="v">{format_confidence_pct(overall.avg_confidence)}</div><div class="l">平均置信度</div></div>
      <div class="cal-kpi"><div class="v">{overall.calibration_gap:+.0%}</div><div class="l">置信度偏差</div></div>
    </div>
    {_notes(report)}
    {_section("按动作", report.by_action)}
    {_section("按置信度", report.by_confidence_bucket)}
    {_section("按市场状态", report.by_regime)}
    {_section("按标的", report.by_ticker, limit=30)}
    """
    return _html_wrap("历史校准", body, "历史校准", extra_css=_CAL_CSS)


def generate_calibration_page(
    output_dir: str = "data/reports",
    *,
    monitoring_dir: str = "data/monitoring",
    ledger_path: str = "data/signals/signals.jsonl",
    auto_build: bool = False,
) -> str:
    """Write ``calibration.html`` next to reports."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ensure_latest_calibration_report(
        monitoring_dir=monitoring_dir,
        ledger_path=ledger_path,
        auto_build=auto_build,
    )
    path = out / "calibration.html"
    path.write_text(render_calibration_page(report), encoding="utf-8")
    return str(path)


def ensure_latest_calibration_report(
    *,
    monitoring_dir: str = "data/monitoring",
    ledger_path: str = "data/signals/signals.jsonl",
    auto_build: bool = False,
) -> CalibrationReport | None:
    """Load latest calibration, optionally building it from the signal ledger."""
    report = load_latest_calibration_report(monitoring_dir)
    if report is not None or not auto_build:
        return report
    ledger = Path(ledger_path)
    if not ledger.exists():
        return None
    try:
        report = build_calibration_report_from_ledger(ledger_path=str(ledger))
        save_calibration_report(report, output_dir=monitoring_dir)
        return report
    except Exception:
        return None


def _notes(report: CalibrationReport) -> str:
    if not report.notes:
        return ""
    return '<div class="cal-note">' + "；".join(_esc(str(n)) for n in report.notes[:5]) + "</div>"


def _section(title: str, cells: Dict[str, CalibrationCell], *, limit: int = 50) -> str:
    if not cells:
        return ""
    rows = sorted(cells.values(), key=lambda c: (-(c.decided_n or 0), c.key))[:limit]
    body = "".join(_row(c) for c in rows)
    return (
        f'<div class="cal-section"><h2>{_esc(title)}</h2>'
        f'<table class="cal-table"><thead><tr>'
        f'<th>切片</th><th>样本</th><th>已决策</th><th>命中</th><th>准确率</th><th>平均置信</th><th>偏差</th>'
        f'</tr></thead><tbody>{body}</tbody></table></div>'
    )


def _row(cell: CalibrationCell) -> str:
    return (
        f'<tr><td>{_esc(cell.key)}</td>'
        f'<td class="num">{cell.n}</td>'
        f'<td class="num">{cell.decided_n}</td>'
        f'<td class="num">{cell.correct_n}</td>'
        f'<td class="num">{cell.accuracy:.0%}</td>'
        f'<td class="num">{format_confidence_pct(cell.avg_confidence)}</td>'
        f'<td class="num">{cell.calibration_gap:+.0%}</td></tr>'
    )
