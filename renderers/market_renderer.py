"""
Market overview page renderer.

Renders the A-share market command center report:
- Hero with regime + KPIs
- Index battle cards
- Breadth & sentiment ecosystem
- Sector engine with interactive treemap
- Limit universe & consecutive board ladder
- Next-day battle brief

Extracted from report_renderer.py to reduce file size.
Treemap/heatmap code lives in market_treemap.py.
All user-facing text is in Chinese (A-share product).
"""

import copy
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .views import MarketView
from .shared_css import _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _pct_to_hex,
    _priority_chip, _delta_arrow, _heat_cell, _section_divider,
)
from .market_treemap import (  # noqa: F401 — treemap/heatmap utilities
    _heatmap_color,
    _heatmap_risk_color,
    _render_heatmap_legend,
    _render_svg_heatmap,
    _render_detail_drawer,
    _render_heatmap_js,
    _TREEMAP_ENGINE_JS,
    _render_inline_treemap,
    _render_plotly_sector_treemap,
    _render_plotly_stock_treemap,
)


_MARKET_CSS = """
/* ── Market Command Center ── */
.mkt-shell {
  position: relative; z-index: 1; max-width: 1360px; margin: 0 auto;
  padding: 1.5rem; display: grid; gap: 1.25rem;
}
.mkt-glass {
  background: rgba(10, 22, 34, 0.82);
  border: 1px solid rgba(100, 150, 180, 0.22);
  border-radius: 14px; padding: 1.25rem;
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  transition: transform 280ms ease, box-shadow 280ms ease, border-color 280ms ease;
}
.mkt-glass:hover {
  transform: translateY(-1px);
  border-color: rgba(100, 150, 180, 0.32);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255,255,255,0.04);
}
.mkt-glass.glow-gold  { box-shadow: 0 0 24px rgba(245,158,11,.12), inset 0 1px 0 rgba(245,158,11,.06); }
.mkt-glass.glow-green { box-shadow: 0 0 20px rgba(52,211,153,.12), inset 0 1px 0 rgba(52,211,153,.06); }
.mkt-glass.glow-red   { box-shadow: 0 0 20px rgba(248,113,113,.12), inset 0 1px 0 rgba(248,113,113,.06); }
.mkt-glass.glow-blue  { box-shadow: 0 0 20px rgba(96,165,250,.12), inset 0 1px 0 rgba(96,165,250,.06); }
.mono { font-family: "JetBrains Mono", "Fira Code", "SF Mono", Menlo, Consolas, monospace; }

/* ── 1. Hero ── */
.mkt-hero {
  position: relative; overflow: hidden; border-radius: 24px;
  background: linear-gradient(135deg, rgba(10,18,32,.96), rgba(14,28,46,.92));
  border: 1px solid rgba(96,165,250,.1);
  padding: 2.2rem 2.4rem;
  box-shadow: 0 16px 48px rgba(0,0,0,.3);
}
.mkt-hero::after {
  content: ""; position: absolute;
  width: 360px; height: 360px; border-radius: 50%;
  top: -30%; right: -6%;
  background: radial-gradient(circle, rgba(245,158,11,.12), transparent 60%);
  pointer-events: none;
}
.mkt-hero::before {
  content: ""; position: absolute;
  width: 240px; height: 240px; border-radius: 50%;
  bottom: -20%; left: 10%;
  background: radial-gradient(circle, rgba(52,211,153,.08), transparent 60%);
  pointer-events: none;
}
.mkt-hero-inner { position: relative; z-index: 1; }
.mkt-hero-top {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 2rem; flex-wrap: wrap;
}
.mkt-hero-left { flex: 1; min-width: 300px; }
.mkt-hero-eyebrow {
  text-transform: uppercase; letter-spacing: .18em;
  font-size: .72rem; color: var(--blue); margin-bottom: .6rem;
}
.mkt-hero h1 {
  font-size: clamp(1.8rem, 3.5vw, 2.6rem);
  letter-spacing: -.03em; line-height: 1.15; margin-bottom: .6rem;
  background: linear-gradient(135deg, #fff 30%, var(--accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.mkt-hero-verdict { font-size: 1rem; color: var(--muted); line-height: 1.7; margin-bottom: .8rem; max-width: 600px; }
.mkt-hero-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
.mkt-hero-chip {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .3rem .75rem; border-radius: 20px;
  font-size: .78rem; font-weight: 600;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.08);
}
.mkt-hero-chip.up   { color: var(--red);   border-color: rgba(248,113,113,.25); }
.mkt-hero-chip.down { color: var(--green); border-color: rgba(52,211,153,.25); }
.mkt-hero-chip.neu  { color: var(--yellow); border-color: rgba(251,191,36,.25); }
.mkt-hero-kpi {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: .6rem; min-width: 340px;
}
.mkt-kpi {
  text-align: center; padding: .7rem .5rem;
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px; transition: border-color .2s;
}
.mkt-kpi:hover { border-color: rgba(96,165,250,.2); }
.mkt-kpi .val {
  font-size: 1.4rem; font-weight: 700;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}
.mkt-kpi .val.up   { color: var(--red); }
.mkt-kpi .val.down { color: var(--green); }
.mkt-kpi .val.neu  { color: var(--yellow); }
.mkt-kpi .val.gold { color: var(--accent); }
.mkt-kpi .lab { font-size: .7rem; color: var(--muted); margin-top: .15rem; }

/* Section head */
.mkt-sec-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: .8rem; }
.mkt-sec-title {
  font-size: 1.1rem; font-weight: 700;
  background: linear-gradient(90deg, var(--blue), var(--green));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.mkt-sec-sub { color: var(--muted); font-size: .78rem; }

/* ── 2. Index Battle Cards ── */
.idx-battle-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .8rem;
}
.idx-battle-card { position: relative; overflow: hidden; padding: .9rem 1rem; }
.idx-battle-card .idx-name { font-size: .82rem; color: var(--muted); margin-bottom: .3rem; }
.idx-battle-card .idx-close {
  font-size: 1.4rem; font-weight: 700; font-family: "JetBrains Mono", monospace;
}
.idx-battle-card .idx-pct {
  font-size: .95rem; font-weight: 600; font-family: "JetBrains Mono", monospace; margin-top: .15rem;
}
.idx-battle-card .idx-pct.up { color: var(--red); }
.idx-battle-card .idx-pct.down { color: var(--green); }
.idx-battle-card .idx-pct.flat { color: var(--muted); }
.idx-battle-card .idx-bar {
  position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 0 0 14px 14px;
}
.idx-battle-card .idx-tag {
  display: inline-block; margin-top: .4rem;
  font-size: .68rem; padding: .15rem .45rem; border-radius: 4px;
  background: rgba(255,255,255,.04); color: var(--muted);
}
.idx-battle-card .idx-tag.strong { background: rgba(52,211,153,.1); color: var(--green); }
.idx-battle-card .idx-tag.weak { background: rgba(248,113,113,.1); color: var(--red); }

/* ── 3. Breadth & Sentiment ── */
.sentiment-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.breadth-dual-bar {
  display: flex; height: 36px; border-radius: 6px; overflow: hidden;
  margin: .6rem 0; position: relative;
}
.breadth-dual-bar .bar-up { background: linear-gradient(90deg, rgba(248,113,113,.6), var(--red)); }
.breadth-dual-bar .bar-dn { background: linear-gradient(90deg, var(--green), rgba(52,211,153,.6)); }
.breadth-dual-bar .bar-label {
  position: absolute; top: 50%; transform: translateY(-50%);
  font-size: .78rem; font-weight: 600; color: #fff;
  font-family: "JetBrains Mono", monospace;
}
.breadth-dual-bar .bar-label.left { left: .6rem; }
.breadth-dual-bar .bar-label.right { right: .6rem; }
.breadth-stats { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; margin-top: .6rem; }
.breadth-stat { text-align: center; padding: .4rem; border-radius: 6px; background: rgba(255,255,255,.02); }
.breadth-stat .bs-val { font-size: 1.1rem; font-weight: 700; font-family: "JetBrains Mono", monospace; }
.breadth-stat .bs-lab { font-size: .7rem; color: var(--muted); }
.thermo-track {
  height: 16px; border-radius: 8px; position: relative;
  background: linear-gradient(90deg, var(--green), var(--yellow), var(--red));
  margin: .8rem 0 .5rem;
}
.thermo-needle {
  position: absolute; top: -4px; width: 3px; height: 24px;
  background: #fff; border-radius: 2px; box-shadow: 0 0 6px rgba(255,255,255,.5);
  transform: translateX(-50%);
}
.thermo-labels { display: flex; justify-content: space-between; font-size: .7rem; color: var(--muted); }
.alert-strip {
  margin-top: .8rem; padding: .5rem .8rem; border-radius: 6px;
  background: rgba(248,113,113,.06); border: 1px solid rgba(248,113,113,.15);
  font-size: .82rem; color: var(--red); line-height: 1.6;
}

/* ── 4. Sector Engine ── */
.sector-engine-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 1rem; }
.sector-hm-wrap { max-width: 100%; }
.shm-node { cursor: default; }
.shm-node text { pointer-events: none; font-family: "JetBrains Mono", monospace; }
.sector-sidebar { display: grid; gap: .8rem; align-content: start; }
.sector-list-title { font-size: .85rem; font-weight: 600; margin-bottom: .5rem; display: flex; align-items: center; gap: .4rem; }
.sector-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: .3rem .4rem; border-bottom: 1px solid rgba(255,255,255,.04); font-size: .82rem;
  border-radius: 6px; transition: background 150ms ease;
}
.sector-item:hover { background: rgba(255,255,255,.02); }
.sector-item .si-name { flex: 1; }
.sector-item .si-flow { font-size: .75rem; font-family: monospace; color: var(--muted); }
.sector-item .si-pct { font-family: monospace; font-weight: 600; min-width: 55px; text-align: right; }
.sector-item .si-pct.up { color: var(--red); }
.sector-item .si-pct.dn { color: var(--green); }
.rotation-phase-badge {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .3rem .6rem; border-radius: 6px;
  font-size: .78rem; font-weight: 600;
  background: rgba(96,165,250,.08); color: var(--blue);
  border: 1px solid rgba(96,165,250,.15);
}
.sector-attr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: .6rem; }
.sector-attr-card { padding: .6rem .8rem; }
.sector-attr-name { font-weight: 600; font-size: .85rem; margin-bottom: .2rem; }
.sector-attr-count { font-size: .72rem; color: var(--muted); }
.sector-attr-bar { height: 3px; border-radius: 2px; background: var(--green); margin-top: .3rem; opacity: .7; }
.sector-attr-stocks { font-size: .7rem; color: var(--muted); margin-top: .2rem; line-height: 1.4; }

/* ── 5. Limit Universe ── */
.limit-universe-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.limit-col-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .6rem; }
.limit-col-header .lch-count { font-size: 1.6rem; font-weight: 700; font-family: "JetBrains Mono", monospace; }
.limit-col-header .lch-count.up { color: var(--red); }
.limit-col-header .lch-count.dn { color: var(--green); }
.limit-col-header .lch-label { font-size: .85rem; color: var(--muted); }
.limit-stock-row {
  display: flex; align-items: center; gap: .4rem;
  padding: .35rem .4rem; border-bottom: 1px solid rgba(255,255,255,.04); font-size: .82rem;
  border-radius: 6px; transition: background 150ms ease;
}
.limit-stock-row:hover { background: rgba(255,255,255,.02);
}
.limit-stock-row .ls-name { flex: 1; font-weight: 500; }
.limit-stock-row .ls-sector {
  font-size: .7rem; padding: .1rem .4rem; border-radius: 4px;
  background: rgba(96,165,250,.06); color: var(--blue);
}
.limit-stock-row .ls-boards {
  font-size: .7rem; padding: .1rem .35rem; border-radius: 4px; font-weight: 700; font-family: monospace;
}
.limit-stock-row .ls-boards.hot { background: rgba(245,158,11,.12); color: var(--accent); }
.limit-stock-row .ls-boards.normal { background: rgba(248,113,113,.1); color: var(--red); }
.limit-stock-row .ls-seal { font-size: .75rem; color: var(--muted); font-family: monospace; min-width: 48px; text-align: right; }
.limit-stock-row .ls-pct { font-size: .78rem; font-family: monospace; font-weight: 600; min-width: 52px; text-align: right; }
.limit-stock-row .ls-pct.up { color: var(--red); }
.limit-stock-row .ls-pct.dn { color: var(--green); }
.consec-ladder { display: flex; gap: .5rem; align-items: flex-end; margin: .8rem 0; }
.consec-ladder-wrap { position: relative; }

/* ── 6. Battle Brief ── */
.battle-brief-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.brief-block { padding: .8rem 1rem; }
.brief-block-title { font-size: .82rem; font-weight: 600; margin-bottom: .4rem; display: flex; align-items: center; gap: .3rem; }
.brief-block-body { font-size: .85rem; line-height: 1.7; color: var(--muted); }
.brief-block-body ul { list-style: none; padding: 0; }
.brief-block-body li { padding: .2rem 0; }
.brief-block-body li::before { content: "\\203A"; color: var(--blue); margin-right: .4rem; font-weight: 700; }

/* ── Risk banner ── */
.mkt-risk-banner {
  background: rgba(248,113,113,.06); border: 1px solid rgba(248,113,113,.15);
  border-left: 4px solid var(--red); border-radius: 8px;
  padding: .6rem 1rem; font-size: .82rem; color: var(--red); line-height: 1.6;
}

/* ── Reused heatmap/drawer/regime ── */
.regime-badge { padding: .25rem .6rem; border-radius: 4px; font-weight: 600; font-size: .85rem; }
.regime-badge.buy { background: rgba(52,211,153,.15); color: var(--green); }
.regime-badge.hold { background: rgba(251,191,36,.15); color: var(--yellow); }
.regime-badge.sell { background: rgba(248,113,113,.15); color: var(--red); }
.heatmap-section { margin: 1.2rem 0; }
.heatmap-wrap { max-width: 960px; margin: 0 auto; }
.hm-node { cursor: pointer; transition: opacity .15s; }
.hm-node:hover { opacity: .85; }
.hm-node text { pointer-events: none; }
.hm-legend { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; font-size: .78rem; color: var(--muted); padding: .4rem 0 .6rem; }
.hm-leg-item { display: flex; align-items: center; gap: .3rem; }
.hm-leg-dot { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.hm-leg-note { font-style: italic; opacity: .7; }
.hm-mobile-list { display: none; }
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 998; display: none; }
.drawer-overlay.open { display: block; }
.detail-drawer { position: fixed; right: 0; top: 0; width: 420px; height: 100vh;
  background: var(--card); border-left: 1px solid var(--border); z-index: 999;
  transform: translateX(100%); transition: transform .25s ease;
  overflow-y: auto; padding: 1.2rem; }
.detail-drawer.open { transform: translateX(0); }
.drawer-close { position: absolute; top: .8rem; right: .8rem; background: none; border: none;
  color: var(--muted); font-size: 1.5rem; cursor: pointer; }
.drawer-header { display: flex; align-items: center; gap: .8rem; margin-bottom: 1rem; padding-right: 2rem; }
.drawer-header h3 { font-size: 1.1rem; }
.drawer-kpi { display: flex; gap: 1rem; margin-bottom: 1rem; }
.drawer-kpi .kpi { background: var(--surface); padding: .5rem .8rem; border-radius: 6px; flex: 1; text-align: center; }
.drawer-kpi .kpi-val { font-size: 1.2rem; font-weight: 700; }
.drawer-kpi .kpi-lab { font-size: .75rem; color: var(--muted); }
.drawer-section { margin: .8rem 0; }
.drawer-section h4 { font-size: .85rem; color: var(--muted); margin-bottom: .4rem; }
.hm-tooltip { position: fixed; pointer-events: none; z-index: 997;
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: .4rem .6rem; font-size: .8rem; display: none; white-space: nowrap; }

/* ── Footer ── */
.mkt-footer {
  display: flex; justify-content: space-between; align-items: center;
  font-size: .72rem; color: var(--muted); padding: .8rem 0;
  border-top: 1px solid var(--border); margin-top: .5rem;
}

/* ── Animations ── */
@keyframes mktFadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.mkt-anim { animation: mktFadeUp .45s ease both; }
.mkt-d1 { animation-delay: .06s; } .mkt-d2 { animation-delay: .12s; }
.mkt-d3 { animation-delay: .18s; } .mkt-d4 { animation-delay: .24s; }
.mkt-d5 { animation-delay: .30s; } .mkt-d6 { animation-delay: .36s; }

/* ── Responsive ── */
@media (min-width: 1200px) { .mkt-shell { max-width: 1360px; } }
@media (min-width: 768px) and (max-width: 1199px) {
  .mkt-shell { max-width: 100%; }
  .mkt-hero-top { flex-direction: column; }
  .mkt-hero-kpi { min-width: auto; }
  .sector-engine-grid { grid-template-columns: 1fr; }
  .detail-drawer { width: 380px; }
}
@media (max-width: 767px) {
  .mkt-shell { padding: .8rem; gap: 1rem; }
  .mkt-hero { padding: 1.2rem; border-radius: 14px; }
  .mkt-hero h1 { font-size: 1.5rem; }
  .mkt-hero-top { flex-direction: column; }
  .mkt-hero-kpi { grid-template-columns: repeat(3, 1fr); min-width: auto; }
  .mkt-kpi .val { font-size: 1.1rem; }
  .idx-battle-grid { grid-template-columns: repeat(2, 1fr); gap: .6rem; }
  .sentiment-grid { grid-template-columns: 1fr; }
  .sector-engine-grid { grid-template-columns: 1fr; }
  .limit-universe-grid { grid-template-columns: 1fr; }
  .battle-brief-grid { grid-template-columns: 1fr; }
  .consec-ladder { flex-direction: column; align-items: stretch; }
  .sector-attr-grid { grid-template-columns: 1fr 1fr; }
  .detail-drawer {
    right: 0; top: auto; bottom: 0; width: 100%; height: 70vh;
    border-radius: 14px 14px 0 0; border-left: none;
    border-top: 1px solid var(--border); transform: translateY(100%);
  }
  .detail-drawer.open { transform: translateY(0); }
  .heatmap-wrap > svg { display: none; }
  .hm-mobile-list { display: block !important; }
}
@media (max-width: 400px) {
  .mkt-hero-kpi { grid-template-columns: repeat(2, 1fr); }
  .idx-battle-grid { grid-template-columns: 1fr; }
}
"""


# ── Render helpers ────────────────────────────────────────────────────


def _regime_color(cls):
    if cls == "buy":
        return "var(--green)"
    elif cls == "sell":
        return "var(--red)"
    return "var(--yellow)"


def _mkt_regime_icon(cls):
    return {"buy": "\u2600\ufe0f", "hold": "\u26c5", "sell": "\U0001f327\ufe0f"}.get(cls, "\u26c5")


def _css_cls(decision_cls: str) -> str:
    """Map decision_labels class (buy/hold/sell) to KPI CSS class (up/neu/down)."""
    return {"buy": "up", "sell": "down", "hold": "neu"}.get(decision_cls, "neu")


# ── Screen 1: Hero — Market Verdict + 6 KPIs ────────────────────────


def _render_mkt_hero(view: MarketView) -> str:
    regime_cls = view.regime_class
    icon = _mkt_regime_icon(regime_cls)

    # Determine max consecutive board height
    max_board = 0
    if view.consecutive_boards:
        for level_str in view.consecutive_boards:
            try:
                max_board = max(max_board, int(level_str))
            except ValueError:
                pass

    # KPI data
    kpis = [
        (f"{view.position_cap:.1f}x", "neu" if view.position_cap == 1.0 else ("up" if view.position_cap > 1.0 else "down"), "\u4ed3\u4f4d\u4e58\u6570"),
        (_esc(view.breadth_label), _css_cls(view.breadth_class), "\u5e02\u573a\u5bbd\u5ea6"),
        (f"{view.limit_up_count}" if view.limit_up_count else "\u2014", "up", "\u6da8\u505c"),
        (f"{view.limit_down_count}" if view.limit_down_count else "\u2014", "down", "\u8dcc\u505c"),
        (f"{max_board}\u677f" if max_board >= 2 else "\u2014", "gold", "\u8fde\u677f\u9ad8\u5ea6"),
        (_esc(view.style_bias or "\u5747\u8861"), "neu", "\u98ce\u683c\u504f\u597d"),
    ]

    kpi_html = ""
    for val, cls, lab in kpis:
        kpi_html += f"""
          <div class="mkt-kpi">
            <div class="val {cls}">{val}</div>
            <div class="lab">{lab}</div>
          </div>"""

    regime_chip_cls = "up" if regime_cls == "buy" else ("down" if regime_cls == "sell" else "neu")
    breadth_chip_cls = "up" if view.breadth_class == "buy" else ("down" if view.breadth_class == "sell" else "neu")

    return f"""
    <div class="mkt-hero mkt-anim">
      <div class="mkt-hero-inner">
        <div class="mkt-hero-top">
          <div class="mkt-hero-left">
            <div class="mkt-hero-eyebrow">{_BRAND_LOGO_SM} TradingAgents \u00b7 \u5e02\u573a\u6307\u6325\u53f0</div>
            <h1>{icon} A\u80a1\u5e02\u573a\u603b\u89c8</h1>
            <div class="mkt-hero-verdict">{_esc(view.client_summary or '\u5e02\u573a\u603b\u89c8\u6570\u636e')}</div>
            <div class="mkt-hero-chips">
              <span class="mkt-hero-chip">\u4ea4\u6613\u65e5 {_esc(view.trade_date)}</span>
              <span class="mkt-hero-chip {regime_chip_cls}">Regime {_esc(view.regime_label)}</span>
              <span class="mkt-hero-chip {breadth_chip_cls}">\u5bbd\u5ea6 {_esc(view.breadth_label)}</span>
            </div>
          </div>
          <div class="mkt-hero-kpi">
            {kpi_html}
          </div>
        </div>
      </div>
    </div>"""


# ── Screen 2: Index Battle Cards ─────────────────────────────────────


def _render_idx_battle_cards(view: MarketView) -> str:
    if not view.index_sparklines:
        return ""

    cards = ""
    for code, info in view.index_sparklines.items():
        pct = info.get("change_pct", 0)
        close_val = info.get("close", 0)
        name = info.get("name", code)
        sign = "+" if pct > 0 else ""
        pct_cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        bar_color = "var(--green)" if pct > 0 else ("var(--red)" if pct < 0 else "var(--muted)")

        # V4: Strength tag → priority_chip with severity tier
        if pct > 1.0:
            tag = _priority_chip("hot", "\u5f3a\u52bf\u9886\u6da8")
        elif pct > 0:
            tag = _priority_chip("warm", "\u5c0f\u5e45\u8d70\u5f3a")
        elif pct > -1.0:
            tag = _priority_chip("cool", "\u5c0f\u5e45\u8d70\u5f31")
        else:
            tag = _priority_chip("hot", "\u663e\u8457\u627f\u538b")

        # V4: volume delta if available
        vol = info.get("volume", 0)
        prev_vol = info.get("prev_volume", 0)
        vol_cell = ""
        if vol and prev_vol:
            vol_ratio = vol / prev_vol if prev_vol else 1.0
            vol_cell = (
                f'<div style="margin-top:.25rem;font-size:var(--t-xs);color:var(--muted)">'
                f'\u91cf\u6bd4 {vol_ratio:.2f} '
                f'{_delta_arrow(prev_vol, vol, "", threshold=prev_vol*0.02, decimals=0)}'
                f'</div>'
            )

        cards += f"""
        <div class="idx-battle-card mkt-glass mkt-anim mkt-d1">
          <div class="idx-name">{_esc(name)}</div>
          <div class="idx-close">{close_val:.2f}</div>
          <div class="idx-pct {pct_cls}">{sign}{pct:.2f}%</div>
          {tag}
          {vol_cell}
          <div class="idx-bar" style="background:{bar_color}"></div>
        </div>"""

    return f"""
    <div class="mkt-glass mkt-anim mkt-d1">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u6307\u6570\u6218\u60c5\u5ba4</div>
        <div class="mkt-sec-sub">\u8c01\u5728\u9886\u6da8\uff0c\u8c01\u5728\u62d6\u540e\u817f\uff0c\u98ce\u683c\u662f\u5426\u4e00\u81f4</div>
      </div>
      <div class="idx-battle-grid">
        {cards}
      </div>
    </div>"""


# ── Screen 3: Breadth & Sentiment Ecosystem ──────────────────────────


def _render_sentiment_ecosystem(view: MarketView) -> str:
    total = view.advance_count + view.decline_count
    adv_pct = int(view.advance_count / total * 100) if total > 0 else 50
    dec_pct = 100 - adv_pct

    # Emotion score: 0=panic, 50=neutral, 100=euphoria
    # Heuristic: based on limit_up vs limit_down ratio and advance_decline
    limit_total = view.limit_up_count + view.limit_down_count
    if limit_total > 0:
        emotion = int(view.limit_up_count / limit_total * 80 + adv_pct * 0.2)
    else:
        emotion = adv_pct

    emotion = max(0, min(100, emotion))

    if emotion > 75:
        emotion_label = "\u4e50\u89c2"
        emotion_cls = "up"
    elif emotion > 40:
        emotion_label = "\u4e2d\u6027"
        emotion_cls = "neu"
    else:
        emotion_label = "\u8c28\u614e"
        emotion_cls = "down"

    # Left: breadth bar + stats
    breadth_html = f"""
    <div class="mkt-glass mkt-anim mkt-d2">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u5e02\u573a\u5bbd\u5ea6</div>
        <div class="mkt-sec-sub">{_esc(view.breadth_label)}</div>
      </div>
      <div class="breadth-dual-bar">
        <div class="bar-up" style="width:{adv_pct}%"></div>
        <div class="bar-dn" style="width:{dec_pct}%"></div>
        <span class="bar-label left">\u2191 {"≈" if view.breadth_estimated else ""}{view.advance_count}</span>
        <span class="bar-label right">{"≈" if view.breadth_estimated else ""}{view.decline_count} \u2193</span>
      </div>{"" if not view.breadth_estimated else '<div style="font-size:.7rem;color:var(--muted);margin-top:.2rem;">≈ 由涨跌比推算，非精确计数</div>'}
      <div class="breadth-stats">
        <div class="breadth-stat">
          <div class="bs-val" style="color:var(--green)">{view.limit_up_count}</div>
          <div class="bs-lab">\u6da8\u505c</div>
        </div>
        <div class="breadth-stat">
          <div class="bs-val" style="color:var(--red)">{view.limit_down_count}</div>
          <div class="bs-lab">\u8dcc\u505c</div>
        </div>
      </div>
      <div style="font-size:.8rem;color:var(--muted);margin-top:.5rem">\u8d8b\u52bf: {_esc(view.breadth_trend or '\u2014')}</div>
    </div>"""

    # Right: emotion thermometer + consec + risk alert
    consec_summary = ""
    if view.consecutive_boards:
        levels = sorted(view.consecutive_boards.items(), key=lambda x: int(x[0]))
        parts = []
        level_labels = {1: "\u9996\u677f", 2: "\u4e8c\u8fde", 3: "\u4e09\u8fde", 4: "\u56db\u8fde", 5: "\u4e94\u8fde",
                        6: "\u516d\u8fde", 7: "\u4e03\u8fde", 8: "\u516b\u8fde"}
        for k, stocks in levels:
            lbl = level_labels.get(int(k), f"{k}\u8fde")
            parts.append(f"{lbl}({len(stocks)})")
        consec_summary = f'<div style="font-size:.8rem;color:var(--muted);margin-top:.5rem">\u8fde\u677f: {" \u203a ".join(parts)}</div>'

    risk_strip = ""
    raw_alerts = view.risk_alerts
    if isinstance(raw_alerts, list):
        raw_alerts = "；".join(str(a) for a in raw_alerts if a)
    if raw_alerts and str(raw_alerts).upper() != "NONE":
        alert_text = raw_alerts[:200] + ("..." if len(raw_alerts) > 200 else "")
        risk_strip = f'<div class="alert-strip">\u26a0 {_esc(alert_text)}</div>'

    emotion_html = f"""
    <div class="mkt-glass mkt-anim mkt-d2">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u60c5\u7eea\u6e29\u5ea6\u8ba1</div>
        <div class="mkt-sec-sub">{_esc(emotion_label)} ({emotion})</div>
      </div>
      <div class="thermo-track">
        <div class="thermo-needle" style="left:{emotion}%"></div>
      </div>
      <div class="thermo-labels">
        <span>\u6050\u614c</span>
        <span>\u4e2d\u6027</span>
        <span>\u4e50\u89c2</span>
      </div>
      <div style="font-size:.7rem;color:var(--muted);margin-top:.25rem;">\u542f\u53d1\u5f0f\u6307\u6807: \u6da8\u8dcc\u505c\u6bd4\u00d780% + \u6da8\u8dcc\u5bb6\u6570\u6bd4\u00d720%</div>
      {consec_summary}
      {risk_strip}
    </div>"""

    return f"""
    <div class="sentiment-grid">
      {breadth_html}
      {emotion_html}
    </div>"""


# ── Screen 4: Sector Engine ──────────────────────────────────────────


def _render_sector_engine(view: MarketView) -> str:
    sectors = view.board_sectors

    # Left: sector heatmap treemap (Plotly interactive)
    treemap_html = ""
    if sectors:
        treemap_html = _render_plotly_sector_treemap(
            sectors, limit_ups=view.limit_up_stocks,
            sector_stocks=view.sector_stocks)
    elif view.sector_momentum:
        # Adaptive fallback: synthesize sector tiles from LLM momentum data.
        # NOTE: turnover is a rough proxy (|flow|*10), NOT real market data.
        synth_sectors = []
        for m in view.sector_momentum:
            if isinstance(m, dict):
                flow = 0.0
                try:
                    flow = float(m.get("flow", 0))
                except (ValueError, TypeError):
                    pass
                synth_sectors.append({
                    "sector": m.get("name", ""),
                    "pct_change": flow,
                    "total_turnover_yi": abs(flow) * 10,
                })
        if synth_sectors:
            treemap_html = (
                '<p style="font-size:.75rem;color:#8fa3b8;margin-bottom:.3rem;">'
                '\u26a0 \u677f\u5757\u6570\u636e\u4e0d\u53ef\u7528\uff0c'
                '\u4ee5\u4e0b\u70ed\u529b\u56fe\u7531LLM\u8f93\u51fa\u5408\u6210'
                '\uff0c\u74e6\u7247\u5927\u5c0f\u4e3a\u4f30\u7b97\u503c</p>'
                + _render_plotly_sector_treemap(
                    synth_sectors, sector_stocks=view.sector_stocks)
            )

    # Right sidebar: leaders + avoid + rotation phase + attribution
    leaders_html = ""
    for s in view.sector_leaders[:5]:
        leaders_html += f'<div class="sector-item"><span class="si-name">{_esc(s)}</span><span class="si-pct up">\u4e3b\u7ebf</span></div>'
    avoids_html = ""
    for s in view.avoid_sectors[:3]:
        avoids_html += f'<div class="sector-item"><span class="si-name">{_esc(s)}</span><span class="si-pct dn">\u9000\u6f6e</span></div>'

    # Momentum flows — split by actual price direction, show change% + net inflow
    pos_items = []
    neg_items = []
    for m in view.sector_momentum:
        if not isinstance(m, dict):
            continue
        try:
            flow_val = float(m.get("flow", 0))
        except (ValueError, TypeError):
            flow_val = 0.0
        (pos_items if flow_val > 0 else neg_items).append(m)
    pos_items.sort(key=lambda x: float(x.get("flow", 0) or 0), reverse=True)
    neg_items.sort(key=lambda x: float(x.get("flow", 0) or 0))

    momentum_html = ""
    for m in pos_items[:5]:
        nm = m.get("name", "")
        pct = m.get("flow", "")
        net = m.get("net_inflow_yi", "")
        net_str = f" ({net:+.1f}\u4ebf)" if net else ""
        momentum_html += f'<div class="sector-item"><span class="si-name">{_esc(nm)}</span><span class="si-flow">{_esc(str(pct))}%{_esc(net_str)}</span><span class="si-pct up">\u2191</span></div>'
    if neg_items:
        momentum_html += '<div style="border-top:1px solid rgba(0,0,0,.08);margin:.4rem 0"></div>'
        for m in neg_items[:5]:
            nm = m.get("name", "")
            pct = m.get("flow", "")
            net = m.get("net_inflow_yi", "")
            net_str = f" ({net:+.1f}\u4ebf)" if net else ""
            momentum_html += f'<div class="sector-item"><span class="si-name">{_esc(nm)}</span><span class="si-flow">{_esc(str(pct))}%{_esc(net_str)}</span><span class="si-pct dn">\u2193</span></div>'

    rotation_badge = ""
    phase_labels = {"early": "\u65e9\u671f", "mid": "\u4e2d\u671f", "late": "\u6676\u671f", "peak": "\u89c1\u9876"}
    if view.rotation_phase:
        phase_label = phase_labels.get(view.rotation_phase, view.rotation_phase)
        rotation_badge = f'<span class="rotation-phase-badge">\u8f6e\u52a8\u9636\u6bb5: {_esc(phase_label)}</span>'

    sidebar_html = f"""
    <div class="sector-sidebar">
      <div class="mkt-glass">
        <div class="sector-list-title">\u4e3b\u5347\u4e3b\u7ebf {rotation_badge}</div>
        {leaders_html or '<div style="font-size:.82rem;color:var(--muted)">\u6682\u65e0\u6570\u636e</div>'}
      </div>
      <div class="mkt-glass">
        <div class="sector-list-title">\u56de\u907f\u65b9\u5411</div>
        {avoids_html or '<div style="font-size:.82rem;color:var(--muted)">\u6682\u65e0\u6570\u636e</div>'}
      </div>
      <div class="mkt-glass">
        <div class="sector-list-title">\u8d44\u91d1\u6d41\u5411</div>
        {momentum_html or '<div style="font-size:.82rem;color:var(--muted)">\u6682\u65e0\u6570\u636e</div>'}
      </div>
    </div>"""

    # Sector attribution (below heatmap if available)
    attr_html = ""
    attr = view.limit_sector_attribution
    if attr:
        max_count = max((v.get("count", 0) if isinstance(v, dict) else (len(v) if isinstance(v, list) else 0)) for v in attr.values()) or 1
        attr_cards = ""
        for sector, info in list(attr.items())[:12]:
            if isinstance(info, dict):
                count = info.get("count", 0)
                stocks = info.get("stocks", [])
            else:
                count = len(info) if isinstance(info, list) else 0
                stocks = info if isinstance(info, list) else []
            bar_pct = int(count / max_count * 100)
            stock_names = "\u3001".join(str(s) for s in stocks[:4])
            if len(stocks) > 4:
                stock_names += "\u2026"
            attr_cards += f"""
            <div class="sector-attr-card mkt-glass">
              <div class="sector-attr-name">{_esc(sector)}</div>
              <div class="sector-attr-count">{count} \u53ea\u6da8\u505c</div>
              <div class="sector-attr-bar" style="width:{bar_pct}%"></div>
              <div class="sector-attr-stocks">{_esc(stock_names)}</div>
            </div>"""

        # Mini donut for top sectors
        import math as _m
        _donut = ""
        _counts = []
        for _s, _info in list(attr.items())[:6]:
            _c = _info.get("count", 0) if isinstance(_info, dict) else (len(_info) if isinstance(_info, list) else 0)
            if _c > 0:
                _counts.append((_s, _c))
        _total = sum(c for _, c in _counts)
        if _total > 0:
            _palette = ["#f87171", "#fbbf24", "#60a5fa", "#34d399", "#a78bfa", "#fb923c"]
            _arcs = ""
            _legend = ""
            _start = 0
            _cx, _cy, _r = 50, 50, 38
            for _i, (_s, _c) in enumerate(_counts):
                _frac = _c / _total
                _end = _start + _frac * 2 * _m.pi
                _large = 1 if _frac > 0.5 else 0
                _x1, _y1 = _cx + _r * _m.sin(_start), _cy - _r * _m.cos(_start)
                _x2, _y2 = _cx + _r * _m.sin(_end), _cy - _r * _m.cos(_end)
                _col = _palette[_i % len(_palette)]
                _arcs += f'<path d="M{_x1:.1f},{_y1:.1f} A{_r},{_r} 0 {_large} 1 {_x2:.1f},{_y2:.1f}" fill="none" stroke="{_col}" stroke-width="12"/>'
                _legend += f'<span style="color:{_col};font-size:.75rem;">\u25cf {_esc(_s)}({_c})</span> '
                _start = _end
            _donut = (
                f'<div style="display:flex;align-items:center;gap:1rem;margin-bottom:.6rem;">'
                f'<svg viewBox="0 0 100 100" width="80" height="80">{_arcs}</svg>'
                f'<div style="line-height:1.8">{_legend}</div></div>'
            )

        attr_html = f"""
      <div style="margin-top:1rem">
        <div class="mkt-sec-head">
          <div class="mkt-sec-title">\u6da8\u505c\u677f\u5757\u5f52\u5c5e</div>
          <div class="mkt-sec-sub">\u6743\u91cd\u5e26\u52a8 vs \u9898\u6750\u6269\u6563</div>
        </div>
        {_donut}
        <div class="sector-attr-grid">
          {attr_cards}
        </div>
      </div>"""

    if not treemap_html and not sidebar_html:
        return ""

    return f"""
    <div class="mkt-glass mkt-anim mkt-d3">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u4e3b\u7ebf\u677f\u5757\u5f15\u64ce</div>
        <div class="mkt-sec-sub">\u9762\u79ef=\u677f\u5757\u6210\u4ea4\u989d \u989c\u8272=\u6da8\u8dcc\u5e45 | \u9886\u6da8/\u9000\u6f6e \u00b7 \u8d44\u91d1\u6d41\u5411</div>
      </div>
      <div class="sector-engine-grid">
        <div>
          {treemap_html}
        </div>
        {sidebar_html}
      </div>
      {attr_html}
    </div>"""


# ── Screen 5: Limit Universe / Consecutive Board Ecosystem ───────────


def _render_limit_universe(view: MarketView) -> str:
    if not view.limit_up_stocks and not view.limit_down_stocks and not view.consecutive_boards:
        return ""

    # Consecutive board ladder — interactive
    consec = view.consecutive_boards
    ladder_html = ""
    if consec:
        import json as _json
        def _safe_level_key(x):
            try:
                return int(x[0])
            except (ValueError, TypeError):
                return 0
        levels = sorted(consec.items(), key=_safe_level_key)
        level_labels = {1: "\u9996\u677f", 2: "\u4e8c\u8fde\u677f", 3: "\u4e09\u8fde\u677f", 4: "\u56db\u8fde\u677f",
                        5: "\u4e94\u8fde\u677f", 6: "\u516d\u8fde\u677f", 7: "\u4e03\u8fde\u677f", 8: "\u516b\u8fde\u677f"}
        # Build JSON data for JS
        ladder_data = []
        prev_count = 0
        for level_str, stocks in levels:
            try:
                level = int(level_str)
            except (ValueError, TypeError):
                continue
            count = len(stocks)
            rate = round(count / prev_count * 100) if prev_count > 0 and level > 1 else 0
            prev_count = count
            stock_list = []
            for s in stocks:
                stock_list.append({
                    "name": str(s.get("name", "")),
                    "ticker": str(s.get("ticker", "")),
                    "sector": str(s.get("sector", "")),
                    "seal": round(float(s.get("seal_amount_yi", 0) or 0), 2),
                    "first": str(s.get("first_seal", "") or ""),
                })
            ladder_data.append({
                "level": level,
                "label": level_labels.get(level, f"{level}\u8fde\u677f"),
                "count": count,
                "rate": rate,
                "stocks": stock_list,
            })
        ladder_json = _json.dumps(ladder_data, ensure_ascii=False).replace("</", "<\\/")  # N-SEC-1: prevent script injection

        ladder_html = f"""
      <div class="mkt-glass mkt-anim mkt-d4" style="margin-bottom:1rem">
        <div class="mkt-sec-head">
          <div class="mkt-sec-title">\u8fde\u677f\u68af\u961f</div>
          <div class="mkt-sec-sub">\u70b9\u51fb\u5c42\u7ea7\u67e5\u770b\u6210\u5458\u80a1</div>
        </div>
        <div class="consec-ladder-wrap" id="consec-ladder-wrap">
          <div class="consec-ladder" id="consec-ladder"></div>
          <div id="consec-detail" style="display:none"></div>
        </div>
      </div>
      <script>
      (function(){{
        var D = {ladder_json};
        var maxC = 0;
        for (var i = 0; i < D.length; i++) if (D[i].count > maxC) maxC = D[i].count;
        var ladder = document.getElementById('consec-ladder');
        var detail = document.getElementById('consec-detail');
        var expanded = -1;

        /* Color gradient: higher tier = more intense */
        var tierColors = [
          '#E8F8DC', '#d4f0c8', '#b8e4a8', '#9cd888',
          '#E8A8B0', '#d89098', '#c87880', '#b86068'
        ];
        function tierColor(lvl, total) {{
          if (total <= 1) return '#E8F8DC';
          var t = (lvl - 1) / Math.max(total - 1, 1);
          var idx = Math.min(Math.round(t * (tierColors.length - 1)), tierColors.length - 1);
          return tierColors[idx];
        }}

        function renderLadder() {{
          ladder.innerHTML = '';
          ladder.style.display = 'flex';
          ladder.style.gap = '6px';
          ladder.style.alignItems = 'flex-end';
          detail.style.display = 'none';
          expanded = -1;

          for (var i = 0; i < D.length; i++) {{
            (function(idx) {{
              var d = D[idx];
              var barH = Math.max(Math.round(d.count / maxC * 140), 32);
              var col = document.createElement('div');
              col.style.cssText = 'flex:1;display:flex;flex-direction:column;align-items:center;cursor:pointer;transition:all 0.2s ease';

              /* Bar */
              var bar = document.createElement('div');
              var bg = tierColor(d.level, D.length);
              bar.style.cssText = 'width:100%;border-radius:10px 10px 4px 4px;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:32px;transition:all 0.2s ease;box-shadow:inset 0 1px 0 rgba(255,255,255,0.4),inset 0 -1px 0 rgba(0,0,0,0.05),0 2px 8px rgba(0,0,0,0.06)';
              bar.style.height = barH + 'px';
              bar.style.background = 'linear-gradient(180deg, ' + bg + ', ' + bg + 'cc)';

              var numEl = document.createElement('div');
              numEl.style.cssText = 'font:700 1.5rem/1 "PingFang SC","Microsoft YaHei",sans-serif;color:#2a2a2a';
              numEl.textContent = d.count;
              bar.appendChild(numEl);

              /* Top stock name preview */
              if (d.stocks.length > 0 && barH > 48) {{
                var preview = document.createElement('div');
                preview.style.cssText = 'font:400 11px/1.3 "PingFang SC",sans-serif;color:rgba(42,42,42,0.6);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:90%;text-align:center';
                preview.textContent = d.stocks[0].name + (d.stocks.length > 1 ? ' ...' : '');
                bar.appendChild(preview);
              }}
              col.appendChild(bar);

              /* Label */
              var lbl = document.createElement('div');
              lbl.style.cssText = 'font:500 13px/1.4 "PingFang SC",sans-serif;color:#666;margin-top:6px';
              lbl.textContent = d.label;
              col.appendChild(lbl);

              /* Promotion rate */
              if (d.rate > 0) {{
                var rate = document.createElement('div');
                rate.style.cssText = 'font:400 11px/1.3 "PingFang SC",sans-serif;color:#888;margin-top:2px';
                rate.textContent = '\u664b\u7ea7 ' + d.rate + '%';
                col.appendChild(rate);
              }}

              /* Hover */
              col.addEventListener('mouseenter', function() {{
                bar.style.transform = 'scaleY(1.05)';
                bar.style.transformOrigin = 'bottom';
                bar.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.5),0 4px 16px rgba(0,0,0,0.1)';
              }});
              col.addEventListener('mouseleave', function() {{
                bar.style.transform = '';
                bar.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.4),inset 0 -1px 0 rgba(0,0,0,0.05),0 2px 8px rgba(0,0,0,0.06)';
              }});

              /* Click to expand */
              col.addEventListener('click', function() {{
                if (expanded === idx) {{ renderLadder(); return; }}
                showDetail(idx);
              }});

              ladder.appendChild(col);

              /* Arrow between tiers */
              if (idx < D.length - 1) {{
                var arrow = document.createElement('div');
                arrow.style.cssText = 'display:flex;align-items:center;color:#bbb;font-size:18px;align-self:center;padding-bottom:24px';
                arrow.textContent = '\u203a';
                ladder.appendChild(arrow);
              }}
            }})(i);
          }}
        }}

        function showDetail(idx) {{
          expanded = idx;
          var d = D[idx];
          detail.innerHTML = '';
          detail.style.display = 'block';
          detail.style.cssText = 'display:block;margin-top:12px;border-radius:12px;background:rgba(255,255,255,0.92);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid rgba(0,0,0,0.05);overflow:hidden;animation:fadeIn 0.25s ease';

          /* Header */
          var hdr = document.createElement('div');
          hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid rgba(0,0,0,0.05);background:rgba(0,0,0,0.015)';
          var title = document.createElement('div');
          title.style.cssText = 'font:600 14px/1.4 "PingFang SC",sans-serif;color:#1a1a1a';
          title.textContent = d.label + ' \u00b7 ' + d.count + ' \u53ea';
          hdr.appendChild(title);
          var closeBtn = document.createElement('div');
          closeBtn.style.cssText = 'cursor:pointer;font:400 13px/1 sans-serif;color:#888;padding:4px 10px;border-radius:16px;background:rgba(0,0,0,0.04);transition:all 0.15s ease';
          closeBtn.textContent = '\u2715 \u6536\u8d77';
          closeBtn.addEventListener('mouseenter', function(){{ closeBtn.style.background = 'rgba(0,0,0,0.08)'; }});
          closeBtn.addEventListener('mouseleave', function(){{ closeBtn.style.background = 'rgba(0,0,0,0.04)'; }});
          closeBtn.addEventListener('click', function(){{ renderLadder(); }});
          hdr.appendChild(closeBtn);
          detail.appendChild(hdr);

          /* Stock grid */
          var grid = document.createElement('div');
          grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1px;background:rgba(0,0,0,0.04);padding:1px';

          for (var j = 0; j < d.stocks.length; j++) {{
            var s = d.stocks[j];
            var cell = document.createElement('div');
            cell.style.cssText = 'background:#fff;padding:10px 14px;display:flex;flex-direction:column;gap:3px;transition:background 0.15s ease';
            cell.addEventListener('mouseenter', function(){{ this.style.background = 'rgba(0,0,0,0.015)'; }});
            cell.addEventListener('mouseleave', function(){{ this.style.background = '#fff'; }});

            var row1 = document.createElement('div');
            row1.style.cssText = 'display:flex;align-items:center;justify-content:space-between';
            var nameEl = document.createElement('span');
            nameEl.style.cssText = 'font:600 13px/1.4 "PingFang SC",sans-serif;color:#1a1a1a';
            nameEl.textContent = s.name;
            row1.appendChild(nameEl);
            if (s.seal > 0) {{
              var sealEl = document.createElement('span');
              sealEl.style.cssText = 'font:500 11px/1 "PingFang SC",sans-serif;color:#c87880;background:rgba(232,168,176,0.15);padding:2px 6px;border-radius:10px';
              sealEl.textContent = '\u5c01 ' + s.seal.toFixed(1) + '\u4ebf';
              row1.appendChild(sealEl);
            }}
            cell.appendChild(row1);

            var row2 = document.createElement('div');
            row2.style.cssText = 'display:flex;align-items:center;gap:8px;font:400 11px/1.3 "PingFang SC",sans-serif;color:#999';
            var tickerEl = document.createElement('span');
            tickerEl.textContent = s.ticker;
            row2.appendChild(tickerEl);
            if (s.sector) {{
              var secEl = document.createElement('span');
              secEl.style.cssText = 'color:#aaa';
              secEl.textContent = s.sector;
              row2.appendChild(secEl);
            }}
            if (s.first) {{
              var firstEl = document.createElement('span');
              firstEl.style.cssText = 'margin-left:auto;color:#bbb';
              firstEl.textContent = '\u9996\u5c01 ' + s.first;
              row2.appendChild(firstEl);
            }}
            cell.appendChild(row2);
            grid.appendChild(cell);
          }}

          detail.appendChild(grid);
        }}

        /* fadeIn keyframe */
        var style = document.createElement('style');
        style.textContent = '@keyframes fadeIn {{ from {{ opacity:0;transform:translateY(-8px) }} to {{ opacity:1;transform:translateY(0) }} }}';
        document.head.appendChild(style);

        renderLadder();
      }})();
      </script>"""

    # Limit up/down dual columns
    limit_html = ""
    if view.limit_up_stocks or view.limit_down_stocks:
        # Limit up column
        up_rows = ""
        for s in view.limit_up_stocks[:25]:
            boards = int(s.get("boards", 1))
            board_cls = "hot" if boards >= 3 else "normal"
            seal = float(s.get("seal_amount_yi", 0) or 0)
            seal_str = f"{seal:.1f}\u4ebf" if seal > 0 else ""
            up_rows += f"""
            <div class="limit-stock-row">
              <span class="ls-name">{_esc(str(s.get('name', '')))}</span>
              <span class="ls-sector">{_esc(str(s.get('sector', '')))}</span>
              <span class="ls-boards {board_cls}">{boards}\u677f</span>
              <span class="ls-seal">{seal_str}</span>
            </div>"""

        up_col = ""
        if up_rows:
            up_col = f"""
          <div class="limit-col">
            <div class="limit-col-header">
              <span class="lch-count up">{len(view.limit_up_stocks)}</span>
              <span class="lch-label">\u6da8\u505c</span>
            </div>
            {up_rows}
          </div>"""

        # Limit down column
        down_rows = ""
        for s in view.limit_down_stocks[:15]:
            pct = float(s.get("pct_change", 0) or 0)
            down_rows += f"""
            <div class="limit-stock-row">
              <span class="ls-name">{_esc(str(s.get('name', '')))}</span>
              <span class="ls-sector">{_esc(str(s.get('sector', '')))}</span>
              <span class="ls-pct dn">{pct:+.1f}%</span>
            </div>"""

        down_col = ""
        if down_rows:
            down_col = f"""
          <div class="limit-col">
            <div class="limit-col-header">
              <span class="lch-count dn">{len(view.limit_down_stocks)}</span>
              <span class="lch-label">\u8dcc\u505c</span>
            </div>
            {down_rows}
          </div>"""

        limit_html = f"""
      <div class="mkt-glass mkt-anim mkt-d4">
        <div class="mkt-sec-head">
          <div class="mkt-sec-title">\u6da8\u8dcc\u505c\u5b87\u5b99</div>
          <div class="mkt-sec-sub">\u9ad8\u8fa8\u8bc6\u5ea6\u9f99\u5934 \u00b7 \u4e8f\u94b1\u6548\u5e94\u6837\u672c</div>
        </div>
        <div class="limit-universe-grid">
          {up_col}
          {down_col}
        </div>
      </div>"""

    return f"{ladder_html}{limit_html}"


# ── Screen 6: Next-Day Battle Brief ──────────────────────────────────


def _render_battle_brief(view: MarketView) -> str:
    # Extract structured content from market_context fields
    conclusion = view.market_weather or ""
    leaders = view.sector_leaders
    avoids = view.avoid_sectors
    position_advice = f"\u5efa\u8bae\u4ed3\u4f4d\u4e58\u6570 {view.position_cap:.1f}x\uff0c\u98ce\u683c\u504f {_esc(view.style_bias or '\u5747\u8861')}"

    # Build leader/avoid lists
    leaders_li = "".join(f"<li>{_esc(s)}</li>" for s in leaders[:5]) if leaders else "<li>\u6682\u65e0\u660e\u786e\u4e3b\u7ebf</li>"
    avoids_li = "".join(f"<li>{_esc(s)}</li>" for s in avoids[:5]) if avoids else "<li>\u6682\u65e0\u660e\u786e\u56de\u907f\u65b9\u5411</li>"

    return f"""
    <div class="mkt-glass mkt-anim mkt-d5">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u6b21\u65e5\u4f5c\u6218\u7b80\u62a5</div>
        <div class="mkt-sec-sub">\u770b\u5b8c\u77e5\u9053\u660e\u5929\u600e\u4e48\u5e72</div>
      </div>
      <div class="battle-brief-grid">
        <div class="brief-block mkt-glass glow-blue">
          <div class="brief-block-title">\u5e02\u573a\u7ed3\u8bba</div>
          <div class="brief-block-body">{_esc(conclusion or '\u6682\u65e0\u603b\u7ed3')}</div>
        </div>
        <div class="brief-block mkt-glass glow-gold">
          <div class="brief-block-title">\u4ed3\u4f4d\u5efa\u8bae</div>
          <div class="brief-block-body">{position_advice}</div>
        </div>
        <div class="brief-block mkt-glass glow-green">
          <div class="brief-block-title">\u91cd\u70b9\u89c2\u5bdf\u65b9\u5411</div>
          <div class="brief-block-body"><ul>{leaders_li}</ul></div>
        </div>
        <div class="brief-block mkt-glass glow-red">
          <div class="brief-block-title">\u660e\u786e\u56de\u907f\u65b9\u5411</div>
          <div class="brief-block-body"><ul>{avoids_li}</ul></div>
        </div>
      </div>
    </div>"""


# ── render_market_page (complete page assembly) ──────────────────────


def render_market_page(view: MarketView) -> str:
    """Render the /market overview page as a complete HTML document."""
    # Screen 1: Hero
    hero = _render_mkt_hero(view)

    # Screen 2: Index battle cards
    idx_cards = _render_idx_battle_cards(view)

    # Screen 3: Breadth & sentiment ecosystem
    sentiment = _render_sentiment_ecosystem(view)

    # Screen 4: Sector engine
    sector_engine = _render_sector_engine(view)

    # Screen 5: Limit universe & consecutive boards
    limit_universe = _render_limit_universe(view)

    # Screen 6: Battle brief
    battle_brief = _render_battle_brief(view)

    # Stock-level heatmap — only when real per-stock data exists
    # (skip when heatmap was synthesized from sector_momentum — same as sector engine)
    heatmap_section = ""
    if view.heatmap_data:
        hm_mode = view.heatmap_data.get("view_mode", "") if isinstance(view.heatmap_data, dict) else ""
        if hm_mode != "momentum":
            plotly_stock = _render_plotly_stock_treemap(view.heatmap_data)
            if plotly_stock:
                heatmap_section = f"""
    <div class="mkt-glass mkt-anim mkt-d6">
      <div class="mkt-sec-head">
        <div class="mkt-sec-title">\u4e2a\u80a1\u70ed\u529b\u56fe</div>
        <div class="mkt-sec-sub">\u60ac\u505c\u67e5\u770b\u8be6\u60c5</div>
      </div>
      {plotly_stock}
    </div>"""

    disclaimer = '<div class="mkt-glass" style="font-size:.8rem;color:var(--muted);text-align:center;padding:.6rem">\u672c\u62a5\u544a\u7531 AI \u591a\u667a\u80fd\u4f53\u7cfb\u7edf\u81ea\u52a8\u751f\u6210\uff0c\u4ec5\u4f9b\u7814\u7a76\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002</div>'

    body = f"""
    <div class="mkt-shell">
      {hero}
      {disclaimer}
      {idx_cards}
      {sentiment}
      {sector_engine}
      {limit_universe}
      {heatmap_section}
      {battle_brief}

      <div class="mkt-footer">
        <div>{_BRAND_LOGO_SM} TradingAgents \u00b7 \u5e02\u573a\u6307\u6325\u53f0
        {' \u00b7 <a href="recap-' + view.trade_date.replace('-','') + '.html" style="color:var(--accent);text-decoration:none;">\u2192 \u6bcf\u65e5\u590d\u76d8</a>' if view.trade_date else ''}</div>
        <div>\u4ea4\u6613\u65e5 {_esc(view.trade_date)} \u00b7 v0.2.0</div>
      </div>
    </div>"""

    from .pool_renderer import _POOL_CSS

    return _html_wrap(
        f"\u5e02\u573a\u6307\u6325\u53f0 \u2014 {view.trade_date}",
        body, "\u5e02\u573a\u6307\u6325\u53f0",
        extra_css=_POOL_CSS + _MARKET_CSS,
    )


def generate_market_report(
    market_context: dict,
    market_snapshot=None,
    output_dir: str = "data/reports",
    trade_date: str = "",
    heatmap_data=None,
    board_data: dict = None,
    allow_live_fetch: bool = True,
) -> Optional[str]:
    """Generate standalone market overview HTML report.

    Args:
        market_context: Market context dict.
        market_snapshot: MarketSnapshot instance. Pass None only for
            degraded rendering (limit data will be missing).
        output_dir: Where to write HTML.
        trade_date: Trade date string.
        heatmap_data: Optional HeatmapData for embedding.
        board_data: Optional dict with sectors, limit_ups, limit_downs,
                    consecutive_boards, limit_sector_attribution.

    Returns:
        Path to generated HTML file, or None.
    """
    if not market_context:
        return None
    if market_snapshot is None:
        logger.warning(
            "generate_market_report called with market_snapshot=None — "
            "limit_up/limit_down data will be missing. "
            "Use MarketLayerData.load() to ensure snapshot is available."
        )

    # Override sector_momentum with snapshot's actual price-change data.
    # The LLM agent's sector_momentum is sorted by net_inflow which is
    # misleading (sectors can have inflow yet fall in price).  The snapshot
    # sector_fund_flow is now sorted by actual 涨跌幅, which is ground truth.
    market_context = copy.copy(market_context)  # avoid mutating caller's dict
    if market_snapshot:
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

    # Adaptive heatmap: board_data → sector_momentum → None
    if heatmap_data is None:
        from ..heatmap import HeatmapData
        if board_data and (board_data.get("sector_stocks") or board_data.get("sectors")):
            spot_data = getattr(market_snapshot, "stock_spots", {}) if market_snapshot else {}
            heatmap_data = HeatmapData.build_from_sectors(
                board_data=board_data,
                market_context=market_context or {},
                spot_data=spot_data,
            )
        elif market_context.get("sector_momentum"):
            heatmap_data = HeatmapData.build_from_momentum(market_context)

    # Adaptive sector drill-down: when board_data lacks sector_stocks,
    # try fetching constituent stocks for momentum sectors via akshare
    if board_data is None:
        board_data = {}
    if not board_data.get("sector_stocks"):
        momentum = market_context.get("sector_momentum", []) if market_context else []
        sector_names = [m.get("name", "") for m in momentum
                        if isinstance(m, dict) and m.get("name")]
        if sector_names and allow_live_fetch:
            try:
                from ..akshare_collector import collect_sector_leader_stocks
                fetched = collect_sector_leader_stocks(sector_names)
                if fetched:
                    board_data["sector_stocks"] = fetched
            except Exception:
                logger.warning("Sector drill-down fetch failed, rendering without constituent stocks", exc_info=True)

    view = MarketView.build(
        market_context=market_context,
        market_snapshot=market_snapshot,
        heatmap_data=heatmap_data,
        board_data=board_data,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    date_slug = (trade_date or market_context.get("trade_date", "")).replace("-", "")
    if not date_slug:
        from datetime import date as _date
        date_slug = _date.today().isoformat().replace("-", "")

    path = out_dir / f"market-{date_slug}.html"
    path.write_text(render_market_page(view), encoding="utf-8")
    return str(path)
