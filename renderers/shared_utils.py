"""
Shared utility functions for HTML report renderers.

Extracted from report_renderer.py to allow reuse across
report_renderer, recap_renderer, and other renderer modules
without circular imports.
"""

import math
import logging
import os
import re
import tempfile
from typing import Optional

from .decision_labels import EVIDENCE_STRENGTH_LABELS
from .shared_css import _BASE_CSS, _SHARED_SVG_DEFS
# Confidence normalization is defined once in the foundation module so that
# parsing (bridge.py) and display (renderers) share ONE implementation.
from ..shared import _CONFIDENCE_LABELS, normalize_confidence_value  # noqa: F401

logger = logging.getLogger(__name__)

_CROSS_NAV_START = "<!-- cross-nav:start -->"
_CROSS_NAV_END = "<!-- cross-nav:end -->"
_CROSS_NAV_BLOCK_RE = re.compile(
    re.escape(_CROSS_NAV_START) + r".*?" + re.escape(_CROSS_NAV_END),
    re.S,
)
# Match only the exact ``cross-nav`` class token. Similarly named custom
# classes such as ``my-cross-nav-foo`` are left in place and treated as
# unrelated page markup.
_LEGACY_CROSS_NAV_RE = re.compile(
    r'<nav\b[^>]*\bclass=["\'][^"\']*(?<![-\w])cross-nav(?![-\w])[^"\']*["\'][^>]*>.*?</nav>',
    re.S,
)
_CONTAINER_OPEN_RE = re.compile(
    r'(<div\b[^>]*\bclass=["\'][^"\']*\bcontainer\b[^"\']*["\'][^>]*>\s*)',
    re.S,
)


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def _cross_nav_block(nav_html: str = "") -> str:
    """Return the replaceable cross-report navigation block."""
    if not nav_html:
        return ""
    return f"{_CROSS_NAV_START}\n{nav_html}\n{_CROSS_NAV_END}"


def _render_industry_compare_card(industry_compare: dict) -> str:
    """Peer-comparison card. Used by snapshot + research renderers.

    Inputs (dict shape from akshare_collector.AkshareBundle.industry_compare):
      industry_name, pe_percentile_5y, pb_percentile_5y, history_days,
      industry_pe_median, industry_pb_median, industry_size, peers (list).

    Visual logic:
      - Header strip: 行业名 / PE 分位 / PB 分位 / 行业中位
      - peers >= 3 → render comparison table; current ticker row highlighted
        with ★ marker and background tint. Peer PE / PB cells colored:
          * green badge "低" when value <= 0.7 × industry_median
          * red badge "高" when value >= 1.3 × industry_median
          * neutral otherwise
      - peers < 3 → header only + "对比样本不足" message

    Returns "" when industry_compare is empty / lacks an industry name.
    """
    if not industry_compare or not industry_compare.get("industry_name"):
        return ""

    ic = industry_compare
    name = ic.get("industry_name", "—")
    pe_pct = ic.get("pe_percentile_5y")
    pb_pct = ic.get("pb_percentile_5y")
    pe_med = ic.get("industry_pe_median")
    pb_med = ic.get("industry_pb_median")
    ps_med = ic.get("industry_ps_median")
    roe_med = ic.get("industry_roe_median")
    gm_med = ic.get("industry_gross_margin_median")
    rev_med = ic.get("industry_revenue_growth_median")
    history_days = ic.get("history_days") or 0
    ind_size = ic.get("industry_size") or 0
    rel_val = ic.get("relative_valuation_label", "")
    rel_quality = ic.get("relative_quality_label", "")

    # Header strip cells
    header_cells: list = []

    def _pct_color(v):
        if v is None:
            return "var(--muted)"
        if v <= 30:
            return "var(--green)"   # 低估
        if v >= 70:
            return "var(--red)"     # 高估
        return "var(--yellow)"

    def _hcell(label: str, value: str, color: str = "") -> str:
        clr = f' style="color:{color}"' if color else ""
        return (
            f'<div style="display:flex;flex-direction:column;gap:.1rem">'
            f'<span style="font-size:.7rem;color:var(--muted);letter-spacing:.05em;'
            f'text-transform:uppercase">{_esc(label)}</span>'
            f'<span class="mono" style="font-size:.95rem;font-weight:600;color:var(--white)"{clr}>{value}</span>'
            f'</div>'
        )

    if pe_pct is not None:
        clr = _pct_color(pe_pct)
        suffix = f"<span style='font-size:.65em;margin-left:.2rem;color:var(--muted)'>近{history_days}日</span>" if history_days else ""
        header_cells.append(_hcell(
            "PE 历史分位",
            f'{pe_pct:.1f}% {suffix}',
            color=clr,
        ))
    if pb_pct is not None:
        header_cells.append(_hcell(
            "PB 历史分位",
            f"{pb_pct:.1f}%",
            color=_pct_color(pb_pct),
        ))
    if pe_med is not None:
        header_cells.append(_hcell(
            "行业中位 PE",
            f"{pe_med:.2f}",
        ))
    if pb_med is not None:
        header_cells.append(_hcell(
            "行业中位 PB",
            f"{pb_med:.2f}",
        ))
    if ps_med is not None:
        header_cells.append(_hcell("行业中位 PS", f"{ps_med:.2f}"))
    if roe_med is not None:
        header_cells.append(_hcell("行业中位 ROE", f"{roe_med:.2f}%"))

    _VAL_LABELS = {
        "premium": ("估值溢价", "var(--red)"),
        "discount": ("估值折价", "var(--green)"),
        "fair": ("估值接近行业", "var(--yellow)"),
        "unavailable": ("估值相对位置不足", "var(--muted)"),
    }
    _QLT_LABELS = {
        "quality_premium": ("质量支撑", "var(--green)"),
        "weak_quality": ("质量偏弱", "var(--red)"),
        "mixed": ("质量分化", "var(--yellow)"),
        "unavailable": ("质量对比不足", "var(--muted)"),
    }
    rel_bits = []
    if rel_val:
        txt, clr = _VAL_LABELS.get(rel_val, (rel_val, "var(--muted)"))
        basis = ic.get("relative_valuation_basis", "")
        rel_bits.append(f'<span class="badge" style="border-color:{clr};color:{clr}">{_esc(txt)}{f"({_esc(basis)})" if basis else ""}</span>')
    if rel_quality:
        txt, clr = _QLT_LABELS.get(rel_quality, (rel_quality, "var(--muted)"))
        rel_bits.append(f'<span class="badge" style="border-color:{clr};color:{clr}">{_esc(txt)}</span>')
    relative_html = (
        f'<div style="display:flex;gap:.45rem;flex-wrap:wrap;margin:-.2rem 0 .65rem">'
        f'{"".join(rel_bits)}</div>'
    ) if rel_bits else ""

    header_html = (
        f'<div style="display:flex;flex-wrap:wrap;gap:1.4rem;'
        f'padding:.6rem .9rem;background:rgba(255,255,255,0.025);'
        f'border:1px solid rgba(255,255,255,0.06);border-radius:10px;'
        f'margin-bottom:.7rem">{"".join(header_cells)}</div>'
    ) if header_cells else ""

    # Peer table
    peers = ic.get("peers") or []
    table_html = ""
    show_quality_cols = any(
        p.get("roe") is not None or p.get("gross_margin") is not None or p.get("revenue_growth") is not None
        for p in peers
    )
    if len(peers) >= 3:
        rows: list = []
        for p in peers:
            code = p.get("ticker", "")
            n = p.get("name", "")
            pe = p.get("pe")
            pb = p.get("pb")
            roe = p.get("roe")
            gross_margin = p.get("gross_margin")
            revenue_growth = p.get("revenue_growth")
            turnover = p.get("turnover_yi")
            is_cur = bool(p.get("is_current"))

            def _val_with_tag(v, median):
                if v is None:
                    return '<span class="mono" style="color:var(--muted)">—</span>'
                tag = ""
                if median:
                    if v <= median * 0.7:
                        tag = '<span class="badge badge-buy" style="margin-left:.3rem;font-size:.65em">低</span>'
                    elif v >= median * 1.3:
                        tag = '<span class="badge badge-sell" style="margin-left:.3rem;font-size:.65em">高</span>'
                return f'<span class="mono">{v:.2f}</span>{tag}'

            star = '<span style="color:var(--yellow);margin-right:.2rem">★</span>' if is_cur else ""
            row_bg = ' style="background:rgba(251,191,36,0.05);font-weight:600"' if is_cur else ""
            turnover_str = f'{turnover:.2f} 亿' if isinstance(turnover, (int, float)) else "—"
            quality_cells = ""
            if show_quality_cols:
                roe_str = f"{roe:.1f}%" if isinstance(roe, (int, float)) else "—"
                gm_str = f"{gross_margin:.1f}%" if isinstance(gross_margin, (int, float)) else "—"
                rg_str = f"{revenue_growth:.1f}%" if isinstance(revenue_growth, (int, float)) else "—"
                quality_cells = (
                    f'<td class="mono" style="padding:.4rem .5rem;color:var(--muted)">{roe_str}</td>'
                    f'<td class="mono" style="padding:.4rem .5rem;color:var(--muted)">{gm_str}</td>'
                    f'<td class="mono" style="padding:.4rem .5rem;color:var(--muted)">{rg_str}</td>'
                )
            rows.append(
                f'<tr{row_bg}><td style="padding:.4rem .5rem">{star}{_esc(code)}</td>'
                f'<td style="padding:.4rem .5rem">{_esc(n)}</td>'
                f'<td style="padding:.4rem .5rem">{_val_with_tag(pe, pe_med)}</td>'
                f'<td style="padding:.4rem .5rem">{_val_with_tag(pb, pb_med)}</td>'
                f'{quality_cells}'
                f'<td class="mono" style="padding:.4rem .5rem;color:var(--muted)">{turnover_str}</td>'
                f'</tr>'
            )
        quality_head = ""
        if show_quality_cols:
            quality_head = (
                f'<th style="text-align:left;padding:.4rem .5rem">ROE</th>'
                f'<th style="text-align:left;padding:.4rem .5rem">毛利率</th>'
                f'<th style="text-align:left;padding:.4rem .5rem">营收增速</th>'
            )
        table_html = (
            f'<table style="width:100%;border-collapse:collapse;font-size:.86rem">'
            f'<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.08);'
            f'color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em">'
            f'<th style="text-align:left;padding:.4rem .5rem">代码</th>'
            f'<th style="text-align:left;padding:.4rem .5rem">名称</th>'
            f'<th style="text-align:left;padding:.4rem .5rem">{_pe_label_html()}</th>'
            f'<th style="text-align:left;padding:.4rem .5rem">PB</th>'
            f'{quality_head}'
            f'<th style="text-align:left;padding:.4rem .5rem">成交额</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )
    elif peers:
        table_html = (
            f'<div style="font-size:.85rem;color:var(--muted);padding:.4rem 0">'
            f'对比样本不足（仅 {len(peers)} 只可对比）</div>'
        )

    sample_size_note = (
        f'<div style="font-size:.7rem;color:var(--muted);margin-top:.4rem">'
        f'行业成份股 {ind_size} 只 · 选取 {len(peers)} 只活跃同业 · ★ 当前标的</div>'
    ) if ind_size and peers else ""

    return (
        f'<div class="card industry-compare reveal" style="padding:1rem 1.15rem">'
        f'<h3 style="display:flex;align-items:center;gap:.4rem;margin-bottom:.6rem">'
        f'<span>行业对比</span>'
        f'<span style="color:var(--muted);font-size:.85rem;font-weight:500">· {_esc(name)}</span>'
        f'</h3>'
        f'{relative_html}'
        f'{header_html}'
        f'{table_html}'
        f'{sample_size_note}'
        f'</div>'
    )


def _render_hero_industry_kpis(industry_compare: dict) -> str:
    """Three mini KPIs for snapshot hero right-side fill.

    Shows industry-context numbers (median PE / median PB / 5Y PE percentile)
    when industry data is available. Returns "" when not — graceful degradation.
    """
    if not industry_compare:
        return ""
    ic = industry_compare
    pe_pct = ic.get("pe_percentile_5y")
    pe_med = ic.get("industry_pe_median")
    pb_med = ic.get("industry_pb_median")
    if pe_pct is None and pe_med is None and pb_med is None:
        return ""

    parts: list = []
    if pe_med is not None:
        parts.append(
            f'<div class="kpi kpi-tertiary" style="padding:.45rem .55rem">'
            f'<span class="kpi-val mono" style="font-size:.95rem">{pe_med:.1f}</span>'
            f'<span class="kpi-label" style="font-size:.65rem">行业 PE</span>'
            f'</div>'
        )
    if pb_med is not None:
        parts.append(
            f'<div class="kpi kpi-tertiary" style="padding:.45rem .55rem">'
            f'<span class="kpi-val mono" style="font-size:.95rem">{pb_med:.1f}</span>'
            f'<span class="kpi-label" style="font-size:.65rem">行业 PB</span>'
            f'</div>'
        )
    if pe_pct is not None:
        clr = "var(--green)" if pe_pct <= 30 else ("var(--red)" if pe_pct >= 70 else "var(--yellow)")
        parts.append(
            f'<div class="kpi kpi-tertiary" style="padding:.45rem .55rem">'
            f'<span class="kpi-val mono" style="font-size:.95rem;color:{clr}">{pe_pct:.0f}%</span>'
            f'<span class="kpi-label" style="font-size:.65rem">5Y PE 分位</span>'
            f'</div>'
        )
    if not parts:
        return ""
    return (
        f'<div style="display:grid;grid-template-columns:repeat({len(parts)},1fr);'
        f'gap:.4rem;margin-top:.5rem;padding-top:.5rem;'
        f'border-top:1px solid rgba(255,255,255,0.05)">'
        f'{"".join(parts)}</div>'
    )


def _quality_grade_badge_html(
    grade: str = "",
    score: float = 0.0,
    weak_dims: Optional[list] = None,
) -> str:
    """Inline grade badge for the report watermark row.

    grade ∈ {"A", "B", "C", "D"}; empty string returns "" (graceful skip).
    Color: A=green, B=blue, C=yellow, D=red. C/D shows weak dimensions inline.
    """
    if not grade:
        return ""
    color = {
        "A": "var(--green)",
        "B": "var(--blue)",
        "C": "var(--yellow)",
        "D": "var(--red)",
    }.get(grade, "var(--muted)")
    warn = ""
    if grade in ("C", "D") and weak_dims:
        wk = "、".join(weak_dims[:2])
        warn = (
            f' <span style="color:var(--muted);font-size:.7em">'
            f'(薄弱: {_esc(wk)})</span>'
        )
    return (
        f'<span style="display:inline-flex;align-items:center;gap:.25rem;'
        f'padding:1px 8px;border-radius:999px;background:rgba(255,255,255,0.04);'
        f'border:1px solid {color};color:{color};'
        f'font-weight:700;font-size:.7rem;letter-spacing:.04em" '
        f'title="研究质量综合评分 {score:.2f} / 1.00 (7 维度加权)">'
        f'\U0001f4ca {_esc(grade)} 级 · {score:.2f}'
        f'</span>{warn}'
    )


def _render_stock_profile_card(profile: dict) -> str:
    """Render stock-type lens and required checks."""
    if not profile:
        return ""
    label = profile.get("label_cn") or profile.get("primary") or "普通个股"
    reasons = profile.get("reasons") or []
    checks = profile.get("key_checks") or []
    warnings = profile.get("warnings") or []
    reason_html = "".join(f"<li>{_esc(str(x))}</li>" for x in reasons[:4])
    check_html = "".join(
        f'<span class="badge badge-hold" style="margin:.12rem .18rem .12rem 0">{_esc(str(x))}</span>'
        for x in checks[:6]
    )
    warn_html = ""
    if warnings:
        warn_items = "".join(f"<li>{_esc(str(x))}</li>" for x in warnings[:4])
        warn_html = f'<div style="margin-top:.55rem;color:var(--yellow)"><ul>{warn_items}</ul></div>'
    return (
        f'<div class="card stock-profile-card reveal">'
        f'<h3>个股类型</h3>'
        f'<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin-bottom:.55rem">'
        f'<span class="badge badge-buy" style="font-size:.85rem">{_esc(label)}</span>'
        f'{check_html}'
        f'</div>'
        f'{f"<ul>{reason_html}</ul>" if reason_html else ""}'
        f'{warn_html}'
        f'</div>'
    )


def _render_calibration_card(summary: dict) -> str:
    """Render historical calibration summary."""
    if not summary:
        return ""

    def _cell(label: str, cell: dict) -> str:
        decided = int(cell.get("decided_n", 0) or 0)
        if decided <= 0:
            val = "样本不足"
            sub = "—"
            cls = "hold"
        else:
            acc = float(cell.get("accuracy", 0) or 0)
            gap = float(cell.get("calibration_gap", 0) or 0)
            val = f"{acc:.0%}"
            sub = f"n={decided} · 偏差 {gap:+.0%}"
            # Direction-neutral confidence-strength tiers (not buy/sell) — AQ-F1.
            cls = "conf-strong" if acc >= 0.55 else ("conf-mid" if acc >= 0.45 else "conf-weak")
        return (
            f'<div class="kpi kpi-secondary">'
            f'<span class="kpi-val badge badge-{cls}" style="font-size:.85rem">{_esc(val)}</span>'
            f'<span class="kpi-label">{_esc(label)}</span>'
            f'<span style="font-size:.68rem;color:var(--muted)">{_esc(sub)}</span>'
            f'</div>'
        )

    notes = summary.get("notes") or []
    notes_html = ""
    if notes:
        notes_html = (
            f'<div style="font-size:.8rem;color:var(--muted);margin-top:.55rem">'
            f'{_esc("；".join(str(n) for n in notes[:3]))}</div>'
        )
    return (
        f'<div class="card calibration-card reveal">'
        f'<h3>历史校准</h3>'
        f'<div class="kpi-row">'
        f'{_cell("整体", summary.get("overall") or {})}'
        f'{_cell("本标的", summary.get("ticker") or {})}'
        f'{_cell("当前置信层", summary.get("confidence_bucket") or {})}'
        f'{_cell("当前动作", summary.get("action") or {}) if summary.get("action") else ""}'
        f'</div>'
        f'{notes_html}'
        f'</div>'
    )


def _render_data_quality_flags(flags: list) -> str:
    """Render data/metric caveats."""
    if not flags:
        return ""
    rows = ""
    for f in flags[:6]:
        sev = str(f.get("severity", "medium")).lower()
        # Severity badges (direction-neutral), NOT buy/sell — else the A-share
        # action flip would make a CRITICAL flag green and a low flag red (COLOR-006).
        cls = "high" if sev in ("high", "critical") else ("medium" if sev == "medium" else "low")
        rows += (
            f'<li><span class="badge badge-{cls}" style="margin-right:.35rem">'
            f'{_esc(sev.upper())}</span>{_esc(str(f.get("message", "")))}</li>'
        )
    return (
        f'<div class="card data-quality-card reveal">'
        f'<h3>数据口径风险</h3>'
        f'<ul>{rows}</ul>'
        f'</div>'
    )


def _render_report_delta_card(view) -> str:
    """Render current-vs-previous report delta for the same ticker."""
    history = getattr(view, "signal_history", None) or []
    if not history:
        return ""
    prev = history[0] or {}
    prev_action = str(prev.get("action", "") or "")
    prev_date = str(prev.get("trade_date", "") or "")
    prev_run_id = str(prev.get("run_id", "") or "")
    cur_action = str(getattr(view, "research_action", "") or "")
    cur_conf = getattr(view, "confidence", -1.0)
    prev_conf = prev.get("confidence", -1.0)
    def _valid_conf(value) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return -1.0
        return v if 0.0 <= v <= 1.0 else -1.0

    cur_conf_f = _valid_conf(cur_conf)
    prev_conf_f = _valid_conf(prev_conf)
    report_diff = getattr(view, "report_diff", None) or {}
    diff_summary = list(report_diff.get("summary") or []) if isinstance(report_diff, dict) else []
    diff_severity = str(report_diff.get("severity", "") or "") if isinstance(report_diff, dict) else ""

    changed = bool(prev_action and cur_action and prev_action != cur_action)
    has_delta = cur_conf_f >= 0 and prev_conf_f >= 0
    delta = cur_conf_f - prev_conf_f if has_delta else 0.0
    if not changed and (not has_delta or abs(delta) < 0.01) and not diff_summary:
        return ""
    d_cls = "buy" if delta > 0.03 else ("sell" if delta < -0.03 else "hold")
    change_cls = "sell" if changed else "hold"
    change_text = f"{prev_action} → {cur_action}" if changed else "方向未变"
    delta_text = f"置信度 {delta:+.0%}" if has_delta else "置信度 —"

    prev_link = ""
    if prev_run_id:
        try:
            from .report_renderer import _safe_filename
            safe_t = _safe_filename(getattr(view, "ticker", ""))
            short = prev_run_id.replace("run-", "")[:12]
            href = f"{safe_t}-run-{short}-snapshot.html"
            prev_link = f'<a href="{_esc(href)}" style="color:var(--blue);text-decoration:none">查看上一版</a>'
        except Exception:
            prev_link = ""
    sev_label = {
        "major": "重大变化",
        "moderate": "明显变化",
        "minor": "轻微变化",
        "stable": "基本稳定",
    }.get(diff_severity, "")
    sev_html = f'<span class="badge badge-{change_cls}">{_esc(sev_label)}</span>' if sev_label else ""
    summary_html = ""
    if diff_summary:
        summary_html = (
            '<ul style="margin:.65rem 0 0 1.05rem;color:var(--fg);font-size:.86rem;line-height:1.65">'
            + "".join(f"<li>{_esc(str(item))}</li>" for item in diff_summary[:5])
            + "</ul>"
        )

    return (
        f'<div class="card report-delta-card reveal">'
        f'<h3>与上次报告相比</h3>'
        f'<div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">'
        f'<span class="badge badge-{change_cls}">{_esc(change_text)}</span>'
        f'<span class="badge badge-{d_cls}">{_esc(delta_text)}</span>'
        f'{sev_html}'
        f'<span style="color:var(--muted);font-size:.82rem">上一版 {_esc(prev_date or "—")}</span>'
        f'{prev_link}'
        f'</div>'
        f'{summary_html}'
        f'</div>'
    )


def _vague_phrase_warning(text: str) -> str:
    """Render an inline warning when a falsifiability condition contains
    vague language. Returns "" when the text is concrete (has number / date).

    Used by renderers when displaying invalidation_conditions / failure
    triggers — surfaces prompt-level quality issues at render time so
    quality drift doesn't silently degrade the report.
    """
    if not text:
        return ""
    t = str(text)
    # Concrete trigger keywords / patterns — if any present, no warning
    has_number = bool(re.search(r"\d+\.\d{1,3}|\d+%|\d+亿|\d+万|\d+\.\d+\s*元|\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日", t))
    if has_number:
        return ""
    # Vague phrase blacklist — soft signals only
    vague_tokens = (
        "市场转弱", "情况恶化", "风险上升", "环境变化",
        "若发生不利", "如果失败", "出现问题", "信号不再有效",
        "基本面转差", "若市场",
    )
    if not any(vt in t for vt in vague_tokens):
        return ""
    return (
        f' <span class="vague-warn" '
        f'style="display:inline-block;margin-left:.3rem;padding:0 6px;'
        f'border-radius:999px;background:rgba(248,113,113,0.1);'
        f'border:1px solid rgba(248,113,113,0.4);color:var(--red);'
        f'font-size:.62em;font-weight:600;letter-spacing:.04em" '
        f'title="此条件含糊，缺少具体数字阈值/日期 — 可证伪性不足">'
        f'⚠ 含糊条件'
        f'</span>'
    )


def _pe_label_html() -> str:
    """Canonical PE display: 'PE' + small TTM superscript.

    Used everywhere PE values are rendered so readers know the consistent
    口径 is trailing-twelve-month (not static / dynamic / forward).
    """
    return (
        'PE<sup class="pe-tag" '
        'style="font-size:.62em;color:var(--muted);font-weight:500;'
        'margin-left:1px;letter-spacing:.02em">TTM</sup>'
    )


def _format_finance_num(value, kind: str = "default") -> str:
    """Canonical finance-number formatter for KPI cards.

    Standardizes precision per metric family so a row of KPIs is visually
    coherent (e.g. PE/PB/ROE all using 2 decimals instead of mixing 95.32 with
    0.27 and 0.01). Returns "—" for missing/invalid values.

    kinds:
      price       → 2 dp                     e.g. 8.27
      ratio       → 2 dp (PE, PB, PS)        e.g. 95.32
      pct         → 2 dp + '%' + sign        e.g. +1.23%
      pct_simple  → 2 dp + '%'  (no sign)    e.g. 13.05%
      mktcap_yi   → 1 dp + ' 亿'              e.g. 34.7 亿
      eps         → 2 dp                      e.g. 0.01
      int         → integer                   e.g. 100
      default     → up to 2 dp, trailing zero stripped
    """
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v) or math.isinf(v):
        return "—"
    if kind == "price":
        return f"{v:.2f}"
    if kind == "ratio":
        return f"{v:.2f}"
    if kind == "pct":
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.2f}%"
    if kind == "pct_simple":
        return f"{v:.2f}%"
    if kind == "mktcap_yi":
        return f"{v:.1f} 亿"
    if kind == "eps":
        return f"{v:.2f}"
    if kind == "int":
        return f"{int(round(v))}"
    # default: 2 dp, trim trailing zeros / trailing dot
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def format_confidence_pct(val) -> str:
    """Format a confidence value as 'NN%', or empty string when missing/unparseable."""
    conf = normalize_confidence_value(val)
    return "" if conf < 0 else f"{conf:.0%}"


def _html_wrap(title: str, body: str, tier_label: str, extra_css: str = "",
               extra_head: str = "", nav_html: str = "") -> str:
    """Wrap body content in a full HTML document.

    Args:
        nav_html: Optional cross-report navigation bar (from _nav_bar()).
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(title)}</title>
<style>{_BASE_CSS}{extra_css}</style>
{extra_head}
</head>
<body>
{_SHARED_SVG_DEFS}
<div class="container">
{_cross_nav_block(nav_html)}
{body}
<div class="footer">TradingAgents {tier_label} v0.2.0</div>
</div>
</body>
</html>"""


def _ticker_display(view) -> str:
    """Return 'TICKER NAME' if name is available, else just 'TICKER'."""
    name = getattr(view, "ticker_name", "")
    if name:
        return f"{view.ticker} {name}"
    return view.ticker


def _status_light(ok: bool, label: str) -> str:
    cls = "light-green" if ok else "light-red"
    return f'<span class="light {cls}"></span>{label}'


def _strip_preamble(text: str) -> str:
    """Remove common LLM self-introduction preambles from excerpt text."""
    from .decision_labels import INTERNAL_TOKEN_PREFIXES
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(p) for p in INTERNAL_TOKEN_PREFIXES):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


_SVG_ICONS = {
    "chart": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="18" width="5" height="10" rx="1"/>'
        '<rect x="13.5" y="10" width="5" height="18" rx="1"/>'
        '<rect x="23" y="4" width="5" height="24" rx="1"/></svg>'
    ),
    "lightning": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 2L6 18h8l-2 12 12-16h-8z"/></svg>'
    ),
    "swords": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 6l20 20M26 6L6 26"/>'
        '<circle cx="6" cy="6" r="2"/><circle cx="26" cy="6" r="2"/>'
        '<circle cx="6" cy="26" r="2"/><circle cx="26" cy="26" r="2"/></svg>'
    ),
    "magnifier": (
        '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5"'
        ' stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="14" cy="14" r="9"/><path d="M21 21l7 7"/></svg>'
    ),
}
_ICON_MAP = {"📊": "chart", "⚡": "lightning", "⚔️": "swords", "🔍": "magnifier"}


def _svg_icon(name: str, size: int = 32) -> str:
    """Return inline SVG icon by name. Returns empty string for unknown names."""
    svg = _SVG_ICONS.get(name, "")
    if not svg:
        return ""
    return svg.replace('viewBox=', f'width="{size}" height="{size}" viewBox=', 1)


def _empty_state(icon: str, title: str, hint: str = "") -> str:
    """Render a polished empty-state placeholder.

    If *icon* matches a known emoji (📊⚡⚔️🔍), renders an SVG icon
    with pulse animation instead. Unknown icons render as-is.
    """
    hint_html = f'<div class="empty-state-hint">{_esc(hint)}</div>' if hint else ""
    svg_name = _ICON_MAP.get(icon)
    if svg_name:
        icon_html = f'<div class="empty-state-icon empty-state-icon--svg" title="{_esc(icon)}">{_svg_icon(svg_name, 48)}</div>'
    else:
        icon_html = f'<div class="empty-state-icon">{icon}</div>'
    return (f'<div class="empty-state">'
            f'{icon_html}'
            f'<div class="empty-state-title">{_esc(title)}</div>'
            f'{hint_html}</div>')


def _format_price_zone(zone: list) -> str:
    """Format price zone safely — handles both float and string values."""
    if len(zone) < 2:
        return "\u2014"
    try:
        return f"{float(zone[0]):.2f} - {float(zone[1]):.2f}"
    except (ValueError, TypeError):
        return f"{_esc(str(zone[0]))} - {_esc(str(zone[1]))}"


def _evidence_strength_label(level: str) -> str:
    return EVIDENCE_STRENGTH_LABELS.get(level, level)


def _degraded_banner(reasons: list, audit_link: str = "") -> str:
    """Render a degraded mode warning banner."""
    items = "".join(f"<li>{_esc(r)}</li>" for r in reasons)
    audit_btn = f'<a href="{audit_link}" style="display:inline-block;margin-top:.75rem;padding:6px 16px;background:var(--yellow);color:var(--bg);border-radius:4px;text-decoration:none;font-weight:600;">查看审计详情</a>' if audit_link else ""
    return f"""
    <div class="card" style="border:2px solid var(--yellow); background:#1c1208;">
      <div style="font-size:1.1rem; font-weight:700; color:var(--yellow); margin-bottom:.5rem;">
        输出质量退化
      </div>
      <div style="color:var(--fg); margin-bottom:.5rem;">
        本次研究输出存在结构化退化，以下内容仅供快速参考，建议优先查看审计页。
      </div>
      <ul style="color:var(--muted); margin-bottom:.5rem;">{items}</ul>
      {audit_btn}
    </div>"""


def _bull_bear_bar(bull, bear) -> str:
    """Render bull-vs-bear strength bar.

    Accepts either int (raw claim count) or float (confidence-weighted sum).
    Float inputs render with one decimal so "看多 12.4 / 看空 14.7" reads
    naturally; int inputs render plain. Total of zero returns empty string.
    """
    try:
        bull_v = float(bull or 0)
        bear_v = float(bear or 0)
    except (TypeError, ValueError):
        bull_v = bear_v = 0.0
    total = bull_v + bear_v
    if total <= 0:
        return ""
    bp = int(bull_v / total * 100)
    is_float = isinstance(bull, float) or isinstance(bear, float)
    bull_lbl = f"{bull_v:.1f}" if is_float else f"{int(bull_v)}"
    bear_lbl = f"{bear_v:.1f}" if is_float else f"{int(bear_v)}"
    return f"""
    <div class="bb-label"><span>看多 ({bull_lbl})</span><span>看空 ({bear_lbl})</span></div>
    <div class="bb-bar">
      <div class="bb-bull" style="width:{bp}%"></div>
      <div class="bb-bear" style="width:{100-bp}%"></div>
    </div>"""


def _direction_badge(direction: str) -> str:
    """Render a small direction badge for catalysts."""
    cls_map = {"bullish": "buy", "bearish": "sell", "neutral": "hold"}
    labels = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
    badge_cls = cls_map.get(direction, "hold")
    return f'<span class="badge badge-{badge_cls}">{_esc(labels.get(direction, direction))}</span>'


def _radar_svg(pillars, action_class, size=180):
    """SVG radar chart for 4-pillar scores (0-4 scale)."""
    cx = cy = size / 2
    max_r = size * 0.38
    axes = [(-math.pi / 2 + i * math.pi / 2) for i in range(4)]  # top, right, bottom, left
    labels = ["\u6280\u672f\u9762", "\u57fa\u672c\u9762", "\u65b0\u95fb\u9762", "\u60c5\u7eea\u9762"]
    # A-share action colors: 买入=红, 卖出=绿, VETO=紫.
    color_map = {"buy": "#f87171", "hold": "#fbbf24", "sell": "#34d399", "veto": "#a78bfa"}
    fill_color = color_map.get(action_class, "#60a5fa")

    def polar(angle, r):
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    svg = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    # Grid polygons at r=max_r/4 (score 1), r=max_r/2 (score 2), r=3*max_r/4 (score 3), r=max_r (score 4)
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{polar(a, max_r * frac)[0]:.1f},{polar(a, max_r * frac)[1]:.1f}" for a in axes)
        svg.append(f'<polygon points="{pts}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>')
    # Axis lines
    for a in axes:
        ex, ey = polar(a, max_r)
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>')
    # Data polygon
    scores = []
    for i, p in enumerate(pillars[:4]):
        s = p.get("score", 0)
        scores.append(s)
    if scores:
        data_pts = " ".join(
            f"{polar(axes[i], max_r * s / 4)[0]:.1f},{polar(axes[i], max_r * s / 4)[1]:.1f}"
            for i, s in enumerate(scores)
        )
        svg.append(f'<polygon points="{data_pts}" fill="{fill_color}" fill-opacity="0.18" '
                   f'stroke="{fill_color}" stroke-width="1.5"/>')
        for i, s in enumerate(scores):
            dx, dy = polar(axes[i], max_r * s / 4)
            svg.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="3" fill="{fill_color}"/>')
    # Labels
    offsets = [(0, -12), (12, 0), (0, 14), (-12, 0)]  # top, right, bottom, left
    anchors = ["middle", "start", "middle", "end"]
    for i, lbl in enumerate(labels[:len(axes)]):
        lx, ly = polar(axes[i], max_r + 16)
        svg.append(f'<text x="{lx + offsets[i][0]:.1f}" y="{ly + offsets[i][1]:.1f}" '
                   f'text-anchor="{anchors[i]}" fill="var(--muted)" '
                   f'font-size="10" font-weight="600">{lbl}</text>')
    svg.append('</svg>')
    return "\n".join(svg)


def _pct_to_hex(pct: float) -> str:
    """Map % change to hex color for treemap.

    A-share convention: red = up, green = down.
    Pastel diverging palette with narrow clamped domain and sqrt compression.

    Design rules:
      - Domain clamped to [-3%, +3%] — beyond that gets the endpoint color
      - Non-linear (sqrt) compression — small moves are visible, large moves
        don't jump to saturated extremes
      - Warm off-white center with wide transition zone
      - Never pure red/green — stays pastel and restrained at all values

    Endpoints:
      rise max  #FDA5B5  (soft salmon pink)
      fall max  #AAD993  (muted mint green)
      neutral   #F0EAE7  (warm off-white)
    """
    CLAMP = 3.0  # narrow domain: [-3%, +3%]
    # Neutral center (warm off-white)
    nr, ng, nb = 0xF0, 0xEA, 0xE7

    # Clamp
    clamped = max(-CLAMP, min(CLAMP, pct))
    # Normalize to [-1, 1]
    t = clamped / CLAMP
    # Sqrt compression: preserves sign, softens extremes, reveals small moves
    compressed = math.copysign(math.sqrt(abs(t)), t)

    if compressed >= 0:
        # Rise: warm off-white → soft salmon pink (#FDA5B5)
        er, eg, eb = 0xFD, 0xA5, 0xB5
    else:
        # Fall: warm off-white → muted mint (#AAD993)
        er, eg, eb = 0xAA, 0xD9, 0x93
        compressed = -compressed  # make positive for interpolation

    r = int(nr + (er - nr) * compressed)
    g = int(ng + (eg - ng) * compressed)
    b = int(nb + (eb - nb) * compressed)
    return f"#{max(0,min(255,r)):02X}{max(0,min(255,g)):02X}{max(0,min(255,b)):02X}"


# ── Treemap Subsystem ────────────────────────────────────────────
# Two rendering modes share the same squarify layout:
#   1. render_svg_treemap() — Python SVG, flat single-level (recap, stock heatmap)
#   2. _TREEMAP_ENGINE_JS (market_renderer) — JS drill-down, hierarchical


def _squarify(values, x, y, w, h):
    """Squarified treemap layout algorithm.

    Args:
        values: list of (index, value) sorted desc by value
        x, y, w, h: bounding rectangle

    Returns:
        list of (index, rx, ry, rw, rh) rectangles
    """
    if not values:
        return []

    total = sum(v for _, v in values)
    if total <= 0:
        return [(idx, x, y, w / max(len(values), 1), h) for idx, _ in values]

    rects = []

    def _layout_row(row, rx, ry, rw, rh, horizontal, base_total):
        row_sum = sum(v for _, v in row)
        if row_sum <= 0:
            return
        if horizontal:
            row_h = rh * (row_sum / base_total) if base_total > 0 else rh
            cx = rx
            for idx, val in row:
                cw = rw * (val / row_sum) if row_sum > 0 else rw / max(len(row), 1)
                rects.append((idx, cx, ry, max(cw, 1), max(row_h, 1)))
                cx += cw
        else:
            row_w = rw * (row_sum / base_total) if base_total > 0 else rw
            cy = ry
            for idx, val in row:
                ch = rh * (val / row_sum) if row_sum > 0 else rh / max(len(row), 1)
                rects.append((idx, rx, cy, max(row_w, 1), max(ch, 1)))
                cy += ch

    remaining = list(values)
    cx, cy, cw, ch = x, y, w, h
    remaining_total = total

    while remaining:
        horizontal = cw < ch
        if len(remaining) <= 2:
            _layout_row(remaining, cx, cy, cw, ch, horizontal, remaining_total)
            break

        best_row = [remaining[0]]
        best_ratio = float('inf')

        for i in range(1, len(remaining)):
            test_row = remaining[:i + 1]
            row_sum = sum(v for _, v in test_row)
            if remaining_total <= 0:
                break
            frac = row_sum / remaining_total

            if horizontal:
                row_h = ch * frac
                widths = [(cw * v / row_sum) if row_sum > 0 else 1 for _, v in test_row]
                ratios = [max(ww / row_h, row_h / ww) if min(ww, row_h) > 0 else float('inf') for ww in widths]
            else:
                row_w = cw * frac
                heights = [(ch * v / row_sum) if row_sum > 0 else 1 for _, v in test_row]
                ratios = [max(row_w / hh, hh / row_w) if min(row_w, hh) > 0 else float('inf') for hh in heights]

            worst = max(ratios) if ratios else float('inf')
            if worst <= best_ratio:
                best_ratio = worst
                best_row = test_row
            else:
                break

        row_sum = sum(v for _, v in best_row)
        frac = row_sum / remaining_total if remaining_total > 0 else 1

        if horizontal:
            row_h = ch * frac
            _layout_row(best_row, cx, cy, cw, ch, True, remaining_total)
            cy += row_h
            ch -= row_h
        else:
            row_w = cw * frac
            _layout_row(best_row, cx, cy, cw, ch, False, remaining_total)
            cx += row_w
            cw -= row_w

        remaining = remaining[len(best_row):]
        remaining_total -= row_sum

    return rects


def render_svg_treemap(nodes, width=600, height=340, size_key="value",
                       color_fn=None, label_fn=None, tooltip_fn=None,
                       data_idx=True, node_cls="shm-node",
                       extra_g_attrs_fn=None, extra_rect_attrs_fn=None,
                       svg_attrs="", rect_gap=0):
    """Render a flat single-level SVG treemap from a list of node dicts.

    Args:
        nodes: list of dicts — each must have *size_key* for area sizing.
        width, height: SVG viewBox dimensions.
        size_key: dict key for the sizing value (area ∝ value).
        color_fn: ``(node) -> str`` returning a CSS color for the rect fill.
                  Defaults to ``"#3d5068"`` (neutral slate).
        label_fn: ``(node) -> (name_str, subtitle_str)`` for the two text
                  lines inside each rect.  Defaults to ``("", "")``.
        tooltip_fn: ``(node) -> str`` for the ``<title>`` hover tooltip.
                    Defaults to empty string.
        data_idx: if *True*, each ``<g>`` gets ``data-idx="{i}"`` (needed by
                  drawer click handlers).
        node_cls: CSS class on each ``<g>`` group. Default ``"shm-node"``
                  (recap/sector drawer); market heatmap uses ``"hm-node"``.
        extra_g_attrs_fn: ``(idx, node) -> str`` returning additional
                  attributes for the ``<g>`` element (e.g. ``data-ticker``).
        extra_rect_attrs_fn: ``(idx, node, fill) -> str`` returning
                  additional attributes for the ``<rect>`` element.
        svg_attrs: extra attributes string appended to the ``<svg>`` tag
                   (e.g. ``'preserveAspectRatio="xMidYMid meet"'``).
        rect_gap: pixels to subtract from each rect width/height for gaps.

    Returns:
        Complete ``<svg …>…</svg>`` string.
    """
    if not nodes:
        return ""

    # Defaults
    if color_fn is None:
        color_fn = lambda n: "#3d5068"  # noqa: E731
    if label_fn is None:
        label_fn = lambda n: ("", "")  # noqa: E731
    if tooltip_fn is None:
        tooltip_fn = lambda n: ""  # noqa: E731

    # Build indexed values for squarify
    indexed = []
    for i, n in enumerate(nodes):
        v = max(float(n.get(size_key, 1) or 0), 0.01)
        indexed.append((i, v))
    indexed.sort(key=lambda x: x[1], reverse=True)

    rects = _squarify(indexed, 0, 0, width, height)

    svg_parts = []
    for idx, rx, ry, rw, rh in rects:
        node = nodes[idx]
        fill = color_fn(node)
        name, subtitle = label_fn(node)
        tip = tooltip_fn(node)

        # Apply rect gap
        draw_w = max(rw - rect_gap, 1)
        draw_h = max(rh - rect_gap, 1)

        # Auto-size text based on rect dimensions
        font_size = min(rw / 5, rh / 3, 14)
        font_size = max(font_size, 8)

        text_el = ""
        if rw > 50 and rh > 30:
            name_esc = _esc(name) if name else ""
            sub_esc = _esc(subtitle) if subtitle else ""
            text_el = (
                f'<text x="{rx + rw / 2}" y="{ry + rh / 2 - 4}" '
                f'text-anchor="middle" fill="white" '
                f'font-size="{font_size}px" font-weight="600">'
                f'{name_esc}</text>'
            )
            if sub_esc:
                text_el += (
                    f'<text x="{rx + rw / 2}" y="{ry + rh / 2 + font_size}" '
                    f'text-anchor="middle" fill="rgba(255,255,255,.7)" '
                    f'font-size="{max(font_size - 2, 7)}px" '
                    f'font-family="monospace">'
                    f'{sub_esc}</text>'
                )

        idx_attr = f' data-idx="{idx}"' if data_idx else ""
        g_extra = ""
        if extra_g_attrs_fn is not None:
            g_extra = " " + extra_g_attrs_fn(idx, node)
        tip_el = f"<title>{_esc(tip)}</title>" if tip else ""
        rect_extra = ""
        if extra_rect_attrs_fn is not None:
            rect_extra = " " + extra_rect_attrs_fn(idx, node, fill)

        # When extra_rect_attrs_fn is provided, it supplies its own
        # stroke/stroke-width; otherwise use sensible defaults.
        if extra_rect_attrs_fn is not None:
            stroke_attrs = ""
        else:
            stroke_attrs = ' stroke="var(--bg)" stroke-width="2"'

        svg_parts.append(
            f'<g class="{node_cls}"{idx_attr}{g_extra}>'
            f'{tip_el}'
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{draw_w:.1f}" '
            f'height="{draw_h:.1f}" '
            f'fill="{fill}"{stroke_attrs} rx="3"'
            f'{rect_extra}/>'
            f'{text_el}</g>'
        )

    style_attr = f' style="max-height:{height}px"' if not svg_attrs else ""
    extra_svg = f" {svg_attrs}" if svg_attrs else ""
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto"{style_attr}{extra_svg} '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(svg_parts)}</svg>'
    )


# ── Visual enhancement utilities (added 2026-04-05) ─────────────────────


def _trend_arrow(current: float, previous: float = None,
                 threshold: float = 0.01) -> str:
    """Return a small trend arrow HTML span.

    If *previous* is given, compares current vs previous.
    Otherwise uses sign of *current* (positive=up, negative=down).
    """
    if previous is not None and previous != 0:
        ratio = (current - previous) / abs(previous)
        if ratio > threshold:
            return '<span class="trend-arrow trend-up">↑</span>'
        elif ratio < -threshold:
            return '<span class="trend-arrow trend-down">↓</span>'
        return '<span class="trend-arrow trend-neutral">→</span>'
    # No previous — use sign
    if current > threshold:
        return '<span class="trend-arrow trend-up">↑</span>'
    elif current < -threshold:
        return '<span class="trend-arrow trend-down">↓</span>'
    return '<span class="trend-arrow trend-neutral">→</span>'


def _kline_with_signals_svg(
    prices: list,
    signals: list = None,
    width: int = 600,
    height: int = 240,
    period_days: int = 0,
) -> str:
    """Render a full-width close-price line chart with high/low markers, X-axis
    date hints, and an optional signal-history strip below the chart.

    Args:
      prices: list of recent close prices (oldest → newest); typically 20-30 entries.
      signals: optional list of signal dicts {trade_date, action, confidence};
               drawn as a chip row below the chart (NOT aligned to price K-line —
               there's no shared date axis between price_history and signal log).
      width / height: SVG viewBox dimensions.
      period_days: total trading-day span of `prices` (for the X-axis caption).

    Returns "" when there's not enough data.
    """
    if not prices or len(prices) < 2:
        return ""
    n = len(prices)
    lo, hi = min(prices), max(prices)
    span = hi - lo if hi != lo else 1.0
    open_p = prices[0]
    last_p = prices[-1]
    trend = last_p - open_p

    # A-share convention: red for up, green for down
    line_color = "#f87171" if trend > 0 else ("#34d399" if trend < 0 else "#60a5fa")
    r_, g_, b_ = int(line_color[1:3], 16), int(line_color[3:5], 16), int(line_color[5:7], 16)
    fill_rgba = f"rgba({r_},{g_},{b_},0.10)"

    pad_l, pad_r = 50, 18           # left for price labels, right for spacing
    pad_t, pad_b = 28, 38           # top for header strip, bottom for X-axis
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def _x(i):
        return pad_l + i * plot_w / (n - 1)

    def _y(v):
        return pad_t + (1 - (v - lo) / span) * plot_h

    parts: list = []

    # Y-axis price ticks (5 evenly spaced)
    for k in range(5):
        v = lo + span * k / 4
        y = _y(v)
        parts.append(
            f'<line x1="{pad_l - 3}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="rgba(255,255,255,0.04)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="9.5" font-family="var(--mono)">{v:.2f}</text>'
        )

    # Polyline + gradient area
    pts = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(prices))
    poly_pts = (
        f"{_x(0):.1f},{_y(lo):.1f} "
        + pts
        + f" {_x(n - 1):.1f},{_y(lo):.1f}"
    )
    parts.append(
        f'<polygon points="{poly_pts}" fill="{fill_rgba}" stroke="none"/>'
    )
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{line_color}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # High / Low markers
    hi_idx = max(range(n), key=lambda i: prices[i])
    lo_idx = min(range(n), key=lambda i: prices[i])
    parts.append(
        f'<circle cx="{_x(hi_idx):.1f}" cy="{_y(hi):.1f}" r="3.5" fill="#fbbf24" '
        f'stroke="rgba(9,20,32,0.9)" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_x(hi_idx):.1f}" y="{_y(hi) - 7:.1f}" text-anchor="middle" '
        f'fill="#fbbf24" font-size="9" font-family="var(--mono)" font-weight="600">高 {hi:.2f}</text>'
    )
    parts.append(
        f'<circle cx="{_x(lo_idx):.1f}" cy="{_y(lo):.1f}" r="3.5" fill="#60a5fa" '
        f'stroke="rgba(9,20,32,0.9)" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{_x(lo_idx):.1f}" y="{_y(lo) + 12:.1f}" text-anchor="middle" '
        f'fill="#60a5fa" font-size="9" font-family="var(--mono)" font-weight="600">低 {lo:.2f}</text>'
    )

    # Current price marker (last)
    parts.append(
        f'<circle cx="{_x(n - 1):.1f}" cy="{_y(last_p):.1f}" r="4" fill="{line_color}" '
        f'stroke="rgba(9,20,32,0.95)" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="{_x(n - 1) - 4:.1f}" y="{_y(last_p) - 8:.1f}" text-anchor="end" '
        f'fill="{line_color}" font-size="10" font-family="var(--mono)" font-weight="700">'
        f'{last_p:.2f}</text>'
    )

    # Header strip (top): open / high / low / now + period change
    pct = (trend / open_p * 100) if open_p > 0 else 0.0
    pct_sign = "+" if pct > 0 else ""
    pct_color = "#f87171" if pct > 0 else ("#34d399" if pct < 0 else "var(--muted)")
    period_lbl = f"近 {period_days} 日" if period_days else f"近 {n} 个交易日"
    parts.append(
        f'<text x="{pad_l}" y="16" fill="var(--muted)" font-size="11" font-weight="600" '
        f'letter-spacing=".05em" text-transform="uppercase">价格走势 · {_esc(period_lbl)}</text>'
    )
    parts.append(
        f'<text x="{width - pad_r}" y="16" text-anchor="end" fill="{pct_color}" '
        f'font-size="11" font-family="var(--mono)" font-weight="700">'
        f'{open_p:.2f} → {last_p:.2f}  {pct_sign}{pct:.2f}%</text>'
    )

    # X-axis (start / end labels using positional hints, no real dates)
    x_baseline = height - pad_b + 8
    parts.append(
        f'<line x1="{pad_l}" y1="{x_baseline:.1f}" x2="{width - pad_r}" y2="{x_baseline:.1f}" '
        f'stroke="rgba(255,255,255,0.08)" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{pad_l}" y="{x_baseline + 14:.1f}" fill="var(--muted)" font-size="9.5" '
        f'font-family="var(--mono)">起点 (T-{n - 1})</text>'
    )
    parts.append(
        f'<text x="{(pad_l + width - pad_r) / 2:.1f}" y="{x_baseline + 14:.1f}" '
        f'text-anchor="middle" fill="var(--muted)" font-size="9.5" '
        f'font-family="var(--mono)">中段 (T-{n // 2})</text>'
    )
    parts.append(
        f'<text x="{width - pad_r}" y="{x_baseline + 14:.1f}" text-anchor="end" '
        f'fill="var(--muted)" font-size="9.5" font-family="var(--mono)">最新 (T)</text>'
    )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="auto" '
        f'preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="price trend with high/low markers" '
        f'style="display:block;max-width:100%">{"".join(parts)}</svg>'
    )

    # Signal-history chip row (separate, BELOW the svg — not aligned to price axis)
    signal_html = ""
    if signals:
        # Reverse so oldest → newest reads left-to-right
        sigs = list(reversed(signals))
        chips: list = []
        for s in sigs[:8]:
            act = (s.get("action") or "").upper()
            # VETO has its own (purple) class — never lump it with SELL (which is
            # now green): a vetoed signal must not read as a bearish sell.
            css = "buy" if act == "BUY" else ("veto" if act == "VETO" else ("sell" if act == "SELL" else "hold"))
            ico = "▲" if act == "BUY" else ("⊘" if act == "VETO" else ("▼" if act == "SELL" else "■"))
            d = (s.get("trade_date") or "")[-5:]   # MM-DD
            conf_pct = ""
            try:
                cv = float(s.get("confidence", 0))
                if cv > 0:
                    conf_pct = f" {cv * 100:.0f}%"
            except (TypeError, ValueError):
                pass
            chips.append(
                f'<span class="kline-sig kline-sig-{css}" '
                f'style="display:inline-flex;align-items:center;gap:.25rem;'
                f'padding:.18rem .55rem;border-radius:999px;font-family:var(--mono);'
                f'font-size:.72rem;letter-spacing:.02em;margin-right:.35rem;'
                f'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08)">'
                f'<span style="color:var(--{ "red" if css=="buy" else ("green" if css=="sell" else ("purple" if css=="veto" else "yellow")) })">{ico}</span>'
                f'<span style="color:var(--white)">{_esc(d)}</span>'
                f'<span style="color:var(--muted)">{_esc(act)}{_esc(conf_pct)}</span>'
                f'</span>'
            )
        if chips:
            signal_html = (
                f'<div class="kline-signals" style="margin-top:.6rem;'
                f'display:flex;align-items:center;flex-wrap:wrap;gap:.15rem;'
                f'padding:.45rem .55rem;border-top:1px dashed rgba(255,255,255,0.08)">'
                f'<span style="font-size:.72rem;color:var(--muted);'
                f'letter-spacing:.05em;text-transform:uppercase;margin-right:.5rem">'
                f'信号轨迹</span>'
                f'{"".join(chips)}'
                f'</div>'
            )

    return f'<div class="kline-card">{svg}{signal_html}</div>'


def _sparkline_svg(prices: list, width: int = 200, height: int = 60) -> str:
    """Render a mini sparkline SVG from a list of close prices.

    Shows polyline with gradient fill, current price dot + label.
    """
    if not prices or len(prices) < 2:
        return ""
    n = len(prices)
    lo, hi = min(prices), max(prices)
    spread = hi - lo if hi != lo else 1.0
    pad_x, pad_y = 4, 6

    def _x(i):
        return pad_x + i * (width - 2 * pad_x) / (n - 1)

    def _y(v):
        return pad_y + (1 - (v - lo) / spread) * (height - 2 * pad_y)

    pts = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(prices))
    last_x, last_y = _x(n - 1), _y(prices[-1])

    # Trend color — A-share convention: 红涨绿跌 (red up, green down).
    trend = prices[-1] - prices[0]
    color = "#f87171" if trend > 0 else "#34d399" if trend < 0 else "#60a5fa"
    fill_color = color.replace(")", ",0.15)").replace("#", "rgba(") if "#" in color else color
    # Simple hex to rgba for fill
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fill_rgba = f"rgba({r},{g},{b},0.12)"

    # Polygon for gradient fill (close the area under the line)
    poly_pts = pts + f" {_x(n-1):.1f},{height - pad_y} {_x(0):.1f},{height - pad_y}"

    # Current price label
    price_label = f"{prices[-1]:.2f}"

    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="overflow:visible">'
        f'<polygon points="{poly_pts}" fill="{fill_rgba}" stroke="none"/>'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{color}" stroke="#070e1b" stroke-width="1.5"/>'
        f'<text x="{last_x:.1f}" y="{last_y - 6:.1f}" text-anchor="middle" '
        f'font-size="9" font-family="var(--mono)" fill="{color}" font-weight="600">{price_label}</text>'
        f'</svg>'
    )


def _svg_minify(svg: str) -> str:
    """Strip redundant whitespace and newlines from inline SVG strings.

    Intended for programmatically-generated SVG where human readability of the
    source isn't needed. Reduces payload by ~15-20% for chart-heavy reports
    (recap_renderer.py consumes this for K-line / MACD / RSI panels).
    """
    if not svg:
        return ""
    import re
    # Collapse any run of whitespace to a single space
    out = re.sub(r"\s+", " ", svg)
    # Tighten around tag boundaries (safe for attributes because we already collapsed)
    out = re.sub(r"\s*(<)\s*", r"\1", out)
    out = re.sub(r"\s*(/?>)\s*", r"\1", out)
    return out.strip()


# ── V4: Visualization primitives (score_pill, priority_chip, confidence_ring, etc.) ──
# All primitives return inline HTML/SVG strings. No JS deps. A11y via role="img" + aria-label.
# Color-blind-safe: red/green are layered with icons (▲/●/○/◆/—) and patterns (url(#pat-*))
# for deuteranopia/protanopia accessibility.


def _conf_tier(conf: float) -> str:
    """Classify confidence into a tier for CSS class dispatch.

    Returns one of: "hi" (>=0.65), "md" (>=0.50), "lo" (<0.50), "na" (non-finite).
    """
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "na"
    if not math.isfinite(c):
        return "na"
    if c >= 0.65:
        return "hi"
    if c >= 0.50:
        return "md"
    return "lo"


def _score_pill(score, max_score: int = 4, label: str = "") -> str:
    """Discrete dot-array for pillar scores (default 4 dots for 0-4 scale).

    Colors use --conf-hi/md/lo tier based on fill ratio. Filled dots include
    a `●` Unicode pre-fill + box-shadow for non-color redundancy.

    Example:
        >>> _score_pill(3, 4, "技术")  # ●●●○ 技术
    """
    try:
        s = int(score) if score is not None else 0
    except (TypeError, ValueError):
        s = 0
    s = max(0, min(max_score, s))
    ratio = s / max_score if max_score > 0 else 0
    tier = "hi" if ratio >= 0.75 else "md" if ratio >= 0.5 else "lo" if ratio >= 0.25 else "na"

    dots = "".join(
        f'<span class="sp-dot{" on" if i < s else ""}" aria-hidden="true"></span>'
        for i in range(max_score)
    )
    lab_html = f'<span class="sp-lab">{_esc(label)}</span>' if label else ""
    aria = f"{label}: {s} of {max_score}" if label else f"{s} of {max_score}"
    return (
        f'<span class="score-pill conf-{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{dots}{lab_html}'
        f'</span>'
    )


_PRIO_ICONS = {"hot": "▲", "warm": "◆", "cool": "●", "mute": "—"}


def _priority_chip(level: str, text: str = "") -> str:
    """Severity chip with icon + color + label.

    Args:
        level: one of {"hot", "warm", "cool", "mute"}
        text:  display text (if empty, chip shows only the icon)
    """
    lv = level if level in _PRIO_ICONS else "mute"
    ico = _PRIO_ICONS[lv]
    body_txt = f'<span class="pc-txt">{_esc(text)}</span>' if text else ""
    aria = f"{lv} severity: {text}" if text else f"{lv} severity"
    return (
        f'<span class="prio-chip {lv}" role="img" aria-label="{_esc(aria)}">'
        f'<span class="pc-ico" aria-hidden="true">{ico}</span>{body_txt}'
        f'</span>'
    )


def _confidence_ring_svg(pct, size: int = 72, label: str = "") -> str:
    """Circular progress ring for a single 0..1 confidence value.

    Renders an SVG with stroke-dasharray progress, colored by conf tier,
    center text shows percentage. Safe on NaN / None — renders "—".
    """
    try:
        p = float(pct)
        if not math.isfinite(p):
            raise ValueError
        p = max(0.0, min(1.0, p))
    except (TypeError, ValueError):
        p = None

    stroke_w = max(4, int(size * 0.10))
    r = (size - stroke_w) / 2
    cx = cy = size / 2
    circumference = 2 * math.pi * r

    if p is None:
        pct_txt = "—"
        color = "var(--conf-na)"
        dash = f"0 {circumference:.1f}"
    else:
        tier = _conf_tier(p)
        color = f"var(--conf-{tier})"
        pct_txt = f"{int(round(p * 100))}%"
        dash = f"{circumference * p:.1f} {circumference:.1f}"

    aria = f"confidence {pct_txt}" + (f" ({label})" if label else "")
    lab_html = f'<div class="cr-lab">{_esc(label)}</div>' if label else ""

    svg = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="{_esc(aria)}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" '
        f'stroke="rgba(255,255,255,0.08)" stroke-width="{stroke_w}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke_w}" '
        f'stroke-dasharray="{dash}" stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'</svg>'
    )
    return (
        f'<div class="conf-ring" style="width:{size}px;height:{size}px">'
        f'{svg}'
        f'<div class="cr-val"><div class="cr-pct">{pct_txt}</div>{lab_html}</div>'
        f'</div>'
    )


def _ridge_bar(values: list, labels: list = None, height: int = 28) -> str:
    """Compact horizontal mini-bar strip; auto-scales to max abs.

    Positive values use --conf-hi gradient, negatives use --conf-lo.
    Labels (optional) render below bars.
    """
    if not values:
        return ""
    try:
        vals = [float(v) if v is not None else 0.0 for v in values]
    except (TypeError, ValueError):
        vals = [0.0] * len(values)
    vals = [v if math.isfinite(v) else 0.0 for v in vals]

    max_abs = max((abs(v) for v in vals), default=1.0) or 1.0
    segs = []
    for v in vals:
        ratio = abs(v) / max_abs
        h_pct = max(4, int(ratio * 100))
        cls = " neg" if v < 0 else ""
        segs.append(
            f'<div class="rb-seg{cls}" style="height:{h_pct}%" '
            f'title="{v:.2f}" aria-hidden="true"></div>'
        )

    labels_html = ""
    if labels and len(labels) == len(vals):
        lab_items = "".join(
            f'<span style="flex:1;text-align:center">{_esc(str(l))}</span>'
            for l in labels
        )
        labels_html = f'<div class="rb-labels">{lab_items}</div>'

    aria = f"distribution of {len(vals)} values, max {max_abs:.2f}"
    return (
        f'<div role="img" aria-label="{_esc(aria)}">'
        f'<div class="ridge-bar" style="height:{height}px">{"".join(segs)}</div>'
        f'{labels_html}'
        f'</div>'
    )


def _delta_arrow(from_v, to_v, unit: str = "", threshold: float = 0.001, decimals: int = 2) -> str:
    """Directional arrow showing magnitude of change.

    Returns '▲+2.3%', '▼-1.1%', or '— flat'. Safe on None.
    """
    try:
        fv = float(from_v) if from_v is not None else None
        tv = float(to_v) if to_v is not None else None
    except (TypeError, ValueError):
        return '<span class="delta-arr flat" role="img" aria-label="no delta available">—</span>'
    if fv is None or tv is None or not math.isfinite(fv) or not math.isfinite(tv):
        return '<span class="delta-arr flat" role="img" aria-label="no delta available">—</span>'

    diff = tv - fv
    if abs(diff) < threshold:
        return f'<span class="delta-arr flat" role="img" aria-label="no change">— {unit}</span>'

    sign = "+" if diff > 0 else ""
    cls = "up" if diff > 0 else "down"
    ico = "▲" if diff > 0 else "▼"
    aria = f"{'increased' if diff > 0 else 'decreased'} by {abs(diff):.{decimals}f}{unit}"
    return (
        f'<span class="delta-arr {cls}" role="img" aria-label="{_esc(aria)}">'
        f'<span aria-hidden="true">{ico}</span>{sign}{diff:.{decimals}f}{_esc(unit)}'
        f'</span>'
    )


def _heat_cell(value, vmin: float = 0.0, vmax: float = 1.0,
               scale: str = "diverging", w: int = 40, h: int = 20,
               label: str = "", pattern: str = "") -> str:
    """Single heat-map cell with optional pattern overlay for CB-safety.

    Args:
        value: numeric value to color-map
        vmin, vmax: domain bounds
        scale: "diverging" (red→neutral→green) or "sequential" (blue-cool→amber-hot)
        w, h: pixel dims
        label: text overlay (typically the value formatted)
        pattern: "" | "diag" | "dot" — adds pattern fill for CB redundancy
    """
    try:
        v = float(value)
        if not math.isfinite(v):
            raise ValueError
    except (TypeError, ValueError):
        return (
            f'<span class="v-heat-cell" style="width:{w}px;height:{h}px;'
            f'background:rgba(255,255,255,0.05)" '
            f'role="img" aria-label="no value"'
            f'{(" data-label=" + chr(34) + _esc(label) + chr(34)) if label else ""}>'
            f'</span>'
        )

    if vmax <= vmin:
        vmax = vmin + 1.0
    t = (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))

    if scale == "diverging":
        # 0 -> red, 0.5 -> neutral-ish, 1 -> green
        if t < 0.5:
            # red → neutral
            r, g, b = 248, int(113 + (143 * (t * 2))), int(113 + (160 * (t * 2)))
        else:
            # neutral → green
            k = (t - 0.5) * 2
            r, g, b = int(248 - 196 * k), int(211 + 0 * k), int(153 + 0 * k)
            g, b = 211, 153
            r = int(248 - (248 - 52) * k)
    else:  # sequential cool→hot
        r = int(96 + (245 - 96) * t)
        g = int(165 + (158 - 165) * t)
        b = int(250 + (11 - 250) * t)
    color = f"rgb({r},{g},{b})"
    pat_attr = f' data-pattern="{_esc(pattern)}"' if pattern in ("diag", "dot") else ""
    lab = label or (f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}")
    aria = f"{lab}" + (f" ({label})" if label and label != lab else "")

    return (
        f'<span class="v-heat-cell" style="width:{w}px;height:{h}px;background:{color}" '
        f'data-label="{_esc(lab)}"{pat_attr} '
        f'role="img" aria-label="{_esc(aria)}"></span>'
    )


def _conf_dots(conf, n: int = 5) -> str:
    """Dense 5-dot confidence indicator (denser than _score_pill; for claim cards).

    Dots fill based on round(conf * n), color by conf tier.
    """
    try:
        c = float(conf) if conf is not None else 0.0
        if not math.isfinite(c):
            raise ValueError
    except (TypeError, ValueError):
        c = 0.0
    c = max(0.0, min(1.0, c))
    filled = int(round(c * n))
    tier = _conf_tier(c)
    dots = "".join(
        f'<span class="cd-dot{" on" if i < filled else ""}" aria-hidden="true"></span>'
        for i in range(n)
    )
    aria = f"confidence {int(round(c * 100))}%"
    return (
        f'<span class="conf-dots" data-tier="{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{dots}'
        f'</span>'
    )


def _price_ladder_svg(
    stop_loss: float = 0.0,
    entries: list = None,
    targets: list = None,
    current: float = 0.0,
    width: int = 280,
    height: int = 220,
    side: str = "BUY",
) -> str:
    """Vertical price ladder — stop / current / entries / targets bands.

    Direction-aware (added 2026-04-30): for SELL/SHORT trades, stop sits ABOVE
    current and the red "danger zone" extends UPWARD from stop; targets sit BELOW
    current. For BUY/LONG/HOLD (and AVOID/VETO non-participation), the original
    orientation is kept (red below stop, targets above).

    Each entry/target is either a single float or a [low, high] tuple (price
    zone). Draws a labelled vertical axis with shaded zones. Gracefully
    degrades to empty string when there's no data.

    Colour-blind safety: zones are labelled with ✖ / ● / ▲ so redundant with hue.
    """
    side_upper = (side or "BUY").upper()
    # AVOID/VETO mean "do not participate" (rule #5: AVOID≠SELL) — they are NOT
    # short positions, so they must not draw a short-style red "loss zone" above
    # the current price. Only genuine SELL/SHORT flips the ladder orientation.
    is_short = side_upper in ("SELL", "SHORT")
    entries = [e for e in (entries or []) if e]
    targets = [t for t in (targets or []) if t]
    # Collect all numeric prices to determine range
    prices: list = []

    def _pair(v):
        if isinstance(v, (list, tuple)) and v:
            try:
                return float(v[0]), float(v[-1])
            except (TypeError, ValueError):
                return None
        try:
            f = float(v)
            return f, f
        except (TypeError, ValueError):
            return None

    e_pairs = [p for p in (_pair(e) for e in entries) if p]
    t_pairs = [p for p in (_pair(t) for t in targets) if p]
    if stop_loss and stop_loss > 0:
        prices.append(float(stop_loss))
    prices.extend(lo for lo, _ in e_pairs)
    prices.extend(hi for _, hi in e_pairs)
    prices.extend(lo for lo, _ in t_pairs)
    prices.extend(hi for _, hi in t_pairs)
    if current and current > 0:
        prices.append(float(current))
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 2:
        return ""

    lo, hi = min(prices), max(prices)
    pad = max((hi - lo) * 0.08, 0.01)
    lo, hi = lo - pad, hi + pad
    span = hi - lo or 1.0

    pad_top, pad_bot = 14, 14
    plot_h = height - pad_top - pad_bot
    axis_x = 62

    def _y(price: float) -> float:
        return pad_top + plot_h * (1 - (price - lo) / span)

    parts: list = []
    # Background track
    parts.append(
        f'<rect x="{axis_x - 1}" y="{pad_top}" width="2" height="{plot_h}" '
        f'fill="rgba(255,255,255,0.06)" rx="1"/>'
    )

    # Gridline ticks at 4 evenly spaced prices
    n_ticks = 4
    for i in range(n_ticks + 1):
        p = lo + span * i / n_ticks
        y = _y(p)
        parts.append(
            f'<line x1="{axis_x - 4}" y1="{y:.1f}" x2="{axis_x + 4}" y2="{y:.1f}" '
            f'stroke="rgba(255,255,255,0.15)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{axis_x - 8}" y="{y + 3:.1f}" text-anchor="end" '
            f'fill="var(--muted)" font-size="10" font-family="var(--mono)">{p:.2f}</text>'
        )

    def _zone(lo_p: float, hi_p: float, color: str, opacity: str = "0.22"):
        y_top = _y(hi_p)
        y_bot = _y(lo_p)
        h = max(3.0, y_bot - y_top)
        parts.append(
            f'<rect x="{axis_x + 3}" y="{y_top:.1f}" width="{width - axis_x - 8}" height="{h:.1f}" '
            f'fill="{color}" fill-opacity="{opacity}" rx="3"/>'
        )

    def _label(price_y: float, text: str, icon: str, color: str):
        parts.append(
            f'<circle cx="{axis_x}" cy="{price_y:.1f}" r="5" fill="{color}" '
            f'stroke="rgba(9,20,32,0.9)" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{axis_x + 12}" y="{price_y + 3.5:.1f}" fill="{color}" '
            f'font-size="11" font-weight="600">{_esc(icon)} {_esc(text)}</text>'
        )

    # Stop loss: red band — direction aware
    # BUY/LONG: red below stop (price drop = loss)
    # SELL/SHORT: red above stop (price rise = loss). AVOID/VETO are not short.
    if stop_loss and stop_loss > 0:
        if is_short:
            _zone(float(stop_loss), hi, "var(--red)")
        else:
            _zone(lo, float(stop_loss), "var(--red)")
        _label(_y(float(stop_loss)), f"止损 {stop_loss:.2f}", "✖", "var(--red)")

    # Entry zones: yellow bands
    for i, (e_lo, e_hi) in enumerate(e_pairs[:3], start=1):
        _zone(e_lo, e_hi, "var(--yellow)", opacity="0.28")
        mid = (e_lo + e_hi) / 2
        lbl = f"{e_lo:.2f}-{e_hi:.2f}" if e_hi != e_lo else f"{e_lo:.2f}"
        _label(_y(mid), f"买点{i} {lbl}", "●", "var(--yellow)")

    # Targets: green bands
    for i, (t_lo, t_hi) in enumerate(t_pairs[:3], start=1):
        _zone(t_lo, t_hi, "var(--green)")
        mid = (t_lo + t_hi) / 2
        lbl = f"{t_lo:.2f}-{t_hi:.2f}" if t_hi != t_lo else f"{t_lo:.2f}"
        _label(_y(mid), f"目标{i} {lbl}", "▲", "var(--green)")

    # Current-price marker (blue, drawn last so it's on top)
    if current and current > 0:
        cy = _y(float(current))
        parts.append(
            f'<line x1="{axis_x + 3}" y1="{cy:.1f}" x2="{width - 6}" y2="{cy:.1f}" '
            f'stroke="var(--blue)" stroke-width="1.5" stroke-dasharray="4 3" opacity="0.85"/>'
        )
        _label(cy, f"现价 {float(current):.2f}", "◆", "var(--blue)")

    aria = (
        f"price ladder: stop {stop_loss or 0:.2f}, "
        f"{len(e_pairs)} entry zones, {len(t_pairs)} targets"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(aria)}" '
        f'class="price-ladder">'
        + "".join(parts)
        + '</svg>'
    )


def _stacked_prob_bar(segments: list, height: int = 22) -> str:
    """Horizontal stacked probability bar. Renders labels below/inside the bar.

    Args:
        segments: list of {"label": str, "value": float (0-1 or 0-100), "color": css_color, "icon": optional}
    Returns HTML string; values auto-normalized to sum 100.
    """
    if not segments:
        return ""
    # Parse values
    parsed = []
    for s in segments:
        try:
            v = float(s.get("value", 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v <= 0:
            continue
        if v <= 1.0:
            v *= 100.0
        parsed.append({
            "label": str(s.get("label", "") or ""),
            "value": v,
            "color": s.get("color") or "var(--blue)",
            "icon": s.get("icon", ""),
        })
    if not parsed:
        return ""
    total = sum(p["value"] for p in parsed) or 1.0
    if total <= 0:
        return ""
    # Normalize
    for p in parsed:
        p["pct"] = round(p["value"] * 100 / total)

    segs_html = "".join(
        f'<div class="spb-seg" style="width:{p["pct"]}%;background:{p["color"]}" '
        f'title="{_esc(p["label"])} {p["pct"]}%">'
        f'<span class="spb-seg-label">{_esc(p["icon"])} {p["pct"]}%</span>'
        f'</div>'
        for p in parsed
    )
    legend_html = "".join(
        f'<span class="spb-legend-item">'
        f'<span class="spb-legend-swatch" style="background:{p["color"]}"></span>'
        f'<span class="spb-legend-label">{_esc(p["label"])}</span>'
        f'<span class="spb-legend-value mono">{p["pct"]}%</span>'
        f'</span>'
        for p in parsed
    )
    aria = "probability breakdown: " + ", ".join(f'{p["label"]} {p["pct"]}%' for p in parsed)
    return (
        f'<div class="stacked-prob" role="img" aria-label="{_esc(aria)}">'
        f'<div class="spb-track" style="height:{height}px">{segs_html}</div>'
        f'<div class="spb-legend">{legend_html}</div>'
        f'</div>'
    )


def _pillar_bar(score, max_score: int = 4, label: str = "") -> str:
    """4-segment progress bar for pillar scores.

    Like _score_pill but drawn as horizontal segments with gap — reads faster
    at a glance than a row of dots when the user is scanning multiple pillars.
    """
    try:
        n = int(float(score))
    except (TypeError, ValueError):
        n = 0
    n = max(0, min(n, max_score))
    tier = _conf_tier(n / max_score if max_score else 0)
    segs = "".join(
        f'<span class="pb-seg{" on" if i < n else ""}" aria-hidden="true"></span>'
        for i in range(max_score)
    )
    aria = f"{label or 'pillar'} score {n} of {max_score}"
    return (
        f'<span class="pillar-bar" data-tier="{tier}" role="img" aria-label="{_esc(aria)}">'
        f'{segs}'
        f'<span class="pb-text mono">{n}/{max_score}</span>'
        f'</span>'
    )


def _history_sparkline(
    points: list,
    width: int = 220,
    height: int = 44,
) -> str:
    """Confidence/price sparkline with color-coded action dots.

    Args:
        points: list of dicts with {"value": 0-1 float, "action": "BUY"/"SELL"/"HOLD"/"VETO",
                                     "date": "YYYY-MM-DD" (optional)}
    Returns SVG string. Empty when fewer than 2 points.
    """
    if not points or len(points) < 2:
        return ""
    vals: list = []
    for p in points:
        try:
            v = float(p.get("value", 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        vals.append(max(0.0, min(1.0, v)))

    pad = 6
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    n = len(vals)
    step = plot_w / (n - 1) if n > 1 else plot_w

    def _coord(i: int, v: float):
        return pad + i * step, pad + plot_h * (1 - v)

    pts = [_coord(i, v) for i, v in enumerate(vals)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

    # Fill under line (area sparkline)
    area_d = path_d + f" L {pts[-1][0]:.1f},{pad + plot_h:.1f} L {pts[0][0]:.1f},{pad + plot_h:.1f} Z"

    _ACTION_COLORS = {
        # A-share action colors: 买入=红, 卖出=绿, VETO=紫.
        "BUY": "var(--red)",
        "SELL": "var(--green)",
        "VETO": "var(--purple)",
        "HOLD": "var(--yellow)",
        "WAIT": "var(--yellow)",
    }
    dots_html = ""
    for i, (p, (x, y)) in enumerate(zip(points, pts)):
        action = str(p.get("action", "") or "").upper()
        color = _ACTION_COLORS.get(action, "var(--blue)")
        title = f'{p.get("date", "")} {action} {int(vals[i] * 100)}%'
        dots_html += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" '
            f'stroke="rgba(9,20,32,0.9)" stroke-width="1"><title>{_esc(title)}</title></circle>'
        )

    aria = f"signal history sparkline, {n} points, latest {int(vals[-1] * 100)}%"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(aria)}" class="hist-spark">'
        f'<path d="{area_d}" fill="var(--blue)" fill-opacity="0.12"/>'
        f'<path d="{path_d}" stroke="var(--blue)" stroke-width="1.5" fill="none" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots_html}'
        f'</svg>'
    )


def _section_divider(title: str, icon: str = "", count=None) -> str:
    """Horizontal divider with title + optional icon + optional count chip.

    Use at section boundaries in long reports.
    """
    icon_html = f'<span aria-hidden="true">{icon}</span>' if icon else ""
    count_html = f'<span class="sd-count">{count}</span>' if count is not None else ""
    aria = f"{title} section" + (f", {count} items" if count is not None else "")
    return (
        f'<div class="sec-div" role="separator" aria-label="{_esc(aria)}">'
        f'<div class="sd-line" aria-hidden="true"></div>'
        f'<div class="sd-title">{icon_html}{_esc(title)}{count_html}</div>'
        f'<div class="sd-line" aria-hidden="true"></div>'
        f'</div>'
    )


# ── (Enhanced) _empty_state with variant support ──
def _empty_state_v2(icon: str, title: str, hint: str = "", variant: str = "block") -> str:
    """Empty-state variant-aware dispatcher. Backwards-compat with _empty_state().

    variant: "block" (default) | "inline" | "error"
    """
    aria = f"{title}" + (f": {hint}" if hint else "")
    if variant == "inline":
        return (
            f'<div class="empty-state" role="status" aria-label="{_esc(aria)}" '
            f'style="padding:.5rem 1rem;flex-direction:row;gap:.6rem">'
            f'<span class="empty-state-icon" aria-hidden="true" style="font-size:1rem;margin:0">{_esc(icon)}</span>'
            f'<span class="empty-state-title">{_esc(title)}</span>'
            f'{f"<span class=\"empty-state-hint\" style=\"margin-left:.5rem\">{_esc(hint)}</span>" if hint else ""}'
            f'</div>'
        )
    if variant == "error":
        return (
            f'<div class="empty-state" role="alert" aria-label="{_esc(aria)}" '
            f'style="border:1px solid rgba(248,113,113,0.3);'
            f'background:rgba(248,113,113,0.05);border-radius:14px;color:var(--red)">'
            f'<div class="empty-state-icon" aria-hidden="true" style="color:var(--red)">{_esc(icon)}</div>'
            f'<div class="empty-state-title">{_esc(title)}</div>'
            f'{f"<div class=\"empty-state-hint\">{_esc(hint)}</div>" if hint else ""}'
            f'</div>'
        )
    return _empty_state(icon, title, hint)


def _nav_bar(ticker: str, run_id: str, current_page: str, *, artifact_dir=None, artifact_exists=None) -> str:
    """Render cross-report navigation bar.

    Links between snapshot/research/audit/committee for the same run.
    ``artifact_exists`` is a test hook for injecting artifact visibility.
    """
    if not run_id:
        return ""
    from ..report_index import safe_filename as _safe_filename
    safe_t = _safe_filename(ticker)
    short_id = run_id.replace("run-", "")[:12]

    def _artifact_exists(href: str) -> bool:
        from pathlib import Path

        if artifact_exists is not None:
            return bool(artifact_exists(href))
        if artifact_dir:
            return (Path(artifact_dir) / href).exists()
        candidates = [
            Path(href),
            Path("data/reports").joinpath(href),
        ]
        return any(path.exists() for path in candidates)

    pages = []
    try:
        if _artifact_exists("workbench.html"):
            pages.append(("workbench", "工作台", "workbench.html"))
    except Exception:
        pass
    tier_pages = [
        ("snapshot", "结论", f"{safe_t}-run-{short_id}-snapshot.html"),
        ("research", "研究", f"{safe_t}-run-{short_id}-research.html"),
        ("audit", "审计", f"{safe_t}-run-{short_id}-audit.html"),
    ]
    committee_href = f"{safe_t}-{run_id}-committee.html"
    if current_page == "committee" or _artifact_exists(committee_href):
        tier_pages.append(("committee", "辩论", committee_href))
    pages.extend(tier_pages)
    links = []
    for key, label, href in pages:
        cls = ' class="active"' if key == current_page else ""
        links.append(f'<a href="{_esc(href)}"{cls}>{label}</a>')
    return f'<nav class="cross-nav">{"".join(links)}</nav>'


def _replace_cross_nav_block(html: str, nav_html: str, *, path: str = "") -> str:
    nav_block = _cross_nav_block(nav_html)
    new_html, count = _CROSS_NAV_BLOCK_RE.subn(nav_block, html, count=1)
    if count:
        return new_html
    new_html, count = _LEGACY_CROSS_NAV_RE.subn(nav_block, html, count=1)
    if count:
        logger.info("cross-nav legacy block upgraded in %s", path or "<html>")
        return new_html
    new_html, count = _CONTAINER_OPEN_RE.subn(lambda m: m.group(1) + nav_block + "\n", html, count=1)
    if count:
        logger.warning("cross-nav sentinel missing; inserted nav block into %s", path or "<html>")
        return new_html
    logger.warning("cross-nav refresh skipped; no nav anchor found in %s", path or "<html>")
    return html


def _atomic_write_text(path, text: str) -> None:
    from pathlib import Path

    p = Path(path)
    mode = _replacement_file_mode(p)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            logger.debug("failed to remove temporary file %s after atomic write failure", tmp, exc_info=True)
        raise


def _replacement_file_mode(path) -> int:
    """Preserve an existing file's permissions; otherwise use normal text defaults."""
    from pathlib import Path
    import stat

    p = Path(path)
    try:
        return stat.S_IMODE(p.stat().st_mode)
    except OSError:
        current = os.umask(0)
        os.umask(current)
        return 0o666 & ~current


def refresh_report_nav(ticker: str, run_id: str, artifact_dir) -> list[str]:
    """Refresh cross-report nav in already-written run-scoped HTML files."""
    if not run_id or not artifact_dir:
        return []
    from pathlib import Path
    from ..report_index import safe_filename as _safe_filename

    out = Path(artifact_dir)
    safe_t = _safe_filename(ticker)
    short_id = run_id.replace("run-", "")[:12]
    targets = {
        "snapshot": out / f"{safe_t}-run-{short_id}-snapshot.html",
        "research": out / f"{safe_t}-run-{short_id}-research.html",
        "audit": out / f"{safe_t}-run-{short_id}-audit.html",
    }
    updated: list[str] = []
    for page, path in targets.items():
        if not path.exists():
            continue
        try:
            html = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            logger.warning("cross-nav refresh read failed for %s", path, exc_info=True)
            continue
        nav = _nav_bar(ticker, run_id, page, artifact_dir=out)
        new_html = _replace_cross_nav_block(html, nav, path=str(path))
        if new_html == html:
            continue
        try:
            _atomic_write_text(path, new_html)
        except Exception:
            logger.warning("cross-nav refresh write failed for %s", path, exc_info=True)
            continue
        updated.append(str(path))
    return updated
