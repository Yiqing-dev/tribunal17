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

# ── Shared CSS ────────────────────────────────────────────────────────────

_BASE_CSS = """
/* ═══════════════════════════════════════════════════════════════
   Unified Theme v3 — Institutional Research Command Center
   Tokens aligned with pool/market/debate reports
   ═══════════════════════════════════════════════════════════════ */
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
  --white: #f1f7fd;
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
* { margin: 0; padding: 0; box-sizing: border-box; }
::selection { background: rgba(96, 165, 250, 0.25); color: var(--white); }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(100, 150, 180, 0.2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(100, 150, 180, 0.35); }
body {
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", -apple-system,
               BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background:
    radial-gradient(ellipse at 15% 20%, rgba(251, 191, 36, 0.10), transparent 32%),
    radial-gradient(ellipse at 85% 18%, rgba(96, 165, 250, 0.08), transparent 30%),
    radial-gradient(ellipse at 50% 110%, rgba(52, 211, 153, 0.08), transparent 38%),
    linear-gradient(180deg, #091420 0%, #070e1b 55%, #050c17 100%);
  color: var(--fg); line-height: 1.75;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.container { max-width: 1060px; margin: 0 auto; padding: 2.2rem 1.5rem 4rem; }

/* ── Typography ── */
h1 {
  margin-bottom: .3rem;
  font-size: clamp(1.6rem, 3vw, 2.2rem); font-weight: 800; letter-spacing: -0.03em;
  background: linear-gradient(135deg, var(--white) 40%, var(--blue));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
h2 {
  color: var(--accent); margin: 2rem 0 1rem;
  font-size: .95rem; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
  border-bottom: none; padding-bottom: 0;
}
h3 {
  color: var(--white); margin: .8rem 0 .5rem;
  font-size: .92rem; font-weight: 700; letter-spacing: 0.02em;
}
.mono { font-variant-numeric: tabular-nums; }
.subtitle { color: var(--muted); margin-bottom: 1.2rem; font-size: .88rem; letter-spacing: 0.04em; }

/* ── Banner ── */
.banner {
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 14px;
  padding: .65rem 1rem; margin-bottom: 1.2rem;
  color: var(--yellow); font-size: .82rem;
}

/* ── Glass Card ── */
.card {
  position: relative;
  background: linear-gradient(180deg, rgba(12, 23, 35, 0.94), rgba(8, 16, 25, 0.92));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 20px;
  padding: 1.25rem 1.3rem;
  margin-bottom: 1rem;
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.18), inset 0 1px 0 rgba(255,255,255,0.04);
  backdrop-filter: blur(12px);
  transition: transform 280ms ease, box-shadow 280ms ease, border-color 280ms ease;
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255,255,255,0.06);
  border-color: rgba(255, 255, 255, 0.1);
}

/* ── Hero (Decision Cockpit) ── */
.hero {
  position: relative; overflow: hidden;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background:
    linear-gradient(135deg, rgba(12, 29, 45, 0.96) 0%, rgba(12, 21, 31, 0.88) 45%, rgba(24, 34, 28, 0.9) 100%);
  box-shadow: 0 22px 54px rgba(0, 0, 0, 0.26);
  padding: 2rem;
  margin-bottom: 1.2rem;
}
.hero::after {
  content: ""; position: absolute;
  inset: -20% auto auto 56%;
  width: 340px; height: 340px; border-radius: 50%;
  background: radial-gradient(circle, rgba(245, 158, 11, 0.14), transparent 64%);
  pointer-events: none;
}
.hero-grid {
  position: relative; z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(280px, 0.9fr);
  gap: 1.2rem; align-items: start;
}
.hero-left {}
.hero-right { display: grid; gap: .7rem; }
.eyebrow {
  display: inline-flex; align-items: center; gap: .5rem;
  text-transform: uppercase; letter-spacing: .18em;
  font-size: .72rem; color: var(--yellow); margin-bottom: .6rem;
}
.hero-action {
  font-size: clamp(2.2rem, 4vw, 3.2rem);
  font-weight: 800; line-height: 1; letter-spacing: -0.04em;
  margin-bottom: .5rem;
}
.hero-summary {
  color: var(--fg); font-size: .95rem; line-height: 1.6;
  max-width: 36rem; margin-bottom: .75rem;
}

/* ── KPI Panels ── */
.kpi-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: .75rem; margin-bottom: 1rem; }
.kpi {
  position: relative; overflow: hidden;
  background: linear-gradient(180deg, rgba(10, 22, 34, 0.94), rgba(10, 18, 28, 0.88));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 18px;
  padding: .9rem 1rem; text-align: center;
  box-shadow: 0 10px 22px rgba(0, 0, 0, 0.14), inset 0 1px 0 rgba(255,255,255,0.03);
  transition: transform 200ms ease, box-shadow 200ms ease;
}
.kpi:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255,255,255,0.05);
}
.kpi::before {
  content: ""; position: absolute; inset: 0 auto auto 0;
  width: 100%; height: 3px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.04));
}
.kpi-val {
  display: block; font-size: 1.8rem; font-weight: 800;
  font-family: var(--mono); color: var(--white); line-height: 1;
}
.kpi-label { display: block; font-size: .72rem; color: var(--muted); margin-top: .35rem; letter-spacing: .04em; }
.kpi.buy .kpi-val { color: var(--green); }
.kpi.buy::before { background: linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.8), transparent); }
.kpi.sell .kpi-val, .kpi.veto .kpi-val { color: var(--red); }
.kpi.sell::before, .kpi.veto::before { background: linear-gradient(90deg, transparent, rgba(248, 113, 113, 0.8), transparent); }
.kpi.hold .kpi-val { color: var(--yellow); }
.kpi.hold::before { background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.8), transparent); }

/* ── Badges (pill) ── */
.badge {
  display: inline-flex; align-items: center;
  padding: 3px 12px; border-radius: 999px;
  font-size: .74rem; font-weight: 600;
  backdrop-filter: blur(8px);
}
.badge-buy { background: rgba(52, 211, 153, 0.14); color: var(--green); }
.badge-hold { background: rgba(251, 191, 36, 0.14); color: var(--yellow); }
.badge-sell, .badge-veto { background: rgba(248, 113, 113, 0.14); color: var(--red); }
.badge-high { background: rgba(248, 113, 113, 0.14); color: var(--red); }
.badge-medium { background: rgba(251, 191, 36, 0.14); color: var(--yellow); }
.badge-low { background: rgba(96, 165, 250, 0.12); color: var(--muted); }
.badge-muted { background: rgba(255, 255, 255, 0.06); color: var(--muted); }
.badge-ok, .badge-good { background: rgba(52, 211, 153, 0.14); color: var(--green); }
.badge-warn, .badge-bad { background: rgba(248, 113, 113, 0.14); color: var(--red); }

/* ── Status lights ── */
.light { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; box-shadow: 0 0 6px currentColor; }
.light-green { background: var(--green); color: var(--green); }
.light-red { background: var(--red); color: var(--red); }
.light-yellow { background: var(--yellow); color: var(--yellow); }
.light-gray { background: var(--muted); color: var(--muted); }

/* ── Bull/Bear bar ── */
.bb-bar { display: flex; height: 24px; border-radius: 999px; overflow: hidden; margin: .5rem 0; background: rgba(255,255,255,0.04); }
.bb-bull { background: linear-gradient(90deg, rgba(52, 211, 153, 0.85), rgba(52, 211, 153, 0.55)); }
.bb-bear { background: linear-gradient(90deg, rgba(248, 113, 113, 0.55), rgba(248, 113, 113, 0.85)); }
.bb-label { font-size: .75rem; color: var(--muted); display: flex; justify-content: space-between; }

/* ── Probability bar ── */
.prob-bar { display: flex; height: 32px; border-radius: 999px; overflow: hidden; margin: .5rem 0; background: rgba(255,255,255,0.04); }
.prob-bar > div { display: flex; align-items: center; justify-content: center; font-size: .75rem; font-weight: 600; }
.prob-seg { position:relative; transition: width 800ms cubic-bezier(0.22,1,0.36,1); }
.prob-seg[data-tip]:hover::after {
  content:attr(data-tip); position:absolute; bottom:110%; left:50%;
  transform:translateX(-50%); background:var(--surface); border:1px solid var(--border);
  border-radius:8px; padding:.3rem .6rem; font-size:.72rem; white-space:nowrap; z-index:10;
  pointer-events:none;
}

/* ── Claim card grid ── */
.claim-grid { display: grid; gap: .75rem; margin: .75rem 0; }
.claim-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 14px;
  padding: .85rem 1rem; font-size: .85rem;
  transition: transform 180ms ease, box-shadow 180ms ease;
}
.claim-card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,0,0,0.2); }
.claim-card .dim { font-size: .7rem; color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin-bottom: .25rem; }
.claim-card .conf-bar { height: 4px; background: rgba(255,255,255,0.06); border-radius: 999px; margin-top: .5rem; }
.claim-card .conf-fill { height: 100%; border-radius: 999px; }
.claim-card .ev-tags { margin-top: .3rem; font-size: .7rem; color: var(--muted); }

/* ── Trade plan card ── */
.tp-table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-bottom: .5rem; }
.tp-table th { text-align: left; color: var(--muted); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.08); padding: .45rem .4rem; font-size: .76rem; letter-spacing: .06em; text-transform: uppercase; }
.tp-table td { padding: .45rem .4rem; border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 150ms ease; }
.tp-table tr:hover td { background: rgba(255,255,255,0.02); }
.tp-table .mono { font-family: var(--mono); }
.tp-row { display: flex; align-items: center; gap: .6rem; padding: .35rem 0; font-size: .85rem; }
.tp-label { font-weight: 600; min-width: 5em; }
.tp-detail { color: var(--muted); font-size: .8rem; }
.tp-section-title { font-size: .76rem; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: .08em; margin-bottom: .4rem; }
.tp-inval-list { margin: .25rem 0 0 1.2rem; font-size: .82rem; color: var(--fg); }
.tp-inval-list li { margin-bottom: .2rem; }
.tp-stop { border-top: 1px solid rgba(255,255,255,0.06); margin-top: .35rem; padding-top: .5rem; }
.tp-target { padding: .2rem 0; }
.mono { font-family: var(--mono); }

/* ── Trust signal cards ── */
.trust-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: .8rem; margin: .75rem 0; }
.trust-card {
  position: relative; overflow: hidden;
  background: linear-gradient(180deg, rgba(10, 22, 34, 0.94), rgba(10, 18, 28, 0.88));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 18px;
  padding: 1rem; text-align: center;
  box-shadow: 0 10px 22px rgba(0, 0, 0, 0.14);
}
.trust-card::before {
  content: ""; position: absolute; inset: 0 auto auto 0;
  width: 100%; height: 3px;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.04));
}
.trust-card .tv { font-size: 1.8rem; font-weight: 800; font-family: var(--mono); }
.trust-card .tl { font-size: .75rem; color: var(--muted); margin-top: .3rem; }
.trust-card .te { font-size: .7rem; color: var(--muted); margin-top: .2rem; }
.trust-card.good .tv { color: var(--green); }
.trust-card.good::before { background: linear-gradient(90deg, transparent, rgba(52, 211, 153, 0.8), transparent); }
.trust-card.warn .tv { color: var(--yellow); }
.trust-card.warn::before { background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.8), transparent); }
.trust-card.bad .tv { color: var(--red); }
.trust-card.bad::before { background: linear-gradient(90deg, transparent, rgba(248, 113, 113, 0.8), transparent); }

/* ── Tables ── */
table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
th, td { padding: .55rem .75rem; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.06); }
th { color: var(--muted); font-weight: 600; font-size: .78rem; letter-spacing: .06em; text-transform: uppercase; }
tbody tr { transition: background 120ms ease; }
tbody tr:hover { background: rgba(255,255,255,0.03); }

/* Lists */
ul, ol { padding-left: 1.5rem; margin-bottom: .75rem; }
li { margin-bottom: .3rem; font-size: .9rem; }

/* ── Excerpt box ── */
.excerpt {
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 14px;
  padding: 1rem; font-size: .85rem; white-space: pre-wrap; word-wrap: break-word;
  max-height: 300px; overflow-y: auto; margin: .5rem 0;
}
.excerpt-short { max-height: 150px; }

/* ── Two-column layout ── */
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }

/* ── Callout ── */
.callout {
  background: rgba(251, 191, 36, 0.08); border-left: 4px solid var(--yellow); border-radius: 14px;
  padding: .75rem 1rem; margin: 1rem 0; font-size: .88rem; color: var(--yellow);
}

/* ── Checklist ── */
.checklist { display: grid; gap: .5rem; margin: .75rem 0; }
.ck-item {
  display: flex; align-items: center; gap: .6rem;
  padding: .55rem .8rem; border-radius: 14px;
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
  transition: transform 160ms ease;
}
.ck-item:hover { transform: translateX(4px); }
.ck-emoji { font-size: 1.2rem; flex-shrink: 0; }
.ck-pillar { font-weight: 600; min-width: 3em; }
.ck-score { color: var(--muted); font-size: .82rem; font-family: var(--mono); margin-left: auto; white-space: nowrap; }
.ck-label { font-size: .82rem; color: var(--muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Risk Debate Summary ── */
.risk-debate-row { display: flex; gap: .75rem; flex-wrap: wrap; }
.rd-col {
  flex: 1; min-width: 140px;
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 18px;
  padding: .85rem; text-align: center;
  transition: transform 160ms ease;
}
.rd-col:hover { transform: translateY(-2px); }
.rd-stance { font-weight: 700; margin-bottom: .35rem; color: var(--white); }
.rd-rec { font-size: 1rem; margin-bottom: .25rem; }
.rd-pos { font-size: .85rem; color: var(--muted); font-family: var(--mono); }
.rd-risk { font-size: .78rem; color: var(--muted); margin-top: .35rem; word-break: break-all; }

/* ── Battle Plan ── */
.battle-plan { border-left: none; }
.battle-plan::before {
  content: ""; position: absolute; inset: 0 auto auto 0;
  width: 4px; height: 100%; border-radius: 20px 0 0 20px;
  background: var(--green);
}
.battle-plan.sell-plan::before { background: var(--red); }
.battle-plan.hold-plan::before { background: var(--yellow); }
.bp-header { display: flex; align-items: center; gap: .6rem; margin-bottom: .75rem; flex-wrap: wrap; }
.bp-side { font-size: 1.4rem; font-weight: 800; letter-spacing: -0.02em; }
.bp-rationale { font-size: .88rem; color: var(--muted); margin-bottom: .75rem; line-height: 1.5; }
.bp-gauge { height: 8px; background: rgba(255,255,255,0.06); border-radius: 999px; overflow: hidden; margin: .3rem 0; }
.bp-gauge-fill { height: 100%; border-radius: 999px; }

/* ── Signal History ── */
.sig-hist-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.sig-hist-table td { padding: .45rem .5rem; border-bottom: 1px solid rgba(255,255,255,0.06); }

/* ── Decision chain timeline ── */
.timeline { border-left: 2px solid rgba(96, 165, 250, 0.3); margin-left: 10px; padding-left: 22px; }
.timeline-item { position: relative; padding: .7rem 0; border-bottom: 1px dashed rgba(255,255,255,0.06); }
.timeline-item:last-child { border-bottom: none; }
.timeline-item::before {
  content: ''; position: absolute; left: -27px; top: 1.1rem;
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--blue); box-shadow: 0 0 8px rgba(96, 165, 250, 0.5);
}
.timeline-node { font-weight: 700; color: var(--white); min-width: 120px; display: inline-block; }
.timeline-detail { font-size: .85rem; color: var(--muted); }

/* ── Status Lights Bar ── */
.status-bar {
  display: flex; gap: 1.2rem; flex-wrap: wrap;
  padding: .8rem 1rem;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 18px;
  margin-bottom: 1rem;
}

/* ── Reveal Animations ── */
.reveal { animation: card-rise 520ms ease both; }
.reveal-d1 { animation-delay: 60ms; }
.reveal-d2 { animation-delay: 120ms; }
.reveal-d3 { animation-delay: 180ms; }
.reveal-d4 { animation-delay: 240ms; }
.reveal-d5 { animation-delay: 300ms; }
.reveal-d6 { animation-delay: 360ms; }
@keyframes card-rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes bar-grow { from { width: 0; } }
.conf-fill, .bb-bull, .bb-bear { animation: bar-grow 600ms cubic-bezier(0.22,1,0.36,1) both; }
details>summary{cursor:pointer;list-style:none}
details>summary::-webkit-details-marker{display:none}
details>summary h2::after{content:" \u25be";font-size:.7em;opacity:.5}
details:not([open])>summary h2::after{content:" \u25b8"}

/* ── Footer ── */
.footer {
  margin-top: 2.5rem; color: var(--muted); font-size: .78rem;
  border-top: 1px solid rgba(255,255,255,0.06); padding-top: 1rem;
  letter-spacing: .04em; text-align: center;
  background: linear-gradient(180deg, transparent, rgba(255,255,255,0.01));
  border-radius: 0 0 20px 20px; padding-bottom: 1rem;
}

/* ── Mobile ── */
@media (max-width: 760px) {
  .cols { grid-template-columns: 1fr; }
  .container { padding: 1.25rem .75rem 2.5rem; }
  .hero { border-radius: 18px; padding: 1.25rem; }
  .hero-grid { grid-template-columns: 1fr; }
  .hero-action { font-size: 2rem; }
  h1 { font-size: 1.3rem; }
  h2 { font-size: .95rem; margin: 1.2rem 0 .6rem; }
  .kpi-row { grid-template-columns: repeat(2, 1fr); gap: .5rem; }
  .kpi { padding: .7rem .5rem; }
  .kpi-val { font-size: 1.4rem; }
  .card { padding: 1rem; border-radius: 14px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .badge { min-height: 28px; }
  .claim-grid { gap: .5rem; }
  .claim-card { padding: .6rem .8rem; font-size: .82rem; border-radius: 10px; }
  .trust-grid { grid-template-columns: repeat(2, 1fr); gap: .6rem; }
  .trust-card { padding: .75rem; border-radius: 14px; }
  .trust-card .tv { font-size: 1.5rem; }
  th, td { padding: .4rem .5rem; font-size: .82rem; }
  .excerpt { font-size: .82rem; max-height: 220px; border-radius: 10px; }
  .timeline { padding-left: 16px; margin-left: 6px; }
  .footer { font-size: .75rem; }
  .rd-col { border-radius: 14px; }
  .status-bar { gap: .8rem; }
  .reveal { animation: none !important; }
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

/* ── V1: Card hierarchy ── */
.card {
  box-shadow: 0 8px 20px rgba(0,0,0,0.12), inset 0 1px 0 rgba(255,255,255,0.03);
}
.card:hover {
  box-shadow: 0 12px 28px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.05);
}
.hero { box-shadow: 0 22px 54px rgba(0,0,0,0.26), 0 0 0 1px rgba(255,255,255,0.06); }

/* ── V3: Numeric alignment ── */
td.num, .num { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
.kpi-val, .card-value, .trust-card .tv { font-variant-numeric: tabular-nums; }

/* ── V4: Staggered animation ── */
.bb-bull { animation-delay: 80ms; }
.bb-bear { animation-delay: 220ms; }
.prob-seg:nth-child(1) { animation: bar-grow 600ms cubic-bezier(0.22,1,0.36,1) 0ms both; }
.prob-seg:nth-child(2) { animation: bar-grow 600ms cubic-bezier(0.22,1,0.36,1) 100ms both; }
.prob-seg:nth-child(3) { animation: bar-grow 600ms cubic-bezier(0.22,1,0.36,1) 200ms both; }
.prob-seg:nth-child(4) { animation: bar-grow 600ms cubic-bezier(0.22,1,0.36,1) 300ms both; }

/* ── V5a: Keyboard focus ── */
.toggle-btn:focus-visible, .csv-btn:focus-visible, .filter-btn:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* ── V5: Touch feedback ── */
@media (hover: none) and (pointer: coarse) {
  .card:active, .kpi:active, .claim-card:active, .trust-card:active {
    transform: scale(0.97); transition: transform 60ms ease;
  }
  .toggle-btn:active, .csv-btn:active { opacity: 0.7; transition: opacity 60ms ease; }
}

/* ── V6: Tooltip/drawer consistency ── */
.hm-tooltip {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; box-shadow: 0 12px 28px rgba(0,0,0,0.3);
  backdrop-filter: blur(14px); font-size: .78rem;
}
.detail-drawer {
  background: var(--surface); border-left: 1px solid var(--border);
  box-shadow: -8px 0 24px rgba(0,0,0,0.3); backdrop-filter: blur(16px);
}
.drawer-header {
  position: sticky; top: 0; z-index: 2;
  background: inherit; padding-bottom: .8rem;
  border-bottom: 1px solid var(--border);
}

/* ── V7: Table scan ── */
tbody tr:nth-child(even) { background: rgba(255,255,255,0.015); }
thead th { position: sticky; top: 0; z-index: 1; background: var(--surface); }

/* ── V8: Empty state ── */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 2rem 1rem; text-align: center; color: var(--muted);
}
.empty-state-icon { font-size: 2rem; margin-bottom: .6rem; opacity: .6; }
.empty-state-title { font-size: .88rem; font-weight: 600; margin-bottom: .25rem; }
.empty-state-hint { font-size: .78rem; opacity: .8; }

/* ── S1: Contrast boost ── */
.kpi-label, .card-title, .tl, .te, .sec-sub,
.kpi-cell .lab, .audit-cell .al, .verdict-kpi .vk-label {
  font-weight: 500;
}

/* ── S4: Elevation system ── */
.card, .kpi, .trust-card { box-shadow: var(--elev-1); }
.card:hover, .kpi:hover { box-shadow: var(--elev-2); }
.hero { box-shadow: var(--elev-3); }
.hm-tooltip, .prob-seg[data-tip]:hover::after { box-shadow: var(--elev-2); }
.detail-drawer { box-shadow: var(--elev-3); }

/* ── S5: Unified timing ── */
.card, .kpi, .claim-card, .trust-card {
  transition: transform var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out);
}
.reveal { animation: card-rise var(--dur-med) var(--ease-out) both; }

/* ── S2: KPI hierarchy ── */
.kpi-primary .kpi-val, .kpi-primary .card-value {
  font-size: 2.4rem; text-shadow: 0 0 24px currentColor;
}
.kpi-secondary .kpi-val, .kpi-secondary .card-value {
  font-size: 1.4rem; opacity: .85;
}

/* ── S6: Table readability ── */
tbody tr:nth-child(even) { background: rgba(255,255,255,0.025); }
tbody tr:hover { background: rgba(255,255,255,0.045); }

/* ── S3: 8px spacing rhythm ── */
.card { padding: var(--sp-3); margin-bottom: var(--sp-2); }
.hero { padding: var(--sp-4); margin-bottom: var(--sp-3); }
.kpi-row, .trust-grid, .claim-grid { gap: var(--sp-2); }
.kpi { padding: var(--sp-2); }
h2 { margin: var(--sp-4) 0 var(--sp-2); }
.container { padding: var(--sp-4) var(--sp-3) var(--sp-6); }

/* ── S7: Mobile first-screen ── */
@media (min-width: 761px) {
  details.mobile-collapse { display: contents; }
  details.mobile-collapse > summary { display: none; }
}
@media (max-width: 760px) {
  details.mobile-collapse { margin-bottom: var(--sp-1); }
  details.mobile-collapse > summary {
    cursor: pointer; list-style: none;
    padding: var(--sp-1) var(--sp-2); border-radius: 10px;
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
    font-size: .88rem; font-weight: 600; color: var(--fg);
  }
  details.mobile-collapse > summary::-webkit-details-marker { display: none; }
  details.mobile-collapse > summary::after { content: " \u25b8"; font-size: .7em; opacity: .5; }
  details.mobile-collapse[open] > summary::after { content: " \u25be"; }
}

/* ── F3: Heatmap toggle ── */
.hm-toolbar { display: flex; gap: .5rem; margin-bottom: .5rem; }
.hm-toggle { display: inline-flex; padding: .3rem .7rem; border-radius: 6px; font-size: .75rem;
  cursor: pointer; background: rgba(255,255,255,.04); border: 1px solid var(--border);
  color: var(--muted); transition: all var(--dur-fast) var(--ease-out); }
.hm-toggle:hover { background: rgba(255,255,255,.07); }
.hm-toggle.active { color: var(--blue, #60a5fa); background: rgba(96,165,250,.08);
  border-color: rgba(96,165,250,.3); }
.hm-leg-item { cursor: pointer; transition: opacity var(--dur-fast) var(--ease-out); }
.hm-leg-item:hover { opacity: .85; }

@media print {
  :root{--bg:#fff;--fg:#111;--card:#fff;--border:#ddd;--muted:#666;--white:#111;--accent:#333}
  body{background:#fff!important;color:#111!important}
  .card,.hero{background:#fff!important;box-shadow:none!important;backdrop-filter:none!important;
    border:1px solid #ddd!important;border-radius:4px!important}
  .hero::after,body::before{display:none}
  .reveal{animation:none!important}
  .conf-fill,.bb-bull,.bb-bear{animation:none!important}
  .container{max-width:100%;padding:0}
  details[open]>div{display:block!important}
  .toggle-btn,.csv-btn{display:none!important}
  h2{color:#333!important}
  .card{page-break-inside:avoid}
}
"""

_COUNTUP_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('.kpi-val').forEach(function(el){
    var raw=el.textContent.trim();
    var m=raw.match(/([+-]?[\\d.]+)/);
    if(!m)return;
    var target=parseFloat(m[1]),suffix=raw.replace(m[1],''),
        neg=raw.startsWith('-')||raw.startsWith('+'),
        dec=m[1].indexOf('.')>=0?m[1].split('.')[1].length:0,
        dur=600,start=performance.now();
    function step(ts){
      var p=Math.min((ts-start)/dur,1);
      p=1-Math.pow(1-p,3);
      var v=(target*p).toFixed(dec);
      if(neg&&target>=0) v='+'+v;
      el.textContent=v+suffix;
      if(p<1)requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
});
</script>"""


def _html_wrap(title: str, body: str, tier_label: str, extra_css: str = "",
               extra_head: str = "") -> str:
    """Wrap body content in a full HTML document."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>{_BASE_CSS}{extra_css}</style>
{extra_head}
</head>
<body>
<div class="container">
{body}
<div class="footer">TradingAgents {tier_label} v0.2.0</div>
</div>
</body>
</html>"""


def _bull_bear_bar(bull: int, bear: int) -> str:
    total = bull + bear
    if total == 0:
        return ""
    bp = int(bull / total * 100)
    return f"""
    <div class="bb-label"><span>看多 ({bull})</span><span>看空 ({bear})</span></div>
    <div class="bb-bar">
      <div class="bb-bull" style="width:{bp}%"></div>
      <div class="bb-bear" style="width:{100-bp}%"></div>
    </div>"""


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


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _empty_state(icon: str, title: str, hint: str = "") -> str:
    """Render a polished empty-state placeholder."""
    hint_html = f'<div class="empty-state-hint">{_esc(hint)}</div>' if hint else ""
    return (f'<div class="empty-state">'
            f'<div class="empty-state-icon">{icon}</div>'
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


def _ticker_display(view) -> str:
    """Return 'TICKER NAME' if name is available, else just 'TICKER'."""
    name = getattr(view, "ticker_name", "")
    if name:
        return f"{view.ticker} {name}"
    return view.ticker


def _evidence_strength_label(level: str) -> str:
    return EVIDENCE_STRENGTH_LABELS.get(level, level)


def _direction_badge(direction: str) -> str:
    """Render a small direction badge for catalysts."""
    cls_map = {"bullish": "buy", "bearish": "sell", "neutral": "hold"}
    labels = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
    badge_cls = cls_map.get(direction, "hold")
    return f'<span class="badge badge-{badge_cls}">{_esc(labels.get(direction, direction))}</span>'


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


# ── Feature 2: Checklist + Risk Debate Summary ──────────────────────────


def _radar_svg(pillars, action_class, size=180):
    """SVG radar chart for 4-pillar scores (0-4 scale)."""
    import math
    cx = cy = size / 2
    max_r = size * 0.38
    axes = [(-math.pi / 2 + i * math.pi / 2) for i in range(4)]  # top, right, bottom, left
    labels = ["\u6280\u672f\u9762", "\u57fa\u672c\u9762", "\u65b0\u95fb\u9762", "\u60c5\u7eea\u9762"]
    color_map = {"buy": "#34d399", "hold": "#fbbf24", "sell": "#f87171", "veto": "#f87171"}
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
    conf_cls = "buy" if confidence >= 0.7 else ("hold" if confidence >= 0.4 else "sell")

    header = (
        f'<div class="bp-header">'
        f'<span class="bp-side">{emoji} {_esc(side_label)}</span>'
        f'<span class="badge badge-{conf_cls}">\u7f6e\u4fe1\u5ea6 {confidence:.0%}</span>'
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
        hero_kpis.append(f'<div class="kpi kpi-primary {conf_cls}"><span class="kpi-val">{conf_pct}%</span><span class="kpi-label">置信度</span></div>')
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
            <div class="kpi {'buy' if view.confidence >= 0.7 else ('hold' if view.confidence >= 0.4 else 'sell')}"><span class="kpi-val">{conf_pct_r}%</span><span class="kpi-label">置信度</span></div>
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
        scenario_html = f"""
    <div class="card">
      <h3>情景分析</h3>
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


_BRAND_LOGO_SM = (
    '<svg width="22" height="22" viewBox="0 0 44 44" fill="none">'
    '<rect width="44" height="44" rx="12" fill="rgba(245,158,11,0.15)"/>'
    '<rect x="9" y="11" width="26" height="3" rx="1.5" fill="#f59e0b"/>'
    '<rect x="20" y="11" width="4" height="22" rx="2" fill="#f59e0b"/>'
    '</svg>'
)

_BRAND_LOGO_LG = (
    '<svg width="72" height="72" viewBox="0 0 44 44" fill="none">'
    '<rect width="44" height="44" rx="12" fill="rgba(245,158,11,0.12)"/>'
    '<rect x="9" y="11" width="26" height="3" rx="1.5" fill="#f59e0b" opacity="0.9"/>'
    '<rect x="20" y="11" width="4" height="22" rx="2" fill="#f59e0b" opacity="0.9"/>'
    '</svg>'
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
# ║  Market Page + Heatmap + Drawer (P3/P4/P5)                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

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
.mkt-hero-chip.up   { color: var(--green); border-color: rgba(52,211,153,.25); }
.mkt-hero-chip.down { color: var(--red);   border-color: rgba(248,113,113,.25); }
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
.mkt-kpi .val.up   { color: var(--green); }
.mkt-kpi .val.down { color: var(--red); }
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
.idx-battle-card .idx-pct.up { color: var(--green); }
.idx-battle-card .idx-pct.down { color: var(--red); }
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
.breadth-dual-bar .bar-up { background: linear-gradient(90deg, rgba(52,211,153,.6), var(--green)); }
.breadth-dual-bar .bar-dn { background: linear-gradient(90deg, var(--red), rgba(248,113,113,.6)); }
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
.sector-item .si-pct.up { color: var(--green); }
.sector-item .si-pct.dn { color: var(--red); }
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
.limit-col-header .lch-count.up { color: var(--green); }
.limit-col-header .lch-count.dn { color: var(--red); }
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
.limit-stock-row .ls-boards.normal { background: rgba(52,211,153,.1); color: var(--green); }
.limit-stock-row .ls-seal { font-size: .75rem; color: var(--muted); font-family: monospace; min-width: 48px; text-align: right; }
.limit-stock-row .ls-pct { font-size: .78rem; font-family: monospace; font-weight: 600; min-width: 52px; text-align: right; }
.limit-stock-row .ls-pct.up { color: var(--green); }
.limit-stock-row .ls-pct.dn { color: var(--red); }
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


# ── Squarified Treemap + Heatmap Helpers ─────────────────────────────


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


def _heatmap_color(pct_change, action=""):
    """Return fill color for a heatmap node."""
    if action == "BUY":
        if pct_change > 0:
            return "#1a7f37"
        return "#2ea043"
    elif action == "SELL":
        if pct_change < 0:
            return "#cf222e"
        return "#da3633"
    elif action == "VETO":
        return "#6e40c9"
    # Neutral / HOLD
    if pct_change > 3:
        return "#1a7f37"
    elif pct_change > 0:
        return "#2ea043"
    elif pct_change > -3:
        return "#da3633"
    return "#cf222e"


def _heatmap_risk_color(confidence):
    """Blue-orange color mapping for risk/confidence view of heatmap."""
    conf = float(confidence) if confidence else 0
    if conf >= 0.8:
        return "#1d4ed8"   # deep blue — high confidence
    elif conf >= 0.6:
        return "#3b82f6"   # blue
    elif conf >= 0.4:
        return "#6b7280"   # grey — neutral
    elif conf >= 0.2:
        return "#ea580c"   # orange
    return "#dc2626"       # red — low confidence


def _render_heatmap_legend():
    """Render heatmap color legend."""
    return (
        '<div class="hm-legend">'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#1a7f37"></span> BUY/\u2191</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#2ea043"></span> HOLD/\u2191</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#da3633"></span> HOLD/\u2193</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#cf222e"></span> SELL/\u2193</span>'
        '<span class="hm-leg-item"><span class="hm-leg-dot" style="background:#6e40c9"></span> VETO</span>'
        '<span class="hm-leg-note">\u9762\u79ef \u221d \u5e02\u503c</span>'
        '</div>'
    )


def _render_svg_heatmap(heatmap_data, width=960, height=400, max_nodes=0):
    """Render an SVG treemap from heatmap_data dict."""
    if not heatmap_data:
        return ""
    nodes = heatmap_data.get("nodes", [])
    if not nodes:
        return ""
    if max_nodes > 0:
        nodes = nodes[:max_nodes]

    values = []
    for i, n in enumerate(nodes):
        cap = float(n.get("market_cap", 0) or n.get("size_score", 1))
        values.append((i, max(cap, 0.01)))
    values.sort(key=lambda x: x[1], reverse=True)

    rects = _squarify(values, 0, 0, width, height)

    svg_nodes = []
    mobile_rows = []
    for idx, rx, ry, rw, rh in rects:
        n = nodes[idx]
        pct = float(n.get("pct_change", 0))
        action = str(n.get("action", "HOLD")).upper()
        name = str(n.get("name", n.get("ticker", "")))
        ticker = str(n.get("ticker", ""))
        fill = _heatmap_color(pct, action)
        sign = "+" if pct > 0 else ""

        show_name = rw > 45 and rh > 24
        show_pct = rw > 35 and rh > 16

        name_el = ""
        if show_name:
            fs = min(max(rw / max(len(name), 1) * 1.2, 8), 14)
            name_el = f'<text x="{rx + rw/2:.1f}" y="{ry + rh/2 - 3:.1f}" text-anchor="middle" fill="#fff" font-size="{fs:.0f}" font-weight="600">{_esc(name)}</text>'
        pct_el = ""
        if show_pct:
            pct_el = f'<text x="{rx + rw/2:.1f}" y="{ry + rh/2 + 11:.1f}" text-anchor="middle" fill="rgba(255,255,255,.7)" font-size="10">{sign}{pct:.1f}%</text>'

        conf = float(n.get("confidence", 0))
        conf_str = f"{conf:.0%}" if conf > 0 else ""
        sector = str(n.get("sector", ""))
        risk_fill = _heatmap_risk_color(conf)
        data_attrs = f'data-idx="{idx}" data-ticker="{_esc(ticker)}" data-name="{_esc(name)}" data-pct="{pct:.2f}" data-action="{_esc(action)}" data-conf="{conf_str}" data-sector="{_esc(sector)}"'

        svg_nodes.append(
            f'<g class="hm-node" {data_attrs}>'
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{max(rw - 1, 1):.1f}" height="{max(rh - 1, 1):.1f}" '
            f'rx="3" fill="{fill}" stroke="var(--bg, #0d1117)" stroke-width="1.5" '
            f'data-return-fill="{fill}" data-risk-fill="{risk_fill}"/>'
            f'{name_el}{pct_el}</g>'
        )

        pct_cls = "up" if pct > 0 else ("dn" if pct < 0 else "")
        mobile_rows.append(
            f'<div class="hm-list-row" {data_attrs}>'
            f'<span class="hm-list-dot" style="background:{fill}"></span>'
            f'<span class="hm-list-name">{_esc(name)}</span>'
            f'<span class="hm-list-pct {pct_cls}">{sign}{pct:.1f}%</span>'
            f'<span class="hm-list-act">{_esc(action)}</span>'
            f'</div>'
        )

    svg = f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet">{"".join(svg_nodes)}</svg>'
    mobile = f'<div class="hm-mobile-list">{"".join(mobile_rows)}</div>'
    return svg + mobile


def _render_detail_drawer():
    """Render the detail drawer overlay for heatmap clicks."""
    return """
    <div class="drawer-overlay" id="drawerOverlay"></div>
    <div class="detail-drawer" id="detailDrawer">
      <button class="drawer-close" id="drawerClose">&times;</button>
      <div class="drawer-header">
        <h3 id="drawerTitle">--</h3>
      </div>
      <div class="drawer-kpi">
        <div class="kpi"><div class="kpi-val" id="drawerPct">--</div><div class="kpi-lab">\u6da8\u8dcc\u5e45</div></div>
        <div class="kpi"><div class="kpi-val" id="drawerAction">--</div><div class="kpi-lab">\u4fe1\u53f7</div></div>
        <div class="kpi"><div class="kpi-val" id="drawerConf">--</div><div class="kpi-lab">\u7f6e\u4fe1\u5ea6</div></div>
      </div>
      <div class="drawer-section">
        <h4>\u677f\u5757</h4>
        <div id="drawerSector">--</div>
      </div>
    </div>"""


def _render_heatmap_js():
    """Render JavaScript for heatmap interactivity."""
    return """
    <div class="hm-tooltip" id="hmTooltip"></div>
    <script>
    (function(){
      var drawer = document.getElementById('detailDrawer');
      var overlay = document.getElementById('drawerOverlay');
      var tooltip = document.getElementById('hmTooltip');
      if (!drawer) return;

      function openDrawer(el) {
        document.getElementById('drawerTitle').textContent = el.dataset.name || '--';
        var pct = parseFloat(el.dataset.pct || 0);
        var pctEl = document.getElementById('drawerPct');
        pctEl.textContent = (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
        pctEl.style.color = pct > 0 ? 'var(--green)' : (pct < 0 ? 'var(--red)' : 'var(--muted)');
        document.getElementById('drawerAction').textContent = el.dataset.action || '--';
        document.getElementById('drawerConf').textContent = el.dataset.conf || '--';
        document.getElementById('drawerSector').textContent = el.dataset.sector || '--';
        drawer.classList.add('open');
        overlay.classList.add('open');
      }

      document.querySelectorAll('.hm-node, .hm-list-row').forEach(function(el){
        el.setAttribute('tabindex', '0');
        el.setAttribute('role', 'button');
        el.addEventListener('click', function(){ openDrawer(el); });
        el.addEventListener('keydown', function(evt) {
          if (evt.key === 'Enter' || evt.key === ' ') { evt.preventDefault(); openDrawer(el); }
        });
      });

      function closeDrawer() { drawer.classList.remove('open'); overlay.classList.remove('open'); }
      document.getElementById('drawerClose').addEventListener('click', closeDrawer);
      overlay.addEventListener('click', closeDrawer);

      document.querySelectorAll('.hm-node').forEach(function(el){
        el.addEventListener('mouseenter', function(e){
          var n = el.dataset.name || '';
          var p = parseFloat(el.dataset.pct || 0);
          tooltip.textContent = n + ' ' + (p>0?'+':'') + p.toFixed(2) + '%';
          tooltip.style.display = 'block';
          var tw = tooltip.offsetWidth || 150;
          var th = tooltip.offsetHeight || 30;
          var vw = window.innerWidth;
          var vh = window.innerHeight;
          var tx = e.clientX + 12;
          var ty = e.clientY - 8;
          if (tx + tw > vw - 8) tx = e.clientX - tw - 8;
          if (tx < 8) tx = 8;
          if (ty + th > vh - 8) ty = vh - th - 8;
          if (ty < 8) ty = 8;
          tooltip.style.left = tx + 'px';
          tooltip.style.top = ty + 'px';
        });
        el.addEventListener('mousemove', function(e){
          var tw = tooltip.offsetWidth || 150;
          var th = tooltip.offsetHeight || 30;
          var vw = window.innerWidth;
          var vh = window.innerHeight;
          var tx = e.clientX + 12;
          var ty = e.clientY - 8;
          if (tx + tw > vw - 8) tx = e.clientX - tw - 8;
          if (tx < 8) tx = 8;
          if (ty + th > vh - 8) ty = vh - th - 8;
          if (ty < 8) ty = 8;
          tooltip.style.left = tx + 'px';
          tooltip.style.top = ty + 'px';
        });
        el.addEventListener('mouseleave', function(){ tooltip.style.display = 'none'; });
      });

      /* F3: Color mode toggle (return vs risk/confidence) */
      var btnReturn = document.getElementById('hmModeReturn');
      var btnRisk = document.getElementById('hmModeRisk');
      if (btnReturn && btnRisk) {
        function setMode(mode) {
          var attr = mode === 'risk' ? 'data-risk-fill' : 'data-return-fill';
          document.querySelectorAll('.hm-node rect[data-return-fill]').forEach(function(r) {
            r.setAttribute('fill', r.getAttribute(attr) || r.getAttribute('data-return-fill'));
          });
          btnReturn.classList.toggle('active', mode === 'return');
          btnRisk.classList.toggle('active', mode === 'risk');
        }
        btnReturn.addEventListener('click', function(){ setMode('return'); });
        btnRisk.addEventListener('click', function(){ setMode('risk'); });
      }

      /* F3: Legend hover — highlight matching nodes */
      document.querySelectorAll('.hm-leg-item').forEach(function(leg) {
        leg.addEventListener('mouseenter', function() {
          var dot = leg.querySelector('.hm-leg-dot');
          if (!dot) return;
          var col = dot.style.background || dot.style.backgroundColor;
          document.querySelectorAll('.hm-node rect').forEach(function(r) {
            var fill = r.getAttribute('fill') || '';
            r.style.opacity = fill === col ? '1' : '0.25';
          });
        });
        leg.addEventListener('mouseleave', function() {
          document.querySelectorAll('.hm-node rect').forEach(function(r) {
            r.style.opacity = '1';
          });
        });
      });
    })();
    </script>"""


# ── Inline Treemap Engine (zero external dependencies) ───────────────

# Pure-JS squarify treemap renderer, embedded in each HTML page.
# Replaces Plotly CDN which doesn't load from file:// protocol.
_TREEMAP_ENGINE_JS = r"""
(function(cid, D, maxD) {
  var c = document.getElementById(cid);
  if (!c) return;
  c.style.position = 'relative';
  c.style.overflow = 'hidden';
  c.style.cursor = 'default';
  c.style.borderRadius = '12px';

  /* Build tree */
  var nodes = {}, rootId = null;
  for (var i = 0; i < D.ids.length; i++) {
    var id = D.ids[i];
    nodes[id] = {id:id, label:D.labels[i], parent:D.parents[i],
      value:D.values[i], color:D.colors[i], text:D.texts[i],
      hover:D.customdata[i], ch:[]};
    if (!D.parents[i]) rootId = id;
  }
  for (var id in nodes) {
    var p = nodes[id].parent;
    if (p && nodes[p]) nodes[p].ch.push(nodes[id]);
  }

  /* Tooltip — frosted glass */
  var tip = document.createElement('div');
  tip.style.cssText = 'position:fixed;display:none;padding:10px 14px;border-radius:8px;font:13px/1.6 "PingFang SC","Microsoft YaHei",sans-serif;pointer-events:none;z-index:9999;max-width:320px;background:rgba(255,255,255,0.95);color:#1a1a1a;box-shadow:0 8px 32px rgba(0,0,0,0.10),0 1px 3px rgba(0,0,0,0.06);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(0,0,0,0.06)';
  document.body.appendChild(tip);

  var curParent = rootId;

  /* Squarify */
  function sq(items, x, y, w, h) {
    if (!items.length || w < 1 || h < 1) return;
    var total = 0;
    for (var i = 0; i < items.length; i++) total += items[i]._v;
    if (total <= 0) return;
    var sc = w * h / total;
    /* No sort — respect the interleaved red-green order from Python. */
    _lay(items, 0, x, y, w, h, sc);
  }
  function _lay(a, s, x, y, w, h, sc) {
    if (s >= a.length) return;
    if (s === a.length - 1) { a[s]._r = [x,y,w,h]; return; }
    var sh = Math.min(w, h), rA = 0, best = 1e9, end = s;
    for (var i = s; i < a.length; i++) {
      var tA = rA + a[i]._v * sc, sl = tA / sh, worst = 0;
      for (var j = s; j <= i; j++) {
        var d = a[j]._v * sc / sl;
        var asp = sl > d ? sl/d : d/sl;
        if (asp > worst) worst = asp;
      }
      if (worst <= best || i === s) { best = worst; end = i; rA = tA; }
      else break;
    }
    var sl = rA / sh, p = 0;
    for (var i = s; i <= end; i++) {
      var il = a[i]._v * sc / sl;
      if (w <= h) { a[i]._r = [x+p, y, il, sl]; p += il; }
      else { a[i]._r = [x, y+p, sl, il]; p += il; }
    }
    if (w <= h) _lay(a, end+1, x, y+sl, w, h-sl, sc);
    else _lay(a, end+1, x+sl, y, w-sl, h, sc);
  }

  /* Adaptive font size based on tile area */
  function fontSize(w, h) {
    var area = w * h;
    if (area > 30000) return 15;
    if (area > 15000) return 13;
    if (area > 6000) return 12;
    if (area > 2000) return 11;
    return 10;
  }

  /* Render */
  function render(pid) {
    curParent = pid;
    c.innerHTML = '';
    var par = nodes[pid];
    if (!par || !par.ch.length) return;
    var W = c.clientWidth, H = c.clientHeight;
    if (W < 10 || H < 10) return;
    var items = par.ch.map(function(n){ return {_v: Math.max(n.value, 0.01), node: n}; });
    sq(items, 0, 0, W, H);
    var frag = document.createDocumentFragment();
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it._r) continue;
      var r = it._r, n = it.node;
      var rw = Math.round(r[2]), rh = Math.round(r[3]);
      var t = document.createElement('div');
      var fs = fontSize(rw, rh);
      var hasCh = n.ch && n.ch.length && maxD > 1;
      t.style.cssText = 'position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;overflow:hidden;padding:4px;font-family:"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif;letter-spacing:0.3px;border:1px solid rgba(0,0,0,0.06);transition:all 0.18s cubic-bezier(0.22,1,0.36,1)';
      t.style.left = Math.round(r[0])+'px';
      t.style.top = Math.round(r[1])+'px';
      t.style.width = rw+'px';
      t.style.height = rh+'px';
      t.style.fontSize = fs+'px';
      t.style.lineHeight = '1.35';
      t.style.color = '#2a2a2a';
      t.style.background = n.color;
      t.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.35), inset 0 -1px 0 rgba(0,0,0,0.03)';
      if (hasCh) t.style.cursor = 'pointer';

      /* Content: name bold, pct below */
      if (rw > 32 && rh > 16) {
        var txt = n.text || n.label;
        var parts = txt.split('<br>');
        var nameStr = parts[0] || '';
        var pctStr = parts[1] || '';
        var html = '';
        if (rw > 50 && rh > 28) {
          html = '<div style="font-weight:600;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:'+(rw-8)+'px">' + nameStr + '</div>';
          if (pctStr && rh > 38) {
            html += '<div style="pointer-events:none;opacity:0.7;font-size:'+(fs-1)+'px;margin-top:1px">' + pctStr + '</div>';
          }
        } else {
          html = '<div style="pointer-events:none;font-weight:500;font-size:'+(fs-1)+'px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:'+(rw-6)+'px">' + nameStr + '</div>';
        }
        t.innerHTML = html;
      }

      (function(n, t) {
        t.addEventListener('mouseenter', function() {
          tip.innerHTML = n.hover || n.label;
          tip.style.display = 'block';
          t.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.5)';
          t.style.zIndex = '5';
          t.style.transform = 'scale(1.02)';
        });
        t.addEventListener('mousemove', function(e) {
          var tx = e.clientX + 14, ty = e.clientY + 14;
          if (tx + 320 > window.innerWidth) tx = e.clientX - 320;
          if (tx < 8) tx = 8;
          if (ty + 200 > window.innerHeight) ty = e.clientY - 200;
          if (ty < 8) ty = 8;
          tip.style.left = tx+'px';
          tip.style.top = ty+'px';
        });
        t.addEventListener('mouseleave', function() {
          tip.style.display = 'none';
          t.style.boxShadow = 'inset 0 1px 0 rgba(255,255,255,0.25), inset 0 -1px 0 rgba(0,0,0,0.04)';
          t.style.zIndex = '';
          t.style.transform = '';
        });
        if (n.ch && n.ch.length && maxD > 1) {
          t.addEventListener('click', function(){ render(n.id); });
        }
      })(n, t);
      frag.appendChild(t);
    }
    c.appendChild(frag);

    /* Fade-in animation */
    c.style.opacity = '0';
    requestAnimationFrame(function(){ c.style.transition = 'opacity 0.3s ease'; c.style.opacity = '1'; });

    /* Back button — pill style */
    if (pid !== rootId) {
      var parName = nodes[pid] ? nodes[pid].label : '';
      var b = document.createElement('div');
      b.style.cssText = 'position:absolute;top:10px;left:10px;background:rgba(255,255,255,0.88);color:#1a1a1a;padding:5px 14px;border-radius:20px;cursor:pointer;font:500 13px/1.4 "PingFang SC","Microsoft YaHei",sans-serif;z-index:10;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);box-shadow:0 2px 8px rgba(0,0,0,0.1);border:1px solid rgba(0,0,0,0.06);transition:all 0.15s ease';
      b.innerHTML = '\u2190 ' + parName;
      b.addEventListener('mouseenter', function(){ b.style.background = 'rgba(255,255,255,0.98)'; b.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'; });
      b.addEventListener('mouseleave', function(){ b.style.background = 'rgba(255,255,255,0.88)'; b.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)'; });
      b.addEventListener('click', function(){ render(rootId); });
      c.appendChild(b);
    }
  }
  render(rootId);
  var _rt;
  window.addEventListener('resize', function(){ clearTimeout(_rt); _rt = setTimeout(function(){ render(curParent); }, 200); });
})
"""


def _render_inline_treemap(div_id: str, data: dict, max_depth: int = 2,
                           height: int = 520) -> str:
    """Render a self-contained treemap using inline JS (no CDN)."""
    import json as _json
    data_json = _json.dumps(data, ensure_ascii=False)
    return (
        f'<div id="{div_id}" style="width:100%;height:{height}px;'
        f'border-radius:12px;overflow:hidden;background:linear-gradient(135deg,#f0eded,#e8e6e4)"></div>\n'
        f'<script>\n{_TREEMAP_ENGINE_JS}(\'{div_id}\', {data_json}, {max_depth});\n</script>'
    )


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
    import math

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


def _render_plotly_sector_treemap(sectors: list, limit_ups: list = None,
                                  sector_stocks: dict = None,
                                  div_id: str = "sectorTreemap") -> str:
    """Build a Plotly treemap for board data.

    Hierarchy: stock → sector → root.  Click a sector to drill in.
    When ``sector_stocks`` is available (from stock_board_industry_cons_em),
    tiles are sized by real market_cap_yi.  Otherwise falls back to
    turnover-based allocation using limit-up stocks and leaders.

    Returns HTML div + JS script (requires plotly.js CDN in <head>).
    """
    if not sectors:
        return ""

    import json as _json

    ids = ["root"]
    labels = ["全市场"]
    parents = [""]
    values = [0]
    colors = ["#E0E0DC"]
    texts = [""]
    customdata = [""]

    # Build limit-up lookup: sector → list of stocks
    lu_by_sector: dict = {}
    for stock in (limit_ups or []):
        sec = str(stock.get("sector", "") or "")
        if sec:
            lu_by_sector.setdefault(sec, []).append(stock)

    # Interleave gainers and losers for visual red-green patchwork effect.
    # Pair by turnover rank: biggest gainer next to biggest loser, etc.
    # This ensures adjacent tiles in the squarify layout have different colors.
    _gainers = sorted(
        [s for s in sectors[:60] if float(s.get("pct_change", 0) or 0) > 0],
        key=lambda s: float(s.get("total_turnover_yi", 0) or 0), reverse=True,
    )
    _losers = sorted(
        [s for s in sectors[:60] if float(s.get("pct_change", 0) or 0) <= 0],
        key=lambda s: float(s.get("total_turnover_yi", 0) or 0), reverse=True,
    )
    _interleaved = []
    gi, li = 0, 0
    while gi < len(_gainers) or li < len(_losers):
        if gi < len(_gainers):
            _interleaved.append(_gainers[gi]); gi += 1
        if li < len(_losers):
            _interleaved.append(_losers[li]); li += 1
    # If one side is much larger, insert neutral-ish items from the dominant
    # side between minority items to keep visual balance.
    # (The squarify JS now respects this order without re-sorting.)

    seen_sectors = set()
    _used_ids = {"root"}
    for s in _interleaved:
        sector_name = str(s.get("sector", ""))
        if not sector_name or sector_name in seen_sectors:
            continue
        seen_sectors.add(sector_name)

        pct = float(s.get("pct_change", 0) or 0)
        turnover = float(s.get("total_turnover_yi", 0) or 0)
        leader = str(s.get("leader", "") or "")
        leader_pct = float(s.get("leader_pct", 0) or 0)
        adv = int(s.get("advance_count", 0) or 0)
        dec = int(s.get("decline_count", 0) or 0)
        net_flow = float(s.get("net_flow_yi", 0) or 0)

        # Sector parent node (id = "sec:{name}")
        sec_id = f"sec:{sector_name}"
        sign = "+" if pct > 0 else ""
        ids.append(sec_id)
        labels.append(sector_name)
        parents.append("root")
        values.append(max(turnover, 0.01))
        colors.append(_pct_to_hex(pct))
        texts.append(f"{sector_name} {sign}{pct:.2f}%")

        hover_parts = [
            f"<b>{_esc(sector_name)}</b>",
            f"板块涨跌: {sign}{pct:.2f}%",
            f"成交额: {turnover:.1f}亿",
        ]
        if adv or dec:
            hover_parts.append(f"涨/跌: {adv}/{dec}")
        if net_flow:
            fsign = "+" if net_flow > 0 else ""
            hover_parts.append(f"净流入: {fsign}{net_flow:.1f}亿")
        customdata.append("<br>".join(hover_parts))

        # Helper to generate unique stock id
        def _stock_id(name, sector):
            base = f"st:{name}@{sector}"
            if base not in _used_ids:
                _used_ids.add(base)
                return base
            i = 2
            while f"{base}#{i}" in _used_ids:
                i += 1
            uid = f"{base}#{i}"
            _used_ids.add(uid)
            return uid

        # --- Child stock nodes ---
        # Priority: sector_stocks (real market cap) > limit-ups > leader only
        real_stocks = (sector_stocks or {}).get(sector_name, [])
        lu_stocks = lu_by_sector.get(sector_name, [])
        sector_val = max(turnover, 0.01)

        if real_stocks:
            # Best case: real constituent data with market_cap_yi
            total_mcap = sum(float(st.get("market_cap_yi", 0) or 0) for st in real_stocks) or 1.0
            child_sum = 0.0
            for st in real_stocks:
                st_name = str(st.get("name", ""))
                st_pct = float(st.get("pct_change", 0) or 0)
                st_mcap = float(st.get("market_cap_yi", 0) or 0)
                st_amount = float(st.get("amount_yi", 0) or 0)
                st_size = max(st_mcap / total_mcap * sector_val, 0.01)
                child_sum += st_size

                st_sign = "+" if st_pct > 0 else ""
                ids.append(_stock_id(st_name, sector_name))
                labels.append(st_name)
                parents.append(sec_id)
                values.append(st_size)
                colors.append(_pct_to_hex(st_pct))
                texts.append(f"{st_name}<br>{st_sign}{st_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(st_name)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {st_sign}{st_pct:.2f}%<br>"
                    f"总市值: {st_mcap:.0f}亿"
                    + (f"<br>成交额: {st_amount:.1f}亿" if st_amount else "")
                )

            # Remainder → "其他" bucket
            remainder = max(sector_val - child_sum, 0.01)
            if remainder > 0.02:
                ids.append(f"other:{sector_name}")
                labels.append("其他")
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(pct))
                texts.append("")
                customdata.append(f"{_esc(sector_name)} 其他成份股")

        elif lu_stocks:
            # Fallback: limit-up stocks (no real market cap, use amount)
            total_lu_amount = sum(float(st.get("amount_yi", 0) or 0) for st in lu_stocks) or 1.0
            lu_names = {str(st.get("name", "")) for st in lu_stocks}
            has_extra_leader = leader and leader not in lu_names
            lu_share = 0.7 if has_extra_leader else 1.0
            child_sum = 0.0

            for st in lu_stocks:
                st_name = str(st.get("name", ""))
                st_pct = float(st.get("pct_change", 0) or 0)
                st_amount = float(st.get("amount_yi", 0) or 0)
                boards = int(st.get("boards", 1) or 1)
                seal = float(st.get("seal_amount_yi", 0) or 0)
                st_size = max(st_amount / total_lu_amount * sector_val * lu_share, 0.01)
                child_sum += st_size

                st_sign = "+" if st_pct > 0 else ""
                ids.append(_stock_id(st_name, sector_name))
                labels.append(st_name)
                parents.append(sec_id)
                values.append(st_size)
                colors.append(_pct_to_hex(st_pct))
                texts.append(f"{st_name}<br>{st_sign}{st_pct:.1f}%")

                st_hover = [
                    f"<b>{_esc(st_name)}</b> ({_esc(sector_name)})",
                    f"涨跌幅: {st_sign}{st_pct:.2f}%",
                    f"成交额: {st_amount:.2f}亿",
                ]
                if boards > 1:
                    st_hover.append(f"连板: {boards}板")
                if seal > 0:
                    st_hover.append(f"封板资金: {seal:.1f}亿")
                customdata.append("<br>".join(st_hover))

            remainder = max(sector_val - child_sum, 0.01)
            if has_extra_leader:
                lsign = "+" if leader_pct > 0 else ""
                ids.append(_stock_id(leader, sector_name))
                labels.append(leader)
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(leader_pct))
                texts.append(f"{leader}<br>{lsign}{leader_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(leader)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {lsign}{leader_pct:.2f}%<br>领涨股"
                )
            else:
                ids.append(f"other:{sector_name}")
                labels.append("其他")
                parents.append(sec_id)
                values.append(remainder)
                colors.append(_pct_to_hex(pct))
                texts.append("")
                customdata.append(f"{_esc(sector_name)} 其他成份股")
        else:
            # Minimal fallback: leader as sole child
            if leader:
                lsign = "+" if leader_pct > 0 else ""
                ids.append(_stock_id(leader, sector_name))
                labels.append(leader)
                parents.append(sec_id)
                values.append(sector_val)
                colors.append(_pct_to_hex(leader_pct))
                texts.append(f"{leader}<br>{lsign}{leader_pct:.1f}%")
                customdata.append(
                    f"<b>{_esc(leader)}</b> ({_esc(sector_name)})<br>"
                    f"涨跌幅: {lsign}{leader_pct:.2f}%<br>"
                    f"板块成交额: {turnover:.1f}亿"
                )

    # Root value must equal sum of direct children (branchvalues="total")
    values[0] = sum(values[i] for i, p in enumerate(parents) if p == "root")

    data = {
        "ids": ids, "labels": labels, "parents": parents,
        "values": values, "colors": colors, "texts": texts,
        "customdata": customdata,
    }
    return _render_inline_treemap(div_id, data, max_depth=2, height=520)


def _render_plotly_stock_treemap(heatmap_data: dict, div_id: str = "stockTreemap") -> str:
    """Build a Plotly treemap for stock-level heatmap data.

    Hierarchy: stock → sector → root.
    Size = market_cap, Color = pct_change.
    """
    if not heatmap_data:
        return ""

    nodes = heatmap_data.get("nodes", [])
    if not nodes:
        return ""

    ids = ["root"]
    labels = ["研究池"]
    parents = [""]
    values = [0]
    colors = ["#E0E0DC"]
    texts = [""]
    customdata = [""]
    seen_sectors = set()
    _used_ids = {"root"}

    # First pass: collect unique sectors
    for n in nodes:
        sector = str(n.get("sector", "其他") or "其他")
        if sector not in seen_sectors:
            seen_sectors.add(sector)
            sec_id = f"sec:{sector}"
            ids.append(sec_id)
            labels.append(sector)
            parents.append("root")
            values.append(0)
            colors.append("#BCBCB8")
            texts.append(sector)
            customdata.append(f"<b>{_esc(sector)}</b>")

    # Second pass: add stocks
    for n in nodes:
        name = str(n.get("name", n.get("ticker", "")))
        ticker = str(n.get("ticker", ""))
        sector = str(n.get("sector", "其他") or "其他")
        pct = float(n.get("pct_change", 0) or 0)
        cap = float(n.get("market_cap", 0) or n.get("size_score", 1) or 1)
        action = str(n.get("action", "HOLD")).upper()
        conf = float(n.get("confidence", 0) or 0)

        st_id = f"st:{name}@{sector}"
        if st_id in _used_ids:
            i = 2
            while f"{st_id}#{i}" in _used_ids:
                i += 1
            st_id = f"{st_id}#{i}"
        _used_ids.add(st_id)

        ids.append(st_id)
        labels.append(name)
        parents.append(f"sec:{sector}")
        values.append(max(cap, 0.01))
        colors.append(_pct_to_hex(pct))
        sign = "+" if pct > 0 else ""
        texts.append(f"{name}<br>{sign}{pct:.1f}%")

        action_labels = {"BUY": "建议关注", "SELL": "建议回避", "HOLD": "维持观察", "VETO": "风控否决"}
        hover_parts = [
            f"<b>{_esc(name)}</b> ({_esc(ticker)})",
            f"涨跌幅: {sign}{pct:.2f}%",
            f"信号: {action_labels.get(action, action)}",
        ]
        if conf > 0:
            hover_parts.append(f"置信度: {conf:.0%}")
        hover_parts.append(f"板块: {_esc(sector)}")
        customdata.append("<br>".join(hover_parts))

    # Sector values = sum of children; root = sum of sectors
    for i, pid in enumerate(parents):
        if pid.startswith("sec:"):
            # Find sector index and add to its value
            for j, sid in enumerate(ids):
                if sid == pid:
                    values[j] += values[i]
                    break
    values[0] = sum(values[i] for i, p in enumerate(parents) if p == "root")

    data = {
        "ids": ids, "labels": labels, "parents": parents,
        "values": values, "colors": colors, "texts": texts,
        "customdata": customdata,
    }
    return _render_inline_treemap(div_id, data, max_depth=1, height=480)


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

        # Strength tag
        if pct > 1.0:
            tag = '<span class="idx-tag strong">\u5f3a\u52bf\u9886\u6da8</span>'
        elif pct > 0:
            tag = '<span class="idx-tag strong">\u5c0f\u5e45\u8d70\u5f3a</span>'
        elif pct > -1.0:
            tag = '<span class="idx-tag weak">\u5c0f\u5e45\u8d70\u5f31</span>'
        else:
            tag = '<span class="idx-tag weak">\u663e\u8457\u627f\u538b</span>'

        cards += f"""
        <div class="idx-battle-card mkt-glass mkt-anim mkt-d1">
          <div class="idx-name">{_esc(name)}</div>
          <div class="idx-close">{close_val:.2f}</div>
          <div class="idx-pct {pct_cls}">{sign}{pct:.2f}%</div>
          {tag}
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
        <span class="bar-label left">\u2191 {view.advance_count}</span>
        <span class="bar-label right">{view.decline_count} \u2193</span>
      </div>
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
        <div class="mkt-sec-sub">{_esc(emotion_label)}</div>
      </div>
      <div class="thermo-track">
        <div class="thermo-needle" style="left:{emotion}%"></div>
      </div>
      <div class="thermo-labels">
        <span>\u6050\u614c</span>
        <span>\u4e2d\u6027</span>
        <span>\u4e50\u89c2</span>
      </div>
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
        # Adaptive fallback: synthesize sector tiles from LLM momentum data
        synth_sectors = []
        for m in view.sector_momentum:
            if isinstance(m, dict):
                flow = 0.0
                try:
                    flow = float(m.get("flow", 0))
                except (ValueError, TypeError):
                    pass
                # flow already carries sign (-4.1 for outflow)
                synth_sectors.append({
                    "sector": m.get("name", ""),
                    "pct_change": flow,
                    "total_turnover_yi": abs(flow) * 10,
                })
        if synth_sectors:
            treemap_html = _render_plotly_sector_treemap(
                synth_sectors, sector_stocks=view.sector_stocks)

    # Right sidebar: leaders + avoid + rotation phase + attribution
    leaders_html = ""
    for s in view.sector_leaders[:5]:
        leaders_html += f'<div class="sector-item"><span class="si-name">{_esc(s)}</span><span class="si-pct up">\u4e3b\u7ebf</span></div>'
    avoids_html = ""
    for s in view.avoid_sectors[:3]:
        avoids_html += f'<div class="sector-item"><span class="si-name">{_esc(s)}</span><span class="si-pct dn">\u9000\u6f6e</span></div>'

    # Momentum flows
    momentum_html = ""
    for m in view.sector_momentum[:5]:
        if isinstance(m, dict):
            nm = m.get("name", "")
            flow = m.get("flow", "")
            direction = m.get("direction", "")
            cls = "up" if direction == "in" else ("dn" if direction == "out" else "")
            arrow = "\u2191" if direction == "in" else ("\u2193" if direction == "out" else "")
            momentum_html += f'<div class="sector-item"><span class="si-name">{_esc(nm)}</span><span class="si-flow">{_esc(flow)}</span><span class="si-pct {cls}">{arrow}</span></div>'

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

        attr_html = f"""
      <div style="margin-top:1rem">
        <div class="mkt-sec-head">
          <div class="mkt-sec-title">\u6da8\u505c\u677f\u5757\u5f52\u5c5e</div>
          <div class="mkt-sec-sub">\u6743\u91cd\u5e26\u52a8 vs \u9898\u6750\u6269\u6563</div>
        </div>
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
        <div class="mkt-sec-sub">\u70ed\u529b\u56fe \u00b7 \u9886\u6da8/\u9000\u6f6e \u00b7 \u8d44\u91d1\u6d41\u5411</div>
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
        levels = sorted(consec.items(), key=lambda x: int(x[0]))
        level_labels = {1: "\u9996\u677f", 2: "\u4e8c\u8fde\u677f", 3: "\u4e09\u8fde\u677f", 4: "\u56db\u8fde\u677f",
                        5: "\u4e94\u8fde\u677f", 6: "\u516d\u8fde\u677f", 7: "\u4e03\u8fde\u677f", 8: "\u516b\u8fde\u677f"}
        # Build JSON data for JS
        ladder_data = []
        prev_count = 0
        for level_str, stocks in levels:
            level = int(level_str)
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
        ladder_json = _json.dumps(ladder_data, ensure_ascii=False)

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
        <div>{_BRAND_LOGO_SM} TradingAgents \u00b7 \u5e02\u573a\u6307\u6325\u53f0</div>
        <div>\u4ea4\u6613\u65e5 {_esc(view.trade_date)} \u00b7 v0.2.0</div>
      </div>
    </div>"""

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
        market_snapshot: Optional MarketSnapshot instance.
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
