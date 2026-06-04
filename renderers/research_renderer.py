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
    _summarize_display_text,
    _truncate_display_text,
)
from .decision_labels import (
    get_action_label, get_action_class, get_action_explanation,
    get_soft_action_label,
    get_thesis_label, get_risk_label, get_node_label, get_dimension_label,
    get_signal_emoji,
    safe_badge_class, get_severity_label,
    AI_DISCLAIMER_BANNER, RESEARCH_HEADER_BANNER,
)
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _strip_preamble,
    _format_price_zone, _degraded_banner, _empty_state, _nav_bar,
    _conf_dots, _conf_tier, _ridge_bar, _section_divider,
    _priority_chip, _render_industry_compare_card,
    _quality_grade_badge_html,
    _render_stock_profile_card, _render_calibration_card,
    _render_data_quality_flags, _render_report_delta_card,
)
from .snapshot_renderer import _render_cover_card, _render_kline_card


# ── Tier 2 Degraded Mode ───────────────────────────────────────────────

def _render_research_degraded(view: ResearchView, *, artifact_dir=None) -> str:
    """Render degraded Tier 2 -- warning banner + synthesis + risk only."""
    # A-share action colors: 买入=红, 卖出=绿, VETO=紫.
    color_var = 'red' if view.action_class == 'buy' else ('green' if view.action_class == 'sell' else ('purple' if view.action_class == 'veto' else 'yellow'))

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

    _short_run = (view.run_id[-8:] if view.run_id else "\u2014")
    _grade_badge = _quality_grade_badge_html(
        grade=view.quality_grade,
        score=view.quality_score,
        weak_dims=list(view.quality_weak_dims),
    )
    _watermark = (
        f'<div class="report-watermark" style="display:inline-flex;align-items:center;gap:.4rem;'
        f'font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-bottom:.2rem;letter-spacing:.04em">'
        f'{_grade_badge}{"<span>\u00b7</span>" if _grade_badge else ""}'
        f'<span>\u62a5\u544a ID \u00b7 {_esc(_short_run)}</span><span>\u00b7</span>'
        f'<span>\u6570\u636e\u622a\u6b62 \u00b7 {_esc(view.trade_date)}</span><span>\u00b7</span>'
        f'<span>系统生成</span></div>'
    )
    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 个股深度研究</p>
    {_watermark}
    {_degraded_banner(view.degradation_reasons)}
    {exec_summary}
    {synth_html}
    {risk_html}
    <div class="banner banner-footer" style="margin:2rem 0 0;background:rgba(255,255,255,0.03);border-color:rgba(255,255,255,0.06);color:var(--muted);font-size:.75rem">{AI_DISCLAIMER_BANNER}</div>"""

    nav = _nav_bar(view.ticker, view.run_id, "research", artifact_dir=artifact_dir)
    return _html_wrap(f"{_ticker_display(view)} \u6df1\u5ea6\u7814\u7a76 \u2014 {view.trade_date}", body, "\u6df1\u5ea6\u7814\u7a76\u62a5\u544a", extra_head=_COUNTUP_JS, nav_html=nav)


def _render_trade_plan_card(tp: dict) -> str:
    """Render the public observation-plan card.

    Shows 6 key lines: bias, breakout entry, pullback entry, stop loss,
    targets, and invalidation conditions.
    """
    def _normalize_confidence(val) -> float:
        # Trade-plan cards have historically treated unparseable/missing as 0
        # (they are already inside a "low-confidence" visual context). Preserve
        # that UI behavior while delegating parsing to the canonical helper.
        from .shared_utils import normalize_confidence_value
        conf = normalize_confidence_value(val)
        return 0.0 if conf < 0 else conf

    bias = tp.get("bias", "WAIT")
    # AVOID = \u4e0d\u53c2\u4e0e/\u56de\u907f \u2192 neutral (hold) styling, NOT a red sell badge (rule #5).
    bias_labels = {"LONG": ("\u504f\u591a", "buy"), "WAIT": ("\u7b49\u5f85", "hold"), "AVOID": ("\u56de\u907f", "hold")}
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
    confirmations = tp.get("confirmations", [])
    avoid_conditions = tp.get("avoid_conditions", [])
    review_triggers = tp.get("review_triggers", [])
    time_stop = tp.get("time_stop", "")
    scenario_actions = tp.get("scenario_actions", {})
    horizon = tp.get("holding_horizon", "")
    confidence = _normalize_confidence(tp.get("confidence", 0))

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
        pct_badge = f' <span class="mono" style="color:var(--red);font-size:.85em">(下行幅度 {sl_max_pct:.0%})</span>' if sl_max_pct > 0 else ""
        sl_html = f"""
        <div class="tp-row tp-stop">
          <span class="tp-label">下行警戒位</span>
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
        t_label = (t_label or "参考价位").replace("目标", "参考")
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
          <div class="tp-section-title" style="color:var(--red)">观点失效条件</div>
          <ul class="tp-inval-list">{items}</ul>
        </div>"""

    def _list_block(title: str, items, color: str = "var(--muted)") -> str:
        if isinstance(items, str):
            items = [items] if items.strip() else []
        if not isinstance(items, list) or not items:
            return ""
        lis = "".join(f"<li>{_esc(str(x))}</li>" for x in items[:5])
        return (
            f'<div style="margin-top:.75rem">'
            f'<div class="tp-section-title" style="color:{color}">{_esc(title)}</div>'
            f'<ul class="tp-inval-list">{lis}</ul></div>'
        )

    confirmations_html = _list_block("参与前确认", confirmations, "var(--green)")
    avoid_html = _list_block("不参与条件", avoid_conditions, "var(--yellow)")
    review_html = _list_block("重新评估触发", review_triggers, "var(--blue)")
    time_stop_html = (
        f'<div class="tp-row"><span class="tp-label">观察期限</span>'
        f'<span class="tp-detail">{_esc(str(time_stop))}</span></div>'
        if time_stop else ""
    )
    scenario_html = ""
    if isinstance(scenario_actions, dict) and scenario_actions:
        rows = "".join(
            f'<tr><td>{_esc(str(k))}</td><td>{_esc(str(v))}</td></tr>'
            for k, v in list(scenario_actions.items())[:3]
        )
        scenario_html = (
            f'<div style="margin-top:.75rem"><div class="tp-section-title">情景应对</div>'
            f'<table class="tp-table"><tbody>{rows}</tbody></table></div>'
        )

    return f"""
    <div class="card" style="overflow:hidden;">
      <div style="position:absolute;inset:0 auto auto 0;width:4px;height:100%;background:var(--blue);border-radius:20px 0 0 20px;"></div>
      <div style="padding-left:.6rem;">
        <h3>观察计划</h3>
        <div style="display:flex;gap:.8rem;align-items:center;margin-bottom:.75rem;flex-wrap:wrap">
          <span class="badge badge-{bias_class}" style="font-size:.9rem;padding:5px 16px">{bias_label} ({bias})</span>
          <span style="color:var(--muted);font-size:.85rem;font-family:var(--mono)">\u7f6e\u4fe1\u5ea6 {confidence:.0%}</span>
          <span style="color:var(--muted);font-size:.85rem">{_esc(horizon_label)}</span>
        </div>
        <div class="tp-section-title">关注区间</div>
        <table class="tp-table">
          <thead><tr><th>情形</th><th>价格区间</th><th>需要看到的条件</th></tr></thead>
          <tbody>{setup_rows if setup_rows else '<tr><td colspan="3" style="color:var(--muted)">当前不建议参与</td></tr>'}</tbody>
        </table>
        {sl_html}
        {target_rows}
        {confirmations_html}
        {avoid_html}
        {inval_html}
        {review_html}
        {time_stop_html}
        {scenario_html}
      </div>
    </div>"""


def _format_lineage_confidence(value) -> str:
    """Format lineage confidence only when the source actually provided it."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return ""
    if conf < 0:
        return ""
    if conf > 1.0:
        conf = conf / 100.0 if conf > 10 else conf / 10.0
    conf = max(0.0, min(1.0, conf))
    return f"{conf:.0%}"


def _render_debate_crosstalk(view: ResearchView) -> str:
    """多空交锋: the bear's strongest rebuttals + the PM's verdict on each
    challenged bull claim (AQ-01/AQ-03). Surfaces REAL clash to the reader
    instead of an opaque quality grade. Empty when there were no rebuttals."""
    rows = [r for r in (getattr(view, "debate_crosstalk", None) or []) if r.get("rebuttal_text")]
    if not rows:
        return ""
    # AQ-F2: the PM's verdict is on the MULTI (bull) claim being challenged, so
    # spell out the subject — ACCEPT of the bull claim means the bear's rebuttal
    # was NOT adopted, and vice versa. Badge colors stay direction-neutral.
    _verdict = {
        "ACCEPT": ("PM 维持多方该论点（未采纳此质疑）", "low"),
        "REJECT": ("PM 否定多方该论点（认可此质疑）", "medium"),
        "DEFER": ("PM 搁置（待验证）", "hold"),
    }
    items = ""
    for r in rows:
        conf = r.get("rebuttal_confidence", -1.0)
        conf_str = f"{conf:.0%}" if isinstance(conf, (int, float)) and conf >= 0 else "—"
        vlabel, vcls = _verdict.get((r.get("pm_verdict") or "").upper(), ("未回应", "low"))
        tgt = _esc(_truncate_display_text(r.get("target_claim_text") or r.get("target_claim_id") or "", max_chars=120))
        reason = _esc(_truncate_display_text(r.get("pm_reason", ""), max_chars=160)) if r.get("pm_reason") else ""
        items += (
            '<div style="border-left:3px solid var(--border);padding:.4rem .7rem;margin:.55rem 0;">'
            f'<div style="font-size:.88rem;"><strong>\U0001f43b 空方质疑</strong> '
            f'<span class="badge">置信 {conf_str}</span></div>'
            f'<div style="margin:.25rem 0;">{_esc(_truncate_display_text(r.get("rebuttal_text", ""), max_chars=200))}</div>'
            f'<div style="font-size:.78rem;color:var(--muted);">↳ 针对多方观点: {tgt}</div>'
            f'<div style="font-size:.85rem;margin-top:.3rem;">⚖️ PM 裁决: '
            f'<span class="badge badge-{vcls}">{vlabel}</span> {reason}</div>'
            '</div>'
        )
    return (
        '<div class="card">'
        '<h3>多空交锋 · 空方最强质疑与 PM 回应</h3>'
        '<div style="font-size:.78rem;color:var(--muted);margin-bottom:.4rem;">'
        '空方针对多方具体论点的反驳，及研究经理是否逐条回应（采纳/驳回/搁置）。'
        '空缺即表示该质疑未被 PM 正面回应。</div>'
        f'{items}</div>'
    )


def render_research(view: ResearchView, skip_vendors: bool = False, *, artifact_dir=None) -> str:
    """Render Tier 2 Research Report -- cards not essays, zero LLM leakage.

    When is_degraded=True, prepends a warning banner but continues with the
    normal card layout — each section renderer already guards against
    missing data, so bull/bear debate, catalysts and scenarios still appear
    when their underlying nodes parsed cleanly. Only the affected sections
    will be empty.
    """

    # Degradation banner — prepended to normal content when parse issues exist.
    degradation_banner_html = ""
    if view.is_degraded:
        degradation_banner_html = _degraded_banner(view.degradation_reasons)

    # Executive summary -- hero cockpit
    _sig_emoji_r = get_signal_emoji(view.research_action)
    # A-share action colors: 买入=红, 卖出=绿, VETO=紫.
    color_var = 'red' if view.action_class == 'buy' else ('green' if view.action_class == 'sell' else ('purple' if view.action_class == 'veto' else 'yellow'))
    conf_pct_r = int(view.confidence * 100)
    if view.confidence >= 0:
        # Direction-neutral confidence tiers (not buy/sell) — AQ-F1.
        _conf_cls_r = "conf-strong" if view.confidence >= 0.7 else ("conf-mid" if view.confidence >= 0.4 else "conf-weak")
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
          <div class="eyebrow">个股深度研究 &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji_r} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.action_explanation)}</div>
        </div>
        <div class="hero-right">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;">
            {_conf_kpi_r}
            <div class="kpi"><span class="kpi-val">{risk_display}</span><span class="kpi-label">\u98ce\u9669\u8bc4\u5206/10</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_evidence}</span><span class="kpi-label">依据</span></div>
            <div class="kpi"><span class="kpi-val">{view.total_claims}</span><span class="kpi-label">要点</span></div>
          </div>
        </div>
      </div>
    </div>"""

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
                # -1.0 sentinel means "not provided" — display as 0 for UI.
                if isinstance(conf, (int, float)) and conf < 0:
                    conf = 0
                conf_pct = int(conf * 100)
                # Bar fill = the panel's DIRECTION color (bull=红 / bear=绿); the
                # WIDTH conveys confidence strength. Using price-direction colors
                # (red/green) to mean "strong/weak" conflicts with 红涨绿跌.
                conf_color = f"var(--{color})"
                # V4: tier class drives left-border width; dots array in top-right
                tier = _conf_tier(conf)
                ev_count = len(c.get("evidence_ids", []))
                ev_label = f"{ev_count}条依据" if ev_count else "无引用"
                cards += f"""
                <div class="claim-card conf-{tier}">
                  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:.5rem">
                    <div style="flex:1;min-width:0">{dim_badge}</div>
                    <div>{_conf_dots(conf)}</div>
                  </div>
                  <div>{_esc(_truncate_display_text(c.get("text", ""), max_chars=180))}</div>
                  <div class="conf-bar"><div class="conf-fill" style="width:{conf_pct}%;background:{conf_color};"></div></div>
                  <div class="ev-tags">{_esc(ev_label)}</div>
                </div>"""
            content = f'<div class="claim-grid">{cards}</div>'
        else:
            # Fallback: truncated excerpt, strip tokens
            content = f'<div class="excerpt excerpt-short">{_esc(_summarize_display_text(_strip_preamble(excerpt), max_chars=320))}</div>'

        # Summary line: use counts not raw IDs
        ev_count_total = len(evidence)
        ev_summary = f"{ev_count_total}\u6761\u5f15\u7528" if ev_count_total else "\u65e0\u5f15\u7528"

        return f"""
        <div class="card">
          <h3 style="color:var(--{color})">{title}</h3>
          {content}
          <div style="margin-top:.5rem; font-size:.85rem; color:var(--muted);">
            {len(claims)} 条核心要点 &middot; 依据: {_esc(ev_summary)}
          </div>
        </div>"""

    _has_bull = view.bull_claims or view.bull_excerpt
    _has_bear = view.bear_claims or view.bear_excerpt
    if _has_bull or _has_bear:
        # A-share convention: \u770b\u591a/bullish = \u7ea2, \u770b\u7a7a/bearish = \u7eff.
        bull_html = _case_panel("\u770b\u591a\u8bba\u70b9", view.bull_claims, view.bull_excerpt,
                                view.bull_evidence_ids, "red")
        bear_html = _case_panel("\u770b\u7a7a\u8bba\u70b9", view.bear_claims, view.bear_excerpt,
                                view.bear_evidence_ids, "green")
    else:
        bull_html = f'<div class="card">{_empty_state("\u2694\ufe0f", "\u6682\u65e0\u591a\u7a7a\u8fa9\u8bba\u6570\u636e", "\u7814\u7a76\u5458\u672a\u4ea7\u51fa\u7ed3\u6784\u5316\u8bba\u70b9")}</div>'
        bear_html = ""

    crosstalk_html = _render_debate_crosstalk(view)

    # ── PM Synthesis -- structured conclusion + cases ──
    thesis_label = get_thesis_label(view.thesis_effect)
    thesis_ok = view.thesis_effect in ("unchanged", "strengthened", "strengthen", "")

    synth_body = f'<div style="font-size:.95rem; margin:.5rem 0;">{_esc(_summarize_display_text(_strip_preamble(view.synthesis_excerpt), max_chars=360))}</div>'

    if view.synthesis_detail:
        cases = ""
        for key, label in [("base_case", "\u57fa\u51c6\u60c5\u666f"), ("bull_case", "\u4e50\u89c2\u60c5\u666f"), ("bear_case", "\u60b2\u89c2\u60c5\u666f")]:
            text = view.synthesis_detail.get(key, "")
            if text:
                cases += f'<div style="margin:.5rem 0;"><strong>{label}:</strong> {_esc(_truncate_display_text(text, max_chars=220))}</div>'
        if cases:
            synth_body += cases

    ev_count = len(view.synthesis_evidence_ids)
    ev_summary = f"{ev_count}\u6761" if ev_count else "\u65e0"

    synthesis_html = f"""
    <div class="card">
      <h3>综合判断</h3>
      <div style="margin-bottom:.5rem;">
        观点状态: <span class="badge badge-{'ok' if thesis_ok else 'warn'}">{_esc(thesis_label)}</span>
        &nbsp; 引用依据: {_esc(ev_summary)}
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
        base_tip = _esc(_truncate_display_text(sp.get("base_trigger", ""), max_chars=90))
        bull_tip = _esc(_truncate_display_text(sp.get("bull_trigger", ""), max_chars=90))
        bear_tip = _esc(_truncate_display_text(sp.get("bear_trigger", ""), max_chars=90))
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
        <div><strong>\u57fa\u51c6\u89e6\u53d1:</strong> {_esc(_truncate_display_text(sp.get("base_trigger", ""), max_chars=180))}</div>
        <div><strong>\u4e50\u89c2\u89e6\u53d1:</strong> {_esc(_truncate_display_text(sp.get("bull_trigger", ""), max_chars=180))}</div>
        <div><strong>\u60b2\u89c2\u89e6\u53d1:</strong> {_esc(_truncate_display_text(sp.get("bear_trigger", ""), max_chars=180))}</div>
      </div>
    </div>"""
    elif view.scenario_excerpt:
        scenario_html = f"""
    <div class="card">
      <h3>\u60c5\u666f\u5206\u6790</h3>
      <div class="excerpt excerpt-short">{_esc(_summarize_display_text(_strip_preamble(view.scenario_excerpt), max_chars=420))}</div>
    </div>"""

    # ── Risk review -- card-per-flag with severity color ──
    risk_content = ""
    if view.risk_flags_detail:
        for f in view.risk_flags_detail:
            sev_cls = safe_badge_class(f.get("severity_class", ""))
            sev_label = get_severity_label(f.get("severity", ""))
            ev_count = len(f.get("evidence_ids", []))
            ev_label = f"{ev_count}条依据" if ev_count else "无引用"
            mitigant = f.get("mitigant", "")
            mitigant_html = f'<div style="font-size:.8rem;color:var(--muted);margin-top:.25rem;">\u7f13\u91ca: {_esc(_truncate_display_text(mitigant, max_chars=120))}</div>' if mitigant else ""
            risk_content += f"""
            <div class="claim-card">
              <span class="badge badge-{sev_cls}">{_esc(sev_label)}</span>
              <strong>{_esc(get_risk_label(f.get("category", "")))}</strong>
              <div style="margin-top:.25rem;">{_esc(_truncate_display_text(f.get("description", ""), max_chars=180))}</div>
              <div class="ev-tags">{_esc(ev_label)}</div>
              {mitigant_html}
            </div>"""
        risk_content = f'<div class="claim-grid">{risk_content}</div>'
    elif view.risk_flag_categories:
        items = "".join(f"<li>{_esc(get_risk_label(c))}</li>" for c in view.risk_flag_categories)
        risk_content = f"<ul>{items}</ul>"

    risk_html = f"""
    <div class="card">
      <h3>主要风险</h3>
      <div style="margin-bottom:.5rem;">
        \u8bc4\u5206: <strong>{view.risk_score if view.risk_score is not None else '\u65e0'}</strong>/10 &middot;
        风险结论: <span class="badge badge-{'ok' if view.risk_cleared else 'warn'}">
        {'未触发硬性风险' if view.risk_cleared else '需要谨慎复核'}</span> &middot;
        风险提示: {view.risk_flag_count} 项
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
      <div class="excerpt excerpt-short">{_esc(_summarize_display_text(_strip_preamble(view.catalyst_excerpt), max_chars=420))}</div>
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
                parts.append(f'\u6574\u5408 {len(cl_in)} \u6761\u8bba\u636e')
            if action_raw:
                action_cn = get_soft_action_label(action_raw)
                thesis_cn = get_thesis_label(thesis_raw) if thesis_raw else ""
                thesis_badge = f' \u00b7 \u8bba\u9898{_esc(thesis_cn)}' if thesis_cn and thesis_cn != "\u65e0" else ""
                conf_label = _format_lineage_confidence(confidence)
                action_label = f'{_esc(action_cn)} ({conf_label})' if conf_label else _esc(action_cn)
                parts.append(f'<strong>{action_label}</strong>{thesis_badge}')
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
      <h3>研究依据</h3>
      <div class="timeline">{"".join(steps)}</div>
    </div>"""

    _short_run2 = (view.run_id[-8:] if view.run_id else "\u2014")
    _grade_badge2 = _quality_grade_badge_html(
        grade=view.quality_grade,
        score=view.quality_score,
        weak_dims=list(view.quality_weak_dims),
    )
    _watermark2 = (
        f'<div class="report-watermark" style="display:inline-flex;align-items:center;gap:.4rem;'
        f'font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-bottom:.2rem;letter-spacing:.04em">'
        f'{_grade_badge2}{"<span>\u00b7</span>" if _grade_badge2 else ""}'
        f'<span>\u62a5\u544a ID \u00b7 {_esc(_short_run2)}</span><span>\u00b7</span>'
        f'<span>\u6570\u636e\u622a\u6b62 \u00b7 {_esc(view.trade_date)}</span><span>\u00b7</span>'
        f'<span>系统生成</span></div>'
    )
    cover_html = _render_cover_card(view)
    kline_html = _render_kline_card(view)
    industry_html = _render_industry_compare_card(view.industry_compare or {})
    stock_profile_html = _render_stock_profile_card(view.stock_profile or {})
    calibration_html = _render_calibration_card(view.calibration_summary or {})
    data_quality_html = _render_data_quality_flags(view.data_quality_flags or [])
    report_delta_html = _render_report_delta_card(view)
    context_html = (
        f'<div class="cols reveal reveal-d1">{stock_profile_html}{calibration_html}</div>'
        if (stock_profile_html or calibration_html) else ""
    )
    _research_banner2 = (
        f'<div class="research-banner" style="margin:.6rem 0 .8rem;'
        f'padding:.6rem .9rem;background:linear-gradient(90deg,rgba(96,165,250,0.12),rgba(96,165,250,0.04));'
        f'border:1px solid rgba(96,165,250,0.32);border-radius:12px;'
        f'color:var(--blue);font-size:.78rem;line-height:1.5;letter-spacing:.02em">'
        f'{RESEARCH_HEADER_BANNER}</div>'
    )
    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u6df1\u5ea6\u7814\u7a76\u62a5\u544a</p>
    {_watermark2}
    {_research_banner2}
    {cover_html}
    {kline_html}
    {degradation_banner_html}
    {exec_summary}
    {report_delta_html}
    {context_html}
    {data_quality_html}
    <nav style="font-size:.8rem;margin:.5rem 0;">
      <a href="#bull-bear" style="color:var(--blue);text-decoration:none;">正反观点</a> &middot;
      <a href="#synthesis" style="color:var(--blue);text-decoration:none;">综合判断</a> &middot;
      <a href="#industry" style="color:var(--blue);text-decoration:none;">\u884c\u4e1a\u5bf9\u6bd4</a> &middot;
      <a href="#risk" style="color:var(--blue);text-decoration:none;">主要风险</a> &middot;
      <a href="#trade-plan" style="color:var(--blue);text-decoration:none;">观察计划</a>
    </nav>
    <details open><summary><h2 id="bull-bear">正反观点</h2></summary>
    <div class="cols reveal reveal-d1">{bull_html}{bear_html}</div>
    {f'<div class="reveal reveal-d2">{crosstalk_html}</div>' if crosstalk_html else ''}
    </details>
    {f'<a id="industry"></a>{industry_html}' if industry_html else ''}
    <details open><summary><h2 id="synthesis">综合判断</h2></summary>
    <div class="reveal reveal-d2">{synthesis_html}</div>
    <div class="reveal reveal-d3">{scenario_html}</div>
    </details>
    <details open><summary><h2 id="risk">主要风险</h2></summary>
    <div class="reveal reveal-d4">{risk_html}</div>
    <div class="reveal reveal-d5" id="trade-plan">{trade_plan_html}</div>
    <div class="reveal reveal-d5">{catalyst_html}</div>
    </details>
    <details><summary><h2 id="lineage">研究依据</h2></summary>
    <div class="reveal reveal-d6">{inval_html}</div>
    <div class="reveal reveal-d6">{lineage_html}</div>
    </details>
    <div class="banner banner-footer" style="margin:2rem 0 0;background:rgba(255,255,255,0.03);border-color:rgba(255,255,255,0.06);color:var(--muted);font-size:.75rem">{AI_DISCLAIMER_BANNER}</div>"""

    nav = _nav_bar(view.ticker, view.run_id, "research", artifact_dir=artifact_dir)
    return _html_wrap(f"{_ticker_display(view)} \u6df1\u5ea6\u7814\u7a76 \u2014 {view.trade_date}", body, "\u6df1\u5ea6\u7814\u7a76\u62a5\u544a", extra_head=_COUNTUP_JS, nav_html=nav)
