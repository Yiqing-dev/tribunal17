"""Product workbench renderer.

This is the product entry point: report library, watchlist state, follow-up
triggers, and links into snapshot/research/audit reports.
"""

from __future__ import annotations

from pathlib import Path

from ..replay_service import ReplayService
from ..replay_store import ReplayStore
from .decision_labels import AI_DISCLAIMER_BANNER
from .shared_utils import _esc, _html_wrap
from .workbench_view import WorkbenchView, WorkbenchRow


_WORKBENCH_CSS = """
.workbench-head{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:.2rem 0 1rem}
.workbench-head h1{margin:0;font-size:1.8rem;letter-spacing:0}
.workbench-sub{color:var(--muted);font-size:.86rem;margin-top:.25rem}
.wb-tabs{display:flex;gap:.45rem;flex-wrap:wrap;margin:.75rem 0 1rem}
.wb-tab{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.035);border-radius:999px;padding:.42rem .72rem;color:var(--fg);font-size:.8rem}
.wb-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}
.wb-kpi{border:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.025);border-radius:8px;padding:.75rem .85rem}
.wb-kpi .v{font-size:1.45rem;font-weight:800;line-height:1;color:var(--white)}
.wb-kpi .l{font-size:.72rem;color:var(--muted);margin-top:.22rem}
.wb-board{border:1px solid rgba(255,255,255,.07);border-radius:8px;overflow:hidden;background:rgba(255,255,255,.02)}
.wb-row,.wb-th{display:grid;grid-template-columns:1.15fr .56fr .48fr .62fr .72fr 1.25fr 1.15fr .72fr;gap:.65rem;align-items:center}
.wb-th{padding:.7rem .9rem;background:rgba(255,255,255,.04);color:var(--muted);font-size:.72rem;letter-spacing:.04em;text-transform:uppercase}
.wb-row{padding:.8rem .9rem;border-top:1px solid rgba(255,255,255,.055);font-size:.84rem}
.wb-row:hover{background:rgba(96,165,250,.045)}
.wb-name{font-weight:700;color:var(--white)}
.wb-meta{font-size:.72rem;color:var(--muted);margin-top:.15rem}
.wb-small{font-size:.78rem;color:var(--muted);line-height:1.45}
.wb-links{display:flex;gap:.35rem;flex-wrap:wrap}
.wb-links a{color:var(--blue);text-decoration:none;border:1px solid rgba(96,165,250,.22);border-radius:999px;padding:.18rem .45rem;font-size:.72rem}
.wb-links a:hover{background:rgba(96,165,250,.1)}
.wb-change{font-size:.72rem;color:var(--muted);margin-top:.18rem}
.wb-delta-up{color:var(--green)}.wb-delta-down{color:var(--red)}.wb-delta-flat{color:var(--muted)}
.wb-empty{padding:2rem;text-align:center;color:var(--muted)}
.wb-footer{margin-top:1rem;color:var(--muted);font-size:.74rem;line-height:1.55}
@media(max-width:980px){.wb-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.wb-th{display:none}.wb-row{grid-template-columns:1fr;gap:.45rem}.workbench-head{align-items:flex-start;flex-direction:column}}
"""


_STATUS_TIPS = {
    "可跟踪": "结论与质量门禁均可接受，进入观察池跟踪触发条件",
    "等待触发": "目前不直接参与，等待价格/事件/行业条件确认",
    "需复核": "存在数据口径、质量或风险缺口，需人工确认后再使用",
    "回避": "当前结论或风控状态偏负面，不作为参与候选",
    "已生成": "报告已生成，缺少足够状态信号",
}

_REL_VAL = {
    "premium": "估值溢价",
    "discount": "估值折价",
    "fair": "估值接近行业",
    "unavailable": "估值不足",
}

_REL_Q = {
    "quality_premium": "质量支撑",
    "weak_quality": "质量偏弱",
    "mixed": "质量分化",
    "unavailable": "质量不足",
}


def _badge(label: str, cls: str = "hold", title: str = "") -> str:
    tip = f' title="{_esc(title)}"' if title else ""
    return f'<span class="badge badge-{_esc(cls or "hold")}"{tip}>{_esc(label or "—")}</span>'


def _delta(row: WorkbenchRow) -> str:
    if not row.previous_run_id:
        return '<div class="wb-change">首次入库</div>'
    action = "动作未变"
    if row.action_changed:
        action = f"{row.previous_action or '—'} → {row.action or '—'}"
    d = row.confidence_delta
    cls = "wb-delta-up" if d > 0.03 else ("wb-delta-down" if d < -0.03 else "wb-delta-flat")
    return (
        f'<div class="wb-change">{_esc(action)} · '
        f'<span class="{cls}">{d:+.0%}</span></div>'
    )


def _row(row: WorkbenchRow) -> str:
    profile = row.profile_label or "—"
    val = _REL_VAL.get(row.relative_valuation_label, row.relative_valuation_label or "—")
    qlt = _REL_Q.get(row.relative_quality_label, row.relative_quality_label or "—")
    quality = row.quality_grade or "—"
    q_cls = "buy" if quality in ("A", "B") else ("hold" if quality == "C" else "sell")
    links = row.report_links or {}
    links_html = (
        f'<div class="wb-links">'
        f'<a href="{_esc(links.get("snapshot", "#"))}">结论</a>'
        f'<a href="{_esc(links.get("research", "#"))}">研究</a>'
        f'<a href="{_esc(links.get("audit", "#"))}">审计</a>'
        f'</div>'
    )
    flags = []
    if row.data_quality_count:
        flags.append(f"口径 {row.data_quality_count}")
    if row.risk_count:
        flags.append(f"风险 {row.risk_count}")
    flags_text = " · ".join(flags) or "—"
    return (
        f'<div class="wb-row" data-status="{_esc(row.status)}" data-action="{_esc(row.action)}">'
        f'<div><div class="wb-name">{_esc(row.display_name)}</div>'
        f'<div class="wb-meta">{_esc(row.trade_date)} · {_esc(profile)}</div>{_delta(row)}</div>'
        f'<div>{_badge(row.status, row.status_class, _STATUS_TIPS.get(row.status, ""))}</div>'
        f'<div>{_badge(row.action_label, row.action_class)}</div>'
        f'<div><strong>{_esc(row.confidence_pct)}</strong><div class="wb-meta">质量 {quality}</div></div>'
        f'<div class="wb-small">{_esc(val)}<br>{_esc(qlt)} · {flags_text}</div>'
        f'<div class="wb-small">{_esc(row.why_now or "—")}</div>'
        f'<div class="wb-small">{_esc(row.next_review or row.invalidator or "—")}</div>'
        f'<div>{links_html}</div>'
        f'</div>'
    )


def render_workbench(view: WorkbenchView) -> str:
    """Render product workbench HTML."""
    grade_mix = " · ".join(f"{_esc(k)}:{v}" for k, v in sorted(view.grade_mix.items())) or "—"
    rows_html = "".join(_row(r) for r in view.rows)
    if not rows_html:
        rows_html = '<div class="wb-empty">暂无报告。生成单股报告后，这里会自动形成报告库和观察池。</div>'

    body = f"""
    <div class="workbench-head">
      <div>
        <h1>个股研究工作台</h1>
        <div class="workbench-sub">报告库 · 观察池 · 复盘触发 · 历史变化</div>
      </div>
      <div class="workbench-sub">生成时间 {_esc(view.generated_at)}</div>
    </div>
    <div class="wb-tabs">
      <span class="wb-tab">日期 {' / '.join(_esc(d) for d in view.trade_dates) or '—'}</span>
      <span class="wb-tab">质量分布 {grade_mix}</span>
    </div>
    <div class="wb-kpis">
      <div class="wb-kpi"><div class="v">{view.total_tickers}</div><div class="l">覆盖标的</div></div>
      <div class="wb-kpi"><div class="v">{view.total_reports}</div><div class="l">历史报告</div></div>
      <div class="wb-kpi"><div class="v">{view.buy_count}</div><div class="l">可跟踪 BUY</div></div>
      <div class="wb-kpi"><div class="v">{view.wait_count}</div><div class="l">等待触发</div></div>
      <div class="wb-kpi"><div class="v">{view.review_count}</div><div class="l">需复核</div></div>
      <div class="wb-kpi"><div class="v">{view.changed_count}</div><div class="l">较上次变化</div></div>
    </div>
    <div class="wb-board">
      <div class="wb-th">
        <div>标的</div><div>状态</div><div>结论</div><div>置信/质量</div>
        <div>相对行业</div><div>为什么现在</div><div>下一步</div><div>报告</div>
      </div>
      {rows_html}
    </div>
    <div class="wb-footer">{AI_DISCLAIMER_BANNER}</div>
    """
    return _html_wrap("个股研究工作台", body, "产品工作台", extra_css=_WORKBENCH_CSS)


def generate_workbench_report(
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    *,
    limit: int = 120,
    latest_per_ticker: bool = True,
) -> str:
    """Generate the workbench/report-library page from replay traces."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    store = ReplayStore(storage_dir=storage_dir)
    svc = ReplayService(store=store)
    view = WorkbenchView.build(svc, limit=limit, latest_per_ticker=latest_per_ticker)
    path = out / "workbench.html"
    path.write_text(render_workbench(view), encoding="utf-8")
    return str(path)

