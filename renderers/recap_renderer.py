"""
Daily Recap renderer — Neon Trading Cockpit visual theme.

Sections:
1. Hero (date, weather, summary, position, risk)
2. Index KPI ribbon + K-line/MACD/RSI chart panel (5 indices, tab switch)
3. Sector heatmap (treemap, click → drawer)
4. Limit board (dual cards, consecutive board count)
5. Consecutive board flow (ladder chart)
6. Red close screener (tables, CSV copy)

All CSS/JS inline — self-contained HTML for static export.
"""

import json as _json
from pathlib import Path
from typing import Optional

from .report_renderer import _squarify, _html_wrap
from .decision_labels import (
    get_regime_label, get_regime_class,
    get_breadth_label, get_breadth_class,
)


# ── Escape helper ────────────────────────────────────────────────────

def _esc(text: str) -> str:
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ── Neon Trading Cockpit CSS ─────────────────────────────────────────

_RECAP_CSS = """
/* ── Neon Trading Cockpit ── */
:root {
  --bg: #0a0e1a;
  --fg: #c8d6e5;
  --card: rgba(14, 21, 38, 0.88);
  --border: rgba(0, 212, 255, 0.12);
  --green: #00ff88;
  --red: #ff4757;
  --yellow: #ffd32a;
  --blue: #00d4ff;
  --muted: #5a6f82;
  --surface: rgba(12, 18, 32, 0.92);
  --glow-green: rgba(0, 255, 136, 0.15);
  --glow-red: rgba(255, 71, 87, 0.15);
  --glow-blue: rgba(0, 212, 255, 0.12);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", -apple-system,
               BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background:
    linear-gradient(180deg, #0a0e1a 0%, #0d1220 40%, #080c16 100%);
  background-attachment: fixed;
  color: var(--fg);
  line-height: 1.7;
  min-height: 100vh;
}
/* Grid background */
body::before {
  content: "";
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(0,212,255,.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,.03) 1px, transparent 1px);
  background-size: 60px 60px;
  pointer-events: none;
  z-index: 0;
}
.recap-shell { position: relative; z-index: 1; max-width: 1360px; margin: 0 auto; padding: 1.5rem; display: grid; gap: 1.25rem; }

/* ── Glass card ── */
.glass {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1.25rem;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: transform 280ms ease, box-shadow 280ms ease, border-color 280ms ease;
}
.glass:hover {
  transform: translateY(-1px);
  border-color: rgba(0, 212, 255, 0.18);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255,255,255,0.04);
}
.glass-glow-green { box-shadow: 0 0 20px var(--glow-green), inset 0 1px 0 rgba(0,255,136,.06); }
.glass-glow-red   { box-shadow: 0 0 20px var(--glow-red),   inset 0 1px 0 rgba(255,71,87,.06); }
.glass-glow-blue  { box-shadow: 0 0 20px var(--glow-blue),  inset 0 1px 0 rgba(0,212,255,.06); }

/* Monospace numbers */
.mono { font-family: "JetBrains Mono", "Fira Code", "SF Mono", Menlo, Consolas, monospace; }

/* ── Hero ── */
.recap-hero {
  position: relative; overflow: hidden;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(10,14,26,.96), rgba(14,24,42,.92));
  border: 1px solid rgba(0,212,255,.1);
  padding: 2rem 2.2rem;
  box-shadow: 0 12px 40px rgba(0,0,0,.3);
}
.recap-hero::after {
  content: ""; position: absolute;
  width: 300px; height: 300px; border-radius: 50%;
  top: -30%; right: -5%;
  background: radial-gradient(circle, rgba(0,255,136,.08), transparent 60%);
  pointer-events: none;
}
.hero-eyebrow {
  text-transform: uppercase; letter-spacing: .18em;
  font-size: .72rem; color: var(--blue); margin-bottom: .6rem;
}
.recap-hero h1 {
  font-size: clamp(1.8rem, 3.5vw, 2.8rem);
  letter-spacing: -.03em; line-height: 1.1; margin-bottom: .5rem;
  background: linear-gradient(135deg, #fff 30%, var(--blue));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-summary { color: #9ab; font-size: 1rem; margin-bottom: .8rem; }
.hero-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
.hero-chip {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .3rem .75rem; border-radius: 20px;
  font-size: .78rem; font-weight: 600;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.08);
}
.hero-chip.up   { color: var(--green); border-color: rgba(0,255,136,.2); }
.hero-chip.down { color: var(--red);   border-color: rgba(255,71,87,.2); }
.hero-chip.neu  { color: var(--yellow); border-color: rgba(255,211,42,.2); }

/* ── Section head ── */
.sec-head {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: .8rem;
}
.sec-title {
  font-size: 1.1rem; font-weight: 700;
  background: linear-gradient(90deg, var(--blue), var(--green));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.sec-sub { color: var(--muted); font-size: .78rem; }

/* ── KPI Ribbon ── */
.kpi-ribbon {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: .8rem; margin-bottom: 1rem;
}
.kpi-cell { text-align: center; padding: .6rem .5rem; }
.kpi-cell .val {
  font-size: 1.35rem; font-weight: 700;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}
.kpi-cell .lab { font-size: .72rem; color: var(--muted); margin-top: .15rem; }
.kpi-cell .val.up   { color: var(--green); }
.kpi-cell .val.down { color: var(--red); }
.kpi-cell .val.neu  { color: var(--yellow); }

/* ── Index Tabs ── */
.idx-tabs {
  display: flex; gap: .3rem; flex-wrap: wrap;
  border-bottom: 1px solid var(--border); padding-bottom: .3rem; margin-bottom: .8rem;
}
.idx-tab {
  padding: .35rem .8rem; border-radius: 8px 8px 0 0;
  font-size: .8rem; cursor: pointer;
  color: var(--muted); background: transparent;
  border: 1px solid transparent; border-bottom: none;
  transition: all .2s;
}
.idx-tab:hover { color: var(--fg); }
.idx-tab.active {
  color: var(--blue); background: rgba(0,212,255,.06);
  border-color: var(--border);
}

/* ── SVG charts ── */
.chart-wrap { overflow-x: auto; }
.chart-panel { display: none; }
.chart-panel.active { display: block; }

/* ── Toggle buttons (MA, MACD/RSI) ── */
.toggle-bar {
  display: flex; gap: .4rem; margin: .5rem 0;
}
.toggle-btn {
  padding: .25rem .6rem; border-radius: 6px;
  font-size: .72rem; cursor: pointer;
  background: rgba(255,255,255,.04); border: 1px solid var(--border);
  color: var(--muted); transition: all .2s;
}
.toggle-btn.on {
  color: var(--blue); background: rgba(0,212,255,.08);
  border-color: rgba(0,212,255,.3);
}

/* ── Sector heatmap ── */
.sector-hm-wrap { max-width: 960px; margin: 0 auto; }
.shm-node { cursor: pointer; transition: opacity .15s; }
.shm-node:hover { opacity: .85; }
.shm-node text { pointer-events: none; }

/* ── Sector drawer ── */
.sector-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 998; display: none; }
.sector-overlay.open { display: block; }
.sector-drawer {
  position: fixed; right: 0; top: 0; width: 420px; height: 100vh;
  background: var(--card); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-left: 1px solid var(--border); z-index: 999;
  transform: translateX(100%); transition: transform .3s ease;
  overflow-y: auto; padding: 1.2rem;
}
.sector-drawer.open { transform: translateX(0); }
.sd-close {
  position: absolute; top: .8rem; right: .8rem;
  background: none; border: none; color: var(--muted);
  font-size: 1.5rem; cursor: pointer;
}
.sd-header { display: flex; align-items: center; gap: .8rem; margin-bottom: 1rem; padding-right: 2rem; }
.sd-header h3 { font-size: 1.1rem; }
.sd-pct { font-family: monospace; font-size: 1.2rem; font-weight: 700; }
.sd-section { margin: .8rem 0; }
.sd-section h4 { font-size: .85rem; color: var(--muted); margin-bottom: .4rem; }
.sd-stock { display: flex; justify-content: space-between; font-size: .85rem; padding: .25rem 0; }
.sd-stock .nm { color: var(--fg); }
.sd-stock .pc { font-family: monospace; }
.sd-stock .pc.up { color: var(--green); }
.sd-stock .pc.dn { color: var(--red); }
.sd-resonance-badge {
  display: inline-block; padding: .15rem .45rem; border-radius: 4px;
  font-size: .7rem; background: rgba(0,255,136,.1); color: var(--green);
  margin-left: .4rem;
}

/* ── Limit board ── */
.limit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.limit-card-title { font-size: .95rem; font-weight: 700; margin-bottom: .6rem; display: flex; align-items: center; gap: .5rem; }
.limit-card-title .cnt { font-family: monospace; font-size: 1.5rem; }
.limit-card-title .cnt.up { color: var(--green); }
.limit-card-title .cnt.dn { color: var(--red); }
.limit-stock {
  display: flex; justify-content: space-between; align-items: center;
  padding: .35rem .4rem; border-bottom: 1px solid rgba(255,255,255,.04);
  font-size: .82rem; border-radius: 6px;
  transition: background 150ms ease;
}
.limit-stock:hover { background: rgba(255,255,255,.02); }
.limit-stock .nm { flex: 1; }
.limit-stock .sec { color: var(--muted); font-size: .72rem; margin-left: .5rem; }
.limit-stock .boards-badge {
  display: inline-block; padding: .1rem .35rem; border-radius: 4px;
  font-size: .68rem; font-weight: 700; margin-left: .4rem;
  background: rgba(0,255,136,.12); color: var(--green);
}
.limit-stock .boards-badge.dn {
  background: rgba(255,71,87,.12); color: var(--red);
}
.limit-stock .amt { font-family: monospace; font-size: .75rem; color: var(--muted); }

/* ── Consecutive board ladder ── */
.ladder { display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap; margin: .6rem 0; }
.ladder-level {
  display: flex; flex-direction: column; align-items: center;
  min-width: 100px; cursor: pointer;
}
.ladder-bar {
  width: 100%; border-radius: 8px 8px 0 0;
  background: linear-gradient(180deg, var(--green), rgba(0,255,136,.3));
  display: flex; align-items: flex-end; justify-content: center;
  padding-bottom: .3rem; transition: opacity .2s;
  min-height: 24px;
}
.ladder-bar .num { font-family: monospace; font-size: 1.1rem; font-weight: 700; color: var(--bg); }
.ladder-label { font-size: .78rem; color: var(--muted); margin-top: .3rem; }
.ladder-detail {
  display: none; width: 100%; font-size: .8rem;
  margin-top: .5rem; padding: .6rem; border-radius: 8px;
  background: var(--surface); border: 1px solid var(--border);
}
.ladder-detail.open { display: block; }
.ladder-detail .ld-stock { padding: .2rem 0; display: flex; justify-content: space-between; }

/* ── Red close ── */
.rc-tabs { display: flex; gap: .3rem; margin-bottom: .5rem; }
.rc-tab {
  padding: .3rem .7rem; border-radius: 6px; font-size: .78rem; cursor: pointer;
  color: var(--muted); background: transparent; border: 1px solid transparent;
  transition: all .2s;
}
.rc-tab.active { color: var(--green); background: rgba(0,255,136,.06); border-color: rgba(0,255,136,.2); }
.rc-panel { display: none; }
.rc-panel.active { display: block; }
.rc-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
.rc-table th {
  text-align: left; color: var(--muted); font-weight: 600;
  border-bottom: 1px solid var(--border); padding: .5rem .4rem;
}
.rc-table td { padding: .4rem; border-bottom: 1px solid rgba(255,255,255,.04); }
.rc-table .mono { font-family: monospace; }
.csv-btn {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .3rem .7rem; border-radius: 6px;
  font-size: .72rem; cursor: pointer;
  color: var(--blue); background: rgba(0,212,255,.06);
  border: 1px solid rgba(0,212,255,.2); transition: all .2s;
}
.csv-btn:hover { background: rgba(0,212,255,.12); }
.csv-copied { color: var(--green) !important; border-color: rgba(0,255,136,.3) !important; }

/* ── Footer ── */
.recap-footer {
  display: flex; justify-content: space-between; align-items: center;
  font-size: .72rem; color: var(--muted); padding: .8rem 0;
  border-top: 1px solid var(--border); margin-top: .5rem;
}

/* ── Tooltip ── */
.shm-tooltip {
  position: fixed; pointer-events: none; z-index: 997;
  background: rgba(10, 14, 26, 0.92); border: 1px solid rgba(0,212,255,.15); border-radius: 8px;
  padding: .5rem .75rem; font-size: .8rem; display: none; white-space: nowrap;
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 8px 24px rgba(0,0,0,.25);
  line-height: 1.5;
}

/* ── Entry animations ── */
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
.animate-in { animation: fadeSlideUp .45s ease both; }
.delay-1 { animation-delay: .08s; }
.delay-2 { animation-delay: .16s; }
.delay-3 { animation-delay: .24s; }
.delay-4 { animation-delay: .32s; }
.delay-5 { animation-delay: .4s; }

/* ── Risk banner ── */
.risk-banner {
  background: rgba(255,71,87,.06);
  border: 1px solid rgba(255,71,87,.2);
  border-left: 4px solid var(--red);
  border-radius: 8px; padding: .6rem 1rem;
  font-size: .85rem; color: var(--red);
}

/* ── Responsive ── */
@media (min-width: 1200px) {
  .recap-shell { max-width: 1360px; }
  .sector-hm-wrap { max-width: 960px; }
  .limit-grid { grid-template-columns: 1fr 1fr; }
}
@media (min-width: 768px) and (max-width: 1199px) {
  .recap-shell { max-width: 100%; }
  .limit-grid { grid-template-columns: 1fr 1fr; }
  .sector-drawer { width: 380px; }
}
@media (max-width: 767px) {
  .recap-shell { padding: .8rem; gap: 1rem; }
  .recap-hero { padding: 1.2rem; border-radius: 14px; }
  .recap-hero h1 { font-size: 1.5rem; }
  .hero-eyebrow { font-size: .68rem; }
  .hero-summary { font-size: .9rem; }
  .hero-chips { gap: .4rem; }
  .hero-chip { padding: .3rem .6rem; font-size: .75rem; min-height: 32px; }
  .limit-grid { grid-template-columns: 1fr; }
  .kpi-ribbon { grid-template-columns: repeat(3, 1fr); gap: .5rem; }
  .kpi-cell .val { font-size: 1.1rem; }
  .kpi-cell .lab { font-size: .68rem; }
  .sec-title { font-size: 1rem; }
  .glass { padding: 1rem; border-radius: 12px; }
  .idx-tabs { gap: .2rem; }
  .idx-tab { padding: .4rem .6rem; font-size: .75rem; min-height: 36px; }
  .toggle-btn { padding: .3rem .5rem; font-size: .7rem; min-height: 32px; }
  .sector-hm-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .sector-drawer {
    right: 0; top: auto; bottom: 0; width: 100%; height: 70vh;
    border-radius: 14px 14px 0 0; border-left: none;
    border-top: 1px solid var(--border);
    transform: translateY(100%);
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  .sector-drawer.open { transform: translateY(0); }
  .ladder { flex-direction: column; align-items: stretch; }
  .ladder-level { min-width: auto; flex-direction: row; gap: .6rem; align-items: center; }
  .ladder-bar { width: auto; flex: 1; border-radius: 6px; min-height: 28px; }
  .rc-table { font-size: .78rem; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .mkt-ctx-panel { grid-template-columns: 1fr; gap: .5rem; }
  .mkt-row-label { text-align: left; }
}
@media (max-width: 400px) {
  .kpi-ribbon { grid-template-columns: repeat(2, 1fr); }
  .kpi-cell .val { font-size: 1rem; }
  .hero-chip { font-size: .7rem; padding: .25rem .5rem; }
}
@supports (padding: env(safe-area-inset-left)) {
  @media (max-width: 767px) {
    .recap-shell {
      padding-left: max(.8rem, env(safe-area-inset-left));
      padding-right: max(.8rem, env(safe-area-inset-right));
      padding-bottom: max(1rem, env(safe-area-inset-bottom));
    }
  }
}

/* ── AI Market Context Panel ── */
.mkt-ctx-panel {
  display: grid; grid-template-columns: auto 1fr; gap: .8rem 1rem;
  align-items: center;
}
.mkt-badge {
  display: inline-flex; align-items: center; gap: .35rem;
  padding: .3rem .7rem; border-radius: 8px;
  font-size: .82rem; font-weight: 700;
}
.mkt-badge.buy  { color: var(--green); background: rgba(0,255,136,.1); border: 1px solid rgba(0,255,136,.2); }
.mkt-badge.sell { color: var(--red);   background: rgba(255,71,87,.1); border: 1px solid rgba(255,71,87,.2); }
.mkt-badge.hold { color: var(--yellow); background: rgba(255,211,42,.08); border: 1px solid rgba(255,211,42,.18); }
.mkt-row-label { font-size: .78rem; color: var(--muted); text-align: right; white-space: nowrap; }
.mkt-row-val { font-size: .85rem; }
.mkt-chips { display: flex; gap: .4rem; flex-wrap: wrap; }
.mkt-chip {
  display: inline-block; padding: 1px 8px; border-radius: 8px;
  font-size: .72rem; font-weight: 600;
}
.mkt-chip.leader { color: var(--green); background: rgba(0,255,136,.08); border: 1px solid rgba(0,255,136,.15); }
.mkt-chip.avoid  { color: var(--red);   background: rgba(255,71,87,.08); border: 1px solid rgba(255,71,87,.15); }
.mkt-summary { font-size: .82rem; color: var(--fg); grid-column: 1 / -1; padding-top: .4rem; border-top: 1px solid var(--border); }
"""


# ── Color helpers ────────────────────────────────────────────────────

def _sector_color(pct: float) -> str:
    """Map sector pct_change to neon color hex."""
    if pct >= 3:
        return "#00ff88"
    elif pct >= 1.5:
        return "#1ac975"
    elif pct >= 0.3:
        return "#2a9d5e"
    elif pct >= -0.3:
        return "#3d5a6e"
    elif pct >= -1.5:
        return "#b8423a"
    elif pct >= -3:
        return "#e83535"
    else:
        return "#ff4757"


def _pct_class(v: float) -> str:
    if v > 0:
        return "up"
    elif v < 0:
        return "down"
    return "neu"


def _pct_str(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


# ── Section renderers ────────────────────────────────────────────────

def _render_recap_hero(data: dict) -> str:
    date = _esc(data.get("date", ""))
    weather = data.get("market_weather", "震荡")
    advice = data.get("position_advice", "中性")
    summary = _esc(data.get("one_line_summary", ""))
    risk = data.get("risk_note", "")

    w_cls = "up" if weather == "上涨" else ("down" if weather == "下跌" else "neu")
    a_cls = "up" if advice == "进攻" else ("down" if advice == "防守" else "neu")

    risk_html = ""
    if risk:
        risk_html = f'<div class="risk-banner" style="margin-top:.8rem">{_esc(risk)}</div>'

    return f"""
    <section class="recap-hero animate-in">
      <div class="hero-eyebrow">TradingAgents · 每日复盘</div>
      <h1>{date} 市场复盘</h1>
      <p class="hero-summary">{summary}</p>
      <div class="hero-chips">
        <span class="hero-chip {w_cls}">市场: {_esc(weather)}</span>
        <span class="hero-chip {a_cls}">建议: {_esc(advice)}</span>
      </div>
      {risk_html}
    </section>"""


def _render_index_kpi_ribbon(data: dict) -> str:
    idx_summary = data.get("index_summary", {})
    indices = idx_summary.get("indices", [])
    turnover = idx_summary.get("turnover_total_yi", 0)
    turnover_delta = idx_summary.get("turnover_delta_yi", 0)
    nb = idx_summary.get("northbound_flow_yi", 0)
    adv = idx_summary.get("advancers", 0)
    dec = idx_summary.get("decliners", 0)
    flat = idx_summary.get("flat", 0)

    # Index cells — show close point + pct change
    cells = ""
    for ix in indices[:5]:
        pct = ix.get("pct_change", 0)
        close = ix.get("close", 0)
        cls = _pct_class(pct)
        cells += (
            f'<div class="kpi-cell glass">'
            f'<div class="val {cls} mono">{close:.2f}</div>'
            f'<div class="lab">{_esc(ix.get("name", ""))} {_pct_str(pct)}</div>'
            f'</div>'
        )

    # Turnover + delta
    delta_label = ""
    if turnover_delta:
        delta_sign = "+" if turnover_delta > 0 else ""
        vol_word = "放量" if turnover_delta > 0 else "缩量"
        delta_label = f" ({vol_word}{delta_sign}{turnover_delta:.0f})"

    # Extra KPIs
    nb_cls = _pct_class(nb)
    nb_sign = "+" if nb > 0 else ""
    cells += (
        f'<div class="kpi-cell glass">'
        f'<div class="val mono">{turnover:.0f}</div>'
        f'<div class="lab">成交额(亿){delta_label}</div>'
        f'</div>'
        f'<div class="kpi-cell glass">'
        f'<div class="val {nb_cls} mono">{nb_sign}{nb:.1f}</div>'
        f'<div class="lab">北向(亿)</div>'
        f'</div>'
        f'<div class="kpi-cell glass">'
        f'<div class="val up mono">{adv}</div>'
        f'<div class="lab">上涨</div>'
        f'</div>'
        f'<div class="kpi-cell glass">'
        f'<div class="val down mono">{dec}</div>'
        f'<div class="lab">下跌</div>'
        f'</div>'
        f'<div class="kpi-cell glass">'
        f'<div class="val neu mono">{flat}</div>'
        f'<div class="lab">平盘</div>'
        f'</div>'
    )

    return f"""
    <section class="animate-in delay-1">
      <div class="sec-head">
        <div class="sec-title">市场概览</div>
      </div>
      <div class="kpi-ribbon">{cells}</div>
    </section>"""


def _render_index_chart_panel(data: dict) -> str:
    """Pre-render SVG K-line + MA + MACD/RSI charts for each index, with tab switching."""
    idx_summary = data.get("index_summary", {})
    indices = idx_summary.get("indices", [])
    if not indices:
        return '<div class="glass" style="color:var(--muted)">暂无指数数据</div>'

    # Tab bar
    tabs = ""
    panels = ""
    for i, ix in enumerate(indices[:5]):
        name = _esc(ix.get("name", ix.get("code", "")))
        active = " active" if i == 0 else ""
        tabs += f'<div class="idx-tab{active}" data-idx="{i}">{name}</div>'

        points = ix.get("points", [])
        svg = _render_index_svg(points, ix.get("code", ""))
        vis = " active" if i == 0 else ""
        panels += f'<div class="chart-panel{vis}" data-panel="{i}">{svg}</div>'

    # Toggle bar for MA / sub-chart
    toggles = """
    <div class="toggle-bar">
      <span class="toggle-btn on" data-toggle="ma">MA</span>
      <span class="toggle-btn" data-toggle="macd">MACD</span>
      <span class="toggle-btn" data-toggle="rsi">RSI</span>
    </div>"""

    return f"""
    <section class="glass animate-in delay-2">
      <div class="sec-head">
        <div class="sec-title">指数走势</div>
        <div class="sec-sub">K线 + 技术指标</div>
      </div>
      <div class="idx-tabs">{tabs}</div>
      {toggles}
      <div class="chart-wrap">{panels}</div>
    </section>"""


def _render_index_svg(points: list, code: str = "") -> str:
    """Render SVG K-line + MA + MACD sub-chart for one index."""
    if not points:
        return '<div style="color:var(--muted);padding:.5rem">暂无数据</div>'

    n = len(points)
    # Dimensions
    w, main_h, sub_h, pad = 900, 220, 80, 40
    total_h = main_h + sub_h + 10
    bar_w = max((w - 2 * pad) / max(n, 1) * 0.7, 2)
    gap = (w - 2 * pad) / max(n, 1)

    # Price range
    highs = [p.get("high", p.get("close", 0)) for p in points]
    lows = [p.get("low", p.get("close", 0)) for p in points]
    p_max = max(highs) if highs else 1
    p_min = min(lows) if lows else 0
    p_range = p_max - p_min or 1

    def y_main(v):
        return pad + (1 - (v - p_min) / p_range) * (main_h - 2 * pad)

    def x_pos(i):
        return pad + i * gap + gap / 2

    # K-line candles
    candles = []
    for i, p in enumerate(points):
        cx = x_pos(i)
        o, h, l, c = p.get("open", 0), p.get("high", 0), p.get("low", 0), p.get("close", 0)
        color = "#00ff88" if c >= o else "#ff4757"
        y_o, y_c = y_main(o), y_main(c)
        y_h, y_l = y_main(h), y_main(l)
        body_top = min(y_o, y_c)
        body_h = max(abs(y_o - y_c), 1)
        # Wick
        candles.append(
            f'<line x1="{cx}" y1="{y_h}" x2="{cx}" y2="{y_l}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
        # Body
        candles.append(
            f'<rect x="{cx - bar_w/2}" y="{body_top}" width="{bar_w}" height="{body_h}" '
            f'fill="{color}" rx="1"/>'
        )

    # MA polylines
    def _ma_polyline(key, color, cls_name):
        pts = [(x_pos(i), y_main(p[key])) for i, p in enumerate(points) if p.get(key) is not None]
        if len(pts) < 2:
            return ""
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polyline class="ma-line {cls_name}" points="{path}" fill="none" stroke="{color}" stroke-width="1.2" opacity=".7"/>'

    ma5 = _ma_polyline("ma5", "#ffd32a", "ma5")
    ma14 = _ma_polyline("ma14", "#00d4ff", "ma14")
    ma30 = _ma_polyline("ma30", "#ff6b9d", "ma30")

    # MACD sub-chart
    macd_vals = [p.get("macd_hist", 0) for p in points]
    dif_vals = [p.get("macd_dif", 0) for p in points]
    dea_vals = [p.get("macd_dea", 0) for p in points]
    all_macd = macd_vals + dif_vals + dea_vals
    m_max = max(abs(v) for v in all_macd) if all_macd else 1
    m_max = m_max or 1
    sub_top = main_h + 10

    def y_sub(v):
        return sub_top + sub_h / 2 - (v / m_max) * (sub_h / 2 - 4)

    macd_bars = []
    for i, h_val in enumerate(macd_vals):
        cx = x_pos(i)
        color = "#00ff88" if h_val >= 0 else "#ff4757"
        y0 = y_sub(0)
        yv = y_sub(h_val)
        bar_top = min(y0, yv)
        bar_h_px = max(abs(y0 - yv), 1)
        macd_bars.append(
            f'<rect class="macd-el" x="{cx - bar_w/2}" y="{bar_top}" '
            f'width="{bar_w}" height="{bar_h_px}" fill="{color}" opacity=".6" rx="1"/>'
        )

    # DIF/DEA lines
    dif_pts = " ".join(f"{x_pos(i):.1f},{y_sub(v):.1f}" for i, v in enumerate(dif_vals))
    dea_pts = " ".join(f"{x_pos(i):.1f},{y_sub(v):.1f}" for i, v in enumerate(dea_vals))
    dif_line = f'<polyline class="macd-el" points="{dif_pts}" fill="none" stroke="#ffd32a" stroke-width="1" opacity=".8"/>' if dif_pts.strip() else ""
    dea_line = f'<polyline class="macd-el" points="{dea_pts}" fill="none" stroke="#ff6b9d" stroke-width="1" opacity=".8"/>' if dea_pts.strip() else ""

    # RSI sub-chart (hidden by default, same position as MACD)
    rsi_vals = [p.get("rsi", 50) for p in points]
    rsi_pts = " ".join(f"{x_pos(i):.1f},{sub_top + sub_h - (v / 100) * sub_h:.1f}" for i, v in enumerate(rsi_vals))
    # RSI reference lines (30, 70)
    y70 = sub_top + sub_h - 70 / 100 * sub_h
    y30 = sub_top + sub_h - 30 / 100 * sub_h
    rsi_els = (
        f'<line class="rsi-el" x1="{pad}" y1="{y70}" x2="{w-pad}" y2="{y70}" stroke="var(--muted)" stroke-width=".5" stroke-dasharray="4"/>'
        f'<line class="rsi-el" x1="{pad}" y1="{y30}" x2="{w-pad}" y2="{y30}" stroke="var(--muted)" stroke-width=".5" stroke-dasharray="4"/>'
        f'<polyline class="rsi-el" points="{rsi_pts}" fill="none" stroke="#00d4ff" stroke-width="1.2"/>'
    )

    # Sub-chart divider line
    div_line = f'<line x1="{pad}" y1="{sub_top}" x2="{w-pad}" y2="{sub_top}" stroke="var(--border)" stroke-width="1"/>'

    # Axis labels
    first_date = _esc(points[0].get("date", "")[-5:]) if points else ""
    last_date = _esc(points[-1].get("date", "")[-5:]) if points else ""
    axis = (
        f'<text x="{pad}" y="{main_h + 6}" fill="var(--muted)" font-size="10">{first_date}</text>'
        f'<text x="{w-pad}" y="{main_h + 6}" fill="var(--muted)" font-size="10" text-anchor="end">{last_date}</text>'
        f'<text x="{pad-2}" y="{y_main(p_max)}" fill="var(--muted)" font-size="9" text-anchor="end">{p_max:.0f}</text>'
        f'<text x="{pad-2}" y="{y_main(p_min)}" fill="var(--muted)" font-size="9" text-anchor="end">{p_min:.0f}</text>'
    )

    # RSI hidden by default
    rsi_style = ' style="display:none"'

    return (
        f'<svg viewBox="0 0 {w} {total_h}" width="100%" height="auto"'
        f' style="max-height:{total_h}px" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(candles)}'
        f'{ma5}{ma14}{ma30}'
        f'{axis}{div_line}'
        f'{"".join(macd_bars)}{dif_line}{dea_line}'
        f'<g class="rsi-group"{rsi_style}>{rsi_els}</g>'
        f'</svg>'
    )


def _render_sector_heatmap(data: dict) -> str:
    """Render sector heatmap as SVG treemap, colored by pct_change."""
    hm = data.get("sector_heatmap", {})
    nodes = hm.get("nodes", [])
    if not nodes:
        return '<div class="glass" style="color:var(--muted)">暂无板块数据</div>'

    width, height = 960, 380

    # Size by market cap; fall back to turnover if market cap is all zero
    has_mcap = any(n.get("market_cap_yi", 0) > 0 for n in nodes)
    size_key = "market_cap_yi" if has_mcap else "turnover_yi"
    size_label = "面积=市值" if has_mcap else "面积=成交额"

    indexed = []
    for i, n in enumerate(nodes):
        v = max(n.get(size_key, 1), 0.01)
        indexed.append((i, v))
    indexed.sort(key=lambda x: x[1], reverse=True)

    rects = _squarify(indexed, 0, 0, width, height)

    svg_parts = []
    for idx, rx, ry, rw, rh in rects:
        node = nodes[idx]
        pct = node.get("pct_change", 0)
        color = _sector_color(pct)
        name = _esc(node.get("sector", ""))
        sign = "+" if pct > 0 else ""

        font_size = min(rw / 5, rh / 3, 14)
        font_size = max(font_size, 8)

        text_el = ""
        if rw > 50 and rh > 30:
            text_el = (
                f'<text x="{rx + rw/2}" y="{ry + rh/2 - 4}" '
                f'text-anchor="middle" fill="white" font-size="{font_size}px" font-weight="600">'
                f'{name}</text>'
                f'<text x="{rx + rw/2}" y="{ry + rh/2 + font_size}" '
                f'text-anchor="middle" fill="rgba(255,255,255,.7)" '
                f'font-size="{max(font_size-2, 7)}px" '
                f'font-family="monospace">'
                f'{sign}{pct:.2f}%</text>'
            )

        svg_parts.append(
            f'<g class="shm-node" data-idx="{idx}">'
            f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" '
            f'fill="{color}" stroke="var(--bg)" stroke-width="2" rx="3"/>'
            f'{text_el}</g>'
        )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" style="max-height:{height}px" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(svg_parts)}</svg>'
    )

    return f"""
    <section class="glass animate-in delay-3">
      <div class="sec-head">
        <div class="sec-title">板块热力图</div>
        <div class="sec-sub">{size_label} 颜色=涨跌幅 | 点击查看详情</div>
      </div>
      <div class="sector-hm-wrap">{svg}</div>
    </section>"""


def _render_sector_drawer() -> str:
    return """
    <div class="sector-overlay" id="sector-overlay"></div>
    <aside class="sector-drawer" id="sector-drawer">
      <button class="sd-close" id="sd-close">&times;</button>
      <div class="sd-header">
        <h3 id="sd-name">—</h3>
        <span class="sd-pct mono" id="sd-pct">—</span>
      </div>
      <div class="sd-section">
        <h4>成交额</h4>
        <div id="sd-turnover" class="mono">—</div>
      </div>
      <div class="sd-section">
        <h4>领涨股</h4>
        <div id="sd-leaders">—</div>
      </div>
      <div class="sd-section">
        <h4>领跌股</h4>
        <div id="sd-laggards">—</div>
      </div>
      <div class="sd-section">
        <h4>共振股 <span class="sd-resonance-badge">≥7%</span></h4>
        <div id="sd-resonance">—</div>
      </div>
    </aside>
    <div class="shm-tooltip" id="shm-tooltip"></div>"""


def _render_limit_board(data: dict) -> str:
    lb = data.get("limit_board", {})
    up_stocks = lb.get("limit_up_stocks", [])
    down_stocks = lb.get("limit_down_stocks", [])
    up_count = lb.get("limit_up_count", len(up_stocks))
    dn_count = lb.get("limit_down_count", len(down_stocks))

    def _stock_row(s, is_up=True):
        name = _esc(s.get("name", ""))
        sector = _esc(s.get("sector", ""))
        boards = s.get("boards", 1)
        amt = s.get("amount_yi", 0)
        pct = s.get("pct_change", 0)
        board_badge = ""
        if boards > 1:
            cls = "" if is_up else " dn"
            board_badge = f'<span class="boards-badge{cls}">{boards}连板</span>'
        sec_el = f'<span class="sec">{sector}</span>' if sector else ""
        return (
            f'<div class="limit-stock">'
            f'<span class="nm">{name}{sec_el}{board_badge}</span>'
            f'<span class="amt mono">{amt:.1f}亿</span>'
            f'</div>'
        )

    up_rows = "".join(_stock_row(s, True) for s in up_stocks[:20])
    dn_rows = "".join(_stock_row(s, False) for s in down_stocks[:20])

    if not up_rows:
        up_rows = '<div style="color:var(--muted);font-size:.85rem">暂无涨停</div>'
    if not dn_rows:
        dn_rows = '<div style="color:var(--muted);font-size:.85rem">暂无跌停</div>'

    return f"""
    <section class="animate-in delay-4">
      <div class="sec-head">
        <div class="sec-title">涨跌停板</div>
      </div>
      <div class="limit-grid">
        <div class="glass glass-glow-green">
          <div class="limit-card-title">
            <span class="cnt up mono">{up_count}</span> 涨停
          </div>
          {up_rows}
        </div>
        <div class="glass glass-glow-red">
          <div class="limit-card-title">
            <span class="cnt dn mono">{dn_count}</span> 跌停
          </div>
          {dn_rows}
        </div>
      </div>
    </section>"""


def _render_consecutive_board_flow(data: dict) -> str:
    levels = data.get("consecutive_boards", [])
    if not levels:
        return ""

    max_count = max((lv.get("count", 0) for lv in levels), default=1) or 1
    bars = ""
    details = ""
    for lv in levels:
        lvl = lv.get("level", 1)
        label = _esc(lv.get("label", f"{lvl}连板"))
        count = lv.get("count", 0)
        promo = lv.get("promotion_rate", 0)
        prev_count = lv.get("prev_count", 0)
        stocks = lv.get("stocks", [])
        bar_h = max(int(count / max_count * 120), 24)

        # Promotion rate badge for level >= 2
        promo_badge = ""
        if lvl >= 2 and prev_count > 0:
            promo_badge = (
                f'<div class="promo-rate mono" style="font-size:.7rem;color:var(--yellow);margin-top:.15rem">'
                f'{count}/{prev_count} = {promo:.0f}%</div>'
            )

        stock_divs = ""
        for s in stocks[:8]:
            stock_divs += (
                f'<div class="ld-stock">'
                f'<span>{_esc(s.get("name", ""))}</span>'
                f'<span class="mono">{s.get("amount_yi", 0):.1f}亿</span>'
                f'</div>'
            )

        bars += (
            f'<div class="ladder-level" data-level="{lvl}">'
            f'<div class="ladder-bar" style="height:{bar_h}px">'
            f'<span class="num">{count}</span></div>'
            f'<div class="ladder-label">{label}</div>'
            f'{promo_badge}'
            f'</div>'
        )
        details += (
            f'<div class="ladder-detail" data-level-detail="{lvl}">'
            f'{stock_divs or "<div style=color:var(--muted)>暂无</div>"}'
            f'</div>'
        )

    return f"""
    <section class="glass animate-in delay-4">
      <div class="sec-head">
        <div class="sec-title">连板晋级</div>
        <div class="sec-sub">点击柱体展开明细 | 晋级率=今日N板/昨日(N-1)板</div>
      </div>
      <div class="ladder">{bars}</div>
      {details}
    </section>"""


def _render_red_close_panel(data: dict) -> str:
    rc = data.get("red_close", {})
    red_6 = rc.get("red_close_6", [])
    red_8 = rc.get("red_close_8", [])
    window = rc.get("window_natural_days", 14)
    trade_days = rc.get("window_trade_days", 0)

    if not red_6 and not red_8:
        return ""

    def _table(rows, tid):
        if not rows:
            return '<div style="color:var(--muted);font-size:.85rem">暂无符合条件的个股</div>'
        trs = ""
        for r in rows:
            trs += (
                f'<tr>'
                f'<td>{_esc(r.get("ticker", ""))}</td>'
                f'<td>{_esc(r.get("name", ""))}</td>'
                f'<td class="mono">{r.get("red_days", 0)}</td>'
                f'<td class="mono">{r.get("total_days", 0)}</td>'
                f'</tr>'
            )
        return (
            f'<table class="rc-table" id="{tid}">'
            f'<thead><tr><th>代码</th><th>名称</th><th>红收天数</th><th>交易日数</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>'
        )

    tab6 = f'≥6天 ({len(red_6)})'
    tab8 = f'≥8天 ({len(red_8)})'

    return f"""
    <section class="glass animate-in delay-5">
      <div class="sec-head">
        <div class="sec-title">强势延续观察</div>
        <div class="sec-sub">{window}自然日窗口 · {trade_days}个交易日</div>
      </div>
      <div class="rc-tabs">
        <div class="rc-tab active" data-rc="6">{tab6}</div>
        <div class="rc-tab" data-rc="8">{tab8}</div>
        <button class="csv-btn" id="csv-copy-btn">复制CSV</button>
      </div>
      <div class="rc-panel active" data-rc-panel="6">{_table(red_6, "rc-table-6")}</div>
      <div class="rc-panel" data-rc-panel="8">{_table(red_8, "rc-table-8")}</div>
    </section>"""


# ── JavaScript ───────────────────────────────────────────────────────

def _render_recap_js(data: dict) -> str:
    """All interactive JS — tabs, toggles, drawer, ladder expand, CSV copy."""
    hm_data = data.get("sector_heatmap", {})
    data_json = _json.dumps(hm_data, ensure_ascii=False)

    return f"""
    <script>
    (function() {{
      // ── Index tab switching ──
      document.querySelectorAll('.idx-tab').forEach(function(tab) {{
        tab.addEventListener('click', function() {{
          var idx = tab.getAttribute('data-idx');
          document.querySelectorAll('.idx-tab').forEach(function(t) {{ t.classList.remove('active'); }});
          document.querySelectorAll('.chart-panel').forEach(function(p) {{ p.classList.remove('active'); }});
          tab.classList.add('active');
          var panel = document.querySelector('.chart-panel[data-panel="' + idx + '"]');
          if (panel) panel.classList.add('active');
        }});
      }});

      // ── MA / MACD / RSI toggle ──
      document.querySelectorAll('.toggle-btn').forEach(function(btn) {{
        btn.addEventListener('click', function() {{
          var t = btn.getAttribute('data-toggle');
          if (t === 'ma') {{
            btn.classList.toggle('on');
            var show = btn.classList.contains('on');
            document.querySelectorAll('.ma-line').forEach(function(el) {{
              el.style.display = show ? '' : 'none';
            }});
          }} else if (t === 'macd') {{
            btn.classList.toggle('on');
            var show = btn.classList.contains('on');
            document.querySelectorAll('.macd-el').forEach(function(el) {{
              el.style.display = show ? '' : 'none';
            }});
            // hide RSI when showing MACD
            if (show) {{
              var rsiBtn = document.querySelector('.toggle-btn[data-toggle="rsi"]');
              if (rsiBtn) rsiBtn.classList.remove('on');
              document.querySelectorAll('.rsi-group').forEach(function(el) {{ el.style.display = 'none'; }});
            }}
          }} else if (t === 'rsi') {{
            btn.classList.toggle('on');
            var show = btn.classList.contains('on');
            document.querySelectorAll('.rsi-group').forEach(function(el) {{
              el.style.display = show ? '' : 'none';
            }});
            // hide MACD when showing RSI
            if (show) {{
              var macdBtn = document.querySelector('.toggle-btn[data-toggle="macd"]');
              if (macdBtn) macdBtn.classList.remove('on');
              document.querySelectorAll('.macd-el').forEach(function(el) {{ el.style.display = 'none'; }});
            }}
          }}
        }});
      }});

      // ── Sector heatmap → drawer ──
      var SECTOR_DATA = {data_json};
      var sNodes = SECTOR_DATA.nodes || [];
      var sDrawer = document.getElementById('sector-drawer');
      var sOverlay = document.getElementById('sector-overlay');
      var sTooltip = document.getElementById('shm-tooltip');

      function openSectorDrawer(node) {{
        document.getElementById('sd-name').textContent = node.sector || '';
        var pct = node.pct_change || 0;
        var pctEl = document.getElementById('sd-pct');
        pctEl.textContent = (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
        pctEl.style.color = pct > 0 ? 'var(--green)' : pct < 0 ? 'var(--red)' : 'var(--muted)';

        document.getElementById('sd-turnover').textContent = (node.turnover_yi || 0).toFixed(1) + '亿';

        function renderStocks(el, stocks) {{
          if (!stocks || !stocks.length) {{ el.innerHTML = '<span style="color:var(--muted)">暂无</span>'; return; }}
          var html = '';
          stocks.forEach(function(s) {{
            var pc = s.pct_change || 0;
            var cls = pc > 0 ? 'up' : pc < 0 ? 'dn' : '';
            html += '<div class="sd-stock"><span class="nm">' + (s.name || s.ticker) +
              '</span><span class="pc ' + cls + ' mono">' + (pc > 0 ? '+' : '') + pc.toFixed(2) + '%</span></div>';
          }});
          el.innerHTML = html;
        }}
        renderStocks(document.getElementById('sd-leaders'), node.leaders);
        renderStocks(document.getElementById('sd-laggards'), node.laggards);
        renderStocks(document.getElementById('sd-resonance'), node.resonance_stocks);

        sDrawer.classList.add('open');
        sOverlay.classList.add('open');
      }}

      function closeSectorDrawer() {{
        sDrawer.classList.remove('open');
        sOverlay.classList.remove('open');
      }}

      if (sOverlay) sOverlay.addEventListener('click', closeSectorDrawer);
      var sdClose = document.getElementById('sd-close');
      if (sdClose) sdClose.addEventListener('click', closeSectorDrawer);

      document.querySelectorAll('.shm-node').forEach(function(el) {{
        el.addEventListener('click', function() {{
          var idx = parseInt(el.getAttribute('data-idx'), 10);
          if (idx >= 0 && idx < sNodes.length) openSectorDrawer(sNodes[idx]);
        }});
      }});

      // Desktop tooltip
      var sTipTimer = null;
      document.querySelectorAll('.shm-node').forEach(function(el) {{
        el.addEventListener('mouseenter', function(e) {{
          if (window.innerWidth < 768) return;
          var idx = parseInt(el.getAttribute('data-idx'), 10);
          if (idx < 0 || idx >= sNodes.length) return;
          var n = sNodes[idx];
          sTipTimer = setTimeout(function() {{
            var pct = n.pct_change || 0;
            sTooltip.innerHTML = '<b>' + (n.sector || '') + '</b> ' +
              (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
            sTooltip.style.display = 'block';
          }}, 100);
        }});
        el.addEventListener('mousemove', function(e) {{
          if (sTooltip) {{ sTooltip.style.left = (e.clientX + 12) + 'px'; sTooltip.style.top = (e.clientY + 12) + 'px'; }}
        }});
        el.addEventListener('mouseleave', function() {{
          clearTimeout(sTipTimer);
          if (sTooltip) sTooltip.style.display = 'none';
        }});
      }});

      // ── Ladder expand ──
      document.querySelectorAll('.ladder-level').forEach(function(el) {{
        el.addEventListener('click', function() {{
          var lvl = el.getAttribute('data-level');
          var detail = document.querySelector('.ladder-detail[data-level-detail="' + lvl + '"]');
          if (detail) detail.classList.toggle('open');
        }});
      }});

      // ── Red close tab switching ──
      document.querySelectorAll('.rc-tab').forEach(function(tab) {{
        tab.addEventListener('click', function() {{
          var rc = tab.getAttribute('data-rc');
          if (!rc) return;
          document.querySelectorAll('.rc-tab').forEach(function(t) {{ t.classList.remove('active'); }});
          document.querySelectorAll('.rc-panel').forEach(function(p) {{ p.classList.remove('active'); }});
          tab.classList.add('active');
          var panel = document.querySelector('.rc-panel[data-rc-panel="' + rc + '"]');
          if (panel) panel.classList.add('active');
        }});
      }});

      // ── CSV copy ──
      var csvBtn = document.getElementById('csv-copy-btn');
      if (csvBtn) {{
        csvBtn.addEventListener('click', function() {{
          var activePanel = document.querySelector('.rc-panel.active');
          if (!activePanel) return;
          var table = activePanel.querySelector('.rc-table');
          if (!table) return;
          var csv = '';
          table.querySelectorAll('tr').forEach(function(tr) {{
            var cols = [];
            tr.querySelectorAll('th, td').forEach(function(td) {{ cols.push(td.textContent.trim()); }});
            csv += cols.join(',') + '\\n';
          }});
          if (navigator.clipboard) {{
            navigator.clipboard.writeText(csv).then(function() {{
              csvBtn.textContent = '已复制!';
              csvBtn.classList.add('csv-copied');
              setTimeout(function() {{
                csvBtn.textContent = '复制CSV';
                csvBtn.classList.remove('csv-copied');
              }}, 1500);
            }});
          }}
        }});
      }}

      // ── ESC close ──
      document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape') closeSectorDrawer();
      }});
    }})();
    </script>"""


# ── AI Market Context Panel ──────────────────────────────────────────

def _render_market_context_panel(data: dict) -> str:
    """Render AI market layer judgment panel (regime, breadth, sectors)."""
    ctx = data.get("market_context") or {}
    if not ctx:
        return ""

    regime = ctx.get("regime", "")
    breadth = ctx.get("breadth_state", "")
    if not regime and not breadth:
        return ""

    rows = ""
    # Regime row
    if regime:
        r_label = get_regime_label(regime)
        r_class = get_regime_class(regime)
        cap = ctx.get("position_cap_multiplier", 1.0)
        style_bias = ctx.get("style_bias", "")
        cap_str = f" | 仓位系数 {cap:.1f}x" if cap != 1.0 else ""
        style_str = f" | 风格偏好 {_esc(style_bias)}" if style_bias else ""
        rows += (
            f'<div class="mkt-row-label">市场研判</div>'
            f'<div class="mkt-row-val">'
            f'<span class="mkt-badge {r_class}">{_esc(r_label)}</span>'
            f'<span style="margin-left:.6rem;font-size:.78rem;color:var(--muted)">{cap_str}{style_str}</span>'
            f'</div>'
        )

    # Breadth row
    if breadth:
        b_label = get_breadth_label(breadth)
        b_class = get_breadth_class(breadth)
        rows += (
            f'<div class="mkt-row-label">市场宽度</div>'
            f'<div class="mkt-row-val">'
            f'<span class="mkt-badge {b_class}">{_esc(b_label)}</span>'
            f'</div>'
        )

    # Sector leaders / avoid
    leaders = ctx.get("sector_leaders", [])
    avoid = ctx.get("avoid_sectors", [])
    if leaders or avoid:
        chips = ""
        for s in leaders[:5]:
            name = s.get("name", s) if isinstance(s, dict) else s
            chips += f'<span class="mkt-chip leader">{_esc(str(name))}</span>'
        for s in avoid[:4]:
            name = s.get("name", s) if isinstance(s, dict) else s
            chips += f'<span class="mkt-chip avoid">{_esc(str(name))}</span>'
        rows += (
            f'<div class="mkt-row-label">板块轮动</div>'
            f'<div class="mkt-row-val"><div class="mkt-chips">{chips}</div></div>'
        )

    # Client summary
    summary = ctx.get("client_summary", "")
    if summary:
        rows += f'<div class="mkt-summary">{_esc(summary)}</div>'

    return f"""
    <section class="glass animate-in delay-1" style="border-left:3px solid var(--blue)">
      <div class="sec-head">
        <div class="sec-title">AI 综合研判</div>
        <div class="sec-sub">市场环境评估</div>
      </div>
      <div class="mkt-ctx-panel">{rows}</div>
    </section>"""


# ── Main entry ───────────────────────────────────────────────────────

def render_daily_recap(data) -> str:
    """Render complete Daily Recap page from DailyRecapData.to_dict().

    Args:
        data: DailyRecapData instance or dict from .to_dict().

    Returns:
        Complete HTML string.
    """
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    hero = _render_recap_hero(data)
    mkt_ctx = _render_market_context_panel(data)
    kpi = _render_index_kpi_ribbon(data)
    chart = _render_index_chart_panel(data)
    sector = _render_sector_heatmap(data)
    sector_drawer = _render_sector_drawer()
    limit = _render_limit_board(data)
    consec = _render_consecutive_board_flow(data)
    red_close = _render_red_close_panel(data)
    js = _render_recap_js(data)

    date_str = _esc(data.get("date", ""))
    elapsed = data.get("collection_seconds", 0)

    body = f"""
    <div class="recap-shell">
      {hero}
      {mkt_ctx}
      {kpi}
      {chart}
      {sector}
      {limit}
      {consec}
      {red_close}
      <footer class="recap-footer">
        <span>TradingAgents · 每日复盘 · {date_str}</span>
        <span>采集耗时 {elapsed:.1f}s · v0.2.0</span>
      </footer>
    </div>
    {sector_drawer}
    {js}"""

    return _html_wrap(
        f"每日复盘 — {date_str}",
        body, "每日复盘",
        extra_css=_RECAP_CSS,
    )


def generate_daily_recap_report(
    data,
    output_dir: str = "data/reports",
) -> Optional[str]:
    """Generate standalone daily recap HTML report.

    Args:
        data: DailyRecapData instance or dict from .to_dict().
        output_dir: Directory to write HTML.

    Returns:
        Path to generated file, or None.
    """
    if not data:
        return None
    # Accept both DailyRecapData and dict
    if hasattr(data, "to_dict"):
        data = data.to_dict()

    html = render_daily_recap(data)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    date_slug = (data.get("date", "") or "").replace("-", "")
    if not date_slug:
        from datetime import date as _d
        date_slug = _d.today().isoformat().replace("-", "")

    path = out / f"recap-{date_slug}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)
