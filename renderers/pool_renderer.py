"""
Divergence pool report renderer.

Multi-stock divergence pool with heatmap, conviction chart, risk chart,
priority table, and per-stock drill-down cards.

Extracted from report_renderer.py to reduce file size.
All user-facing text is in Chinese (A-share product).
"""

import copy
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .views import DivergencePoolView, StockDivergenceRow, _strip_internal_tokens
from .decision_labels import (
    get_signal_emoji, get_severity_label, get_risk_label,
    get_regime_label, get_regime_class, AI_DISCLAIMER_BANNER,
)
from .shared_css import _BRAND_LOGO_SM, _BRAND_LOGO_LG
from .shared_utils import _esc, _html_wrap, _empty_state
from .market_renderer import _MARKET_CSS
from .market_treemap import (
    _render_heatmap_legend,
    _render_svg_heatmap,
    _render_detail_drawer,
    _render_heatmap_js,
)


_POOL_CSS = """
/* Pool-specific overrides (base :root tokens from shared_css._BASE_CSS) */
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
/* Heat bar behind conviction value */
.heat-cell { position: relative; }
.heat-bar-bg { position: absolute; inset: 0; border-radius: 3px; }
.heat-bar-fill { height: 100%; border-radius: 3px; opacity: 0.12; }
.heat-val { position: relative; z-index: 1; font-family: var(--mono); font-variant-numeric: tabular-nums; }
/* Mini bull/bear bar in divergence column */
.mini-bb { display: flex; height: 4px; border-radius: 2px; overflow: hidden; margin-bottom: .15rem; }
.mini-bb-bull { background: var(--green); }
.mini-bb-bear { background: var(--red); }
.mini-bb-label { font-size: .72rem; color: var(--muted); font-family: var(--mono); }
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

/* print rules consolidated in shared_css.py */
"""


def _pool_action_color(action_class: str) -> str:
    return {
        "buy": "#34d399",
        "hold": "#fbbf24",
        "sell": "#f87171",
        "veto": "#f87171",
    }.get(action_class, "#60a5fa")


def _mini_bb(bull: float, bear: float) -> str:
    """Mini bull/bear bar for table cell."""
    total = bull + bear
    bp = int(bull / total * 100) if total > 0 else 50
    return (
        f'<div class="mini-bb"><div class="mini-bb-bull" style="width:{bp}%"></div>'
        f'<div class="mini-bb-bear" style="width:{100-bp}%"></div></div>'
        f'<span class="mini-bb-label">{bull:.1f} / {bear:.1f}</span>'
    )


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
          <td class="heat-cell"><div class="heat-bar-bg"><div class="heat-bar-fill" style="width:{row.conviction_pct}%;background:{_pool_action_color(row.action_class)}"></div></div><span class="heat-val">{row.conviction_pct}%</span></td>
          <td>{_mini_bb(row.bull_score, row.bear_score)}</td>
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
        <div class="cover-disclaimer">{AI_DISCLAIMER_BANNER}</div>
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
      <div class="banner">{AI_DISCLAIMER_BANNER}</div>
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

    if market_snapshot is None:
        logger.warning(
            "generate_pool_report called with market_snapshot=None — "
            "limit data will be missing. Use MarketLayerData.load()."
        )

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
