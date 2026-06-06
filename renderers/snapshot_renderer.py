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
    _summarize_display_text,
    _truncate_display_text,
)
from .decision_labels import (
    get_action_label, get_action_class,
    get_soft_action_label,
    get_risk_label, get_node_label,
    get_signal_emoji, PILLAR_EMOJI,
    get_severity_label,
    safe_badge_class,
    AI_DISCLAIMER_BANNER, RESEARCH_HEADER_BANNER,
)
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light, _strip_preamble,
    _empty_state, _format_price_zone, _evidence_strength_label,
    _degraded_banner, _bull_bear_bar, _direction_badge, _radar_svg,
    _trend_arrow, _sparkline_svg, _nav_bar,
    _price_ladder_svg, _pillar_bar, _history_sparkline,
    _confidence_ring_svg, _priority_chip, _score_pill,
    normalize_confidence_value,
    _delta_arrow, _section_divider, _format_finance_num,
    _kline_with_signals_svg, _pe_label_html,
    _render_industry_compare_card, _render_hero_industry_kpis,
    _quality_grade_badge_html, _vague_phrase_warning,
    _render_stock_profile_card, _render_calibration_card,
    _render_data_quality_flags, _render_report_delta_card,
)


def _render_kline_card(view: SnapshotView) -> str:
    """Full-width price line chart + signal trail. Replaces the decorative
    hero sparkline with a labelled chart + signal-history chip row.
    Returns "" when there's no usable price history.
    """
    if not view.price_history or len(view.price_history) < 2:
        return ""
    chart = _kline_with_signals_svg(
        prices=view.price_history,
        signals=view.signal_history,
        period_days=view.period_days or len(view.price_history),
    )
    if not chart:
        return ""
    return (
        f'<div class="card reveal" style="padding:.95rem 1.1rem;margin-bottom:1rem">'
        f'{chart}'
        f'</div>'
    )


# ── Cover card (institutional-style header) ─────────────────────────────


def _render_cover_card(view: SnapshotView) -> str:
    """Bloomberg-style summary strip below the H1 title.

    Single horizontal row: current price · 5d change · period high/low ·
    PE / PB / ROE / market cap. All values fall back to "—" when missing.
    Uses cover-derived fields populated in SnapshotView.build (no new data
    collection needed — derived from price_history + metrics_fallback).
    """
    if not (view.current_price or view.metrics_fallback):
        return ""

    fb = view.metrics_fallback or {}
    cells: list = []

    def _cell(label: str, value: str, color_var: str = "", label_html: bool = False) -> str:
        color_style = f' style="color:{color_var}"' if color_var else ""
        # When label_html=True, caller has pre-built safe HTML (e.g. PE^TTM
        # superscript markup); otherwise we escape per default.
        label_render = label if label_html else _esc(label)
        return (
            f'<div class="cover-cell">'
            f'<div class="cc-label">{label_render}</div>'
            f'<div class="cc-val mono"{color_style}>{_esc(value)}</div>'
            f'</div>'
        )

    if view.current_price:
        cells.append(_cell("最新价", _format_finance_num(view.current_price, "price")))
    if view.pct_change_5d:
        clr = "var(--red)" if view.pct_change_5d > 0 else (
            "var(--green)" if view.pct_change_5d < 0 else "var(--muted)"
        )
        cells.append(_cell(f"近 5 日", _format_finance_num(view.pct_change_5d, "pct"), clr))
    if view.period_high and view.period_low and view.period_high != view.period_low:
        rng = (
            f'{_format_finance_num(view.period_low, "price")} – '
            f'{_format_finance_num(view.period_high, "price")}'
        )
        cells.append(_cell(f"近 {view.period_days} 日区间", rng))
    # Financial ratios
    pe_v = fb.get("pe")
    if pe_v is not None:
        cells.append(_cell(_pe_label_html(), _format_finance_num(pe_v, "ratio"), label_html=True))
    pb_v = fb.get("pb")
    if pb_v is not None:
        cells.append(_cell("PB", _format_finance_num(pb_v, "ratio")))
    roe_v = fb.get("roe")
    if roe_v is not None:
        cells.append(_cell("ROE", _format_finance_num(roe_v, "pct_simple")))
    mc_v = fb.get("market_cap")
    if mc_v is not None:
        cells.append(_cell("总市值", _format_finance_num(mc_v, "mktcap_yi")))

    if not cells:
        return ""

    # Inline minimal CSS (one-shot for cover card, doesn't pollute global)
    style = """<style>
/* Premium P2c: equal-width data strip — hairline gutters form the grid (1px gap
   over the container's hairline bg shows through between var(--card) cells). */
.cover-card{display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:1px;
  margin:.4rem 0 1rem;background:var(--hairline);border:1px solid var(--hairline);
  border-radius:14px;overflow:hidden;font-size:.86rem}
.cover-cell{display:flex;flex-direction:column;gap:.2rem;min-width:0;padding:.6rem .85rem;
  background:var(--card)}
.cover-cell .cc-label{font-size:.7rem;color:var(--muted);letter-spacing:.05em;text-transform:uppercase}
.cover-cell .cc-val{font-size:1.05rem;font-weight:600;color:var(--white);font-variant-numeric:tabular-nums}
.report-watermark{display:inline-flex;align-items:center;gap:.4rem;font-family:var(--mono);
  font-size:.7rem;color:var(--muted);margin-bottom:.2rem;letter-spacing:.04em}
.banner.banner-footer{margin:2rem 0 0;background:rgba(255,255,255,0.03);
  border-color:var(--hairline);color:var(--muted);font-size:.75rem}
</style>"""
    return f'{style}<div class="cover-card">{"".join(cells)}</div>'


# ── Feature 2: Checklist + Risk Debate Summary ──────────────────────────


def _render_pillar_consensus_bar(view: SnapshotView) -> str:
    """Render compact pillar-consensus summary bar.

    One line: 观星[空] 度支[空] 通政[多] 察言[多]   →   2:2 split
    Optionally flags tension when ≥3 pillars agree but action is HOLD.
    """
    pc = view.pillar_consensus or {}
    if not pc or pc.get("verdict") == "insufficient":
        return ""

    # Map pillar checklist (already in proper order) into compact icons
    _ICONS = {
        "技术面": "观星",   # 技术面 → 观星
        "基本面": "度支",   # 基本面 → 度支
        "消息面": "通政",   # 消息面 → 通政
        "情绪面": "察言",   # 情绪面 → 察言
    }
    chips = []
    for p in view.pillar_checklist:
        name = p.get("pillar", "")
        icon = _ICONS.get(name, name)
        score = p.get("score", -1)
        if score >= 3:
            tag = "多"  # 多 (bullish)
            cls = "buy"
        elif 0 <= score <= 1:
            tag = "空"  # 空 (bearish)
            cls = "sell"
        else:
            tag = "平"  # 平 (neutral)
            cls = "hold"
        chips.append(
            f'<span class="pc-chip"><span class="pc-icon">{_esc(icon)}</span>'
            f'<span class="badge badge-{cls}">{tag}</span></span>'
        )

    bull = pc.get("bullish", 0)
    bear = pc.get("bearish", 0)
    neut = pc.get("neutral", 0)
    verdict = pc.get("verdict", "")
    _VERDICT_LABEL = {
        "strong_bullish": "强多共识 (4:0)",
        "lean_bullish":   f"偏多 ({bull}:{bear})",
        "split":          f"多空胶着 ({bull}:{bear})",
        "lean_bearish":   f"偏空 ({bear}:{bull})",
        "strong_bearish": "强空共识 (4:0)",
        "neutral":        "中性占多",
    }
    verdict_text = _VERDICT_LABEL.get(verdict, verdict or "—")
    if neut:
        verdict_text += f" · 中性 {neut}"

    tension_html = ""
    if pc.get("tension"):
        tension_html = (
            '<span class="pc-tension" title="≥3个支柱共识但决策为 HOLD，存在张力，请参考设计外部人工复查">'
            ' ⚠️ 决策张力</span>'
        )

    return f"""
    <div class="card pc-card" style="padding:0.7rem 1rem;margin-bottom:0.6rem;">
      <div class="pc-row" style="display:flex;align-items:center;gap:0.8rem;flex-wrap:wrap;">
        <span class="pc-title" style="font-weight:600;color:var(--muted);">支柱共识</span>
        <div class="pc-chips" style="display:flex;gap:0.4rem;">{"".join(chips)}</div>
        <span class="pc-arrow" style="color:var(--muted);">→</span>
        <span class="pc-verdict" style="font-weight:600;">{_esc(verdict_text)}</span>
        {tension_html}
      </div>
    </div>"""


def _render_checklist(view: SnapshotView) -> str:
    """Render pillar score checklist card.

    The radar chart is only meaningful when there's actual pillar dispersion;
    when all 4 pillars are tightly clustered (max-min < 2) the polygon
    collapses to a tiny dot near centre that adds nothing. In that case we
    drop the radar and let the per-pillar bars take the full row width.
    """
    if not view.pillar_checklist:
        return ""
    items = ""
    scores = []
    for p in view.pillar_checklist:
        emoji = _esc(p.get("emoji", ""))
        pillar = _esc(p.get("pillar", ""))
        score = p.get("score", 0)
        label = _esc(p.get("label", ""))
        bar = _pillar_bar(score, max_score=4, label=pillar)
        scores.append(score if isinstance(score, (int, float)) else 0)
        items += (
            f'<div class="ck-item">'
            f'<span class="ck-emoji">{emoji}</span>'
            f'<span class="ck-pillar">{pillar}</span>'
            f'<span class="ck-label">{label}</span>'
            f'<span class="ck-score">{bar}</span>'
            f'</div>'
        )

    # Decide whether to render radar based on dispersion
    radar_html = ""
    if scores and (max(scores) - min(scores)) >= 2:
        radar_html = (
            f'<div style="flex-shrink:0">{_radar_svg(view.pillar_checklist, view.action_class)}</div>'
        )

    return f"""
    <div class="card">
      <h3>四个维度怎么看</h3>
      <div style="display:flex;gap:1.2rem;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:200px"><div class="checklist">{items}</div></div>
        {radar_html}
      </div>
    </div>"""


def _render_risk_debate_summary(view: SnapshotView) -> str:
    """Render 3-stance risk-debate viewpoint card (research-tier).

    Three perspectives (\u6fc0\u8fdb / \u4fdd\u5b88 / \u4e2d\u6027) frame the same evidence under
    different priors. Each stance is shown with its directional view and core
    risk argument \u2014 NO position percentages, since this report is research,
    not a position-sizing instruction.
    """
    if not view.risk_debate_summary:
        return ""
    # Map BUY/SELL/HOLD into research-tier viewpoint language
    _VIEW_LABEL = {"BUY": "\u503e\u5411\u504f\u591a", "SELL": "\u503e\u5411\u504f\u7a7a", "VETO": "\u8bc1\u636e\u4e0d\u8db3", "HOLD": "\u7ef4\u6301\u4e2d\u6027"}
    cols = ""
    for rd in view.risk_debate_summary:
        stance = _esc(rd.get("stance", ""))
        rec = rd.get("recommendation", "").upper()
        rec_class = "buy" if rec == "BUY" else ("veto" if rec == "VETO" else ("sell" if rec == "SELL" else "hold"))
        view_label = _esc(_VIEW_LABEL.get(rec, rec or "\u2014"))
        risk = _esc(str(rd.get("key_risk", "") or "\u2014"))
        cols += (
            f'<div class="rd-col">'
            f'<div class="rd-stance">{stance}\u6d3e\u89c6\u89d2</div>'
            f'<div class="rd-rec badge badge-{rec_class}">{view_label}</div>'
            f'<div class="rd-risk">\u6838\u5fc3\u8bba\u636e: {risk}</div>'
            f'</div>'
        )
    return f"""
    <div class="card">
      <h3>风险视角对照 <span style="font-size:.65rem;color:var(--muted);font-weight:500;margin-left:.4rem">不同假设下的观点差异</span></h3>
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
    # Reconcile with the aggregated, authoritative trace direction: a risk VETO
    # dominates a stale/contradictory trade-card side, and the trace-level action
    # wins over a conflicting card side — so the card can never show a bullish
    # plan for a vetoed/sold signal (SIG-004; AVOID≠SELL rule #5).
    if view.was_vetoed or view.research_action == "VETO":
        side = "VETO"
    elif view.research_action in ("BUY", "SELL", "HOLD") and view.research_action != side:
        side = view.research_action
    # Canonical normalizer: prevents un-clamped values (e.g. "72" → 7200%) and
    # keeps display in sync with parsed confidence. Missing → -1.0 → "—" badge.
    confidence = normalize_confidence_value(
        tc.get("confidence", tp.get("confidence"))
    )
    # VETO-02: don't show the (bullish) trade-card confidence on a vetoed card.
    if side in ("AVOID", "VETO"):
        confidence = -1.0
    rationale = tc.get("rationale", "")
    risk_score = tc.get("risk_score", 0)
    if isinstance(risk_score, str):
        try:
            risk_score = float(risk_score)
        except (ValueError, TypeError):
            risk_score = 0

    # Border color class. AVOID/VETO = "do not participate" \u2192 neutral styling,
    # NOT the red sell-plan (rule #5: AVOID\u2260SELL).
    if side in ("SHORT", "SELL"):
        plan_class = "sell-plan"
    elif side in ("AVOID", "VETO"):
        plan_class = "veto-plan"
    elif side in ("WAIT", "HOLD"):
        plan_class = "hold-plan"
    else:
        plan_class = ""
    emoji = get_signal_emoji(
        "VETO" if side in ("VETO", "AVOID") else (
        "SELL" if side in ("SHORT", "SELL") else (
        "HOLD" if side in ("WAIT", "HOLD") else "BUY"
    )))

    # Research-tier language (NOT trading instruction). These describe the
    # weight of evidence for downstream decision-makers, not orders.
    # AVOID/VETO are non-participation, NOT bearish (\u504f\u7a7a) \u2014 rule #5.
    side_label = {"LONG": "\u504f\u591a", "SHORT": "\u504f\u7a7a", "WAIT": "\u4e2d\u6027\u89c2\u5bdf",
                  "BUY": "\u504f\u591a", "SELL": "\u504f\u7a7a", "AVOID": "\u56de\u907f\u00b7\u4e0d\u53c2\u4e0e",
                  "HOLD": "\u4e2d\u6027\u89c2\u5bdf", "VETO": "\u98ce\u63a7\u5426\u51b3\u00b7\u4e0d\u53c2\u4e0e"}.get(side, side)
    if confidence >= 0:
        # Direction-neutral confidence tiers (not buy/sell) \u2014 AQ-F1.
        conf_cls = "conf-strong" if confidence >= 0.7 else ("conf-mid" if confidence >= 0.4 else "conf-weak")
        conf_badge = f'<span class="badge badge-{conf_cls}">\u7f6e\u4fe1\u5ea6 {confidence:.0%}</span>'
    else:
        conf_badge = '<span class="badge">\u7f6e\u4fe1\u5ea6 \u2014</span>'

    header = (
        f'<div class="bp-header">'
        f'<span class="bp-side">{emoji} {_esc(side_label)}</span>'
        f'{conf_badge}'
        f'</div>'
    )

    # Rationale: split a long single-paragraph rationale into 3-5 short bullets
    # so traders can scan the core argument quickly. Falls back to inline text
    # when the rationale is already short or has no natural break points.
    rationale_clean = _summarize_display_text(rationale, max_chars=400)
    rationale_html = ""
    if rationale_clean:
        # Split on Chinese clause separators "；。，" but keep clauses ≥ 12 chars
        # to avoid fragmenting tiny phrases.
        import re as _re
        parts = [seg.strip() for seg in _re.split(r"[；。，]", rationale_clean) if seg.strip()]
        # Merge fragments shorter than 12 chars into the previous one
        merged: list = []
        for seg in parts:
            if merged and len(seg) < 12:
                merged[-1] = merged[-1] + "，" + seg
            else:
                merged.append(seg)
        # Cap each bullet at 60 chars and total at 5 bullets
        bullets = [b[:60] + ("…" if len(b) > 60 else "") for b in merged[:5]]
        if len(bullets) >= 2:
            li_html = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
            rationale_html = f'<ul class="bp-rationale-list" style="margin:.3rem 0 .6rem 1.1rem;padding:0;font-size:.88rem;color:var(--fg);line-height:1.55;">{li_html}</ul>'
        else:
            rationale_html = f'<div class="bp-rationale">{_esc(rationale_clean)}</div>'

    # VETO-01: AVOID/VETO means "do not participate" — the card must NOT show any
    # participation price levels (entry / stop / target), only a neutral note.
    _no_levels = side in ("AVOID", "VETO")

    # Entry setups table
    setups = [] if _no_levels else tp.get("entry_setups", [])
    if not isinstance(setups, list):
        setups = []
    setup_html = ""
    if _no_levels:
        setup_html = ('<div class="tp-section-title">参与价位</div>'
                      '<div style="font-size:.85rem;color:var(--muted);">'
                      '因风控否决 / 回避，本研究不提供参与价位（不参与）。</div>')
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
        <div class="tp-section-title">关注区间</div>
        <table class="tp-table">
          <thead><tr><th>情形</th><th>价格区间</th><th>需要看到的条件</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # Stop loss (may be dict or scalar) — suppressed for AVOID/VETO (VETO-01).
    stop_raw = {} if _no_levels else (tp.get("stop_loss") or {})
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
        sl_html = (
            f'<div class="tp-row tp-stop"><span class="tp-label">'
            f'<span title="跌破此水平时，需要重新检查本报告的核心假设">下行警戒位</span></span>'
            f'<span class="mono num" style="color:var(--red)">{sl_price:.2f}</span></div>'
        )

    # Take profit — suppressed for AVOID/VETO (VETO-01).
    targets_raw = [] if _no_levels else tp.get("take_profit", [])
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
        # Research framing: these are reference levels, not trade targets.
        tp_label_research = (t_label or "参考价位").replace("目标", "参考")
        tp_html += (
            f'<div class="tp-row tp-target"><span class="tp-label">{tp_label_research}</span>'
            f'<span class="mono num" style="color:var(--green)">{t_str}</span></div>'
        )

    # Invalidation
    invalidators_raw = tp.get("invalidators", [])
    invalidators = invalidators_raw if isinstance(invalidators_raw, list) else []
    inval_html = ""
    if invalidators:
        # Each invalidator is checked for vague language; concrete conditions
        # render plain, vague ones get an inline \u26a0 "\u542b\u7cca\u6761\u4ef6" red badge.
        items = "".join(
            f'<li>{_esc(str(inv))}{_vague_phrase_warning(str(inv))}</li>'
            for inv in invalidators[:4]
        )
        inval_html = f'<div style="margin-top:.5rem"><div class="tp-section-title" style="color:var(--red)">\u5931\u6548\u6761\u4ef6</div><ul class="tp-inval-list">{items}</ul></div>'

    def _compact_list(title: str, items, color: str) -> str:
        if isinstance(items, str):
            items = [items] if items.strip() else []
        if not isinstance(items, list) or not items:
            return ""
        lis = "".join(f"<li>{_esc(str(x))}</li>" for x in items[:3])
        return (
            f'<div style="margin-top:.5rem"><div class="tp-section-title" style="color:{color}">'
            f'{_esc(title)}</div><ul class="tp-inval-list">{lis}</ul></div>'
        )

    confirmations_html = _compact_list("参与前确认", tp.get("confirmations", []), "var(--green)")
    avoid_html = _compact_list("不参与条件", tp.get("avoid_conditions", []), "var(--yellow)")
    review_html = _compact_list("重新评估触发", tp.get("review_triggers", []), "var(--blue)")
    time_stop = tp.get("time_stop", "")
    time_stop_html = (
        f'<div class="tp-row"><span class="tp-label">观察期限</span>'
        f'<span class="tp-detail">{_esc(str(time_stop))}</span></div>'
        if time_stop else ""
    )

    # Research-tier risk indicator (NOT a position-sizing input)
    gauge_html = ""
    if risk_score > 0:
        gauge_pct = min(int(risk_score * 10), 100)
        gauge_color = "var(--red)" if risk_score >= 7 else ("var(--yellow)" if risk_score >= 4 else "var(--green)")
        risk_lbl = "\u9ad8" if risk_score >= 7 else ("\u4e2d" if risk_score >= 4 else "\u4f4e")
        gauge_html = f"""
        <div style="margin-top:.5rem;">
          <div style="font-size:.8rem;color:var(--muted)">风险提示等级 · {risk_lbl} ({risk_score}/10)</div>
          <div class="bp-gauge"><div class="bp-gauge-fill" style="width:{gauge_pct}%;background:{gauge_color}"></div></div>
        </div>"""

    # Price ladder visualization: stop / current / entries / targets
    ladder_svg = ""
    try:
        current_price = float(getattr(view, "current_price", 0) or tc.get("current_price", 0) or 0)
    except (TypeError, ValueError):
        current_price = 0.0
    ladder_entries = [s.get("price_zone") for s in setups if isinstance(s, dict)]
    ladder_targets = [t.get("price_zone") for t in targets_raw if isinstance(t, dict)]
    if side in ("AVOID", "VETO"):
        # Non-participation (rule #5): no directional entry/stop/target ladder.
        ladder_svg_raw = ""
    else:
        ladder_svg_raw = _price_ladder_svg(
            stop_loss=sl_price,
            entries=ladder_entries,
            targets=ladder_targets,
            current=current_price,
            side=side,
        )
    if ladder_svg_raw:
        ladder_svg = (
            f'<div class="bp-ladder" style="margin-top:.6rem;display:flex;justify-content:center">'
            f'{ladder_svg_raw}'
            f'</div>'
        )

    return f"""
    <div class="card battle-plan {plan_class}">
      <h3>观察计划 · 关键价格与事件 <span style="font-size:.65rem;color:var(--muted);font-weight:500;margin-left:.4rem">仅供分析参考</span></h3>
      {header}
      {rationale_html}
      <div class="bp-body" style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.2rem;align-items:start">
        <div class="bp-body-left" style="min-width:0">
          {setup_html}
          {sl_html}
          {tp_html}
          {confirmations_html}
          {avoid_html}
          {inval_html}
          {review_html}
          {time_stop_html}
          {gauge_html}
        </div>
        <div class="bp-body-right">{ladder_svg}</div>
      </div>
    </div>"""


# ── Feature 5: Signal History ────────────────────────────────────────────

def _render_signal_history(view: SnapshotView) -> str:
    """Render historical signal sparkline + date/action rows."""
    if not view.signal_history:
        return ""

    # Oldest-first for sparkline chronology; prepend so left\u2192right is time-forward.
    history_chrono = list(reversed(view.signal_history[:5]))
    # Append the current run as the right-most point so users see where they are now.
    history_chrono.append({
        "trade_date": view.trade_date,
        "action": view.research_action,
        "confidence": view.confidence if view.confidence >= 0 else 0.0,
    })
    spark_points = [
        {
            "date": p.get("trade_date", ""),
            "action": p.get("action", ""),
            "value": float(p.get("confidence", 0) or 0),
        }
        for p in history_chrono
    ]
    spark_svg = _history_sparkline(spark_points, width=280, height=54)
    spark_html = (
        f'<div class="sh-spark" style="margin-bottom:.6rem">{spark_svg}</div>'
        if spark_svg else ""
    )

    rows = ""
    for sh in view.signal_history[:5]:
        date = _esc(sh.get("trade_date", ""))
        act = sh.get("action", "")
        emoji = get_signal_emoji(act)
        act_label = _esc(get_action_label(act))
        conf = float(sh.get("confidence", 0) or 0)
        conf_txt = f"{conf:.0%}" if conf > 0 else "\u2014"
        rows += (
            f'<tr><td>{date}</td>'
            f'<td>{emoji} {act_label}</td>'
            f'<td class="mono num" style="color:var(--muted)">{conf_txt}</td>'
            f'</tr>'
        )

    return f"""
    <div class="card">
      <h3>\u5386\u53f2\u4fe1\u53f7</h3>
      {spark_html}
      <table class="sig-hist-table">
        <tbody>{rows}</tbody>
      </table>
    </div>"""


# ── Tier 1: Snapshot ─────────────────────────────────────────────────────

def render_snapshot(view: SnapshotView, skip_vendors: bool = False, *, artifact_dir=None) -> str:
    """Render Tier 1 Snapshot — single screen, conclusion-first, zero LLM leakage.

    When is_degraded=True, prepends a warning banner but continues with the
    normal layout — each section renderer already guards against missing
    data, so healthy sections (bull/bear debate, risk debate, catalysts,
    etc.) still appear when their underlying nodes parsed cleanly.
    """
    # A-share action colors: 买入=红, 卖出=绿, VETO=紫.
    color_var = 'red' if view.action_class == 'buy' else ('green' if view.action_class == 'sell' else ('purple' if view.action_class == 'veto' else 'yellow'))

    # Degradation banner — prepended to normal content when parse issues exist.
    degradation_banner_html = ""
    if view.is_degraded:
        degradation_banner_html = _degraded_banner(view.degradation_reasons)

    # ── (legacy minimal-mode path kept for dict-to-dict compat; no longer
    #     early-returns so healthy sections render) ──
    if False and view.is_degraded:  # disabled: preserved as dead code for now
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
            _PE_LABEL = _pe_label_html()
            for key, label, label_html in [
                ("pe", _PE_LABEL, True),
                ("pb", "PB", False),
                ("roe", "ROE(%)", False),
                ("gross_margin", "\u6bdb\u5229\u7387(%)", False),
                ("market_cap", "\u603b\u5e02\u503c(\u4ebf)", False),
                ("eps", "EPS", False),
                ("net_profit", "\u51c0\u5229\u6da6", False),
            ]:
                val = fb.get(key)
                if val is not None:
                    label_render = label if label_html else _esc(label)
                    kpis.append(f'<div class="kpi"><span class="kpi-val">{_esc(str(val))}</span><span class="kpi-label">{label_render}</span></div>')
            if kpis:
                degraded_chart = f'<div class="card"><h3>\u57fa\u672c\u9762\u901f\u89c8</h3><div class="kpi-row">{"".join(kpis)}</div></div>'

        body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; \u7814\u7a76\u5feb\u7167</p>
    {_degraded_banner(view.degradation_reasons)}
    {conclusion}
    {degraded_chart}
    {risks_html}
    <div class="banner banner-footer">{AI_DISCLAIMER_BANNER}</div>"""

        nav = _nav_bar(view.ticker, view.run_id, "snapshot", artifact_dir=artifact_dir)
        return _html_wrap(
            f"{_ticker_display(view)} \u7814\u7a76\u5feb\u7167 \u2014 {view.trade_date}",
            body,
            "\u7814\u7a76\u5feb\u7167",
            extra_head=_COUNTUP_JS,
            nav_html=nav,
        )

    # ── Normal Mode ──
    _sig_emoji = get_signal_emoji(view.research_action)
    conf_pct = int(view.confidence * 100)

    # V4: Hero right-side — confidence ring replaces primary text KPI (more scannable);
    # secondary KPIs in compact 3-col grid; pp-delta arrow only when meaningful.
    hero_kpis = []
    _conf_ring_html = ""
    _conf_delta_html = ""
    if view.confidence >= 0:
        # Research-tier framing: this is "weight of evidence", NOT a calibrated
        # probability. Reflection data shows the 4pp calibration gap means the
        # underlying number is unreliable; we surface it as an evidence strength
        # tier so readers don't mistake it for a price-prediction probability.
        if view.confidence >= 0.70:
            _ring_label = "\u8bc1\u636e\u5f3a\u5ea6 \u00b7 \u5f3a"
        elif view.confidence >= 0.55:
            _ring_label = "\u8bc1\u636e\u5f3a\u5ea6 \u00b7 \u4e2d"
        else:
            _ring_label = "\u8bc1\u636e\u5f3a\u5ea6 \u00b7 \u5f31"
        if getattr(view, "confidence_defaulted", False):
            _ring_label = "\u8bc1\u636e\u5f3a\u5ea6 \u00b7 \u9ed8\u8ba4"
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

    # Hero sparkline removed — full price chart is now rendered as a standalone
    # card below the cover (see _render_kline_card). Keeping this var empty
    # avoids changing the hero_kpi_grid template below.
    _sparkline_html = ""

    _ring_block = (
        f'<div style="display:flex;flex-direction:column;align-items:center;gap:.3rem;margin-bottom:.6rem">'
        f'{_conf_ring_html}{_conf_delta_html}'
        f'</div>'
    ) if _conf_ring_html else ""
    _industry_mini_html = _render_hero_industry_kpis(view.industry_compare or {})
    hero_kpi_grid = (
        f'{_ring_block}{_sparkline_html}'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;">{"".join(hero_kpis)}</div>'
        f'{_industry_mini_html}'
    )

    # Directional lean badge (only show for HOLD with explicit lean to surface tension)
    _lean = (getattr(view, "directional_lean", "") or "").strip().lower()
    _lean_reason = getattr(view, "lean_reason", "") or ""
    _lean_html = ""
    if (view.research_action or "").upper() == "HOLD" and _lean in ("bullish", "bearish", "neutral"):
        _LEAN_LABEL = {"bullish": "\u503e\u5411\u770b\u591a", "bearish": "\u503e\u5411\u770b\u7a7a", "neutral": "\u771f\u4e2d\u6027"}
        _LEAN_CSS = {"bullish": "buy", "bearish": "sell", "neutral": "hold"}
        _label = _LEAN_LABEL.get(_lean, _lean)
        _css = _LEAN_CSS.get(_lean, "hold")
        _reason_attr = f' title="{_esc(_lean_reason)}"' if _lean_reason else ""
        _lean_html = (
            f'<div style="margin-top:.4rem;font-size:.85rem;color:var(--muted);">'
            f'\u65b9\u5411\u503e\u5411: <span class="badge badge-{_css}"{_reason_attr}>{_label}</span>'
            + (f' <span style="color:var(--muted);font-size:.78rem;">\u2014 {_esc(_lean_reason)}</span>' if _lean_reason else '')
            + '</div>'
        )

    conclusion = f"""
    <div class="hero reveal">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="eyebrow">个股研究摘要 &middot; {_esc(view.trade_date)}</div>
          <div class="hero-action" style="color:var(--{color_var});">
            {_sig_emoji} {_esc(view.action_label)}
          </div>
          <div class="hero-summary">{_esc(view.one_line_summary)}</div>
          <div style="font-size:.88rem;color:var(--muted);">{_esc(view.action_explanation)}</div>
          {_lean_html}
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
        # (key, label, kind, label_is_html) \u2014 pe label uses HTML for the
        # 'TTM' superscript; other labels are plain Chinese text.
        _PE_LABEL = _pe_label_html()
        label_map = [
            ("pe", _PE_LABEL, "ratio", True),
            ("pb", "PB", "ratio", False),
            ("roe", "ROE", "pct_simple", False),
            ("gross_margin", "\u6bdb\u5229\u7387", "pct_simple", False),
            ("market_cap", "\u603b\u5e02\u503c", "mktcap_yi", False),
            ("eps", "EPS", "eps", False),
            ("net_profit", "\u51c0\u5229\u6da6", "default", False),
        ]
        for key, label, kind, label_is_html in label_map:
            val = fb.get(key)
            if val is not None:
                fmt = _format_finance_num(val, kind)
                label_render = label if label_is_html else _esc(label)
                kpis.append(
                    f'<div class="kpi"><span class="kpi-val">{_esc(fmt)}</span>'
                    f'<span class="kpi-label">{label_render}</span></div>'
                )
        if kpis:
            chart_html = (
                f'<div class="card reveal reveal-d2"><h3>\u57fa\u672c\u9762\u901f\u89c8</h3>'
                f'<div class="kpi-row">{"".join(kpis)}</div></div>'
            )

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
                    text += f" \u2014 {_esc(_truncate_display_text(desc, max_chars=120))}"
                items += f"<li>{text}</li>"
            else:
                items += f"<li>{_esc(str(r))}</li>"
        risks_html = f'<div class="card reveal reveal-d3"><h3>\u4e3b\u8981\u98ce\u9669</h3><ul>{items}</ul></div>'

    # Evidence strength + Bull/Bear bar
    evidence_html = f"""
    <div class="card reveal reveal-d4">
      <h3>依据强度</h3>
      <div style="display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;margin-bottom:.5rem;">
        <span class="badge badge-{view.evidence_strength_class}">{_esc(ev_label)}</span>
        <span style="font-size:.85rem;color:var(--muted);">{view.total_evidence} 条依据 &middot; {view.attributed_rate:.0%} 引用覆盖</span>
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
    pillar_consensus_html = _render_pillar_consensus_bar(view)
    checklist_html = _render_checklist(view)
    risk_debate_html = _render_risk_debate_summary(view)
    signal_history_html = _render_signal_history(view)

    # Wrap supporting sections for mobile collapse. Core analysis stays open;
    # secondary diagnostic blocks default to closed to lift first-screen density.
    def _mc(summary_label: str, content: str, default_open: bool = True) -> str:
        if not content or not content.strip():
            return ""
        attr = " open" if default_open else ""
        return f'<details class="mobile-collapse"{attr}><summary>{_esc(summary_label)}</summary>{content}</details>'

    cover_html = _render_cover_card(view)
    kline_card_html = _render_kline_card(view)
    industry_card_html = _render_industry_compare_card(view.industry_compare or {})
    stock_profile_html = _render_stock_profile_card(view.stock_profile or {})
    calibration_html = _render_calibration_card(view.calibration_summary or {})
    data_quality_html = _render_data_quality_flags(view.data_quality_flags or [])
    report_delta_html = _render_report_delta_card(view)
    context_html = (
        f'<div class="cols"><div>{stock_profile_html}</div><div>{calibration_html}</div></div>'
        if (stock_profile_html or calibration_html) else ""
    )
    _short_run = (view.run_id[-8:] if view.run_id else "\u2014")

    # Research-quality grade badge \u2014 shared helper across all 4 report types
    _grade_badge_html = _quality_grade_badge_html(
        grade=view.quality_grade,
        score=view.quality_score,
        weak_dims=view.quality_weak_dims,
    )

    watermark_html = (
        f'<div class="report-watermark">'
        f'{_grade_badge_html}'
        f'{"<span>\u00b7</span>" if _grade_badge_html else ""}'
        f'<span>\u62a5\u544a ID \u00b7 {_esc(_short_run)}</span>'
        f'<span>\u00b7</span>'
        f'<span>\u6570\u636e\u622a\u6b62 \u00b7 {_esc(view.trade_date)}</span>'
        f'<span>\u00b7</span>'
        f'<span>系统生成</span>'
        f'</div>'
    )

    research_banner_html = (
        f'<div class="research-banner" style="margin:.6rem 0 .8rem;'
        f'padding:.6rem .9rem;background:linear-gradient(90deg,rgba(96,165,250,0.12),rgba(96,165,250,0.04));'
        f'border:1px solid rgba(96,165,250,0.32);border-radius:12px;'
        f'color:var(--blue);font-size:.78rem;line-height:1.5;letter-spacing:.02em">'
        f'{RESEARCH_HEADER_BANNER}</div>'
    )
    body = f"""
    <h1>{_esc(_ticker_display(view))}</h1>
    <p class="subtitle">{_esc(view.trade_date)} &middot; 个股研究摘要</p>
    {watermark_html}
    {research_banner_html}
    {cover_html}
    {kline_card_html}
    {degradation_banner_html}
    {conclusion}
    {report_delta_html}
    {pillar_consensus_html}
    {lights_html}
    {battle_plan_html}
    {_mc("标的特征 / 历史表现", context_html)}
    {_mc("\u57fa\u672c\u9762\u901f\u89c8", chart_html)}
    {_mc("\u884c\u4e1a\u5bf9\u6bd4", industry_card_html)}
    {_mc("数据提示", data_quality_html, default_open=False)}
    {_mc("核心驱动 / 主要风险", f'<div class="cols"><div>{drivers_html}</div><div>{risks_html}</div></div>')}
    {_mc("依据强度", evidence_html)}
    {_mc("四维观察", checklist_html)}
    {_mc("风险视角", risk_debate_html, default_open=False)}
    {_mc("\u50ac\u5316\u5242", catalyst_html)}
    {_mc("观点历史", signal_history_html, default_open=False)}
    <div class="banner banner-footer">{AI_DISCLAIMER_BANNER}</div>"""

    nav = _nav_bar(view.ticker, view.run_id, "snapshot", artifact_dir=artifact_dir)
    return _html_wrap(f"{_ticker_display(view)} \u7814\u7a76\u5feb\u7167 \u2014 {view.trade_date}", body, "\u7814\u7a76\u5feb\u7167", nav_html=nav)
