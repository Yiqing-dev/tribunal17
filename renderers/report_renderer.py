"""
Three-tier HTML report renderer.

Same evidence chain, three compression levels:
- Tier 1 (Snapshot): Conclusion + signals + risk — single screen
- Tier 2 (Research): Bull/bear + evidence + scenarios + thesis — 3-6 pages
- Tier 3 (Audit):    Evidence chains + replay + parser + compliance — deep dive

All renderers consume view models from views.py, never raw traces.
All user-facing text is in Chinese (A-share product).
"""

import copy
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .views import (
    SnapshotView, ResearchView, AuditView, DivergencePoolView,
    StockDivergenceRow, MarketView, _strip_internal_tokens,
)
from .decision_labels import (
    get_action_label, get_action_class, get_action_explanation,
    get_soft_action_label,
    get_thesis_label, get_risk_label, get_node_label, get_dimension_label,
    get_signal_emoji, PILLAR_EMOJI,
    EVIDENCE_STRENGTH_LABELS, SEVERITY_LABELS, SEVERITY_CSS,
    NODE_STATUS_LABELS, PARSE_STATUS_LABELS, COMPLIANCE_STATUS_LABELS,
    FRESHNESS_STATUS_LABELS, NO_COMPLIANCE_LABEL,
    get_regime_label, get_regime_class, get_breadth_label, get_breadth_class,
    safe_badge_class, get_severity_label,
)
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM, _BRAND_LOGO_LG
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light, _strip_preamble,
    _empty_state, _format_price_zone, _evidence_strength_label,
    _degraded_banner, _bull_bear_bar, _direction_badge, _radar_svg,
    _pct_to_hex, _squarify,
)


# ── Feature 2: Checklist + Risk Debate Summary ──────────────────────────


def _render_checklist(view: SnapshotView) -> str:
    """Render pillar score checklist card."""
    if not view.pillar_checklist:
        return ""
    items = ""
    for p in view.pillar_checklist:
        emoji = _esc(p.get("emoji", ""))
        pillar = _esc(p.get("pillar", ""))
        score = p.get("score", 0)
        label = _esc(p.get("label", ""))
        items += (
            f'<div class="ck-item">'
            f'<span class="ck-emoji">{emoji}</span>'
            f'<span class="ck-pillar">{pillar}</span>'
            f'<span class="ck-label">{label}</span>'
            f'<span class="ck-score num">{score}/4</span>'
            f'</div>'
        )
    radar = _radar_svg(view.pillar_checklist, view.action_class)
    return f"""
    <div class="card">
      <h3>\u5206\u6790\u7ef4\u5ea6\u6838\u67e5</h3>
      <div style="display:flex;gap:1.2rem;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:200px"><div class="checklist">{items}</div></div>
        <div style="flex-shrink:0">{radar}</div>
      </div>
    </div>"""


def _render_risk_debate_summary(view: SnapshotView) -> str:
    """Render 3-column risk debate summary card."""
    if not view.risk_debate_summary:
        return ""
    cols = ""
    for rd in view.risk_debate_summary:
        stance = _esc(rd.get("stance", ""))
        rec = rd.get("recommendation", "").upper()
        rec_class = "buy" if rec == "BUY" else ("sell" if rec in ("SELL", "VETO") else "hold")
        rec_label = _esc(rec or "\u2014")
        pos_raw = rd.get("position_pct", "")
        pos = _esc(f"{pos_raw}%" if isinstance(pos_raw, (int, float)) else (str(pos_raw) or "\u2014"))
        risk = _esc(str(rd.get("key_risk", "") or "\u2014"))
        cols += (
            f'<div class="rd-col">'
            f'<div class="rd-stance">{stance}\u6d3e</div>'
            f'<div class="rd-rec badge badge-{rec_class}">{rec_label}</div>'
            f'<div class="rd-pos">\u4ed3\u4f4d {pos}</div>'
            f'<div class="rd-risk">\u6838\u5fc3\u98ce\u9669: {risk}</div>'
            f'</div>'
        )
    return f"""
    <div class="card">
      <h3>\u98ce\u63a7\u59d4\u5458\u4f1a</h3>
      <div class="risk-debate-row">{cols}</div>
    </div>"""


# ── Feature 3: Battle Plan Card ──────────────────────────────────────────

def _render_battle_plan(view: SnapshotView) -> str:
    """Render battle plan card from tradecard + trade_plan data."""
    tc = view.tradecard
    tp = view.trade_plan
    if not tc and not tp:
        return ""

    side = (tc.get("side") or tc.get("action") or tp.get("bias", "")).upper()
    confidence = tc.get("confidence", tp.get("confidence", 0))
    if isinstance(confidence, str):
        _CONF_MAP = {"high": 0.8, "med": 0.5, "medium": 0.5, "low": 0.2,
                     "高": 0.8, "中": 0.5, "低": 0.2}
        mapped = _CONF_MAP.get(confidence.strip().lower())
        if mapped is not None:
            confidence = mapped
        else:
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = 0
    rationale = tc.get("rationale", "")
    risk_score = tc.get("risk_score", 0)
    if isinstance(risk_score, str):
        try:
            risk_score = float(risk_score)
        except (ValueError, TypeError):
            risk_score = 0

    # Determine border color class
    plan_class = "sell-plan" if side in ("SHORT", "SELL", "AVOID", "VETO") else (
        "hold-plan" if side in ("WAIT", "HOLD") else ""
    )
    emoji = get_signal_emoji(
        "VETO" if side == "VETO" else (
        "SELL" if side in ("SHORT", "SELL", "AVOID") else (
        "HOLD" if side in ("WAIT", "HOLD") else "BUY"
    )))

    side_label = {"LONG": "\u505a\u591a", "SHORT": "\u505a\u7a7a", "WAIT": "\u7b49\u5f85",
                  "BUY": "\u505a\u591a", "SELL": "\u505a\u7a7a", "AVOID": "\u56de\u907f",
                  "HOLD": "\u7b49\u5f85", "VETO": "\u5426\u51b3"}.get(side, side)
    if confidence >= 0:
        conf_cls = "buy" if confidence >= 0.7 else ("hold" if confidence >= 0.4 else "sell")
        conf_badge = f'<span class="badge badge-{conf_cls}">\u7f6e\u4fe1\u5ea6 {confidence:.0%}</span>'
    else:
        conf_badge = '<span class="badge">\u7f6e\u4fe1\u5ea6 \u2014</span>'

    header = (
        f'<div class="bp-header">'
        f'<span class="bp-side">{emoji} {_esc(side_label)}</span>'
        f'{conf_badge}'
        f'</div>'
    )

    rationale_html = f'<div class="bp-rationale">{_esc(_strip_internal_tokens(rationale[:150]))}</div>' if rationale else ""

    # Entry setups table
    setups = tp.get("entry_setups", [])
    if not isinstance(setups, list):
        setups = []
    setup_html = ""
    if setups:
        rows = ""
        for s in setups[:3]:
            if not isinstance(s, dict):
                continue
            label = _esc(s.get("label", s.get("type", "")))
            zone = s.get("price_zone", [])
            if not isinstance(zone, list):
                zone = []
            zone_str = _format_price_zone(zone) if len(zone) >= 2 else "\u2014"
            condition = _esc(s.get("condition", ""))
            rows += f"<tr><td>{label}</td><td class='mono num'>{zone_str}</td><td>{condition}</td></tr>"
        setup_html = f"""
        <div class="tp-section-title">\u4e70\u5165\u8bbe\u7f6e</div>
        <table class="tp-table">
          <thead><tr><th>\u7c7b\u578b</th><th>\u4ef7\u683c\u533a\u95f4</th><th>\u89e6\u53d1\u6761\u4ef6</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # Stop loss (may be dict or scalar)
    stop_raw = tp.get("stop_loss") or {}
    if isinstance(stop_raw, (int, float)):
        stop = {"price": float(stop_raw)}
    elif isinstance(stop_raw, dict):
        stop = stop_raw
    else:
        stop = {}
    sl_html = ""
    sl_price = stop.get("price", 0) or 0
    try:
        sl_price = float(sl_price)
    except (ValueError, TypeError):
        sl_price = 0
    if sl_price > 0:
        sl_html = f'<div class="tp-row tp-stop"><span class="tp-label">\u6b62\u635f\u4f4d</span><span class="mono num" style="color:var(--red)">{sl_price:.2f}</span></div>'

    # Take profit (may be list of dicts, list of strings, float, or scalar)
    targets_raw = tp.get("take_profit", [])
    if isinstance(targets_raw, (int, float)):
        targets_raw = [{"label": "目标", "price_zone": [targets_raw]}]
    elif not isinstance(targets_raw, list):
        targets_raw = []
    tp_html = ""
    for t in targets_raw[:2]:
        if isinstance(t, dict):
            t_zone = t.get("price_zone", [])
            t_str = _format_price_zone(t_zone) if len(t_zone) >= 2 else "\u2014"
            t_label = _esc(t.get("label", ""))
        elif isinstance(t, (int, float)):
            t_str = f"{float(t):.2f}"
            t_label = ""
        elif isinstance(t, str):
            t_str = _esc(t)
            t_label = ""
        else:
            continue
        tp_html += f'<div class="tp-row tp-target"><span class="tp-label">{t_label}</span><span class="mono num" style="color:var(--green)">{t_str}</span></div>'

    # Invalidation
    invalidators_raw = tp.get("invalidators", [])
    invalidators = invalidators_raw if isinstance(invalidators_raw, list) else []
    inval_html = ""
    if invalidators:
        items = "".join(f"<li>{_esc(str(inv))}</li>" for inv in invalidators[:4])
        inval_html = f'<div style="margin-top:.5rem"><div class="tp-section-title" style="color:var(--red)">\u5931\u6548\u6761\u4ef6</div><ul class="tp-inval-list">{items}</ul></div>'

    # Risk gauge
    gauge_html = ""
    if risk_score > 0:
        gauge_pct = min(int(risk_score * 10), 100)
        gauge_color = "var(--red)" if risk_score >= 7 else ("var(--yellow)" if risk_score >= 4 else "var(--green)")
        gauge_html = f"""
        <div style="margin-top:.5rem;">
          <div style="font-size:.8rem;color:var(--muted)">\u98ce\u9669\u8bc4\u5206 {risk_score}/10</div>
          <div class="bp-gauge"><div class="bp-gauge-fill" style="width:{gauge_pct}%;background:{gauge_color}"></div></div>
        </div>"""

    return f"""
    <div class="card battle-plan {plan_class}">
      <h3>AI \u4f5c\u6218\u8ba1\u5212</h3>
      {header}
      {rationale_html}
      {setup_html}
      {sl_html}
      {tp_html}
      {inval_html}
      {gauge_html}
    </div>"""


# ── Feature 5: Signal History ────────────────────────────────────────────

def _render_signal_history(view: SnapshotView) -> str:
    """Render compact historical signal table."""
    if not view.signal_history:
        return ""
    rows = ""
    for sh in view.signal_history[:5]:
        date = _esc(sh.get("trade_date", ""))
        act = sh.get("action", "")
        emoji = get_signal_emoji(act)
        act_label = _esc(get_action_label(act))
        rows += f"<tr><td>{date}</td><td>{emoji} {act_label}</td></tr>"

    return f"""
    <div class="card">
      <h3>\u5386\u53f2\u4fe1\u53f7</h3>
      <table class="sig-hist-table">
        <tbody>{rows}</tbody>
      </table>
    </div>"""


# ── Tier 1: Snapshot ─────────────────────────────────────────────────────

def render_snapshot(view: SnapshotView, skip_vendors: bool = False) -> str:
    """Render Tier 1 Snapshot — single screen, conclusion-first, zero LLM leakage.

    When is_degraded=True, shows a minimal degraded layout with a warning
    banner and only the essential conclusion + risks, directing the user
    to the audit page.
    """
    color_var = 'green' if view.action_class == 'buy' else ('red' if view.action_class in ('sell', 'veto') else 'yellow')

    # ── Degraded Mode: minimal content + audit redirect ──
    if view.is_degraded:
        _sig_emoji_d = get_signal_emoji(view.research_action)
        conclusion = f"""
    <div class="hero">
      <div style="text-align:center;position:relative;z-index:1;">
        <div class="eyebrow">输出质量退化 &middot; 快速参考</div>
        <div class="hero-action" style="color:var(--{color_var});">
          {_sig_emoji_d} {_esc(view.action_label)}
        </div>
        <div style="margin-top:.5rem;color:var(--muted);font-family:var(--mono);">置信度 {f'{view.confidence:.0%}' if view.confidence >= 0 else '—'}</div>
        <div class="hero-summary" style="margin:.75rem auto 0;text-align:center;">{_esc(view.one_line_summary)}</div>
      </div>
    </div>"""

        # Only show risks in degraded mode
        risks_html = ""
        if view.main_risks:
            items = ""
            for r in view.main_risks:
                if isinstance(r, dict):
                    sev_cls = safe_badge_class(r.get("severity_class", ""))
                    cat = get_risk_label(r.get("category", ""))
                    desc = r.get("description", "")
                    sev = get_severity_label(r.get("severity", ""))
                    sev_badge = f'<span class="badge badge-{sev_cls}">{_esc(sev)}</span> ' if sev else ""
                    text = f"{sev_badge}{_esc(cat)}"
                    if desc:
                        text += f" — {_esc(_strip_internal_tokens(desc[:80]))}"
                    items += f"<li>{text}</li>"
            if items:
                risks_html = f'<div class="card"><h3>主要风险</h3><ul>{items}</ul></div>'

        # Metrics fallback card (independent of parse quality)
        degraded_chart = ""
        if view.metrics_fallback:
            fb = view.metrics_fallback
            kpis = []
            for key, label in [("pe", "PE(TTM)"), ("pb", "PB"), ("roe", "ROE(%)"),
                                ("gross_margin", "毛利率(%)"), ("market_cap", "总市值(亿)"),
                                ("eps", "EPS"), ("net_profit", "净利润")]:
                val = fb.get(key)
                if val is not None:
                    kpis.append(f'<div class="kpi"><span class="kpi-val">{_esc(str(val))}</span><span class="kpi-label">{_esc(label)}</span></div>')
            if kpis:
                degraded_chart = f'<div class="card"><h3>基本面速览</h3><div class="kpi-row">{"".join(kpis)}</div></div>'

        body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 研究快照</p>
    <div class="banner">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。使用前请结合人工判断。</div>
    {_degraded_banner(view.degradation_reasons)}
    {conclusion}
    {degraded_chart}
    {risks_html}"""

        return _html_wrap(f"{_ticker_display(view)} 研究快照 — {view.trade_date}", body, "研究快照", extra_head=_COUNTUP_JS)

    # ── Normal Mode ──
    _sig_emoji = get_signal_emoji(view.research_action)
    conf_pct = int(view.confidence * 100)

    # Build right-side KPI mini-panels for hero
    hero_kpis = []
    if view.confidence >= 0:
        conf_cls = "buy" if view.confidence >= 0.7 else ("hold" if view.confidence >= 0.4 else "sell")
        _conf_note = "\u2248" if getattr(view, "confidence_defaulted", False) else ""
        _conf_sub = ' <span style="font-size:.6rem;color:var(--muted);">(\u9ed8\u8ba4)</span>' if getattr(view, "confidence_defaulted", False) else ""
        hero_kpis.append(f'<div class="kpi kpi-primary {conf_cls}"><span class="kpi-val">{_conf_note}{conf_pct}%</span><span class="kpi-label">\u7f6e\u4fe1\u5ea6{_conf_sub}</span></div>')
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val">{view.total_evidence}</span><span class="kpi-label">证据条数</span></div>')
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val">{view.attributed_rate:.0%}</span><span class="kpi-label">绑定率</span></div>')
    ev_label = _evidence_strength_label(view.evidence_strength)
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val" style="font-size:1.2rem">{_esc(ev_label)}</span><span class="kpi-label">证据强度</span></div>')

    hero_kpi_grid = f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;">{"".join(hero_kpis)}</div>'

    conclusion = f"""
    <div class="hero reveal">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="eyebrow">AI 研究快照 &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.one_line_summary)}</div>
          <div style="font-size:.88rem;color:var(--muted);">{_esc(view.action_explanation)}</div>
        </div>
        <div class="hero-right">
          {hero_kpi_grid}
        </div>
      </div>
    </div>"""

    # ── Status lights bar ──
    lights = [
        _status_light(view.risk_cleared or False, "风控: 通过" if view.risk_cleared else "风控: 未通过"),
        _status_light(view.compliance_status in ("allow", ""), "合规: 通过" if view.compliance_status in ("allow", "") else "合规: " + view.compliance_status),
        _status_light(view.freshness_ok, "数据: 新鲜" if view.freshness_ok else "数据: 过期"),
        _status_light(not view.was_vetoed, "否决: 无" if not view.was_vetoed else (
            "否决: 风控门禁" if getattr(view, "veto_source", "") == "risk_gate"
            else ("否决: 研究否决" if getattr(view, "veto_source", "") == "agent_veto"
                  else "否决: 是"))),
    ]
    lights_html = f"""
    <div class="status-bar reveal reveal-d1">
      {"".join(f'<span>{l}</span>' for l in lights)}
    </div>"""

    # ── Fundamentals metrics card ──
    chart_html = ""
    if view.metrics_fallback:
        fb = view.metrics_fallback
        kpis = []
        label_map = [
            ("pe", "PE(TTM)"), ("pb", "PB"), ("roe", "ROE(%)"),
            ("gross_margin", "毛利率(%)"), ("market_cap", "总市值(亿)"),
            ("eps", "EPS"), ("net_profit", "净利润"),
        ]
        for key, label in label_map:
            val = fb.get(key)
            if val is not None:
                kpis.append(f'<div class="kpi"><span class="kpi-val">{_esc(str(val))}</span><span class="kpi-label">{_esc(label)}</span></div>')
        if kpis:
            chart_html = f'<div class="card reveal reveal-d2"><h3>基本面速览</h3><div class="kpi-row">{"".join(kpis)}</div></div>'

    # Core drivers
    drivers_html = ""
    if view.core_drivers:
        items = "".join(f"<li>{_esc(d[:120])}</li>" for d in view.core_drivers)
        drivers_html = f'<div class="card reveal reveal-d3"><h3>核心驱动</h3><ul>{items}</ul></div>'

    # Main risks
    risks_html = ""
    if view.main_risks:
        items = ""
        for r in view.main_risks:
            if isinstance(r, dict):
                sev_cls = safe_badge_class(r.get("severity_class", ""))
                cat = get_risk_label(r.get("category", ""))
                desc = r.get("description", "")
                sev = get_severity_label(r.get("severity", ""))
                sev_badge = f'<span class="badge badge-{sev_cls}">{_esc(sev)}</span> ' if sev else ""
                text = f"{sev_badge}{_esc(cat)}"
                if desc:
                    text += f" — {_esc(_strip_internal_tokens(desc[:80]))}"
                items += f"<li>{text}</li>"
            else:
                items += f"<li>{_esc(str(r))}</li>"
        risks_html = f'<div class="card reveal reveal-d3"><h3>主要风险</h3><ul>{items}</ul></div>'

    # Evidence strength + Bull/Bear bar
    evidence_html = f"""
    <div class="card reveal reveal-d4">
      <h3>证据强度</h3>
      <div style="display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;margin-bottom:.5rem;">
        <span class="badge badge-{view.evidence_strength_class}">{_esc(ev_label)}</span>
        <span style="font-size:.85rem;color:var(--muted);">{view.total_evidence} 条证据 &middot; {view.attributed_rate:.0%} 论据-证据绑定率</span>
      </div>
      {_bull_bear_bar(view.bull_strength, view.bear_strength)}
    </div>"""

    # Catalysts
    catalyst_html = ""
    if view.catalysts:
        items = ""
        for c in view.catalysts:
            if isinstance(c, dict):
                date_str = f'[{_esc(c.get("date", ""))}] ' if c.get("date") else ""
                dir_badge = f' {_direction_badge(c.get("direction", ""))}' if c.get("direction") else ""
                items += f"<li>{date_str}{_esc(_strip_internal_tokens(c.get('event', '')))}{dir_badge}</li>"
            else:
                items += f"<li>{_esc(_strip_internal_tokens(str(c)))}</li>"
        catalyst_html = f'<div class="card reveal reveal-d5"><h3>近期催化剂</h3><ul>{items}</ul></div>'

    # ── Feature cards ──
    battle_plan_html = _render_battle_plan(view)
    checklist_html = _render_checklist(view)
    risk_debate_html = _render_risk_debate_summary(view)
    signal_history_html = _render_signal_history(view)

    # Wrap supporting sections for mobile collapse
    def _mc(summary_label: str, content: str) -> str:
        if not content or not content.strip():
            return ""
        return f'<details class="mobile-collapse" open><summary>{_esc(summary_label)}</summary>{content}</details>'

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 研究快照</p>
    <div class="banner">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。使用前请结合人工判断。</div>
    {conclusion}
    {lights_html}
    {battle_plan_html}
    {_mc("基本面速览", chart_html)}
    {_mc("核心驱动 / 风险", f'<div class="cols"><div>{drivers_html}</div><div>{risks_html}</div></div>')}
    {_mc("证据强度", evidence_html)}
    {_mc("信号核验", checklist_html)}
    {_mc("风控辩论", risk_debate_html)}
    {_mc("催化剂", catalyst_html)}
    {_mc("信号历史", signal_history_html)}"""

    return _html_wrap(f"{_ticker_display(view)} 研究快照 — {view.trade_date}", body, "研究快照")


# ── Tier 2: Research Report ──────────────────────────────────────────────

def _render_research_degraded(view: ResearchView) -> str:
    """Render degraded Tier 2 — warning banner + synthesis + risk only."""
    color_var = 'green' if view.action_class == 'buy' else ('red' if view.action_class in ('sell', 'veto') else 'yellow')

    _sig_emoji_rd = get_signal_emoji(view.research_action)
    exec_summary = f"""
    <div class="hero">
      <div style="text-align:center;position:relative;z-index:1;">
        <div class="eyebrow">输出质量退化 &middot; 深度研究</div>
        <div class="hero-action" style="color:var(--{color_var});">
          {_sig_emoji_rd} {_esc(view.action_label)}
        </div>
        <div style="margin-top:.5rem;color:var(--muted);font-family:var(--mono);">
          置信度 {f'{view.confidence:.0%}' if view.confidence >= 0 else '—'} &middot;
          风险评分 {view.risk_score if view.risk_score is not None else '无'}/10
        </div>
      </div>
    </div>"""

    # Only show synthesis if available
    synth_html = ""
    if view.synthesis_excerpt:
        clean_excerpt = _strip_preamble(_strip_internal_tokens(view.synthesis_excerpt[:300]))
        synth_html = f"""
    <div class="card">
      <h3>综合研判</h3>
      <div style="font-size:.95rem;">{_esc(clean_excerpt)}</div>
    </div>"""

    # Risk summary (kept brief)
    risk_html = ""
    if view.risk_flag_count > 0 or view.risk_flags_detail:
        risk_content = ""
        if view.risk_flags_detail:
            items = "".join(
                f"<li>{_esc(f.get('category', ''))} — {_esc(_strip_internal_tokens(f.get('description', '')[:100]))}</li>"
                for f in view.risk_flags_detail
            )
            risk_content = f"<ul>{items}</ul>"
        else:
            risk_content = f"<div>{view.risk_flag_count} 项风险标记</div>"
        risk_html = f"""
    <div class="card">
      <h3>风险评估</h3>
      <div style="margin-bottom:.5rem;">
        评分: <strong>{view.risk_score if view.risk_score is not None else '无'}</strong>/10 &middot;
        风控通过: <span class="badge badge-{'ok' if view.risk_cleared else 'warn'}">
        {'是' if view.risk_cleared else '否'}</span>
      </div>
      {risk_content}
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 深度研究报告</p>
    <div class="banner">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。使用前请结合人工判断。</div>
    {_degraded_banner(view.degradation_reasons)}
    {exec_summary}
    {synth_html}
    {risk_html}"""

    return _html_wrap(f"{_ticker_display(view)} 深度研究 — {view.trade_date}", body, "深度研究报告", extra_head=_COUNTUP_JS)


def _render_trade_plan_card(tp: dict) -> str:
    """Render the AI Trade Plan card — public entry/exit framework.

    Shows 6 key lines: bias, breakout entry, pullback entry, stop loss,
    targets, and invalidation conditions.
    """
    bias = tp.get("bias", "WAIT")
    bias_labels = {"LONG": ("偏多", "buy"), "WAIT": ("等待", "hold"), "AVOID": ("回避", "sell")}
    bias_label, bias_class = bias_labels.get(bias, ("等待", "hold"))

    setups = tp.get("entry_setups", [])
    stop_raw_tp = tp.get("stop_loss") or {}
    if isinstance(stop_raw_tp, (int, float)):
        stop = {"price": float(stop_raw_tp)}
    elif isinstance(stop_raw_tp, dict):
        stop = stop_raw_tp
    else:
        stop = {}
    targets = tp.get("take_profit", [])
    invalidators = tp.get("invalidators", [])
    horizon = tp.get("holding_horizon", "")
    confidence = tp.get("confidence", 0)

    horizon_labels = {"short_swing": "短线波段", "medium_term": "中期持有"}
    horizon_label = horizon_labels.get(horizon, horizon)

    # Build entry setups rows
    if not isinstance(setups, list):
        setups = []
    setup_rows = ""
    for s in setups[:3]:
        if not isinstance(s, dict):
            continue
        label = _esc(s.get("label", s.get("type", "")))
        zone = s.get("price_zone", [])
        if not isinstance(zone, list):
            zone = []
        zone_str = _format_price_zone(zone) if len(zone) >= 2 else "—"
        condition = _esc(s.get("condition", ""))
        strength = s.get("strength", "medium")
        strength_colors = {"high": "var(--green)", "medium": "var(--yellow)", "low": "var(--muted)"}
        s_color = strength_colors.get(strength, "var(--muted)")
        setup_rows += f"""
        <tr>
          <td><span style="color:{s_color};font-weight:600">{label}</span></td>
          <td class="mono num">{zone_str}</td>
          <td>{condition}</td>
        </tr>"""

    # Stop loss row
    sl_price = stop.get("price", 0) or 0
    try:
        sl_price = float(sl_price)
    except (ValueError, TypeError):
        sl_price = 0
    sl_rule = _esc(stop.get("rule", ""))
    sl_max_pct = stop.get("max_loss_pct", 0) or 0
    try:
        sl_max_pct = float(sl_max_pct)
    except (ValueError, TypeError):
        sl_max_pct = 0
    sl_html = ""
    if sl_price > 0:
        pct_badge = f' <span class="mono" style="color:var(--red);font-size:.85em">(最大亏损 {sl_max_pct:.0%})</span>' if sl_max_pct > 0 else ""
        sl_html = f"""
        <div class="tp-row tp-stop">
          <span class="tp-label">止损位</span>
          <span class="mono num" style="color:var(--red)">{sl_price:.2f}</span>{pct_badge}
          <span class="tp-detail">{sl_rule}</span>
        </div>"""

    # Target rows (targets may be list of dicts, float, or string)
    if isinstance(targets, (int, float)):
        targets = [{"label": "目标", "price_zone": [targets]}]
    elif not isinstance(targets, list):
        targets = []
    target_rows = ""
    for t in targets[:3]:
        if isinstance(t, dict):
            t_label = _esc(t.get("label", ""))
            t_zone = t.get("price_zone", [])
            t_str = _format_price_zone(t_zone) if len(t_zone) >= 2 else "—"
        elif isinstance(t, (int, float)):
            t_label = ""
            t_str = f"{float(t):.2f}"
        elif isinstance(t, str):
            t_label = ""
            t_str = _esc(t)
        else:
            continue
        target_rows += f"""
        <div class="tp-row tp-target">
          <span class="tp-label">{t_label}</span>
          <span class="mono num" style="color:var(--green)">{t_str}</span>
        </div>"""

    # Invalidation
    if not isinstance(invalidators, list):
        invalidators = []
    inval_html = ""
    if invalidators:
        items = "".join(f"<li>{_esc(str(inv))}</li>" for inv in invalidators[:5])
        inval_html = f"""
        <div style="margin-top:.75rem">
          <div class="tp-section-title" style="color:var(--red)">失效条件</div>
          <ul class="tp-inval-list">{items}</ul>
        </div>"""

    return f"""
    <div class="card" style="overflow:hidden;">
      <div style="position:absolute;inset:0 auto auto 0;width:4px;height:100%;background:var(--blue);border-radius:20px 0 0 20px;"></div>
      <div style="padding-left:.6rem;">
        <h3>AI 交易计划</h3>
        <div style="display:flex;gap:.8rem;align-items:center;margin-bottom:.75rem;flex-wrap:wrap">
          <span class="badge badge-{bias_class}" style="font-size:.9rem;padding:5px 16px">{bias_label} ({bias})</span>
          <span style="color:var(--muted);font-size:.85rem;font-family:var(--mono)">置信度 {confidence:.0%}</span>
          <span style="color:var(--muted);font-size:.85rem">{_esc(horizon_label)}</span>
        </div>
        <div class="tp-section-title">买入设置</div>
        <table class="tp-table">
          <thead><tr><th>类型</th><th>价格区间</th><th>触发条件</th></tr></thead>
          <tbody>{setup_rows if setup_rows else '<tr><td colspan="3" style="color:var(--muted)">当前不建议入场</td></tr>'}</tbody>
        </table>
        {sl_html}
        {target_rows}
        {inval_html}
      </div>
    </div>"""


def render_research(view: ResearchView, skip_vendors: bool = False) -> str:
    """Render Tier 2 Research Report — cards not essays, zero LLM leakage.

    When is_degraded=True, shows warning banner + synthesis + risk only.
    Hides bull/bear cards, catalysts, scenarios to avoid displaying
    unreliable structured data.
    """

    # ── Degraded Mode: warning + synthesis + risk only ──
    if view.is_degraded:
        return _render_research_degraded(view)

    # Executive summary — hero cockpit
    _sig_emoji_r = get_signal_emoji(view.research_action)
    color_var = 'green' if view.action_class == 'buy' else ('red' if view.action_class in ('sell', 'veto') else 'yellow')
    conf_pct_r = int(view.confidence * 100)
    if view.confidence >= 0:
        _conf_cls_r = "buy" if view.confidence >= 0.7 else ("hold" if view.confidence >= 0.4 else "sell")
        _conf_note_r = "\u2248" if getattr(view, "confidence_defaulted", False) else ""
        _conf_sub_r = ' <span style="font-size:.6rem;color:var(--muted);">(\u9ed8\u8ba4)</span>' if getattr(view, "confidence_defaulted", False) else ""
        _conf_kpi_r = f'<div class="kpi {_conf_cls_r}"><span class="kpi-val">{_conf_note_r}{conf_pct_r}%</span><span class="kpi-label">\u7f6e\u4fe1\u5ea6{_conf_sub_r}</span></div>'
    else:
        _conf_kpi_r = '<div class="kpi"><span class="kpi-val">\u2014</span><span class="kpi-label">\u7f6e\u4fe1\u5ea6</span></div>'
    risk_display = view.risk_score if view.risk_score is not None else '—'

    exec_summary = f"""
    <div class="hero reveal">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="eyebrow">深度研究报告 &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji_r} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.action_explanation)}</div>
        </div>
        <div class="hero-right">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;">
            {_conf_kpi_r}
            <div class="kpi"><span class="kpi-val">{risk_display}</span><span class="kpi-label">风险评分/10</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_evidence}</span><span class="kpi-label">证据</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_claims}</span><span class="kpi-label">论据</span></div>
          </div>
        </div>
      </div>
    </div>"""

    # ── Detailed financial data ──
    research_chart_html = ""

    # ── Bull/Bear case panels — claim cards if structured, fallback excerpt ──
    def _case_panel(title: str, claims: list, excerpt: str, evidence: list, color: str) -> str:
        ev_html = ", ".join(_esc(e) for e in evidence[:10]) or "无引用"
        has_structured = claims and any(c.get("text") for c in claims)

        if has_structured:
            cards = ""
            for c in claims:
                dim_text = get_dimension_label(c.get("dimension", "")) if c.get("dimension") else ""
                dim_badge = f'<div class="dim">{_esc(dim_text)}</div>' if dim_text else ""
                conf = c.get("confidence", 0)
                conf_pct = int(conf * 100)
                conf_color = "var(--green)" if conf >= 0.7 else ("var(--yellow)" if conf >= 0.4 else "var(--red)")
                # Evidence count, not raw IDs
                ev_count = len(c.get("evidence_ids", []))
                ev_label = f"{ev_count}条证据" if ev_count else "无引用"
                cards += f"""
                <div class="claim-card">
                  {dim_badge}
                  <div>{_esc(_strip_internal_tokens(c.get("text", "")[:150]))}</div>
                  <div class="conf-bar"><div class="conf-fill" style="width:{conf_pct}%;background:{conf_color};"></div></div>
                  <div class="ev-tags">{_esc(ev_label)}</div>
                </div>"""
            content = f'<div class="claim-grid">{cards}</div>'
        else:
            # Fallback: truncated excerpt, strip tokens
            content = f'<div class="excerpt excerpt-short">{_esc(_strip_internal_tokens(_strip_preamble(excerpt)[:500]))}</div>'

        # Summary line: use counts not raw IDs
        ev_count_total = len(evidence)
        ev_summary = f"{ev_count_total}条引用" if ev_count_total else "无引用"

        return f"""
        <div class="card">
          <h3 style="color:var(--{color})">{title}</h3>
          {content}
          <div style="margin-top:.5rem; font-size:.85rem; color:var(--muted);">
            {len(claims)} 条结构化论据 &middot; 证据: {_esc(ev_summary)}
          </div>
        </div>"""

    bull_html = _case_panel("看多论点", view.bull_claims, view.bull_excerpt,
                            view.bull_evidence_ids, "green")
    bear_html = _case_panel("看空论点", view.bear_claims, view.bear_excerpt,
                            view.bear_evidence_ids, "red")

    # ── PM Synthesis — structured conclusion + cases ──
    thesis_label = get_thesis_label(view.thesis_effect)
    thesis_ok = view.thesis_effect in ("unchanged", "strengthened", "strengthen", "")

    synth_body = f'<div style="font-size:.95rem; margin:.5rem 0;">{_esc(_strip_internal_tokens(_strip_preamble(view.synthesis_excerpt)[:300]))}</div>'

    if view.synthesis_detail:
        cases = ""
        for key, label in [("base_case", "基准情景"), ("bull_case", "乐观情景"), ("bear_case", "悲观情景")]:
            text = view.synthesis_detail.get(key, "")
            if text:
                cases += f'<div style="margin:.5rem 0;"><strong>{label}:</strong> {_esc(_strip_internal_tokens(text[:200]))}</div>'
        if cases:
            synth_body += cases

    ev_count = len(view.synthesis_evidence_ids)
    ev_summary = f"{ev_count}条" if ev_count else "无"

    synthesis_html = f"""
    <div class="card">
      <h3>研究经理综合判断</h3>
      <div style="margin-bottom:.5rem;">
        论题状态: <span class="badge badge-{'ok' if thesis_ok else 'warn'}">{_esc(thesis_label)}</span>
        &nbsp; 引用证据: {_esc(ev_summary)}
      </div>
      {synth_body}
    </div>"""

    # ── Scenario — horizontal probability bars (CSS-only) ──
    scenario_html = ""
    if view.scenario_probs:
        sp = view.scenario_probs
        base_pct = int(sp.get("base_prob", 0) * 100)
        bull_pct = int(sp.get("bull_prob", 0) * 100)
        bear_pct = int(sp.get("bear_prob", 0) * 100)
        base_arrow = "" if abs(base_pct - 33) < 5 else ("▲" if base_pct > 33 else "▼")
        bull_arrow = "" if abs(bull_pct - 33) < 5 else ("▲" if bull_pct > 33 else "▼")
        bear_arrow = "" if abs(bear_pct - 33) < 5 else ("▲" if bear_pct > 33 else "▼")
        base_tip = _esc(sp.get("base_trigger", "")[:80])
        bull_tip = _esc(sp.get("bull_trigger", "")[:80])
        bear_tip = _esc(sp.get("bear_trigger", "")[:80])
        base_lbl = f"基准 {base_pct}%{base_arrow}" if base_pct > 18 else ""
        bull_lbl = f"乐观 {bull_pct}%{bull_arrow}" if bull_pct > 18 else ""
        bear_lbl = f"悲观 {bear_pct}%{bear_arrow}" if bear_pct > 18 else ""
        _probs_note = (' <span style="font-size:.75rem;color:#8fa3b8;">'
                       '(\u6982\u7387\u4e3a\u89e3\u6790\u9ed8\u8ba4\u503c'
                       '\uff0c\u4ec5\u4f9b\u53c2\u8003)</span>'
                       if sp.get("probs_defaulted") else "")
        scenario_html = f"""
    <div class="card">
      <h3>\u60c5\u666f\u5206\u6790{_probs_note}</h3>
      <div class="prob-bar">
        <div class="prob-seg" style="width:{base_pct}%;background:var(--blue);color:var(--white);" data-tip="{base_tip}">{base_lbl}</div>
        <div class="prob-seg" style="width:{bull_pct}%;background:var(--green);color:var(--white);" data-tip="{bull_tip}">{bull_lbl}</div>
        <div class="prob-seg" style="width:{bear_pct}%;background:var(--red);color:var(--white);" data-tip="{bear_tip}">{bear_lbl}</div>
      </div>
      <div style="font-size:.85rem; margin-top:.5rem;">
        <div><strong>基准触发:</strong> {_esc(sp.get("base_trigger", "")[:150])}</div>
        <div><strong>乐观触发:</strong> {_esc(sp.get("bull_trigger", "")[:150])}</div>
        <div><strong>悲观触发:</strong> {_esc(sp.get("bear_trigger", "")[:150])}</div>
      </div>
    </div>"""
    elif view.scenario_excerpt:
        scenario_html = f"""
    <div class="card">
      <h3>情景分析</h3>
      <div class="excerpt excerpt-short">{_esc(_strip_internal_tokens(_strip_preamble(view.scenario_excerpt)[:800]))}</div>
    </div>"""

    # ── Risk review — card-per-flag with severity color ──
    risk_content = ""
    if view.risk_flags_detail:
        for f in view.risk_flags_detail:
            sev_cls = safe_badge_class(f.get("severity_class", ""))
            sev_label = get_severity_label(f.get("severity", ""))
            ev_count = len(f.get("evidence_ids", []))
            ev_label = f"{ev_count}条证据" if ev_count else "无引用"
            mitigant = f.get("mitigant", "")
            mitigant_html = f'<div style="font-size:.8rem;color:var(--muted);margin-top:.25rem;">缓释: {_esc(_strip_internal_tokens(mitigant))}</div>' if mitigant else ""
            risk_content += f"""
            <div class="claim-card">
              <span class="badge badge-{sev_cls}">{_esc(sev_label)}</span>
              <strong>{_esc(get_risk_label(f.get("category", "")))}</strong>
              <div style="margin-top:.25rem;">{_esc(_strip_internal_tokens(f.get("description", "")[:150]))}</div>
              <div class="ev-tags">{_esc(ev_label)}</div>
              {mitigant_html}
            </div>"""
        risk_content = f'<div class="claim-grid">{risk_content}</div>'
    elif view.risk_flag_categories:
        items = "".join(f"<li>{_esc(get_risk_label(c))}</li>" for c in view.risk_flag_categories)
        risk_content = f"<ul>{items}</ul>"

    risk_html = f"""
    <div class="card">
      <h3>风险审查</h3>
      <div style="margin-bottom:.5rem;">
        评分: <strong>{view.risk_score if view.risk_score is not None else '无'}</strong>/10 &middot;
        风控通过: <span class="badge badge-{'ok' if view.risk_cleared else 'warn'}">
        {'是' if view.risk_cleared else '否'}</span> &middot;
        风险标记: {view.risk_flag_count} 项
      </div>
      {risk_content}
    </div>"""

    # ── Trade Plan: public entry/exit framework ──
    trade_plan_html = ""
    if view.trade_plan and view.trade_plan.get("bias"):
        trade_plan_html = _render_trade_plan_card(view.trade_plan)

    # Catalyst
    catalyst_html = ""
    if view.catalyst_excerpt:
        catalyst_html = f"""
    <div class="card">
      <h3>催化剂分析</h3>
      <div class="excerpt excerpt-short">{_esc(_strip_internal_tokens(_strip_preamble(view.catalyst_excerpt)[:600]))}</div>
    </div>"""

    # Invalidation
    inval_html = ""
    if view.invalidation_signals:
        items = "".join(f"<li>{_esc(s)}</li>" for s in view.invalidation_signals)
        inval_html = f"""
    <div class="card">
      <h3>论题失效条件</h3>
      <ul>{items}</ul>
    </div>"""

    # Lineage — Research tier: visual pipeline flow, not raw ID table
    lineage_html = ""
    if view.lineage_stages:
        steps = []
        for s in view.lineage_stages:
            node_raw = s.get('node', '')
            node = get_node_label(node_raw)
            ev_in = s.get('evidence_consumed', [])
            cl_out = s.get('claims_produced', [])
            cl_in = s.get('claims_consumed', [])
            attr = s.get('attributed', 0)
            unattr = s.get('unattributed', 0)
            decision = s.get('decision', {})
            risk = s.get('risk', {})
            action_raw = decision.get('action', '') if isinstance(decision, dict) else ''
            confidence = decision.get('confidence', 0) if isinstance(decision, dict) else 0
            thesis_raw = decision.get('thesis_effect', '') if isinstance(decision, dict) else ''

            # Skip empty pass-through nodes
            has_content = ev_in or cl_out or cl_in or action_raw or (isinstance(risk, dict) and risk.get('flags'))
            if not has_content:
                continue

            # Build step content
            parts = []
            if ev_in:
                parts.append(f'<span style="color:var(--blue)">引用 {len(ev_in)} 条证据</span>')
            if cl_out:
                bind_note = f"（{attr}条有据）" if attr > 0 else ""
                parts.append(f'产出 {len(cl_out)} 条论据{bind_note}')
            if cl_in:
                parts.append(f'消费 {len(cl_in)} 条论据')
            if action_raw:
                action_cn = get_soft_action_label(action_raw)
                thesis_cn = get_thesis_label(thesis_raw) if thesis_raw else ""
                thesis_badge = f' · 论题{thesis_cn}' if thesis_cn and thesis_cn != "无" else ""
                parts.append(f'<strong>{_esc(action_cn)} ({confidence:.0%})</strong>{thesis_badge}')
            if isinstance(risk, dict) and risk.get('flags'):
                cats = risk.get('categories', [])
                cat_str = "、".join(_esc(c) for c in cats[:3])
                _vs = risk.get('veto_source', '')
                veto_label = "风控门禁" if _vs == "risk_gate" else ("研究否决" if _vs == "agent_veto" else "否决")
                veto_str = f' <span style="color:var(--red)">→ {veto_label}</span>' if risk.get('vetoed') else ""
                parts.append(f'风控标记 {risk["flags"]} 项（{cat_str}）{veto_str}')

            detail = " → ".join(parts) if parts else ""
            steps.append(f"""
            <div class="timeline-item">
              <span class="timeline-node">{_esc(node)}</span>
              <span class="timeline-detail">{detail}</span>
            </div>""")

        if steps:
            lineage_html = f"""
    <div class="card">
      <h3>决策链路</h3>
      <div class="timeline">{"".join(steps)}</div>
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 深度研究报告</p>
    <div class="banner">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。使用前请结合人工判断。</div>
    {exec_summary}
    {research_chart_html}
    <details open><summary><h2>多空分析</h2></summary>
    <div class="cols reveal reveal-d1">{bull_html}{bear_html}</div>
    </details>
    <details open><summary><h2>综合研判</h2></summary>
    <div class="reveal reveal-d2">{synthesis_html}</div>
    <div class="reveal reveal-d3">{scenario_html}</div>
    </details>
    <details open><summary><h2>风险评估</h2></summary>
    <div class="reveal reveal-d4">{risk_html}</div>
    <div class="reveal reveal-d5">{trade_plan_html}</div>
    <div class="reveal reveal-d5">{catalyst_html}</div>
    </details>
    <details open><summary><h2>决策链路</h2></summary>
    <div class="reveal reveal-d6">{inval_html}</div>
    <div class="reveal reveal-d6">{lineage_html}</div>
    </details>"""

    return _html_wrap(f"{_ticker_display(view)} 深度研究 — {view.trade_date}", body, "深度研究报告", extra_head=_COUNTUP_JS)


# ── Tier 3: Audit Report ────────────────────────────────────────────────

def render_audit(view: AuditView) -> str:
    """Render Tier 3 Trust Audit Report — trust signals first, details below."""

    # ── Trust signals section (new, top of page) ──
    trust_html = ""
    if view.trust_signals:
        cards = ""
        for ts in view.trust_signals:
            status = ts.get("status", "warn")
            value = ts.get("value", 0)
            cards += f"""
            <div class="trust-card {status}">
              <div class="tv">{value:.0%}</div>
              <div class="tl">{_esc(ts.get("label", ""))}</div>
              <div class="te">{_esc(ts.get("explanation", ""))}</div>
            </div>"""
        trust_html = f'<div class="trust-grid">{cards}</div>'

    # ── Weakest link callout ──
    weakest_html = ""
    if view.weakest_node:
        weakest_html = f'<div class="callout">建议人工复核：<strong>{_esc(get_node_label(view.weakest_node))}</strong></div>'

    # ── Manual check items ──
    manual_html = ""
    if view.manual_check_items:
        items = "".join(f"<li>{_esc(m)}</li>" for m in view.manual_check_items)
        manual_html = f'<div class="card"><h3>需人工确认事项</h3><ul>{items}</ul></div>'

    # Metrics dashboard (kept)
    m = view.metrics
    metrics_html = ""
    if m:
        metrics_html = f"""
    <div class="kpi-row">
      <div class="kpi"><span class="kpi-val">{m.strict_parse_rate:.0%}</span><span class="kpi-label">严格解析率</span></div>
      <div class="kpi"><span class="kpi-val">{m.fallback_rate:.0%}</span><span class="kpi-label">回退解析率</span></div>
      <div class="kpi"><span class="kpi-val">{m.narrative_dependency_rate:.0%}</span><span class="kpi-label">叙事依赖率</span></div>
      <div class="kpi"><span class="kpi-val">{m.claim_to_evidence_binding_rate:.0%}</span><span class="kpi-label">论据绑定率</span></div>
      <div class="kpi"><span class="kpi-val">{m.replay_completeness_rate:.0%}</span><span class="kpi-label">回放完整率</span></div>
    </div>"""

    # Parse quality table
    parse_html = ""
    if view.parse_table:
        rows = ""
        for p in view.parse_table:
            status = p.get("parse_status", "")
            label = PARSE_STATUS_LABELS.get(status, status)
            cls = "badge-ok" if status == "strict_ok" else ("badge-warn" if status == "fallback_used" else "badge-low")
            warnings = ", ".join(p.get("warnings", [])) or "-"
            rows += f"""<tr>
              <td>{_esc(get_node_label(p['node_name']))}</td>
              <td><span class="badge {cls}">{_esc(label)}</span></td>
              <td>{p.get('parse_confidence', -1):.1f}</td>
              <td style="font-size:.8rem;">{_esc(warnings)}</td>
            </tr>"""
        parse_html = f"""
    <div class="card">
      <h3>解析质量</h3>
      <table><thead><tr><th>节点</th><th>状态</th><th>置信度</th><th>警告</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Compliance nodes
    compliance_html = ""
    if view.compliance_nodes:
        rows = ""
        for cn in view.compliance_nodes:
            label = COMPLIANCE_STATUS_LABELS.get(cn.compliance_status, cn.compliance_status)
            rules = ", ".join(cn.compliance_rules_fired) or "-"
            rows += f"""<tr>
              <td>{_esc(get_node_label(cn.node_name))}</td>
              <td><span class="badge badge-{'ok' if cn.compliance_status == 'allow' else 'warn'}">{_esc(label)}</span></td>
              <td style="font-size:.8rem;">{_esc(rules)}</td>
            </tr>"""
        compliance_html = f"""
    <div class="card">
      <h3>合规决策</h3>
      <table><thead><tr><th>节点</th><th>状态</th><th>触发规则</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Freshness
    freshness_html = ""
    if view.vendor_freshness:
        rows = ""
        for vf in view.vendor_freshness:
            status = vf.get("status", "unknown")
            label = FRESHNESS_STATUS_LABELS.get(status, status)
            cls = "badge-ok" if status in ("FRESH", "fresh", "RECOVERED") else "badge-warn"
            rows += f"""<tr>
              <td>{_esc(vf.get('key', ''))}</td>
              <td><span class="badge {cls}">{_esc(label)}</span></td>
              <td>{vf.get('system_lag_min', '无')}</td>
              <td>{vf.get('doc_lag_min', '无')}</td>
            </tr>"""
        stale_alert = '' if view.freshness_ok else '<div style="color:var(--red); margin-bottom:.5rem;">检测到过期数据源</div>'
        freshness_html = f"""
    <div class="card">
      <h3>数据源新鲜度</h3>
      {stale_alert}
      <table><thead><tr><th>供应商/方法</th><th>状态</th><th>系统延迟</th><th>文档延迟</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Failures
    _issue_type_labels = {
        "error": "异常", "parse_degraded": "解析降级", "vetoed": "否决",
        "compliance_escalation": "合规升级", "unattributed_claims": "无归属论据",
    }
    failures_html = ""
    if view.failures:
        rows = ""
        for f in view.failures:
            issues_str = "; ".join(
                _issue_type_labels.get(i.get("type", ""), i.get("type", ""))
                + (f": {i.get('details', '')}" if i.get('details') else "")
                for i in f.get("issues", [])
            ) or str(f.get("error", ""))
            status_cn = NODE_STATUS_LABELS.get(str(f.get('status', '')), str(f.get('status', '')))
            rows += f"""<tr>
              <td>{_esc(get_node_label(str(f.get('node_name', ''))))}</td>
              <td>{_esc(status_cn)}</td>
              <td style="font-size:.8rem;">{_esc(issues_str[:200])}</td>
            </tr>"""
        failures_html = f"""
    <div class="card">
      <h3>故障记录</h3>
      <table><thead><tr><th>节点</th><th>状态</th><th>问题</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # Lineage — Audit tier: structured traceability, counts + coverage, not raw IDs
    lineage_html = ""
    if view.lineage_stages:
        rows = ""
        for s in view.lineage_stages:
            node = get_node_label(s.get('node', ''))
            status = s.get('status', '')
            status_cn = NODE_STATUS_LABELS.get(status, status)
            ev_in = s.get('evidence_consumed', [])
            cl_out = s.get('claims_produced', [])
            cl_in = s.get('claims_consumed', [])
            attr = s.get('attributed', 0)
            unattr = s.get('unattributed', 0)
            decision = s.get('decision', {})
            risk = s.get('risk', {})

            # Evidence: count + coverage indicator
            if ev_in:
                ev_str = f"{len(ev_in)}条"
            else:
                ev_str = '<span style="color:var(--muted)">—</span>'

            # Claims: count + attribution quality
            if cl_out:
                total = len(cl_out)
                if unattr > 0:
                    cl_str = f'{total}条 <span style="color:var(--red)">({unattr}条无据)</span>'
                else:
                    cl_str = f'{total}条 <span style="color:var(--green)">全部有据</span>'
            elif cl_in:
                cl_str = f'消费{len(cl_in)}条'
            else:
                cl_str = '<span style="color:var(--muted)">—</span>'

            # Decision
            action_raw = decision.get('action', '') if isinstance(decision, dict) else ''
            if action_raw:
                action_cn = get_action_label(action_raw)
                conf = decision.get('confidence', 0)
                decision_str = f'{_esc(action_cn)} ({conf:.0%})'
            else:
                decision_str = '<span style="color:var(--muted)">—</span>'

            # Risk
            if isinstance(risk, dict) and risk.get('flags'):
                cats = risk.get('categories', [])
                cat_str = "、".join(_esc(c) for c in cats[:3])
                _vs2 = risk.get('veto_source', '')
                veto_label2 = "风控门禁" if _vs2 == "risk_gate" else ("研究否决" if _vs2 == "agent_veto" else "否决")
                veto = f' <span class="badge badge-veto">{veto_label2}</span>' if risk.get('vetoed') else ""
                risk_str = f'{risk["flags"]}项（{cat_str}）{veto}'
            else:
                risk_str = '<span style="color:var(--muted)">—</span>'

            rows += f"""<tr>
              <td><span class="badge badge-{'ok' if status == 'ok' else 'warn'}">{_esc(status_cn)}</span></td>
              <td>{_esc(node)}</td>
              <td style="font-size:.85rem;">{ev_str}</td>
              <td style="font-size:.85rem;">{cl_str}</td>
              <td style="font-size:.85rem;">{decision_str}</td>
              <td style="font-size:.85rem;">{risk_str}</td>
            </tr>"""
        lineage_html = f"""
    <div class="card">
      <h3>证据溯源</h3>
      <table><thead><tr><th>状态</th><th>节点</th><th>证据输入</th><th>论据流转</th><th>决策</th><th>风控标记</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>"""

    # ── Audit conclusion (top-level, computed from trust signals) ──
    conclusion_html = ""
    if view.audit_conclusion_label:
        level = view.audit_conclusion_level
        level_color = {"high": "green", "medium": "yellow", "low": "red"}.get(level, "yellow")
        conclusion_html = f"""
    <div class="card" style="overflow:hidden;">
      <div style="position:absolute;inset:0 auto auto 0;width:4px;height:100%;background:var(--{level_color});border-radius:20px 0 0 20px;"></div>
      <div style="padding-left:.6rem;">
        <div style="font-size:1.1rem;font-weight:800;color:var(--white);">审计结论：{_esc(view.audit_conclusion_label)}</div>
        <div style="margin-top:.3rem;color:var(--muted);font-size:.88rem;line-height:1.6;">
          {_esc(view.audit_conclusion_text)}
        </div>
      </div>
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 信任审计报告</p>
    <div class="banner">本报告帮助您判断：这次结论是否值得信任？哪些环节需要人工复核？</div>

    <div class="reveal">{conclusion_html}</div>

    <h2>信任信号</h2>
    <div class="reveal reveal-d1">{trust_html}</div>
    <div class="reveal reveal-d1">{weakest_html}</div>
    <div class="reveal reveal-d2">{manual_html}</div>

    <h2>控制面板</h2>

    <div class="reveal reveal-d2">
      <h3>质量指标</h3>
      {metrics_html}
    </div>

    <div class="reveal reveal-d3">
      <h3>解析质量与结构化输出</h3>
      {parse_html}
    </div>

    <div class="reveal reveal-d4">
      <h3>合规审查</h3>
      {compliance_html or '<div class="card" style="color:var(--muted);">' + _esc(NO_COMPLIANCE_LABEL) + '</div>'}
    </div>

    <div class="reveal reveal-d4">
      <h3>数据源新鲜度与健康度</h3>
      {freshness_html or '<div class="card">' + _status_light(view.freshness_ok, "所有数据源状态正常") + '</div>'}
    </div>

    <h2>证据溯源</h2>
    <div class="reveal reveal-d5">{lineage_html}</div>

    <div class="reveal reveal-d6">
      <h3>故障与警告</h3>
      {failures_html or '<div class="card" style="color:var(--green);">无故障记录。</div>'}
    </div>"""

    return _html_wrap(f"{_ticker_display(view)} 信任审计报告 — {view.trade_date}", body, "信任审计报告")


# ── Convenience: generate all 3 tiers for a run ─────────────────────────

def generate_all_tiers(run_id: str, output_dir: str = "data/reports",
                       storage_dir: str = "data/replays",
                       skip_vendors: bool = False) -> dict:
    """Generate all 3 tier reports for a single run.

    Returns dict of {tier: filepath} for generated reports.
    """
    from ..replay_store import ReplayStore
    from ..replay_service import ReplayService

    store = ReplayStore(storage_dir=storage_dir)
    svc = ReplayService(store=store)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    short_id = run_id.replace("run-", "")[:12]

    # Tier 1
    snap = SnapshotView.build(svc, run_id)
    if snap:
        path = out_dir / f"{snap.ticker}-run-{short_id}-snapshot.html"
        path.write_text(render_snapshot(snap, skip_vendors=skip_vendors),
                        encoding="utf-8")
        results["snapshot"] = str(path)

    # Tier 2
    res = ResearchView.build(svc, run_id)
    if res:
        path = out_dir / f"{res.ticker}-run-{short_id}-research.html"
        path.write_text(render_research(res, skip_vendors=skip_vendors),
                        encoding="utf-8")
        results["research"] = str(path)

    # Tier 3
    audit = AuditView.build(svc, run_id)
    if audit:
        path = out_dir / f"{audit.ticker}-run-{short_id}-audit.html"
        path.write_text(render_audit(audit), encoding="utf-8")
        results["audit"] = str(path)

    return results


# ── Multi-stock Divergence Pool ──────────────────────────────────────────

_POOL_CSS = """
:root {
  --bg: #070e1b;
  --fg: #dde6f0;
  --card: rgba(11, 20, 35, 0.85);
  --border: rgba(100, 150, 180, 0.18);
  --green: #34d399;
  --red: #f87171;
  --yellow: #fbbf24;
  --blue: #60a5fa;
  --purple: #a78bfa;
  --muted: #8fa3b8;
  --surface: rgba(14, 24, 40, 0.92);
  --accent: #f59e0b;
  --mono: "JetBrains Mono", "Fira Code", "SF Mono", Menlo, monospace;
  --signal-buy: var(--green);
  --signal-sell: var(--red);
  --signal-hold: var(--yellow);
  --signal-veto: var(--red);
  --state-success: var(--green);
  --state-danger: var(--red);
  --state-warning: var(--yellow);
  --state-info: var(--blue);
  --elev-1: 0 4px 12px rgba(0,0,0,0.15);
  --elev-2: 0 12px 28px rgba(0,0,0,0.25);
  --elev-3: 0 22px 54px rgba(0,0,0,0.35);
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --dur-fast: 200ms;
  --dur-med: 360ms;
  --sp-1: 0.5rem; --sp-2: 1rem; --sp-3: 1.5rem; --sp-4: 2rem; --sp-6: 3rem;
}
body {
  background:
    radial-gradient(circle at 12% 20%, rgba(251, 191, 36, 0.16), transparent 28%),
    radial-gradient(circle at 88% 16%, rgba(96, 165, 250, 0.14), transparent 26%),
    radial-gradient(circle at 50% 120%, rgba(52, 211, 153, 0.14), transparent 36%),
    linear-gradient(180deg, #091420 0%, #070e1b 55%, #050c17 100%);
}
.container { max-width: 1360px; padding: 2.2rem 1.5rem 4rem; }
.pool-shell { display: grid; gap: 1.25rem; }
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background:
    linear-gradient(135deg, rgba(12, 29, 45, 0.96) 0%, rgba(12, 21, 31, 0.88) 45%, rgba(24, 34, 28, 0.9) 100%);
  box-shadow: 0 22px 54px rgba(0, 0, 0, 0.26);
  padding: 2rem;
}
.hero::after {
  content: "";
  position: absolute;
  inset: -20% auto auto 56%;
  width: 340px;
  height: 340px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(245, 158, 11, 0.16), transparent 64%);
  pointer-events: none;
}
.hero-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.9fr);
  gap: 1.2rem;
  align-items: stretch;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 0.72rem;
  color: var(--yellow);
  margin-bottom: 0.9rem;
}
.hero h1 {
  font-size: clamp(2.5rem, 4.4vw, 4rem);
  letter-spacing: -0.04em;
  line-height: 1;
  margin-bottom: 0.85rem;
}
.hero-copy {
  max-width: 46rem;
  color: var(--fg);
  font-size: 1rem;
  margin-bottom: 1rem;
}
.hero-chips, .anchor-nav, .spotlight-tags, .stock-badges, .risk-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}
.hero-chip, .anchor-link, .spotlight-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.5rem 0.85rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: var(--fg);
  font-size: 0.84rem;
}
.anchor-nav { margin-top: 1rem; }
.anchor-link {
  color: inherit;
  text-decoration: none;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}
.anchor-link:hover {
  transform: translateY(-1px);
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.08);
}
.hero-spotlights { display: grid; gap: 0.8rem; }
.spotlight-card {
  border-radius: 20px;
  padding: 1rem 1.1rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.06), rgba(255, 255, 255, 0.025));
  backdrop-filter: blur(16px);
}
.spotlight-card.buy { box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.18); }
.spotlight-card.hold { box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.18); }
.spotlight-card.sell, .spotlight-card.veto { box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.18); }
.spotlight-label {
  font-size: 0.76rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.45rem;
}
.spotlight-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.45rem;
}
.spotlight-name {
  font-size: 1.05rem;
  font-weight: 700;
  color: #f1f7fd;
}
.spotlight-score {
  font-size: 1.2rem;
  font-weight: 700;
}
.spotlight-copy {
  color: #bdd0da;
  font-size: 0.86rem;
  line-height: 1.55;
}
.kpi-deck {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.95rem;
}
.kpi-panel {
  position: relative;
  overflow: hidden;
  border-radius: 22px;
  padding: 1.1rem 1.15rem;
  background: linear-gradient(180deg, rgba(10, 22, 34, 0.94), rgba(10, 18, 28, 0.88));
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.16);
}
.kpi-panel::before {
  content: "";
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 3px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.04));
}
.kpi-panel.buy::before { background: linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.9), transparent); }
.kpi-panel.sell::before, .kpi-panel.veto::before { background: linear-gradient(90deg, transparent, rgba(248, 113, 113, 0.9), transparent); }
.kpi-panel.hold::before { background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.9), transparent); }
.kpi-panel.neutral::before { background: linear-gradient(90deg, transparent, rgba(96, 165, 250, 0.9), transparent); }
.kpi-value {
  font-size: 2rem;
  font-weight: 800;
  line-height: 1;
  margin-bottom: 0.3rem;
}
.kpi-title {
  color: #f4fbff;
  font-size: 0.9rem;
  margin-bottom: 0.22rem;
}
.kpi-note {
  color: var(--muted);
  font-size: 0.76rem;
}
.section-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 1rem;
}
.insight-card, .board-card, .method-card {
  background: linear-gradient(180deg, rgba(12, 23, 35, 0.94), rgba(8, 16, 25, 0.92));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 24px;
  padding: 1.2rem;
  box-shadow: 0 18px 34px rgba(0, 0, 0, 0.18);
}
.insight-card { min-height: 100%; }
.insight-card.span-4 { grid-column: span 4; }
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: #f1f7fd;
}
.section-copy {
  color: var(--muted);
  font-size: 0.82rem;
  max-width: 34rem;
}
.pool-summary { display: grid; gap: 0.65rem; }
.pool-stat-row {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  font-size: 0.88rem;
}
.pool-stat-row .num {
  width: 2.8rem;
  font-size: 1.2rem;
  font-weight: 800;
}
.mix-track {
  flex: 1;
  height: 0.8rem;
  display: flex;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}
.mix-seg { height: 100%; }
.mix-seg.buy { background: linear-gradient(90deg, rgba(52, 211, 153, 0.92), rgba(52, 211, 153, 0.58)); }
.mix-seg.hold { background: linear-gradient(90deg, rgba(251, 191, 36, 0.92), rgba(251, 191, 36, 0.6)); }
.mix-seg.sell, .mix-seg.veto { background: linear-gradient(90deg, rgba(248, 113, 113, 0.92), rgba(248, 113, 113, 0.58)); }
.mix-legend, .risk-list, .method-list { display: grid; gap: 0.7rem; }
.legend-item, .risk-row, .method-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 0.7rem;
  font-size: 0.85rem;
}
.legend-dot {
  width: 0.68rem;
  height: 0.68rem;
  border-radius: 50%;
}
.legend-dot.buy { background: var(--green); }
.legend-dot.hold { background: var(--yellow); }
.legend-dot.sell, .legend-dot.veto { background: var(--red); }
.conviction-wrap { display: grid; gap: 0.75rem; }
.chart-svg {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.015));
}
.risk-row { grid-template-columns: minmax(0, 120px) 1fr auto; }
.risk-bar {
  height: 0.7rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
}
.risk-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, rgba(248, 113, 113, 0.92), rgba(251, 191, 36, 0.74));
}
.priority-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
}
.priority-table th {
  font-size: 0.77rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 0.7rem 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.priority-table td {
  padding: 0.9rem 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  vertical-align: middle;
}
.priority-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}
.rank-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2rem;
  height: 2rem;
  border-radius: 999px;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.06);
}
.score-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.58rem;
  border-radius: 999px;
  font-size: 0.76rem;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.05);
}
.stock-grid { display: grid; gap: 1rem; }
.stock-card {
  position: relative;
  overflow: hidden;
  border-radius: 24px;
  padding: 1.25rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background:
    linear-gradient(180deg, rgba(13, 24, 36, 0.95), rgba(8, 15, 24, 0.92)),
    linear-gradient(135deg, rgba(255, 255, 255, 0.02), transparent 55%);
  box-shadow: 0 18px 38px rgba(0, 0, 0, 0.2);
}
.stock-card::before {
  content: "";
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 4px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.26), rgba(255, 255, 255, 0.04));
}
.stock-card.buy::before { background: linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.92), transparent); }
.stock-card.hold::before { background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.92), transparent); }
.stock-card.sell::before, .stock-card.veto::before { background: linear-gradient(90deg, transparent, rgba(248, 113, 113, 0.92), transparent); }
.stock-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.stock-kicker {
  color: var(--muted);
  font-size: 0.8rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 0.2rem;
}
.stock-name {
  font-size: 1.32rem;
  font-weight: 800;
  color: #f6fbff;
}
.stock-sub {
  color: var(--muted);
  margin-top: 0.24rem;
  font-size: 0.84rem;
}
.stock-side { text-align: right; }
.stock-verdict {
  font-size: 1.16rem;
  font-weight: 800;
}
.stock-confidence {
  margin-top: 0.2rem;
  color: var(--muted);
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.stock-badges { margin-top: 0.85rem; }
.risk-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.36rem 0.65rem;
  border-radius: 999px;
  font-size: 0.76rem;
  background: rgba(255, 255, 255, 0.05);
  color: var(--fg);
}
.risk-tag.high, .risk-tag.critical { background: rgba(248, 113, 113, 0.12); color: #ffd2ca; }
.risk-tag.medium { background: rgba(251, 191, 36, 0.12); color: #ffe4b2; }
.risk-tag.low { background: rgba(96, 165, 250, 0.1); color: #d2efff; }
.signal-card {
  margin-top: 1rem;
  padding: 0.9rem 1rem;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
}
.signal-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.82rem;
  color: var(--muted);
  margin-bottom: 0.55rem;
}
.signal-meter {
  display: flex;
  height: 0.9rem;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
}
.signal-bull { background: linear-gradient(90deg, rgba(52, 211, 153, 0.94), rgba(52, 211, 153, 0.62)); }
.signal-bear { background: linear-gradient(90deg, rgba(248, 113, 113, 0.82), rgba(248, 113, 113, 0.56)); }
.signal-labels {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  color: var(--muted);
  font-size: 0.76rem;
  margin-top: 0.45rem;
}
.stock-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(220px, 0.8fr);
  gap: 1rem;
  margin-top: 1rem;
}
.claim-panel, .metric-panel {
  border-radius: 20px;
  padding: 1rem;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.03);
}
.claim-panel h4, .metric-panel h4 {
  font-size: 0.82rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.75rem;
}
.claim-panel.bull h4 { color: var(--green); }
.claim-panel.bear h4 { color: var(--red); }
.claim-stack { display: grid; gap: 0.75rem; }
.claim-item {
  border-radius: 16px;
  padding: 0.8rem 0.88rem;
  background: rgba(5, 12, 19, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.04);
  font-size: 0.86rem;
  line-height: 1.58;
}
.claim-panel.bull .claim-item { border-left: 3px solid rgba(52, 211, 153, 0.8); }
.claim-panel.bear .claim-item { border-left: 3px solid rgba(248, 113, 113, 0.8); }
.claim-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 0.45rem;
  font-size: 0.72rem;
  color: var(--muted);
}
.metric-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 0.75rem;
}
.metric-table td {
  padding: 0.46rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 0.84rem;
}
.metric-table td:last-child {
  text-align: right;
  color: #f2f8fb;
  font-weight: 600;
}
.mini-note {
  color: var(--muted);
  font-size: 0.76rem;
  line-height: 1.55;
}
.method-list { margin-top: 0.2rem; }
.method-item {
  grid-template-columns: auto 1fr;
  align-items: flex-start;
  padding-bottom: 0.55rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.method-item:last-child { border-bottom: none; padding-bottom: 0; }
.method-index {
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(245, 158, 11, 0.12);
  color: var(--accent);
  font-size: 0.76rem;
  font-weight: 700;
}
.reveal { animation: pool-rise 520ms ease both; }
.reveal-delay-1 { animation-delay: 60ms; }
.reveal-delay-2 { animation-delay: 110ms; }
.reveal-delay-3 { animation-delay: 160ms; }
@keyframes pool-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (max-width: 1120px) {
  .hero-grid, .stock-body, .kpi-deck { grid-template-columns: 1fr 1fr; }
  .insight-card.span-4 { grid-column: span 6; }
  .stock-body { grid-template-columns: 1fr 1fr; }
  .metric-panel { grid-column: span 2; }
}
@media (max-width: 760px) {
  .container { padding: 1rem .75rem 2.5rem; }
  .hero, .insight-card, .board-card, .stock-card, .method-card { border-radius: 16px; }
  .hero { padding: 1.25rem; }
  .hero-grid, .kpi-deck, .stock-body { grid-template-columns: 1fr; }
  .insight-card.span-4 { grid-column: span 12; }
  .stock-top, .section-head { flex-direction: column; gap: .5rem; }
  .stock-side { text-align: left; }
  .priority-table { font-size: 0.82rem; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .kpi-deck { gap: .5rem; }
  .stock-card { padding: 1rem; }
  .stock-body { gap: .6rem; }
  .metric-panel { grid-column: span 1; }
  .board-card { padding: 1rem; }
  .insight-card { padding: 1rem; }
}
@supports (padding: env(safe-area-inset-left)) {
  @media (max-width: 760px) {
    .container {
      padding-left: max(.75rem, env(safe-area-inset-left));
      padding-right: max(.75rem, env(safe-area-inset-right));
      padding-bottom: max(2.5rem, env(safe-area-inset-bottom));
    }
  }
}
/* ── Cover Page ─────────────────────────────────────────────── */
.cover-page {
  margin: -2.2rem -1.5rem 1.5rem;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  position: relative;
  overflow: hidden;
  border-radius: 0 0 32px 32px;
  background:
    radial-gradient(circle at 50% 35%, rgba(245, 158, 11, 0.12), transparent 42%),
    radial-gradient(circle at 20% 80%, rgba(52, 211, 153, 0.08), transparent 30%),
    radial-gradient(circle at 80% 70%, rgba(96, 165, 250, 0.08), transparent 30%),
    linear-gradient(180deg, #091420 0%, #070e1b 100%);
}
.cover-page::before {
  content: "";
  position: absolute;
  top: 18%;
  left: 50%;
  transform: translateX(-50%);
  width: 500px;
  height: 500px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.04);
  pointer-events: none;
}
.cover-page::after {
  content: "";
  position: absolute;
  top: 14%;
  left: 50%;
  transform: translateX(-50%);
  width: 700px;
  height: 700px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.025);
  pointer-events: none;
}
.cover-content {
  position: relative;
  z-index: 1;
  max-width: 640px;
}
.cover-logo { margin-bottom: 2rem; }
.cover-title {
  font-size: clamp(3rem, 6vw, 5rem);
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 1;
  color: #f6fbff;
  margin-bottom: 0.6rem;
}
.cover-subtitle {
  font-size: 1rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 2rem;
}
.cover-date {
  font-size: 1.1rem;
  color: var(--fg);
  margin-bottom: 0.5rem;
}
.cover-meta {
  font-size: 0.88rem;
  color: var(--muted);
  margin-bottom: 3rem;
}
.cover-disclaimer {
  font-size: 0.76rem;
  color: var(--muted);
  opacity: 0.7;
  max-width: 420px;
  margin: 0 auto;
  line-height: 1.55;
}
/* ── Brand Mark ─────────────────────────────────────────────── */
.brand-mark {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}
.brand-mark svg { flex-shrink: 0; }
/* ── Brand Footer ───────────────────────────────────────────── */
.brand-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.5rem 0.5rem 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  margin-top: 0.5rem;
}
.brand-footer-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--muted);
  font-size: 0.8rem;
}
.brand-footer-right {
  color: var(--muted);
  font-size: 0.72rem;
  text-align: right;
  opacity: 0.7;
}
/* ── Sparkline ──────────────────────────────────────────────── */
.sparkline-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.2rem;
  margin-top: 0.35rem;
}
.sparkline { display: block; }
.sparkline-label {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
/* ── Filter Bar ─────────────────────────────────────────────── */
.filter-bar {
  position: sticky;
  top: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.8rem 1rem;
  border-radius: 18px;
  background: rgba(8, 16, 26, 0.92);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
}
.filter-bar .filter-label {
  color: var(--muted);
  font-size: 0.8rem;
  margin-right: 0.2rem;
  white-space: nowrap;
}
.filter-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: var(--fg);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}
.filter-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
}
.filter-btn.active {
  background: rgba(245, 158, 11, 0.14);
  border-color: rgba(245, 158, 11, 0.4);
  color: var(--accent);
}
.filter-btn .f-count {
  font-size: 0.7rem;
  opacity: 0.6;
}
.filter-status {
  margin-left: auto;
  color: var(--muted);
  font-size: 0.76rem;
  white-space: nowrap;
}

/* ── V5a: Keyboard focus ── */
button:focus-visible, [role="button"]:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* ── V5: Touch feedback ── */
@media (hover: none) and (pointer: coarse) {
  .stock-card:active, .card:active { transform: scale(0.97); transition: transform 60ms ease; }
}

/* ── V7: Table scan ── */
.priority-table tbody tr:nth-child(even) { background: rgba(255,255,255,0.015); }

/* ── V8: Empty state ── */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 2rem 1rem; text-align: center; color: var(--muted);
}
.empty-state-icon { font-size: 2rem; margin-bottom: .6rem; opacity: .5; }
.empty-state-title { font-size: .88rem; font-weight: 600; margin-bottom: .25rem; }
.empty-state-hint { font-size: .78rem; opacity: .7; }

/* ── Print / Export ─────────────────────────────────────────── */
@media print {
  @page { size: A3 landscape; margin: 12mm; }
  body {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  .cover-page { page-break-after: always; min-height: 100vh; }
  .anchor-nav, .filter-bar { display: none !important; }
  .stock-card { page-break-inside: avoid; break-inside: avoid; }
  .board-card { page-break-before: always; }
  .insight-card { page-break-inside: avoid; break-inside: avoid; }
  .reveal {
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
  }
}
"""


def _pool_action_color(action_class: str) -> str:
    return {
        "buy": "#34d399",
        "hold": "#fbbf24",
        "sell": "#f87171",
        "veto": "#f87171",
    }.get(action_class, "#60a5fa")


def _pool_severity_class(severity: str) -> str:
    level = (severity or "").lower()
    return level if level in ("critical", "high", "medium", "low") else "low"


def _pool_badge(text: str, css_class: str) -> str:
    return f'<span class="risk-tag {css_class}">{_esc(text)}</span>'


def _pool_spotlight_card(
    title: str,
    row: Optional[StockDivergenceRow],
    empty_text: str,
    claim_side: str,
) -> str:
    if not row:
        return f"""
        <div class="spotlight-card reveal">
          <div class="spotlight-label">{_esc(title)}</div>
          <div class="spotlight-copy">{_esc(empty_text)}</div>
        </div>"""

    claims = row.bull_claims if claim_side == "bull" else row.bear_claims
    claim = claims[0]["text"] if claims else row.risk_state_label
    color = _pool_action_color(row.action_class)
    pill = f"{row.action_label} {row.conviction_pct}%"
    return f"""
    <div class="spotlight-card {row.action_class} reveal">
      <div class="spotlight-label">{_esc(title)}</div>
      <div class="spotlight-main">
        <div class="spotlight-name">{_esc(row.display_name)}</div>
        <div class="spotlight-score" style="color:{color}">{row.conviction_pct}%</div>
      </div>
      <div class="spotlight-copy">{_esc(_strip_internal_tokens(claim[:96]))}</div>
      <div class="spotlight-tags" style="margin-top:.7rem;">
        <span class="spotlight-pill">{_esc(pill)}</span>
        <span class="spotlight-pill">{_esc(row.risk_state_label)}</span>
      </div>
    </div>"""


def _render_pool_mix_chart(view: DivergencePoolView) -> str:
    items = [
        ("建议关注", view.buy_count, "buy"),
        ("维持观察", view.hold_count, "hold"),
        ("建议回避", view.sell_count, "sell"),
    ]
    if view.veto_count:
        items.append(("风控否决", view.veto_count, "veto"))

    total = max(view.total_stocks, 1)
    stat_rows = []
    legend_rows = []
    for label, count, cls in items:
        width = max(0, round(count / total * 100, 1))
        stat_rows.append(
            f'<div class="pool-stat-row"><div class="num" style="color:{_pool_action_color(cls)}">{count}</div>'
            f'<div style="min-width:74px">{_esc(label)}</div>'
            f'<div class="mix-track"><div class="mix-seg {cls}" style="width:{width}%"></div></div>'
            f'<div style="color:var(--muted)">{width:.0f}%</div></div>'
        )
        legend_rows.append(
            f'<div class="legend-item"><span class="legend-dot {cls}"></span>'
            f'<span>{_esc(label)}</span><span>{count} 只</span></div>'
        )

    return f"""
    <div class="insight-card span-4 reveal reveal-delay-1">
      <div class="section-head">
        <div>
          <div class="section-title">建议分布图</div>
          <div class="section-copy">进攻、观察和规避的比例分布</div>
        </div>
      </div>
      <div class="pool-summary">{''.join(stat_rows)}</div>
      <div class="mix-legend" style="margin-top:1rem;">{''.join(legend_rows)}</div>
    </div>"""


def _render_pool_conviction_chart(view: DivergencePoolView) -> str:
    rows = view.rows[:8]
    if not rows:
        return ""

    bar_w = 56
    gap = 24
    chart_h = 170
    width = 52 + len(rows) * (bar_w + gap)
    height = 250
    bars = []
    for idx, row in enumerate(rows):
        x = 28 + idx * (bar_w + gap)
        bar_h = max(14, int(row.confidence * chart_h))
        y = 28 + (chart_h - bar_h)
        color = _pool_action_color(row.action_class)
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="14" fill="{color}" opacity="0.9"></rect>'
            f'<text x="{x + bar_w / 2:.0f}" y="{y - 10}" text-anchor="middle" fill="#dce9ef" font-size="12" font-weight="700">{row.conviction_pct}%</text>'
            f'<text x="{x + bar_w / 2:.0f}" y="{28 + chart_h + 22}" text-anchor="middle" fill="#7e91a7" font-size="11">{_esc(row.short_ticker)}</text>'
        )

    grid = "".join(
        f'<line x1="18" y1="{28 + i * 42}" x2="{width - 16}" y2="{28 + i * 42}" stroke="rgba(255,255,255,0.08)" stroke-width="1" />'
        for i in range(5)
    )

    return f"""
    <div class="insight-card span-4 reveal reveal-delay-2">
      <div class="section-head">
        <div>
          <div class="section-title">置信度景深图</div>
          <div class="section-copy">各标的结论强弱一览</div>
        </div>
        <div class="score-pill">平均置信度 {view.avg_confidence:.0%}</div>
      </div>
      <div class="conviction-wrap">
        <svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="置信度景深图">
          {grid}
          {''.join(bars)}
        </svg>
      </div>
    </div>"""


def _render_pool_risk_chart(view: DivergencePoolView) -> str:
    categories = view.top_risk_categories[:5]
    if not categories:
        risk_rows = '<div class="mini-note">当前样本暂未暴露高频风险标签。</div>'
    else:
        top = max(count for _, count in categories)
        risk_rows = "".join(
            f'<div class="risk-row"><span>{_esc(cat)}</span>'
            f'<div class="risk-bar"><div class="risk-fill" style="width:{max(12, int(count / top * 100))}%"></div></div>'
            f'<span>{count} 次</span></div>'
            for cat, count in categories
        )

    return f"""
    <div class="insight-card span-4 reveal reveal-delay-3">
      <div class="section-head">
        <div>
          <div class="section-title">风险热度图</div>
          <div class="section-copy">高频风险类别汇总</div>
        </div>
        <div class="score-pill">总风险标签 {view.risk_alert_count}</div>
      </div>
      <div class="risk-list">{risk_rows}</div>
    </div>"""


def _render_pool_table(view: DivergencePoolView) -> str:
    rows_html = ""
    for idx, row in enumerate(view.rows, start=1):
        risk_text = "、".join(row.primary_risk_categories) if row.primary_risk_categories else "风险较轻"
        divergence = f"多 {row.bull_score:.2f} / 空 {row.bear_score:.2f}"
        metrics = " · ".join(
            part for part in [
                f"PE {row.pe}" if row.pe else "",
                f"PB {row.pb}" if row.pb else "",
                f"市值 {row.market_cap}亿" if row.market_cap else "",
            ] if part
        ) or "估值指标待补充"
        rows_html += f"""
        <tr data-action="{row.action.upper()}">
          <td><span class="rank-pill">{idx:02d}</span></td>
          <td>
            <div style="font-weight:700">{_esc(row.display_name)}</div>
            <div style="color:var(--muted); font-size:.78rem;">{_esc(row.risk_state_label)}</div>
          </td>
          <td><span class="badge badge-{row.action_class}">{get_signal_emoji(row.action)} {_esc(row.action_label)}</span></td>
          <td>{row.conviction_pct}%</td>
          <td>{_esc(divergence)}</td>
          <td>{_esc(metrics)}</td>
          <td>{_esc(risk_text)}</td>
        </tr>"""

    return f"""
    <div class="board-card reveal" id="table">
      <div class="section-head">
        <div>
          <div class="section-title">决策总表</div>
          <div class="section-copy">按优先级排列，点击标的可下钻至个股卡片</div>
        </div>
      </div>
      <table class="priority-table">
        <thead>
          <tr>
            <th>优先级</th>
            <th>标的</th>
            <th>结论</th>
            <th>置信度</th>
            <th>多空分歧</th>
            <th>估值速览</th>
            <th>关键风险</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""


def _render_claim_panel(title: str, side: str, claims: list, empty_text: str) -> str:
    if not claims:
        icon = "\U0001f4cb" if side == "bull" else "\U0001f4cb"
        claims_html = _empty_state(icon, empty_text)
    else:
        parts = []
        for claim in claims:
            supports = claim.get("supports", [])
            evidence = ", ".join(str(s) for s in supports[:2]) if supports else "结构化主张"
            parts.append(
                f'<div class="claim-item"><div>{_esc(claim.get("text", ""))}</div>'
                f'<div class="claim-meta"><span>{_esc(evidence)}</span><span>{claim.get("confidence", 0):.0%}</span></div></div>'
            )
        claims_html = "".join(parts)
    return f"""
    <div class="claim-panel {side}">
      <h4>{_esc(title)}</h4>
      <div class="claim-stack">{claims_html}</div>
    </div>"""


def _render_sparkline(
    prices: list,
    width: int = 120,
    height: int = 36,
) -> str:
    """Render a mini SVG sparkline from close prices. Returns '' if <2 prices."""
    if len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng = mx - mn or 1
    step = width / (len(prices) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - (p - mn) / rng * (height - 4) - 2:.1f}"
        for i, p in enumerate(prices)
    )
    # Color by direction: green rising, red falling, blue flat
    if prices[-1] > prices[0] * 1.005:
        color = "#34d399"
    elif prices[-1] < prices[0] * 0.995:
        color = "#f87171"
    else:
        color = "#60a5fa"

    change = (prices[-1] / prices[0] - 1) * 100 if prices[0] else 0
    sign = "+" if change > 0 else ""
    return (
        f'<div class="sparkline-wrap">'
        f'<svg class="sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
        f'<span class="sparkline-label" style="color:{color}">'
        f'{sign}{change:.1f}%</span>'
        f'</div>'
    )
def _render_cover_page(view: DivergencePoolView) -> str:
    """Full-viewport cover page for print/export."""
    return f"""
    <section class="cover-page">
      <div class="cover-content">
        <div class="cover-logo">{_BRAND_LOGO_LG}</div>
        <div class="cover-title">多空分歧池</div>
        <div class="cover-subtitle">研究报告 · 多空分歧横向对比</div>
        <div class="cover-date">{_esc(view.trade_date)}</div>
        <div class="cover-meta">{view.total_stocks} 只标的覆盖 · 平均置信度 {view.avg_confidence:.0%} · 风险标签 {view.risk_alert_count}</div>
        <div class="cover-disclaimer">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。</div>
      </div>
    </section>"""


def render_divergence_pool(
    view: DivergencePoolView,
    heatmap_data=None,
    market_context: dict = None,
) -> str:
    """Render multi-stock divergence pool as a standalone HTML page."""
    market_context = market_context or {}

    # Market summary banner
    market_banner = ""
    if market_context.get("client_summary"):
        regime = market_context.get("regime", "NEUTRAL")
        r_label = get_regime_label(regime)
        r_class = get_regime_class(regime)
        market_banner = f"""
    <div class="market-summary-banner">
      <span class="regime-badge {r_class}">{_esc(r_label)}</span>
      <span>{_esc(market_context['client_summary'])}</span>
    </div>"""

    # Heatmap section
    heatmap_section = ""
    heatmap_drawer = ""
    heatmap_js = ""
    if heatmap_data:
        hd = heatmap_data.to_dict() if hasattr(heatmap_data, "to_dict") else heatmap_data
        heatmap_section = f"""
    <section class="heatmap-section reveal" id="heatmap">
      <div class="section-head">
        <div class="section-title">热力图</div>
        <div class="section-copy">点击色块查看个股详情</div>
      </div>
      <div class="hm-toolbar">
        <button class="hm-toggle active" id="hmModeReturn" data-mode="return">涨跌幅</button>
        <button class="hm-toggle" id="hmModeRisk" data-mode="risk">置信度</button>
      </div>
      {_render_heatmap_legend()}
      <div class="heatmap-wrap">
        {_render_svg_heatmap(hd)}
      </div>
    </section>"""
        heatmap_drawer = _render_detail_drawer()
        heatmap_js = _render_heatmap_js()

    hero = f"""
    <section class="hero reveal" id="top">
      <div class="hero-grid">
        <div>
          <div class="eyebrow"><span class="brand-mark">{_BRAND_LOGO_SM} TradingAgents</span> · 研究报告</div>
          <h1>多空分歧池</h1>
          <p class="hero-copy">多空分歧、风险审查与估值锚点的横向对比</p>
          <div class="hero-chips">
            <span class="hero-chip">交易日 {_esc(view.trade_date)}</span>
            <span class="hero-chip">{view.total_stocks} 只标的覆盖</span>
            <span class="hero-chip">平均置信度 {view.avg_confidence:.0%}</span>
            <span class="hero-chip">风险标签 {view.risk_alert_count}</span>
          </div>
          <div class="anchor-nav">
            <a class="anchor-link" href="#overview">总览</a>
            <a class="anchor-link" href="#charts">图表</a>
            <a class="anchor-link" href="#table">总表</a>
            <a class="anchor-link" href="#cards">个股卡片</a>
          </div>
        </div>
        <div class="hero-spotlights">
          {_pool_spotlight_card("进攻首选", view.featured_long, "当前样本未出现明确关注标的。", "bull")}
          {_pool_spotlight_card("观察焦点", view.featured_watch, "当前样本没有单独的观察名单。", "bull")}
          {_pool_spotlight_card("风险规避", view.featured_short, "当前样本未出现明确规避标的。", "bear")}
        </div>
      </div>
    </section>"""

    kpis = f"""
    <section class="kpi-deck reveal reveal-delay-1" id="overview">
      <div class="kpi-panel neutral">
        <div class="kpi-value">{view.total_stocks}</div>
        <div class="kpi-title">标的总数</div>
        <div class="kpi-note">本期覆盖标的</div>
      </div>
      <div class="kpi-panel buy">
        <div class="kpi-value">{view.buy_count}</div>
        <div class="kpi-title">建议关注</div>
        <div class="kpi-note">多空共振且置信度较高</div>
      </div>
      <div class="kpi-panel hold">
        <div class="kpi-value">{view.hold_count}</div>
        <div class="kpi-title">维持观察</div>
        <div class="kpi-note">适合做条件触发式跟踪</div>
      </div>
      <div class="kpi-panel sell">
        <div class="kpi-value">{view.sell_count + view.veto_count}</div>
        <div class="kpi-title">规避 / 否决</div>
        <div class="kpi-note">风控否决或看空主导</div>
      </div>
    </section>"""

    charts = f"""
    <section class="section-grid" id="charts">
      {_render_pool_mix_chart(view)}
      {_render_pool_conviction_chart(view)}
      {_render_pool_risk_chart(view)}
    </section>"""

    cards = []
    for row in view.rows:
        metrics_rows = "".join(
            f"<tr><td>{label}</td><td>{_esc(value or '—')}</td></tr>"
            for label, value in [
                ("结论", row.action_label),
                ("置信度", f"{row.conviction_pct}%"),
                ("PE", row.pe),
                ("PB", row.pb),
                ("市值", f"{row.market_cap}亿" if row.market_cap else ""),
                ("风控", row.risk_state_label),
            ]
        )
        risk_tags = "".join(
            _pool_badge(
                f'{get_severity_label(rf.get("severity", ""))} {get_risk_label(rf.get("category", ""))}'.strip(),
                _pool_severity_class(rf.get("severity", "")),
            )
            for rf in row.risk_flags
        ) or _empty_state("\U0001f50d", "暂无显式风险标签")

        signal_bull = int(round(row.bull_ratio * 100))
        signal_bear = 100 - signal_bull
        cards.append(f"""
        <article class="stock-card {row.action_class} reveal" data-action="{row.action.upper()}" id="stock-{_esc(row.short_ticker)}">
          <div class="stock-top">
            <div>
              <div class="stock-kicker">{_esc(row.short_ticker)}</div>
              <div class="stock-name">{_esc(row.display_name)}</div>
              <div class="stock-sub">{_esc(row.risk_state_label)}</div>
            </div>
            <div class="stock-side">
              <div class="stock-verdict" style="color:{_pool_action_color(row.action_class)}">{_esc(row.action_label)}</div>
              <div class="stock-confidence">置信度 {row.conviction_pct}%</div>
              {_render_sparkline(row.sparkline_prices)}
            </div>
          </div>
          <div class="signal-card">
            <div class="signal-head">
              <span>多空强度图</span>
              <span>看多 {row.bull_score:.2f} / 看空 {row.bear_score:.2f}</span>
            </div>
            <div class="signal-meter">
              <div class="signal-bull" style="width:{signal_bull}%"></div>
              <div class="signal-bear" style="width:{signal_bear}%"></div>
            </div>
            <div class="signal-labels">
              <span>看多占比 {signal_bull}%</span>
              <span>看空占比 {signal_bear}%</span>
            </div>
          </div>
          <div class="stock-body">
            {_render_claim_panel("看多核心论据", "bull", row.bull_claims, "暂无结构化看多论据")}
            {_render_claim_panel("看空核心论据", "bear", row.bear_claims, "暂无结构化看空论据")}
            <div class="metric-panel">
              <h4>核心指标</h4>
              <table class="metric-table">{metrics_rows}</table>
              <h4>风险标签</h4>
              <div class="risk-tags">{risk_tags}</div>
            </div>
          </div>
        </article>""")

    methodology = """
    <section class="method-card reveal">
      <div class="section-head">
        <div>
          <div class="section-title">阅读指南</div>
          <div class="section-copy">报告结构与使用说明</div>
        </div>
      </div>
      <div class="method-list">
        <div class="method-item"><span class="method-index">1</span><div>顶部为组合级结论：建议分布图、置信度景深图与风险热度图，呈现整体研判基调。</div></div>
        <div class="method-item"><span class="method-index">2</span><div>中部决策总表按优先级横向对比全部标的，支持快速定位。</div></div>
        <div class="method-item"><span class="method-index">3</span><div>底部个股卡片逐只展示多空论据、估值指标与风险标签。</div></div>
      </div>
    </section>"""

    cover = _render_cover_page(view)

    brand_footer = f"""
    <footer class="brand-footer">
      <div class="brand-footer-left">{_BRAND_LOGO_SM} TradingAgents · AI 多智能体研究系统</div>
      <div class="brand-footer-right">报告日期 {_esc(view.trade_date)} · v0.2.0 · 仅供研究参考</div>
    </footer>"""

    filter_bar = f"""
    <nav class="filter-bar" id="filter-bar">
      <span class="filter-label">筛选</span>
      <button class="filter-btn active" data-filter="ALL">全部 <span class="f-count">{view.total_stocks}</span></button>
      <button class="filter-btn" data-filter="BUY">建议关注 <span class="f-count">{view.buy_count}</span></button>
      <button class="filter-btn" data-filter="HOLD">维持观察 <span class="f-count">{view.hold_count}</span></button>
      <button class="filter-btn" data-filter="SELL">建议回避 <span class="f-count">{view.sell_count}</span></button>
      {'<button class="filter-btn" data-filter="VETO">风控否决 <span class="f-count">' + str(view.veto_count) + '</span></button>' if view.veto_count else ''}
      <span class="filter-status" id="filter-status">显示 {view.total_stocks}/{view.total_stocks}</span>
    </nav>"""

    filter_js = """
    <script>
    (function(){
      var bar = document.getElementById('filter-bar');
      if (!bar) return;
      var status = document.getElementById('filter-status');
      var cards = document.querySelectorAll('.stock-card[data-action]');
      var rows = document.querySelectorAll('.priority-table tr[data-action]');
      var total = cards.length;

      bar.addEventListener('click', function(e) {
        var btn = e.target.closest('.filter-btn');
        if (!btn) return;
        var filter = btn.getAttribute('data-filter');

        bar.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');

        var shown = 0;
        cards.forEach(function(card) {
          var match = filter === 'ALL' || card.getAttribute('data-action') === filter;
          card.style.display = match ? '' : 'none';
          if (match) shown++;
        });
        rows.forEach(function(row) {
          var match = filter === 'ALL' || row.getAttribute('data-action') === filter;
          row.style.display = match ? '' : 'none';
        });

        if (status) status.textContent = '显示 ' + shown + '/' + total;
      });
    })();
    </script>"""

    body = f"""
    {cover}
    <div class="pool-shell">
      {hero}
      <div class="banner">本报告由 AI 多智能体系统自动生成，仅供研究参考，不构成投资建议。使用前请结合人工判断。</div>
      {market_banner}
      {filter_bar}
      {heatmap_section}
      {kpis}
      {charts}
      {_render_pool_table(view)}
      <section class="stock-grid" id="cards">{''.join(cards)}</section>
      {methodology}
      {brand_footer}
    </div>
    {heatmap_drawer}
    {filter_js}
    {heatmap_js}"""

    return _html_wrap(
        f"多空分歧池 — {view.trade_date}",
        body, "多空分歧池",
        extra_css=_POOL_CSS + _MARKET_CSS,
    )


def generate_pool_report(
    run_ids: list,
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    trade_date: str = "",
    market_context: dict = None,
    market_snapshot=None,
) -> Optional[str]:
    """Generate multi-stock divergence pool report.

    Args:
        run_ids: List of run IDs to include.
        output_dir: Where to write HTML.
        storage_dir: Where RunTrace data is stored.
        trade_date: Override trade date for title.
        market_context: Market context dict for heatmap overlay.
        market_snapshot: MarketSnapshot for spot data.

    Returns:
        Path to generated HTML file, or None.
    """
    from ..replay_store import ReplayStore
    from ..replay_service import ReplayService

    store = ReplayStore(storage_dir=storage_dir)
    svc = ReplayService(store=store)

    view = DivergencePoolView.build(svc, run_ids, trade_date=trade_date)
    if not view.rows:
        return None

    # Override sector_momentum with snapshot's actual price-change data.
    # The LLM agent's sector_momentum is sorted by net_inflow which is
    # misleading (sectors can have inflow yet fall in price).  The snapshot
    # sector_fund_flow is now sorted by actual 涨跌幅, which is ground truth.
    if market_context and market_snapshot:
        market_context = copy.copy(market_context)  # avoid mutating caller's dict
        sector_flow = getattr(market_snapshot, "sector_fund_flow", [])
        if sector_flow:
            refreshed = []
            for s in sector_flow:
                pct = s.get("change_pct", 0) or 0
                net = s.get("net_inflow", 0) or 0
                refreshed.append({
                    "name": s.get("name", ""),
                    "flow": str(round(pct, 2)),       # use price change for color
                    "net_inflow_yi": round(net / 1e8, 2) if abs(net) > 1e6 else 0,
                    "direction": "in" if pct > 0 else "out",
                })
            market_context["sector_momentum"] = refreshed
            market_context.pop("_sector_momentum_inflow_only", None)

    # Build heatmap data if market context available
    heatmap_data = None
    if market_context or market_snapshot:
        from ..heatmap import HeatmapData
        spot_data = getattr(market_snapshot, "stock_spots", {}) if market_snapshot else {}
        heatmap_data = HeatmapData.build_from_pool(
            view,
            market_context=market_context or {},
            spot_data=spot_data,
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    date_slug = view.trade_date.replace("-", "")
    path = out_dir / f"pool-{date_slug}-{view.total_stocks}stocks.html"
    path.write_text(
        render_divergence_pool(view, heatmap_data=heatmap_data, market_context=market_context),
        encoding="utf-8",
    )
    return str(path)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Market Page — extracted to market_renderer.py                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .market_renderer import (  # noqa: E402 — re-export for backward compat
    _MARKET_CSS,
    _TREEMAP_ENGINE_JS,
    _heatmap_color,
    _heatmap_risk_color,
    _render_heatmap_legend,
    _render_svg_heatmap,
    _render_detail_drawer,
    _render_heatmap_js,
    _render_inline_treemap,
    _render_plotly_sector_treemap,
    _render_plotly_stock_treemap,
    _regime_color,
    _mkt_regime_icon,
    _css_cls,
    _render_mkt_hero,
    _render_idx_battle_cards,
    _render_sentiment_ecosystem,
    _render_sector_engine,
    _render_limit_universe,
    _render_battle_brief,
    render_market_page,
    generate_market_report,
)



# ── Feature 4: Brief Report ─────────────────────────────────────────────

def generate_brief_report(
    run_ids: list,
    storage_dir: str = "data/replays",
    trade_date: str = "",
) -> str:
    """Generate concise markdown brief -- one line per stock, suitable for push.

    Groups stocks by action (BUY first, HOLD, SELL, VETO).
    Returns markdown string.
    """
    from ..replay_store import ReplayStore

    store = ReplayStore(storage_dir=storage_dir)

    entries = []
    for run_id in run_ids:
        trace = store.load(run_id)
        if not trace:
            continue
        action = (trace.research_action or "HOLD").upper()
        entries.append({
            "ticker": trace.ticker,
            "name": getattr(trace, "ticker_name", ""),
            "action": action,
            "confidence": trace.final_confidence,
            "was_vetoed": trace.was_vetoed,
            "trade_date": trace.trade_date,
        })

    if not trade_date and entries:
        trade_date = entries[0].get("trade_date", "")

    # Group by action in priority order
    order = {"BUY": 0, "HOLD": 1, "SELL": 2, "VETO": 3}
    entries.sort(key=lambda e: (order.get(e["action"], 9), -e.get("confidence", 0)))

    counts = {}
    for e in entries:
        counts[e["action"]] = counts.get(e["action"], 0) + 1

    lines = [
        f"# \u7814\u7a76\u7b80\u62a5 {trade_date}",
        f"",
        f"\u6807\u7684\u6570: {len(entries)} | "
        + " / ".join(f"{get_action_label(a)} {c}" for a, c in sorted(counts.items(), key=lambda x: order.get(x[0], 9))),
        f"",
    ]

    current_action = None
    for e in entries:
        if e["action"] != current_action:
            current_action = e["action"]
            emoji = get_signal_emoji(current_action)
            lines.append(f"## {emoji} {get_action_label(current_action)}")
            lines.append("")

        emoji = get_signal_emoji(e["action"])
        conf = e.get("confidence", 0)
        name = e.get("name", "")
        ticker = e.get("ticker", "")
        display = f"{ticker} {name}" if name else ticker
        label = get_action_label(e["action"])
        lines.append(f"- {emoji} **{display}** | {label} ({conf:.0%})")

    lines.append("")
    lines.append("---")
    lines.append("*AI \u591a\u667a\u80fd\u4f53\u7cfb\u7edf\u81ea\u52a8\u751f\u6210\uff0c\u4ec5\u4f9b\u7814\u7a76\u53c2\u8003*")

    return "\n".join(lines)


def generate_brief_report_file(
    run_ids: list,
    storage_dir: str = "data/replays",
    output_dir: str = "data/reports",
    trade_date: str = "",
) -> Optional[str]:
    """Generate brief report and write to data/reports/brief-{date}.md.

    Returns path to generated file, or None if no runs.
    """
    content = generate_brief_report(run_ids, storage_dir=storage_dir, trade_date=trade_date)
    if not content or not run_ids:
        return None

    # Extract date from content header
    if not trade_date:
        # Try to extract from first line
        for line in content.split("\n"):
            if line.startswith("# "):
                parts = line.split()
                if parts:
                    trade_date = parts[-1]
                break

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    date_slug = trade_date.replace("-", "") if trade_date else "unknown"
    path = out_dir / f"brief-{date_slug}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
