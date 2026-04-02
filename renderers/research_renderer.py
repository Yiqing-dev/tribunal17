"""
Tier 2 Research report renderer.

Bull/bear + evidence + scenarios + thesis -- 3-6 pages.
Consumes ResearchView from views.py, never raw traces.
All user-facing text is in Chinese (A-share product).

Extracted from report_renderer.py to reduce file size.
"""

from .views import (
    ResearchView,
    _strip_internal_tokens,
)
from .decision_labels import (
    get_action_label, get_action_class, get_action_explanation,
    get_soft_action_label,
    get_thesis_label, get_risk_label, get_node_label, get_dimension_label,
    get_signal_emoji,
    safe_badge_class, get_severity_label,
)
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _strip_preamble,
    _format_price_zone, _degraded_banner,
)


# ── Tier 2 Degraded Mode ───────────────────────────────────────────────

def _render_research_degraded(view: ResearchView) -> str:
    """Render degraded Tier 2 -- warning banner + synthesis + risk only."""
    color_var = 'green' if view.action_class == 'buy' else ('red' if view.action_class in ('sell', 'veto') else 'yellow')

    _sig_emoji_rd = get_signal_emoji(view.research_action)
    exec_summary = f"""
    <div class="hero">
      <div style="text-align:center;position:relative;z-index:1;">
        <div class="eyebrow">\u8f93\u51fa\u8d28\u91cf\u9000\u5316 &middot; \u6df1\u5ea6\u7814\u7a76</div>
        <div class="hero-action" style="color:var(--{color_var});">
          {_sig_emoji_rd} {_esc(view.action_label)}
        </div>
        <div style="margin-top:.5rem;color:var(--muted);font-family:var(--mono);">
          \u7f6e\u4fe1\u5ea6 {f'{view.confidence:.0%}' if view.confidence >= 0 else '\u2014'} &middot;
          \u98ce\u9669\u8bc4\u5206 {view.risk_score if view.risk_score is not None else '\u65e0'}/10
        </div>
      </div>
    </div>"""

    # Only show synthesis if available
    synth_html = ""
    if view.synthesis_excerpt:
        clean_excerpt = _strip_preamble(_strip_internal_tokens(view.synthesis_excerpt[:300]))
        synth_html = f"""
    <div class="card">
      <h3>\u7efc\u5408\u7814\u5224</h3>
      <div style="font-size:.95rem;">{_esc(clean_excerpt)}</div>
    </div>"""

    # Risk summary (kept brief)
    risk_html = ""
    if view.risk_flag_count > 0 or view.risk_flags_detail:
        risk_content = ""
        if view.risk_flags_detail:
            items = "".join(
                f"<li>{_esc(f.get('category', ''))} \u2014 {_esc(_strip_internal_tokens(f.get('description', '')[:100]))}</li>"
                for f in view.risk_flags_detail
            )
            risk_content = f"<ul>{items}</ul>"
        else:
            risk_content = f"<div>{view.risk_flag_count} \u9879\u98ce\u9669\u6807\u8bb0</div>"
        risk_html = f"""
    <div class="card">
      <h3>\u98ce\u9669\u8bc4\u4f30</h3>
      <div style="margin-bottom:.5rem;">
        \u8bc4\u5206: <strong>{view.risk_score if view.risk_score is not None else '\u65e0'}</strong>/10 &middot;
        \u98ce\u63a7\u901a\u8fc7: <span class="badge badge-{'ok' if view.risk_cleared else 'warn'}">
        {'\u662f' if view.risk_cleared else '\u5426'}</span>
      </div>
      {risk_content}
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u6df1\u5ea6\u7814\u7a76\u62a5\u544a</p>
    <div class="banner">\u672c\u62a5\u544a\u7531 AI \u591a\u667a\u80fd\u4f53\u7cfb\u7edf\u81ea\u52a8\u751f\u6210\uff0c\u4ec5\u4f9b\u7814\u7a76\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002\u4f7f\u7528\u524d\u8bf7\u7ed3\u5408\u4eba\u5de5\u5224\u65ad\u3002</div>
    {_degraded_banner(view.degradation_reasons)}
    {exec_summary}
    {synth_html}
    {risk_html}"""

    return _html_wrap(f"{_ticker_display(view)} \u6df1\u5ea6\u7814\u7a76 \u2014 {view.trade_date}", body, "\u6df1\u5ea6\u7814\u7a76\u62a5\u544a", extra_head=_COUNTUP_JS)


def _render_trade_plan_card(tp: dict) -> str:
    """Render the AI Trade Plan card -- public entry/exit framework.

    Shows 6 key lines: bias, breakout entry, pullback entry, stop loss,
    targets, and invalidation conditions.
    """
    bias = tp.get("bias", "WAIT")
    bias_labels = {"LONG": ("\u504f\u591a", "buy"), "WAIT": ("\u7b49\u5f85", "hold"), "AVOID": ("\u56de\u907f", "sell")}
    bias_label, bias_class = bias_labels.get(bias, ("\u7b49\u5f85", "hold"))

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

    horizon_labels = {"short_swing": "\u77ed\u7ebf\u6ce2\u6bb5", "medium_term": "\u4e2d\u671f\u6301\u6709"}
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
        zone_str = _format_price_zone(zone) if len(zone) >= 2 else "\u2014"
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
        pct_badge = f' <span class="mono" style="color:var(--red);font-size:.85em">(\u6700\u5927\u4e8f\u635f {sl_max_pct:.0%})</span>' if sl_max_pct > 0 else ""
        sl_html = f"""
        <div class="tp-row tp-stop">
          <span class="tp-label">\u6b62\u635f\u4f4d</span>
          <span class="mono num" style="color:var(--red)">{sl_price:.2f}</span>{pct_badge}
          <span class="tp-detail">{sl_rule}</span>
        </div>"""

    # Target rows (targets may be list of dicts, float, or string)
    if isinstance(targets, (int, float)):
        targets = [{"label": "\u76ee\u6807", "price_zone": [targets]}]
    elif not isinstance(targets, list):
        targets = []
    target_rows = ""
    for t in targets[:3]:
        if isinstance(t, dict):
            t_label = _esc(t.get("label", ""))
            t_zone = t.get("price_zone", [])
            t_str = _format_price_zone(t_zone) if len(t_zone) >= 2 else "\u2014"
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
          <div class="tp-section-title" style="color:var(--red)">\u5931\u6548\u6761\u4ef6</div>
          <ul class="tp-inval-list">{items}</ul>
        </div>"""

    return f"""
    <div class="card" style="overflow:hidden;">
      <div style="position:absolute;inset:0 auto auto 0;width:4px;height:100%;background:var(--blue);border-radius:20px 0 0 20px;"></div>
      <div style="padding-left:.6rem;">
        <h3>AI \u4ea4\u6613\u8ba1\u5212</h3>
        <div style="display:flex;gap:.8rem;align-items:center;margin-bottom:.75rem;flex-wrap:wrap">
          <span class="badge badge-{bias_class}" style="font-size:.9rem;padding:5px 16px">{bias_label} ({bias})</span>
          <span style="color:var(--muted);font-size:.85rem;font-family:var(--mono)">\u7f6e\u4fe1\u5ea6 {confidence:.0%}</span>
          <span style="color:var(--muted);font-size:.85rem">{_esc(horizon_label)}</span>
        </div>
        <div class="tp-section-title">\u4e70\u5165\u8bbe\u7f6e</div>
        <table class="tp-table">
          <thead><tr><th>\u7c7b\u578b</th><th>\u4ef7\u683c\u533a\u95f4</th><th>\u89e6\u53d1\u6761\u4ef6</th></tr></thead>
          <tbody>{setup_rows if setup_rows else '<tr><td colspan="3" style="color:var(--muted)">\u5f53\u524d\u4e0d\u5efa\u8bae\u5165\u573a</td></tr>'}</tbody>
        </table>
        {sl_html}
        {target_rows}
        {inval_html}
      </div>
    </div>"""


def render_research(view: ResearchView, skip_vendors: bool = False) -> str:
    """Render Tier 2 Research Report -- cards not essays, zero LLM leakage.

    When is_degraded=True, shows warning banner + synthesis + risk only.
    Hides bull/bear cards, catalysts, scenarios to avoid displaying
    unreliable structured data.
    """

    # ── Degraded Mode: warning + synthesis + risk only ──
    if view.is_degraded:
        return _render_research_degraded(view)

    # Executive summary -- hero cockpit
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
    risk_display = view.risk_score if view.risk_score is not None else '\u2014'

    exec_summary = f"""
    <div class="hero reveal">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="eyebrow">\u6df1\u5ea6\u7814\u7a76\u62a5\u544a &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji_r} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.action_explanation)}</div>
        </div>
        <div class="hero-right">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;">
            {_conf_kpi_r}
            <div class="kpi"><span class="kpi-val">{risk_display}</span><span class="kpi-label">\u98ce\u9669\u8bc4\u5206/10</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_evidence}</span><span class="kpi-label">\u8bc1\u636e</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_claims}</span><span class="kpi-label">\u8bba\u636e</span></div>
          </div>
        </div>
      </div>
    </div>"""

    # ── Detailed financial data ──
    research_chart_html = ""

    # ── Bull/Bear case panels -- claim cards if structured, fallback excerpt ──
    def _case_panel(title: str, claims: list, excerpt: str, evidence: list, color: str) -> str:
        ev_html = ", ".join(_esc(e) for e in evidence[:10]) or "\u65e0\u5f15\u7528"
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
                ev_label = f"{ev_count}\u6761\u8bc1\u636e" if ev_count else "\u65e0\u5f15\u7528"
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
        ev_summary = f"{ev_count_total}\u6761\u5f15\u7528" if ev_count_total else "\u65e0\u5f15\u7528"

        return f"""
        <div class="card">
          <h3 style="color:var(--{color})">{title}</h3>
          {content}
          <div style="margin-top:.5rem; font-size:.85rem; color:var(--muted);">
            {len(claims)} \u6761\u7ed3\u6784\u5316\u8bba\u636e &middot; \u8bc1\u636e: {_esc(ev_summary)}
          </div>
        </div>"""

    bull_html = _case_panel("\u770b\u591a\u8bba\u70b9", view.bull_claims, view.bull_excerpt,
                            view.bull_evidence_ids, "green")
    bear_html = _case_panel("\u770b\u7a7a\u8bba\u70b9", view.bear_claims, view.bear_excerpt,
                            view.bear_evidence_ids, "red")

    # ── PM Synthesis -- structured conclusion + cases ──
    thesis_label = get_thesis_label(view.thesis_effect)
    thesis_ok = view.thesis_effect in ("unchanged", "strengthened", "strengthen", "")

    synth_body = f'<div style="font-size:.95rem; margin:.5rem 0;">{_esc(_strip_internal_tokens(_strip_preamble(view.synthesis_excerpt)[:300]))}</div>'

    if view.synthesis_detail:
        cases = ""
        for key, label in [("base_case", "\u57fa\u51c6\u60c5\u666f"), ("bull_case", "\u4e50\u89c2\u60c5\u666f"), ("bear_case", "\u60b2\u89c2\u60c5\u666f")]:
            text = view.synthesis_detail.get(key, "")
            if text:
                cases += f'<div style="margin:.5rem 0;"><strong>{label}:</strong> {_esc(_strip_internal_tokens(text[:200]))}</div>'
        if cases:
            synth_body += cases

    ev_count = len(view.synthesis_evidence_ids)
    ev_summary = f"{ev_count}\u6761" if ev_count else "\u65e0"

    synthesis_html = f"""
    <div class="card">
      <h3>\u7814\u7a76\u7ecf\u7406\u7efc\u5408\u5224\u65ad</h3>
      <div style="margin-bottom:.5rem;">
        \u8bba\u9898\u72b6\u6001: <span class="badge badge-{'ok' if thesis_ok else 'warn'}">{_esc(thesis_label)}</span>
        &nbsp; \u5f15\u7528\u8bc1\u636e: {_esc(ev_summary)}
      </div>
      {synth_body}
    </div>"""

    # ── Scenario -- horizontal probability bars (CSS-only) ──
    scenario_html = ""
    if view.scenario_probs:
        sp = view.scenario_probs
        base_pct = int(sp.get("base_prob", 0) * 100)
        bull_pct = int(sp.get("bull_prob", 0) * 100)
        bear_pct = int(sp.get("bear_prob", 0) * 100)
        base_arrow = "" if abs(base_pct - 33) < 5 else ("\u25b2" if base_pct > 33 else "\u25bc")
        bull_arrow = "" if abs(bull_pct - 33) < 5 else ("\u25b2" if bull_pct > 33 else "\u25bc")
        bear_arrow = "" if abs(bear_pct - 33) < 5 else ("\u25b2" if bear_pct > 33 else "\u25bc")
        base_tip = _esc(sp.get("base_trigger", "")[:80])
        bull_tip = _esc(sp.get("bull_trigger", "")[:80])
        bear_tip = _esc(sp.get("bear_trigger", "")[:80])
        base_lbl = f"\u57fa\u51c6 {base_pct}%{base_arrow}" if base_pct > 18 else ""
        bull_lbl = f"\u4e50\u89c2 {bull_pct}%{bull_arrow}" if bull_pct > 18 else ""
        bear_lbl = f"\u60b2\u89c2 {bear_pct}%{bear_arrow}" if bear_pct > 18 else ""
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
        <div><strong>\u57fa\u51c6\u89e6\u53d1:</strong> {_esc(sp.get("base_trigger", "")[:150])}</div>
        <div><strong>\u4e50\u89c2\u89e6\u53d1:</strong> {_esc(sp.get("bull_trigger", "")[:150])}</div>
        <div><strong>\u60b2\u89c2\u89e6\u53d1:</strong> {_esc(sp.get("bear_trigger", "")[:150])}</div>
      </div>
    </div>"""
    elif view.scenario_excerpt:
        scenario_html = f"""
    <div class="card">
      <h3>\u60c5\u666f\u5206\u6790</h3>
      <div class="excerpt excerpt-short">{_esc(_strip_internal_tokens(_strip_preamble(view.scenario_excerpt)[:800]))}</div>
    </div>"""

    # ── Risk review -- card-per-flag with severity color ──
    risk_content = ""
    if view.risk_flags_detail:
        for f in view.risk_flags_detail:
            sev_cls = safe_badge_class(f.get("severity_class", ""))
            sev_label = get_severity_label(f.get("severity", ""))
            ev_count = len(f.get("evidence_ids", []))
            ev_label = f"{ev_count}\u6761\u8bc1\u636e" if ev_count else "\u65e0\u5f15\u7528"
            mitigant = f.get("mitigant", "")
            mitigant_html = f'<div style="font-size:.8rem;color:var(--muted);margin-top:.25rem;">\u7f13\u91ca: {_esc(_strip_internal_tokens(mitigant))}</div>' if mitigant else ""
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
      <h3>\u98ce\u9669\u5ba1\u67e5</h3>
      <div style="margin-bottom:.5rem;">
        \u8bc4\u5206: <strong>{view.risk_score if view.risk_score is not None else '\u65e0'}</strong>/10 &middot;
        \u98ce\u63a7\u901a\u8fc7: <span class="badge badge-{'ok' if view.risk_cleared else 'warn'}">
        {'\u662f' if view.risk_cleared else '\u5426'}</span> &middot;
        \u98ce\u9669\u6807\u8bb0: {view.risk_flag_count} \u9879
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
      <h3>\u50ac\u5316\u5242\u5206\u6790</h3>
      <div class="excerpt excerpt-short">{_esc(_strip_internal_tokens(_strip_preamble(view.catalyst_excerpt)[:600]))}</div>
    </div>"""

    # Invalidation
    inval_html = ""
    if view.invalidation_signals:
        items = "".join(f"<li>{_esc(s)}</li>" for s in view.invalidation_signals)
        inval_html = f"""
    <div class="card">
      <h3>\u8bba\u9898\u5931\u6548\u6761\u4ef6</h3>
      <ul>{items}</ul>
    </div>"""

    # Lineage -- Research tier: visual pipeline flow, not raw ID table
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
                parts.append(f'<span style="color:var(--blue)">\u5f15\u7528 {len(ev_in)} \u6761\u8bc1\u636e</span>')
            if cl_out:
                bind_note = f"\uff08{attr}\u6761\u6709\u636e\uff09" if attr > 0 else ""
                parts.append(f'\u4ea7\u51fa {len(cl_out)} \u6761\u8bba\u636e{bind_note}')
            if cl_in:
                parts.append(f'\u6d88\u8d39 {len(cl_in)} \u6761\u8bba\u636e')
            if action_raw:
                action_cn = get_soft_action_label(action_raw)
                thesis_cn = get_thesis_label(thesis_raw) if thesis_raw else ""
                thesis_badge = f' \u00b7 \u8bba\u9898{thesis_cn}' if thesis_cn and thesis_cn != "\u65e0" else ""
                parts.append(f'<strong>{_esc(action_cn)} ({confidence:.0%})</strong>{thesis_badge}')
            if isinstance(risk, dict) and risk.get('flags'):
                cats = risk.get('categories', [])
                cat_str = "\u3001".join(_esc(c) for c in cats[:3])
                _vs = risk.get('veto_source', '')
                veto_label = "\u98ce\u63a7\u95e8\u7981" if _vs == "risk_gate" else ("\u7814\u7a76\u5426\u51b3" if _vs == "agent_veto" else "\u5426\u51b3")
                veto_str = f' <span style="color:var(--red)">\u2192 {veto_label}</span>' if risk.get('vetoed') else ""
                parts.append(f'\u98ce\u63a7\u6807\u8bb0 {risk["flags"]} \u9879\uff08{cat_str}\uff09{veto_str}')

            detail = " \u2192 ".join(parts) if parts else ""
            steps.append(f"""
            <div class="timeline-item">
              <span class="timeline-node">{_esc(node)}</span>
              <span class="timeline-detail">{detail}</span>
            </div>""")

        if steps:
            lineage_html = f"""
    <div class="card">
      <h3>\u51b3\u7b56\u94fe\u8def</h3>
      <div class="timeline">{"".join(steps)}</div>
    </div>"""

    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u6df1\u5ea6\u7814\u7a76\u62a5\u544a</p>
    <div class="banner">\u672c\u62a5\u544a\u7531 AI \u591a\u667a\u80fd\u4f53\u7cfb\u7edf\u81ea\u52a8\u751f\u6210\uff0c\u4ec5\u4f9b\u7814\u7a76\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002\u4f7f\u7528\u524d\u8bf7\u7ed3\u5408\u4eba\u5de5\u5224\u65ad\u3002</div>
    {exec_summary}
    {research_chart_html}
    <details open><summary><h2>\u591a\u7a7a\u5206\u6790</h2></summary>
    <div class="cols reveal reveal-d1">{bull_html}{bear_html}</div>
    </details>
    <details open><summary><h2>\u7efc\u5408\u7814\u5224</h2></summary>
    <div class="reveal reveal-d2">{synthesis_html}</div>
    <div class="reveal reveal-d3">{scenario_html}</div>
    </details>
    <details open><summary><h2>\u98ce\u9669\u8bc4\u4f30</h2></summary>
    <div class="reveal reveal-d4">{risk_html}</div>
    <div class="reveal reveal-d5">{trade_plan_html}</div>
    <div class="reveal reveal-d5">{catalyst_html}</div>
    </details>
    <details open><summary><h2>\u51b3\u7b56\u94fe\u8def</h2></summary>
    <div class="reveal reveal-d6">{inval_html}</div>
    <div class="reveal reveal-d6">{lineage_html}</div>
    </details>"""

    return _html_wrap(f"{_ticker_display(view)} \u6df1\u5ea6\u7814\u7a76 \u2014 {view.trade_date}", body, "\u6df1\u5ea6\u7814\u7a76\u62a5\u544a", extra_head=_COUNTUP_JS)
