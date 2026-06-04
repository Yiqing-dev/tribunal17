"""Today-change page for the product workbench."""

from __future__ import annotations

from pathlib import Path

from .decision_labels import AI_DISCLAIMER_BANNER
from .shared_utils import _esc, _html_wrap
from .workbench_view import WorkbenchRow, WorkbenchView


_TODAY_CSS = """
.tc-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:.2rem 0 1rem}
.tc-head h1{margin:0;font-size:1.75rem;letter-spacing:0}
.tc-sub{color:var(--muted);font-size:.84rem;margin-top:.2rem}
.tc-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}
.tc-kpi{border:1px solid rgba(255,255,255,.07);border-radius:8px;background:rgba(255,255,255,.025);padding:.72rem .82rem}
.tc-kpi .v{font-size:1.35rem;font-weight:800;color:var(--white);line-height:1}
.tc-kpi .l{font-size:.72rem;color:var(--muted);margin-top:.2rem}
.tc-list{display:grid;gap:.65rem}
.tc-item{border:1px solid rgba(255,255,255,.07);border-radius:8px;background:rgba(255,255,255,.025);padding:.85rem .95rem}
.tc-top{display:flex;gap:.55rem;align-items:center;justify-content:space-between}
.tc-name{font-weight:800;color:var(--white)}
.tc-meta{font-size:.74rem;color:var(--muted)}
.tc-bits{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.55rem}
.tc-bit{border:1px solid rgba(96,165,250,.24);color:var(--fg);border-radius:999px;padding:.16rem .45rem;font-size:.74rem}
.tc-bit.hot{border-color:rgba(248,113,113,.42);color:var(--red)}
.tc-bit.warm{border-color:rgba(251,191,36,.42);color:var(--yellow)}
.tc-next{margin-top:.55rem;color:var(--muted);font-size:.82rem;line-height:1.55}
.tc-links{display:flex;gap:.35rem;flex-wrap:wrap}
.tc-links a{color:var(--blue);text-decoration:none;border:1px solid rgba(96,165,250,.22);border-radius:999px;padding:.16rem .42rem;font-size:.72rem}
.tc-empty{padding:2rem;text-align:center;color:var(--muted)}
@media(max-width:820px){.tc-head{align-items:flex-start;flex-direction:column}.tc-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.tc-top{align-items:flex-start;flex-direction:column}}
"""


def render_today_changes(view: WorkbenchView) -> str:
    """Render a static page of rows that changed or need review."""
    rows = _changed_rows(view)
    body = f"""
    <div class="tc-head">
      <div>
        <h1>今日变化</h1>
        <div class="tc-sub">动作翻转 · 深度差异 · 自动复核触发</div>
      </div>
      <div class="tc-sub"><a href="workbench.html" style="color:var(--blue);text-decoration:none">返回工作台</a></div>
    </div>
    <div class="tc-kpis">
      <div class="tc-kpi"><div class="v">{len(rows)}</div><div class="l">需关注变化</div></div>
      <div class="tc-kpi"><div class="v">{sum(1 for r in rows if r.action_changed)}</div><div class="l">动作变化</div></div>
      <div class="tc-kpi"><div class="v">{sum(1 for r in rows if r.review_triggers)}</div><div class="l">复核触发</div></div>
      <div class="tc-kpi"><div class="v">{sum(1 for r in rows if r.diff_severity == "major")}</div><div class="l">重大变化</div></div>
    </div>
    {_rows_html(rows)}
    <div class="wb-footer" style="margin-top:1rem;color:var(--muted);font-size:.74rem">{AI_DISCLAIMER_BANNER}</div>
    """
    return _html_wrap("今日变化", body, "今日变化", extra_css=_TODAY_CSS)


def generate_today_changes_report(
    *,
    view: WorkbenchView,
    output_dir: str = "data/reports",
) -> str:
    """Write ``today_changes.html`` from an already-built workbench view."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "today_changes.html"
    path.write_text(render_today_changes(view), encoding="utf-8")
    return str(path)


def _changed_rows(view: WorkbenchView) -> list[WorkbenchRow]:
    rows = [
        r for r in view.rows
        if r.action_changed or r.review_triggers or r.diff_score > 0
    ]
    order = {"major": 0, "moderate": 1, "minor": 2, "stable": 3}
    rows.sort(key=lambda r: (
        0 if r.action_changed else 1,
        0 if r.review_triggers else 1,
        order.get(r.diff_severity, 9),
        -max(r.confidence, 0),
        r.ticker,
    ))
    return rows


def _rows_html(rows: list[WorkbenchRow]) -> str:
    if not rows:
        return '<div class="tc-empty">今天没有动作变化、深度差异或自动复核触发。</div>'
    return '<div class="tc-list">' + "".join(_row(r) for r in rows) + "</div>"


def _row(row: WorkbenchRow) -> str:
    bits = []
    if row.action_changed:
        bits.append(f'<span class="tc-bit hot">{_esc(row.previous_action or "—")} → {_esc(row.action or "—")}</span>')
    if row.diff_severity in ("major", "moderate"):
        bits.append(f'<span class="tc-bit warm">{_esc(_sev_label(row.diff_severity))}</span>')
    for item in row.diff_summary[:4]:
        bits.append(f'<span class="tc-bit">{_esc(str(item))}</span>')
    for trigger in row.review_triggers[:3]:
        bits.append(f'<span class="tc-bit warm">{_esc(str(trigger.get("reason") or ""))}</span>')
    links = "".join(
        f'<a href="{_esc(href)}">{_esc(label)}</a>'
        for key, label in (("snapshot", "结论"), ("research", "研究"), ("audit", "审计"))
        for href in [row.report_links.get(key, "")]
        if href
    )
    links_html = f'<div class="tc-links">{links}</div>' if links else ""
    bits_html = "".join(bits) or '<span class="tc-bit">基本稳定</span>'
    return (
        f'<div class="tc-item">'
        f'<div class="tc-top"><div><div class="tc-name">{_esc(row.display_name)}</div>'
        f'<div class="tc-meta">{_esc(row.trade_date)} · {_esc(row.action_label)} · 置信度 {_esc(row.confidence_pct)}</div></div>'
        f'{links_html}</div>'
        f'<div class="tc-bits">{bits_html}</div>'
        f'<div class="tc-next">下一步：{_esc(row.review_reason or row.next_review or row.invalidator or "—")}</div>'
        f'</div>'
    )


def _sev_label(severity: str) -> str:
    return {
        "major": "重大变化",
        "moderate": "明显变化",
        "minor": "轻微变化",
        "stable": "基本稳定",
    }.get(severity, severity)
