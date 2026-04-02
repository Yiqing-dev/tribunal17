"""
Three-tier HTML report renderer.

Same evidence chain, three compression levels:
- Tier 1 (Snapshot): Conclusion + signals + risk — single screen
- Tier 2 (Research): Bull/bear + evidence + scenarios + thesis — 3-6 pages
- Tier 3 (Audit):    Evidence chains + replay + parser + compliance — deep dive

All renderers consume view models from views.py, never raw traces.
All user-facing text is in Chinese (A-share product).
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .views import (
    SnapshotView, ResearchView, AuditView, MarketView,
    _strip_internal_tokens,
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
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light, _strip_preamble,
    _empty_state, _format_price_zone, _evidence_strength_label,
    _degraded_banner, _bull_bear_bar, _direction_badge, _radar_svg,
    _squarify,
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



# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Pool Page — extracted to pool_renderer.py                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .pool_renderer import (  # noqa: E402 — re-export for backward compat
    _POOL_CSS,
    _pool_action_color,
    _pool_severity_class,
    _pool_badge,
    _pool_spotlight_card,
    _render_pool_mix_chart,
    _render_pool_conviction_chart,
    _render_pool_risk_chart,
    _render_pool_table,
    _render_claim_panel,
    _render_sparkline,
    _render_cover_page,
    render_divergence_pool,
    generate_pool_report,
)



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
