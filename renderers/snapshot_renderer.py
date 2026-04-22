"""
Tier 1 Snapshot report renderer.

Conclusion + signals + risk — single screen.
Consumes SnapshotView from views.py, never raw traces.
All user-facing text is in Chinese (A-share product).

Extracted from report_renderer.py to reduce file size.
"""

from .views import (
    SnapshotView,
    _strip_internal_tokens,
)
from .decision_labels import (
    get_action_label, get_action_class,
    get_soft_action_label,
    get_risk_label, get_node_label,
    get_signal_emoji, PILLAR_EMOJI,
    get_severity_label,
    safe_badge_class,
    AI_DISCLAIMER_BANNER,
)
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light, _strip_preamble,
    _empty_state, _format_price_zone, _evidence_strength_label,
    _degraded_banner, _bull_bear_bar, _direction_badge, _radar_svg,
    _trend_arrow, _sparkline_svg, _nav_bar,
    _confidence_ring_svg, _priority_chip, _score_pill,
    _delta_arrow, _section_divider,
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
        targets_raw = [{"label": "\u76ee\u6807", "price_zone": [targets_raw]}]
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
        <div class="eyebrow">\u8f93\u51fa\u8d28\u91cf\u9000\u5316 &middot; \u5feb\u901f\u53c2\u8003</div>
        <div class="hero-action" style="color:var(--{color_var});">
          {_sig_emoji_d} {_esc(view.action_label)}
        </div>
        <div style="margin-top:.5rem;color:var(--muted);font-family:var(--mono);">\u7f6e\u4fe1\u5ea6 {f'{view.confidence:.0%}' if view.confidence >= 0 else '\u2014'}</div>
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
                        text += f" \u2014 {_esc(_strip_internal_tokens(desc[:80]))}"
                    items += f"<li>{text}</li>"
            if items:
                risks_html = f'<div class="card"><h3>\u4e3b\u8981\u98ce\u9669</h3><ul>{items}</ul></div>'

        # Metrics fallback card (independent of parse quality)
        degraded_chart = ""
        if view.metrics_fallback:
            fb = view.metrics_fallback
            kpis = []
            for key, label in [("pe", "PE(TTM)"), ("pb", "PB"), ("roe", "ROE(%)"),
                                ("gross_margin", "\u6bdb\u5229\u7387(%)"), ("market_cap", "\u603b\u5e02\u503c(\u4ebf)"),
                                ("eps", "EPS"), ("net_profit", "\u51c0\u5229\u6da6")]:
                val = fb.get(key)
                if val is not None:
                    kpis.append(f'<div class="kpi"><span class="kpi-val">{_esc(str(val))}</span><span class="kpi-label">{_esc(label)}</span></div>')
            if kpis:
                degraded_chart = f'<div class="card"><h3>\u57fa\u672c\u9762\u901f\u89c8</h3><div class="kpi-row">{"".join(kpis)}</div></div>'

        body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u7814\u7a76\u5feb\u7167</p>
    <div class="banner">{AI_DISCLAIMER_BANNER}</div>
    {_degraded_banner(view.degradation_reasons)}
    {conclusion}
    {degraded_chart}
    {risks_html}"""

        return _html_wrap(f"{_ticker_display(view)} \u7814\u7a76\u5feb\u7167 \u2014 {view.trade_date}", body, "\u7814\u7a76\u5feb\u7167", extra_head=_COUNTUP_JS)

    # ── Normal Mode ──
    _sig_emoji = get_signal_emoji(view.research_action)
    conf_pct = int(view.confidence * 100)

    # V4: Hero right-side — confidence ring replaces primary text KPI (more scannable);
    # secondary KPIs in compact 3-col grid; pp-delta arrow only when meaningful.
    hero_kpis = []
    _conf_ring_html = ""
    _conf_delta_html = ""
    if view.confidence >= 0:
        _ring_label = "\u7f6e\u4fe1\u5ea6"
        if getattr(view, "confidence_defaulted", False):
            _ring_label = "\u7f6e\u4fe1\u5ea6(\u9ed8\u8ba4)"
        _conf_ring_html = _confidence_ring_svg(view.confidence, size=100, label=_ring_label)
        if view.previous_confidence >= 0:
            _cdiff = view.confidence - view.previous_confidence
            if abs(_cdiff) >= 0.005:
                sign = "+" if _cdiff > 0 else ""
                cls = "up" if _cdiff > 0 else "down"
                ico = "\u25b2" if _cdiff > 0 else "\u25bc"
                _conf_delta_html = (
                    f'<span class="delta-arr {cls}" role="img" aria-label="confidence delta">'
                    f'<span aria-hidden="true">{ico}</span>{sign}{_cdiff*100:.1f}pp</span>'
                )
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val">{view.total_evidence}</span><span class="kpi-label">\u8bc1\u636e\u6761\u6570</span></div>')
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val">{view.attributed_rate:.0%}</span><span class="kpi-label">\u7ed1\u5b9a\u7387</span></div>')
    ev_label = _evidence_strength_label(view.evidence_strength)
    hero_kpis.append(f'<div class="kpi kpi-secondary"><span class="kpi-val" style="font-size:1.2rem">{_esc(ev_label)}</span><span class="kpi-label">\u8bc1\u636e\u5f3a\u5ea6</span></div>')

    # Sparkline from price history
    _sparkline_html = ""
    if getattr(view, "price_history", None) and len(view.price_history) >= 2:
        _sparkline_html = f'<div class="hero-sparkline">{_sparkline_svg(view.price_history)}</div>'

    _ring_block = (
        f'<div style="display:flex;flex-direction:column;align-items:center;gap:.3rem;margin-bottom:.6rem">'
        f'{_conf_ring_html}{_conf_delta_html}'
        f'</div>'
    ) if _conf_ring_html else ""
    hero_kpi_grid = (
        f'{_ring_block}{_sparkline_html}'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;">{"".join(hero_kpis)}</div>'
    )

    conclusion = f"""
    <div class="hero reveal">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="eyebrow">AI \u7814\u7a76\u5feb\u7167 &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.one_line_summary)}</div>
          <div style="font-size:.88rem;color:var(--muted);">{_esc(view.action_explanation)}</div>
          <div style="font-size:.65rem;color:var(--muted);margin-top:.3rem;">\u4fe1\u53f7\u8272: <span style="color:var(--red)">\u25cf</span> \u6da8/\u79ef\u6781 <span style="color:var(--green)">\u25cf</span> \u8dcc/\u6d88\u6781</div>
        </div>
        <div class="hero-right">
          {hero_kpi_grid}
        </div>
      </div>
    </div>"""

    # ── V4: Status bar as priority-chip row (multi-level severity, not binary lights) ──
    _risk_lvl = "cool" if view.risk_cleared else "hot"
    _risk_txt = ("\u98ce\u63a7\u901a\u8fc7" if view.risk_cleared else "\u98ce\u63a7\u672a\u901a\u8fc7")
    _comp_ok = view.compliance_status in ("allow", "")
    _comp_lvl = "cool" if _comp_ok else ("warm" if view.compliance_status in ("warn", "defer") else "hot")
    _comp_txt = ("\u5408\u89c4\u901a\u8fc7" if _comp_ok else ("\u5408\u89c4" + view.compliance_status))
    _fresh_lvl = "cool" if view.freshness_ok else "warm"
    _fresh_txt = ("\u6570\u636e\u65b0\u9c9c" if view.freshness_ok else "\u6570\u636e\u8fc7\u671f")
    if view.was_vetoed:
        _veto_lvl = "hot"
        _src = getattr(view, "veto_source", "")
        _veto_txt = (
            "\u98ce\u63a7\u95e8\u7981" if _src == "risk_gate"
            else ("\u7814\u7a76\u5426\u51b3" if _src == "agent_veto" else "\u88ab\u5426\u51b3")
        )
    else:
        _veto_lvl, _veto_txt = "cool", "\u5426\u51b3\u65e0"
    lights_html = f"""
    <div class="status-bar reveal reveal-d1" style="gap:.6rem">
      {_priority_chip(_risk_lvl, _risk_txt)}
      {_priority_chip(_comp_lvl, _comp_txt)}
      {_priority_chip(_fresh_lvl, _fresh_txt)}
      {_priority_chip(_veto_lvl, _veto_txt)}
    </div>"""

    # ── Fundamentals metrics card ──
    chart_html = ""
    if view.metrics_fallback:
        fb = view.metrics_fallback
        kpis = []
        label_map = [
            ("pe", "PE(TTM)"), ("pb", "PB"), ("roe", "ROE(%)"),
            ("gross_margin", "\u6bdb\u5229\u7387(%)"), ("market_cap", "\u603b\u5e02\u503c(\u4ebf)"),
            ("eps", "EPS"), ("net_profit", "\u51c0\u5229\u6da6"),
        ]
        for key, label in label_map:
            val = fb.get(key)
            if val is not None:
                kpis.append(f'<div class="kpi"><span class="kpi-val">{_esc(str(val))}</span><span class="kpi-label">{_esc(label)}</span></div>')
        if kpis:
            chart_html = f'<div class="card reveal reveal-d2"><h3>\u57fa\u672c\u9762\u901f\u89c8</h3><div class="kpi-row">{"".join(kpis)}</div></div>'

    # Core drivers
    drivers_html = ""
    if view.core_drivers:
        items = "".join(f"<li>{_esc(d[:120])}</li>" for d in view.core_drivers)
        drivers_html = f'<div class="card reveal reveal-d3"><h3>\u6838\u5fc3\u9a71\u52a8</h3><ul>{items}</ul></div>'
    else:
        drivers_html = f'<div class="card reveal reveal-d3"><h3>\u6838\u5fc3\u9a71\u52a8</h3>{_empty_state("\U0001f4ca", "\u6682\u65e0\u6838\u5fc3\u9a71\u52a8\u6570\u636e", "\u5206\u6790\u7ed3\u679c\u672a\u4ea7\u751f\u7ed3\u6784\u5316\u9a71\u52a8\u56e0\u7d20")}</div>'

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
                    text += f" \u2014 {_esc(_strip_internal_tokens(desc[:80]))}"
                items += f"<li>{text}</li>"
            else:
                items += f"<li>{_esc(str(r))}</li>"
        risks_html = f'<div class="card reveal reveal-d3"><h3>\u4e3b\u8981\u98ce\u9669</h3><ul>{items}</ul></div>'

    # Evidence strength + Bull/Bear bar
    evidence_html = f"""
    <div class="card reveal reveal-d4">
      <h3>\u8bc1\u636e\u5f3a\u5ea6</h3>
      <div style="display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;margin-bottom:.5rem;">
        <span class="badge badge-{view.evidence_strength_class}">{_esc(ev_label)}</span>
        <span style="font-size:.85rem;color:var(--muted);">{view.total_evidence} \u6761\u8bc1\u636e &middot; {view.attributed_rate:.0%} \u8bba\u636e-\u8bc1\u636e\u7ed1\u5b9a\u7387</span>
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
        catalyst_html = f'<div class="card reveal reveal-d5"><h3>\u8fd1\u671f\u50ac\u5316\u5242</h3><ul>{items}</ul></div>'
    else:
        catalyst_html = f'<div class="card reveal reveal-d5"><h3>\u8fd1\u671f\u50ac\u5316\u5242</h3>{_empty_state("\u26a1", "\u6682\u65e0\u50ac\u5316\u5242\u4fe1\u606f", "\u672a\u68c0\u6d4b\u5230\u8fd1\u671f\u91cd\u5927\u4e8b\u4ef6\u6216\u65f6\u95f4\u8282\u70b9")}</div>'

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
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u7814\u7a76\u5feb\u7167</p>
    <div class="banner">{AI_DISCLAIMER_BANNER}</div>
    {conclusion}
    {lights_html}
    {battle_plan_html}
    {_mc("\u57fa\u672c\u9762\u901f\u89c8", chart_html)}
    {_mc("\u6838\u5fc3\u9a71\u52a8 / \u98ce\u9669", f'<div class="cols"><div>{drivers_html}</div><div>{risks_html}</div></div>')}
    {_mc("\u8bc1\u636e\u5f3a\u5ea6", evidence_html)}
    {_mc("\u4fe1\u53f7\u6838\u9a8c", checklist_html)}
    {_mc("\u98ce\u63a7\u8fa9\u8bba", risk_debate_html)}
    {_mc("\u50ac\u5316\u5242", catalyst_html)}
    {_mc("\u4fe1\u53f7\u5386\u53f2", signal_history_html)}"""

    nav = _nav_bar(view.ticker, view.run_id, "snapshot")
    return _html_wrap(f"{_ticker_display(view)} \u7814\u7a76\u5feb\u7167 \u2014 {view.trade_date}", body, "\u7814\u7a76\u5feb\u7167", nav_html=nav)
