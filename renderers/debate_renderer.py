"""
AI Investment Committee — Neon-themed HTML renderer.

6 sections:
1. Hero + Committee Roster
2. Multi-round Debate Timeline
3. Bull/Bear Arena (confrontation panel)
4. Controversy Focus Points
5. Final Verdict Card
6. Audit Trail Summary

All CSS/JS inline — self-contained HTML for static export.
Consumes DebateView from debate_view.py, never raw traces.
"""

from typing import Optional

from .debate_view import (
    DebateView, ParticipantView, ClaimView,
    TimelineEntry, DebateRound, VerdictView,
)
from .decision_labels import safe_badge_class, AI_DISCLAIMER_BANNER
from .shared_css import _BASE_CSS
from .shared_utils import _esc


# ── CSS ───────────────────────────────────────────────────────────────

_DEBATE_CSS = """
/* ── Debate-specific additions (base theme from shared_css._BASE_CSS) ── */
:root {
  --glow-green: rgba(52, 211, 153, 0.15);
  --glow-red: rgba(248, 113, 113, 0.15);
  --glow-blue: rgba(96, 165, 250, 0.12);
  --glow-yellow: rgba(251, 191, 36, 0.12);
  --glow-purple: rgba(167, 139, 250, 0.12);
}
.debate-shell { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 1.5rem; display: grid; gap: 1.25rem; }

/* ── Glass glow variants (debate-specific --glow-* vars) ── */
.glass-glow-green { box-shadow: 0 0 20px var(--glow-green), inset 0 1px 0 rgba(52,211,153,.06); }
.glass-glow-red   { box-shadow: 0 0 20px var(--glow-red),   inset 0 1px 0 rgba(248,113,113,.06); }
.glass-glow-blue  { box-shadow: 0 0 20px var(--glow-blue),  inset 0 1px 0 rgba(96,165,250,.06); }
.glass-glow-yellow { box-shadow: 0 0 20px var(--glow-yellow), inset 0 1px 0 rgba(251,191,36,.06); }

/* ─────────── Section 1: Hero + Roster ─────────── */
.debate-hero {
  position: relative; overflow: hidden;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(10,14,26,.96), rgba(14,24,42,.92));
  border: 1px solid rgba(96,165,250,.1);
  padding: 2rem 2.2rem;
  box-shadow: 0 12px 40px rgba(0,0,0,.3);
}
.debate-hero::after {
  content: ""; position: absolute;
  width: 300px; height: 300px; border-radius: 50%;
  top: -30%; right: -5%;
  background: radial-gradient(circle, rgba(96,165,250,.08), transparent 60%);
  pointer-events: none;
}
.hero-eyebrow {
  text-transform: uppercase; letter-spacing: .18em;
  font-size: .72rem; color: var(--blue); margin-bottom: .5rem;
}
.debate-hero h1 {
  font-size: clamp(1.8rem, 3.5vw, 2.6rem);
  letter-spacing: -.03em; line-height: 1.15; margin-bottom: .3rem;
  background: linear-gradient(135deg, #fff 30%, var(--blue));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-verdict {
  display: inline-flex; align-items: center; gap: .5rem;
  margin-top: .6rem; padding: .4rem 1rem; border-radius: 20px;
  font-size: .9rem; font-weight: 700;
}
.hero-verdict.buy  { color: var(--green); background: rgba(52,211,153,.1); border: 1px solid rgba(52,211,153,.25); }
.hero-verdict.hold { color: var(--yellow); background: rgba(251,191,36,.1); border: 1px solid rgba(251,191,36,.25); }
.hero-verdict.sell { color: var(--red); background: rgba(248,113,113,.1); border: 1px solid rgba(248,113,113,.25); }
.hero-verdict.veto { color: var(--red); background: rgba(248,113,113,.15); border: 1px solid rgba(248,113,113,.35); }
.hero-meta { color: var(--muted); font-size: .82rem; margin-top: .6rem; }

/* Roster grid */
.roster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(155px, 1fr));
  gap: .6rem; margin-top: .8rem;
}
.roster-card {
  background: rgba(255,255,255,.02);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 12px; padding: .65rem .8rem;
  text-align: center;
  transition: transform 200ms ease, border-color 200ms ease, box-shadow 200ms ease, background 200ms ease;
}
.roster-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96,165,250,.22);
  box-shadow: 0 6px 18px rgba(0,0,0,.2);
  background: rgba(255,255,255,.035);
}
.roster-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  margin: 0 auto .4rem; display: flex; align-items: center;
  justify-content: center; font-size: 1rem;
  border: 2px solid var(--border);
}
.roster-avatar.stance-bull { border-color: var(--green); background: rgba(52,211,153,.08); }
.roster-avatar.stance-bear { border-color: var(--red); background: rgba(248,113,113,.08); }
.roster-avatar.stance-neutral { border-color: var(--blue); background: rgba(96,165,250,.08); }
.roster-avatar.stance-cautious { border-color: var(--yellow); background: rgba(251,191,36,.08); }
.roster-name { font-size: .82rem; font-weight: 600; color: var(--white); }
.roster-role { font-size: .68rem; color: var(--muted); }
.roster-stance {
  display: inline-block; margin-top: .3rem;
  padding: 1px 8px; border-radius: 10px;
  font-size: .65rem; font-weight: 600;
}
.stance-bull   { color: var(--green); background: rgba(52,211,153,.1); }
.stance-bear   { color: var(--red);   background: rgba(248,113,113,.1); }
.stance-neutral { color: var(--blue); background: rgba(96,165,250,.1); }
.stance-cautious { color: var(--yellow); background: rgba(251,191,36,.1); }

/* Phase group label */
.roster-phase-label {
  grid-column: 1 / -1;
  font-size: .72rem; color: var(--blue); font-weight: 600;
  padding: .3rem 0; border-bottom: 1px solid rgba(96,165,250,.08);
  letter-spacing: .1em; text-transform: uppercase;
  margin-top: .3rem;
}

/* ─────────── Section 2: Timeline ─────────── */
.debate-timeline { position: relative; padding-left: 30px; }
.timeline-spine {
  position: absolute; left: 13px; top: 0; bottom: 0;
  width: 2px; background: linear-gradient(180deg, var(--blue), var(--green), var(--yellow), var(--red), var(--blue));
  border-radius: 1px;
}
.tl-phase {
  position: relative; margin-bottom: 1.2rem;
}
.tl-phase-dot {
  position: absolute; left: -24px; top: .2rem;
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--bg); border: 2px solid var(--blue);
  z-index: 2; transition: box-shadow 300ms ease;
}
.tl-phase:hover .tl-phase-dot {
  box-shadow: 0 0 10px currentColor;
}
.tl-phase.phase-initial .tl-phase-dot  { border-color: var(--blue); }
.tl-phase.phase-debate  .tl-phase-dot  { border-color: var(--green); }
.tl-phase.phase-scenario .tl-phase-dot { border-color: var(--yellow); }
.tl-phase.phase-risk    .tl-phase-dot  { border-color: var(--red); }
.tl-phase.phase-verdict .tl-phase-dot  { border-color: var(--blue); background: var(--blue); }

.tl-phase-label {
  font-size: .85rem; font-weight: 700; color: var(--white);
  margin-bottom: .5rem;
}
.tl-phase-en { color: var(--muted); font-size: .72rem; margin-left: .4rem; }
.tl-entry {
  display: flex; gap: .7rem; padding: .5rem .4rem;
  border-bottom: 1px solid rgba(255,255,255,.03);
  border-radius: 8px; transition: background 200ms ease;
}
.tl-entry:hover { background: rgba(255,255,255,.015); }
.tl-entry:last-child { border-bottom: none; }
.tl-entry-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: .75rem; flex-shrink: 0;
  border: 1.5px solid var(--border); margin-top: .15rem;
}
.tl-entry-body { flex: 1; min-width: 0; }
.tl-speaker {
  font-size: .78rem; font-weight: 600; color: var(--fg);
}
.tl-speaker .stance-tag {
  display: inline-block; padding: 0 6px; border-radius: 8px;
  font-size: .62rem; font-weight: 600; margin-left: .3rem;
  vertical-align: middle;
}
.tl-summary {
  font-size: .82rem; color: var(--fg); margin-top: .15rem;
  line-height: 1.55;
}
.tl-evidence {
  margin-top: .25rem; display: flex; gap: .3rem; flex-wrap: wrap;
}
.ev-chip {
  display: inline-block; padding: 0 6px; border-radius: 4px;
  font-size: .62rem; font-weight: 600;
  color: var(--muted); background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.06);
}

/* ─────────── Section 3: Bull/Bear Arena ─────────── */
.arena-wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 700px) { .arena-wrap { grid-template-columns: 1fr; } }

.arena-side { padding: .5rem 0; }
.arena-side-label {
  font-size: .9rem; font-weight: 700; margin-bottom: .6rem;
  display: flex; align-items: center; gap: .4rem;
}
.arena-bull .arena-side-label { color: var(--green); }
.arena-bear .arena-side-label { color: var(--red); }

/* Strength bar */
.strength-bar-wrap { margin-bottom: 1rem; }
.strength-bar-labels {
  display: flex; justify-content: space-between;
  font-size: .72rem; margin-bottom: .3rem;
}
.strength-bar-labels .bull-label { color: var(--green); }
.strength-bar-labels .bear-label { color: var(--red); }
.strength-bar {
  display: flex; height: 8px; border-radius: 4px;
  overflow: hidden; background: rgba(255,255,255,.06);
}
.strength-bull { background: linear-gradient(90deg, rgba(52,211,153,.3), var(--green)); border-radius: 4px 0 0 4px; }
.strength-bear { background: linear-gradient(90deg, var(--red), rgba(248,113,113,.3)); border-radius: 0 4px 4px 0; }
.strength-pct {
  text-align: center; font-size: .72rem; font-weight: 700;
  margin-top: .2rem;
}

/* Claim cards */
.claim-card {
  background: rgba(255,255,255,.02);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px; padding: .7rem .9rem;
  margin-bottom: .6rem; transition: border-color .2s;
}
.claim-card:hover { border-color: rgba(96,165,250,.15); }
.arena-bull .claim-card { border-left: 3px solid rgba(52,211,153,.3); }
.arena-bear .claim-card { border-left: 3px solid rgba(248,113,113,.3); }
.claim-dim {
  font-size: .65rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; margin-bottom: .2rem;
}
.arena-bull .claim-dim { color: var(--green); }
.arena-bear .claim-dim { color: var(--red); }
.claim-text { font-size: .82rem; color: var(--fg); line-height: 1.5; }
.claim-meta {
  display: flex; align-items: center; gap: .6rem;
  margin-top: .4rem; font-size: .68rem; color: var(--muted);
}
.claim-conf-bar {
  flex: 1; max-width: 100px; height: 4px;
  background: rgba(255,255,255,.06); border-radius: 2px;
}
.claim-conf-fill { height: 100%; border-radius: 2px; }
.arena-bull .claim-conf-fill { background: var(--green); }
.arena-bear .claim-conf-fill { background: var(--red); }
.claim-invalidation {
  font-size: .68rem; color: var(--yellow);
  margin-top: .3rem; padding-left: .5rem;
  border-left: 2px solid rgba(251,191,36,.2);
}

/* ─────────── Section 4: Controversy ─────────── */
.controversy-list { display: grid; gap: .6rem; }
.controversy-item {
  display: flex; align-items: flex-start; gap: .6rem;
  padding: .6rem .8rem;
  background: rgba(251,191,36,.03);
  border: 1px solid rgba(251,191,36,.1);
  border-radius: 10px;
}
.controversy-icon {
  flex-shrink: 0; width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  font-size: .85rem; color: var(--yellow);
}
.controversy-text { font-size: .82rem; color: var(--fg); line-height: 1.5; }

/* ─────────── Section 5: Verdict Card ─────────── */
.verdict-card {
  position: relative; overflow: hidden;
  border-radius: 16px; padding: 1.5rem 1.8rem;
}
.verdict-card.buy {
  background: linear-gradient(135deg, rgba(52,211,153,.06), rgba(96,165,250,.04));
  border: 1px solid rgba(52,211,153,.2);
}
.verdict-card.hold {
  background: linear-gradient(135deg, rgba(251,191,36,.06), rgba(96,165,250,.04));
  border: 1px solid rgba(251,191,36,.2);
}
.verdict-card.sell, .verdict-card.veto {
  background: linear-gradient(135deg, rgba(248,113,113,.06), rgba(96,165,250,.04));
  border: 1px solid rgba(248,113,113,.2);
}
.verdict-action {
  display: inline-flex; align-items: center; gap: .4rem;
  font-size: 1.4rem; font-weight: 800;
}
.verdict-action.buy  { color: var(--green); }
.verdict-action.hold { color: var(--yellow); }
.verdict-action.sell, .verdict-action.veto { color: var(--red); }
.verdict-reason {
  font-size: .92rem; color: var(--fg); margin-top: .5rem;
  line-height: 1.6; max-width: 700px;
}
.verdict-kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: .8rem; margin-top: 1rem;
}
.verdict-kpi {
  text-align: center; padding: .7rem .5rem;
  background: rgba(255,255,255,.02);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px;
}
.verdict-kpi .vk-val {
  font-size: 1.5rem; font-weight: 700;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}
.verdict-kpi .vk-label { font-size: .7rem; color: var(--muted); margin-top: .15rem; }
.verdict-kpi.buy .vk-val  { color: var(--green); }
.verdict-kpi.hold .vk-val { color: var(--yellow); }
.verdict-kpi.sell .vk-val, .verdict-kpi.veto .vk-val { color: var(--red); }
.verdict-kpi.risk-ok .vk-val  { color: var(--green); }
.verdict-kpi.risk-warn .vk-val { color: var(--yellow); }
.verdict-kpi.risk-bad .vk-val  { color: var(--red); }

.verdict-conditions {
  display: grid; grid-template-columns: 1fr 1fr; gap: .8rem;
  margin-top: 1rem;
}
@media (max-width: 600px) { .verdict-conditions { grid-template-columns: 1fr; } }
.vc-box {
  padding: .7rem .9rem; border-radius: 10px;
  font-size: .82rem; line-height: 1.5;
}
.vc-box.trigger {
  background: rgba(52,211,153,.04);
  border: 1px solid rgba(52,211,153,.12);
}
.vc-box.invalidator {
  background: rgba(248,113,113,.04);
  border: 1px solid rgba(248,113,113,.12);
}
.vc-label { font-size: .68rem; font-weight: 700; margin-bottom: .25rem; }
.vc-box.trigger .vc-label { color: var(--green); }
.vc-box.invalidator .vc-label { color: var(--red); }

.verdict-flags {
  display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .8rem;
}
.risk-flag {
  display: inline-flex; align-items: center; gap: .25rem;
  padding: .2rem .6rem; border-radius: 8px;
  font-size: .7rem; font-weight: 600;
}
.risk-flag.medium { color: var(--yellow); background: rgba(251,191,36,.08); border: 1px solid rgba(251,191,36,.15); }
.risk-flag.low    { color: var(--muted); background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); }
.risk-flag.high   { color: var(--red); background: rgba(248,113,113,.08); border: 1px solid rgba(248,113,113,.15); }

/* ─────────── Section 6: Audit ─────────── */
.audit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: .6rem;
}
.audit-cell {
  text-align: center; padding: .7rem .5rem;
  background: rgba(255,255,255,.02);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px;
}
.audit-cell .av {
  font-size: 1.3rem; font-weight: 700;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}
.audit-cell .al { font-size: .68rem; color: var(--muted); margin-top: .15rem; }
.audit-cell.good .av { color: var(--green); }
.audit-cell.warn .av { color: var(--yellow); }
.audit-cell.bad .av  { color: var(--red); }
.audit-cell.info .av { color: var(--blue); }

/* ─────────── AI disclaimer ─────────── */
.ai-banner {
  background: rgba(251,191,36,.04);
  border: 1px solid rgba(251,191,36,.15);
  border-radius: 10px; padding: .6rem 1rem;
  font-size: .75rem; color: var(--yellow);
  text-align: center;
}

/* Footer */
.debate-footer {
  text-align: center; color: var(--muted); font-size: .72rem;
  padding: .8rem 0 .5rem; border-top: 1px solid rgba(255,255,255,.04);
  letter-spacing: .04em;
  background: linear-gradient(180deg, transparent, rgba(255,255,255,0.008));
}

/* ─────────── Market Wind Banner ─────────── */
.market-wind-card {
  display: flex; align-items: center; gap: 1rem;
  padding: .8rem 1.2rem; border-radius: 12px;
}
.market-wind-card.wind-tailwind {
  background: rgba(52,211,153,.06); border: 1px solid rgba(52,211,153,.18);
}
.market-wind-card.wind-headwind {
  background: rgba(248,113,113,.06); border: 1px solid rgba(248,113,113,.18);
}
.market-wind-card.wind-neutral {
  background: rgba(96,165,250,.04); border: 1px solid rgba(96,165,250,.12);
}
.wind-icon { font-size: 1.5rem; flex-shrink: 0; }
.wind-body { flex: 1; min-width: 0; }
.wind-title { font-size: .85rem; font-weight: 700; }
.wind-tailwind .wind-title { color: var(--green); }
.wind-headwind .wind-title { color: var(--red); }
.wind-neutral .wind-title { color: var(--blue); }
.wind-detail { font-size: .78rem; color: var(--fg); margin-top: .15rem; }
.wind-chips { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .35rem; }
.wind-chip {
  display: inline-block; padding: 1px 8px; border-radius: 8px;
  font-size: .65rem; font-weight: 600;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
  color: var(--muted);
}
.wind-chip.leader { color: var(--green); border-color: rgba(52,211,153,.15); }
.wind-chip.avoid { color: var(--red); border-color: rgba(248,113,113,.15); }

/* ─────────── Reveal animation ─────────── */
.glass, .debate-hero { animation: db-rise 480ms ease both; }
.debate-shell > :nth-child(2) { animation-delay: 60ms; }
.debate-shell > :nth-child(3) { animation-delay: 120ms; }
.debate-shell > :nth-child(4) { animation-delay: 180ms; }
.debate-shell > :nth-child(5) { animation-delay: 240ms; }
.debate-shell > :nth-child(6) { animation-delay: 300ms; }
@keyframes db-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ─────────── Responsive ─────────── */
@media (max-width: 700px) {
  .glass, .debate-hero { animation: none !important; }
  .debate-shell { padding: .8rem; gap: 1rem; }
  .debate-hero { padding: 1.2rem; border-radius: 14px; }
  .debate-hero h1 { font-size: 1.5rem; }
  .hero-eyebrow { font-size: .68rem; }
  .hero-meta { font-size: .78rem; }
  .roster-grid { grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: .5rem; }
  .roster-card { padding: .5rem .6rem; min-height: 44px; }
  .roster-name { font-size: .78rem; }
  .roster-role { font-size: .65rem; }
  .roster-stance { font-size: .62rem; padding: 2px 7px; }
  .sec-title { font-size: 1rem; }
  .arena-wrap { grid-template-columns: 1fr; gap: .75rem; }
  .arena-claim { padding: .6rem .8rem; font-size: .82rem; }
  .verdict-card { padding: 1rem; border-radius: 14px; }
  .verdict-conditions { grid-template-columns: 1fr; gap: .6rem; }
  .vc-box { padding: .6rem .75rem; font-size: .8rem; }
  .glass { padding: 1rem; border-radius: 12px; }
  .debate-timeline { padding-left: 24px; }
  .tl-phase-label { font-size: .78rem; }
  .tl-entry { font-size: .82rem; }
  .debate-footer { font-size: .72rem; }
}
@supports (padding: env(safe-area-inset-left)) {
  @media (max-width: 700px) {
    .debate-shell {
      padding-left: max(.8rem, env(safe-area-inset-left));
      padding-right: max(.8rem, env(safe-area-inset-right));
      padding-bottom: max(1rem, env(safe-area-inset-bottom));
    }
  }
}

/* ── V5a: Keyboard focus ── */
button:focus-visible, [role="button"]:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

/* ── V5: Touch feedback ── */
@media (hover: none) and (pointer: coarse) {
  .glass:active, .debate-hero:active, .roster-card:active {
    transform: scale(0.97); transition: transform 60ms ease;
  }
}

/* ── S1: Contrast boost ── */
.roster-role, .claim-meta, .sec-sub, .audit-cell .al,
.verdict-kpi .vk-label, .hero-meta { font-weight: 500; }

/* ── S4: Elevation system ── */
.glass, .roster-card, .verdict-kpi, .audit-cell { box-shadow: var(--elev-1); }
.glass:hover { box-shadow: var(--elev-2); }
.debate-hero { box-shadow: var(--elev-3); }

/* ── S5: Unified timing ── */
.glass, .roster-card, .claim-card {
  transition: transform var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out);
}
.glass, .debate-hero { animation: db-rise var(--dur-med) var(--ease-out) both; }

/* ── S3: 8px spacing rhythm ── */
.glass { padding: var(--sp-3); }
.debate-hero { padding: var(--sp-4); }
.debate-shell { gap: var(--sp-3); }

/* ── F2: Radar chart ── */
.radar-wrap { display: flex; justify-content: center; margin: var(--sp-2) 0; }
.radar-wrap svg text { font-size: 10px; fill: #8fa3b8; }

@media print {
  :root{--bg:#fff;--fg:#111;--card:#fff;--border:#ddd;--muted:#666;--white:#111}
  body{background:#fff!important;color:#111!important}
  body::before{display:none}
  .glass,.debate-hero{background:#fff!important;box-shadow:none!important;
    backdrop-filter:none!important;border:1px solid #ddd!important;border-radius:4px!important}
  .glass,.debate-hero{animation:none!important}
  .debate-shell{max-width:100%;padding:0}
  .glass{page-break-inside:avoid}
  h2,.sec-title{color:#333!important}
}
"""


# ── Avatar emoji map ─────────────────────────────────────────────────

_AVATAR_EMOJI = {
    "avatar-fundamental": "\U0001f4ca",  # 📊
    "avatar-technical":   "\U0001f4c8",  # 📈
    "avatar-catalyst":    "\u26a1",      # ⚡
    "avatar-flow":        "\U0001f4b0",  # 💰
    "avatar-bull":        "\U0001f402",  # 🐂
    "avatar-bear":        "\U0001f43b",  # 🐻
    "avatar-aggr":        "\u2694\ufe0f", # ⚔️
    "avatar-cons":        "\U0001f6e1\ufe0f", # 🛡️
    "avatar-neut":        "\u2696\ufe0f", # ⚖️
    "avatar-chair":       "\U0001f451",  # 👑
    "avatar-risk":        "\U0001f6a8",  # 🚨
    "avatar-scenario":    "\U0001f52e",  # 🔮
}

_ACTION_EMOJI = {
    "BUY": "\u2714",   # ✔
    "HOLD": "\u23f8",  # ⏸
    "SELL": "\u2716",  # ✖
    "VETO": "\u26d4",  # ⛔
}


# ── Section renderers ────────────────────────────────────────────────

def _render_hero(v: DebateView) -> str:
    """Section 1: Hero banner + committee roster."""
    action_css = safe_badge_class(v.verdict.action.lower() if v.verdict.action else "hold")
    emoji = _ACTION_EMOJI.get(v.verdict.action, "")

    # Hero
    html = f"""
<div class="debate-hero">
  <div class="hero-eyebrow">AI Investment Committee</div>
  <h1>{_esc(v.ticker_name)} {_esc(v.ticker)}</h1>
  <div class="hero-verdict {action_css}">{emoji} {_esc(v.verdict.action_label)}</div>
  <div class="hero-meta">{_esc(v.trade_date)} &middot; {v.total_rounds} 轮讨论 &middot; {len(v.participants)} 位委员 &middot; 置信度 <span class="mono">{v.verdict.confidence_pct}%</span></div>
</div>
"""

    # Roster — group by phase
    phases_order = ["初判", "辩论", "风控辩论", "裁决", "终审"]
    phase_labels = {
        "初判": "PHASE 1 · 初始研判",
        "辩论": "PHASE 2 · 多空辩论",
        "风控辩论": "PHASE 3 · 风控质疑",
        "裁决": "PHASE 4 · 研究裁决",
        "终审": "PHASE 5 · 终审签署",
    }
    grouped: dict = {}
    for p in v.participants:
        grouped.setdefault(p.phase, []).append(p)

    roster_html = '<div class="glass" style="margin-top:.5rem;">\n'
    roster_html += '  <div class="sec-head"><span class="sec-title">投研委员会成员</span>'
    roster_html += f'<span class="sec-sub">{len(v.participants)} 位委员参与</span></div>\n'
    roster_html += '  <div class="roster-grid">\n'

    for phase in phases_order:
        members = grouped.get(phase, [])
        if not members:
            continue
        label = phase_labels.get(phase, phase)
        roster_html += f'    <div class="roster-phase-label">{_esc(label)}</div>\n'
        for m in members:
            emoji = _AVATAR_EMOJI.get(m.avatar_class, "\U0001f464")
            sc = m.stance_class or "stance-neutral"
            roster_html += f"""    <div class="roster-card">
      <div class="roster-avatar {sc}">{emoji}</div>
      <div class="roster-name">{_esc(m.role_cn)}</div>
      <div class="roster-role">{_esc(m.role_en)}</div>
      <span class="roster-stance {sc}">{_esc(m.stance_label) or '—'}</span>
    </div>
"""

    roster_html += '  </div>\n</div>\n'

    return html + roster_html


def _render_timeline(v: DebateView) -> str:
    """Section 2: Multi-round debate timeline."""
    if not v.rounds:
        return ""

    phase_css_map = {
        "初判": "phase-initial",
        "多空辩论": "phase-debate",
        "场景推演": "phase-scenario",
        "风控质疑": "phase-risk",
        "最终裁决": "phase-verdict",
    }

    html = '<div class="glass">\n'
    html += '  <div class="sec-head"><span class="sec-title">讨论过程</span>'
    html += f'<span class="sec-sub">{v.total_rounds} 轮 &middot; {sum(len(r.entries) for r in v.rounds)} 次发言</span></div>\n'
    html += '  <div class="debate-timeline">\n'
    html += '    <div class="timeline-spine"></div>\n'

    for rd in v.rounds:
        phase_cls = phase_css_map.get(rd.phase_label, "phase-initial")
        html += f'    <div class="tl-phase {phase_cls}">\n'
        html += f'      <div class="tl-phase-dot"></div>\n'
        html += f'      <div class="tl-phase-label">Round {rd.round_number} · {_esc(rd.phase_label)}'
        html += f'<span class="tl-phase-en">{_esc(rd.phase_en)}</span></div>\n'

        for entry in rd.entries:
            emoji = _AVATAR_EMOJI.get(entry.avatar_class, "\U0001f464")
            sc = entry.stance_class or "stance-neutral"
            html += f'      <div class="tl-entry">\n'
            html += f'        <div class="tl-entry-avatar {sc}">{emoji}</div>\n'
            html += f'        <div class="tl-entry-body">\n'
            html += f'          <div class="tl-speaker">{_esc(entry.speaker_cn)}'
            if entry.stance_label:
                html += f' <span class="stance-tag {sc}">{_esc(entry.stance_label)}</span>'
            html += '</div>\n'
            html += f'          <div class="tl-summary">{_esc(entry.summary)}</div>\n'
            if entry.evidence_refs:
                html += '          <div class="tl-evidence">'
                for ev in entry.evidence_refs:
                    html += f'<span class="ev-chip">{_esc(ev)}</span>'
                html += '</div>\n'
            html += '        </div>\n'
            html += '      </div>\n'

        html += '    </div>\n'

    html += '  </div>\n</div>\n'
    return html


def _render_radar_chart(bull_claims: list, bear_claims: list) -> str:
    """SVG 5-axis radar chart comparing bull vs bear argument strength.

    Axes: 技术, 基本面, 催化剂, 资金流, 情绪.
    Each side's score per axis = avg confidence of claims mapped to that axis.
    """
    import math

    axes = ["技术", "基本面", "催化剂", "资金流", "情绪"]
    # Mapping from dimension strings to canonical axes
    dim_map = {
        "技术": "技术", "技术面": "技术", "技术分析": "技术",
        "基本面": "基本面", "财务": "基本面", "估值": "基本面", "盈利": "基本面",
        "催化剂": "催化剂", "事件": "催化剂", "政策": "催化剂", "消息": "催化剂",
        "资金流": "资金流", "资金": "资金流", "主力": "资金流", "北向": "资金流",
        "情绪": "情绪", "市场情绪": "情绪", "舆情": "情绪", "人气": "情绪",
    }

    def _aggregate(claims):
        totals = {a: [] for a in axes}
        for c in claims:
            mapped = dim_map.get(c.dimension, "")
            if not mapped:
                # Distribute unmapped claims evenly
                for a in axes:
                    totals[a].append(c.confidence)
            else:
                totals[mapped].append(c.confidence)
        return [sum(v) / len(v) if v else 0.0 for v in (totals[a] for a in axes)]

    bull_vals = _aggregate(bull_claims)
    bear_vals = _aggregate(bear_claims)

    # Skip if both sides are all zeros
    if all(v == 0 for v in bull_vals) and all(v == 0 for v in bear_vals):
        return ""

    cx, cy, r = 100, 100, 75
    n = len(axes)

    def _vertex(i, scale):
        angle = math.radians(-90 + i * 360 / n)
        return cx + r * scale * math.cos(angle), cy + r * scale * math.sin(angle)

    # Build SVG
    svg = f'<div class="radar-wrap"><svg viewBox="0 0 200 200" width="200" height="200">\n'

    # Concentric pentagons (grid)
    for level in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{_vertex(i, level)[0]:.1f},{_vertex(i, level)[1]:.1f}" for i in range(n))
        svg += f'  <polygon points="{pts}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="0.5"/>\n'

    # Axis lines
    for i in range(n):
        vx, vy = _vertex(i, 1.0)
        svg += f'  <line x1="{cx}" y1="{cy}" x2="{vx:.1f}" y2="{vy:.1f}" stroke="rgba(255,255,255,0.1)" stroke-width="0.5"/>\n'

    # Bull polygon (green)
    bull_pts = " ".join(f"{_vertex(i, max(0.05, v))[0]:.1f},{_vertex(i, max(0.05, v))[1]:.1f}" for i, v in enumerate(bull_vals))
    svg += f'  <polygon points="{bull_pts}" fill="rgba(52,211,153,0.2)" stroke="#34d399" stroke-width="1.5"/>\n'

    # Bear polygon (red)
    bear_pts = " ".join(f"{_vertex(i, max(0.05, v))[0]:.1f},{_vertex(i, max(0.05, v))[1]:.1f}" for i, v in enumerate(bear_vals))
    svg += f'  <polygon points="{bear_pts}" fill="rgba(248,113,113,0.2)" stroke="#f87171" stroke-width="1.5"/>\n'

    # Axis labels
    for i, label in enumerate(axes):
        lx, ly = _vertex(i, 1.2)
        anchor = "middle"
        if lx < cx - 10:
            anchor = "end"
        elif lx > cx + 10:
            anchor = "start"
        svg += f'  <text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" dominant-baseline="central">{label}</text>\n'

    # Legend
    svg += '  <line x1="10" y1="190" x2="22" y2="190" stroke="#34d399" stroke-width="2"/>\n'
    svg += '  <text x="25" y="190" dominant-baseline="central" font-size="9" fill="#8fa3b8">看多</text>\n'
    svg += '  <line x1="55" y1="190" x2="67" y2="190" stroke="#f87171" stroke-width="2"/>\n'
    svg += '  <text x="70" y="190" dominant-baseline="central" font-size="9" fill="#8fa3b8">看空</text>\n'

    svg += '</svg></div>\n'
    return svg


def _render_arena(v: DebateView) -> str:
    """Section 3: Bull/Bear confrontation arena."""
    if not v.bull_claims and not v.bear_claims:
        return ""

    bull_pct = int(v.bull_ratio)
    bear_pct = 100 - bull_pct

    html = '<div class="glass">\n'
    html += '  <div class="sec-head"><span class="sec-title">多空对抗</span>'
    html += f'<span class="sec-sub">Bull vs Bear Arena</span></div>\n'

    # Strength bar
    html += '  <div class="strength-bar-wrap">\n'
    html += '    <div class="strength-bar-labels">'
    html += f'<span class="bull-label">看多 {v.bull_score:.1f}</span>'
    html += f'<span class="bear-label">看空 {v.bear_score:.1f}</span>'
    html += '</div>\n'
    html += f'    <div class="strength-bar"><div class="strength-bull" style="width:{bull_pct}%"></div>'
    html += f'<div class="strength-bear" style="width:{bear_pct}%"></div></div>\n'
    html += f'    <div class="strength-pct" style="color:{"var(--green)" if bull_pct > 55 else "var(--red)" if bull_pct < 45 else "var(--yellow)"}">'
    html += f'{bull_pct}% : {bear_pct}%</div>\n'
    html += '  </div>\n'

    # Radar chart
    radar = _render_radar_chart(v.bull_claims, v.bear_claims)
    if radar:
        html += radar

    # Two columns
    html += '  <div class="arena-wrap">\n'

    # Bull side
    html += '    <div class="arena-side arena-bull">\n'
    html += f'      <div class="arena-side-label">\U0001f402 看多论据 ({len(v.bull_claims)})</div>\n'
    for c in v.bull_claims:
        html += _render_claim_card(c, "bull")
    html += '    </div>\n'

    # Bear side
    html += '    <div class="arena-side arena-bear">\n'
    html += f'      <div class="arena-side-label">\U0001f43b 看空论据 ({len(v.bear_claims)})</div>\n'
    for c in v.bear_claims:
        html += _render_claim_card(c, "bear")
    html += '    </div>\n'

    html += '  </div>\n</div>\n'
    return html


def _render_claim_card(c: ClaimView, side: str) -> str:
    """Render a single claim card."""
    conf_pct = int(c.confidence * 100)
    html = '      <div class="claim-card">\n'
    if c.dimension:
        html += f'        <div class="claim-dim">{_esc(c.dimension)}</div>\n'
    html += f'        <div class="claim-text">{_esc(c.text)}</div>\n'
    html += f'        <div class="claim-meta">\n'
    html += f'          <span class="mono">{conf_pct}%</span>\n'
    html += f'          <div class="claim-conf-bar"><div class="claim-conf-fill" style="width:{conf_pct}%"></div></div>\n'
    if c.evidence_tags:
        for ev in c.evidence_tags:
            html += f'          <span class="ev-chip">{_esc(ev)}</span>\n'
    html += f'        </div>\n'
    if c.invalidation:
        html += f'        <div class="claim-invalidation">失效条件: {_esc(c.invalidation)}</div>\n'
    html += '      </div>\n'
    return html


def _render_controversies(v: DebateView) -> str:
    """Section 4: Controversy focus points."""
    if not v.controversies:
        return ""

    html = '<div class="glass glass-glow-yellow">\n'
    html += '  <div class="sec-head"><span class="sec-title">分歧焦点</span>'
    html += f'<span class="sec-sub">{len(v.controversies)} 个争议点</span></div>\n'
    html += '  <div class="controversy-list">\n'

    for i, text in enumerate(v.controversies, 1):
        html += f"""    <div class="controversy-item">
      <div class="controversy-icon">\u26a0\ufe0f</div>
      <div class="controversy-text">{_esc(text)}</div>
    </div>
"""

    html += '  </div>\n</div>\n'
    return html


def _render_verdict(v: DebateView) -> str:
    """Section 5: Final verdict card."""
    vd = v.verdict
    action_css = safe_badge_class(vd.action.lower() if vd.action else "hold")
    emoji = _ACTION_EMOJI.get(vd.action, "")

    risk_css = "risk-ok" if vd.risk_score is not None and vd.risk_score <= 3 else "risk-warn" if vd.risk_score is not None and vd.risk_score <= 6 else "risk-bad"

    html = f'<div class="verdict-card {action_css}">\n'
    html += f'  <div class="sec-head"><span class="sec-title">投委会裁决</span></div>\n'
    html += f'  <div class="verdict-action {action_css}">{emoji} {_esc(vd.action_label)}</div>\n'
    if vd.core_reason:
        html += f'  <div class="verdict-reason">{_esc(vd.core_reason)}</div>\n'

    # KPI row
    html += '  <div class="verdict-kpi-row">\n'
    html += f'    <div class="verdict-kpi {action_css}"><div class="vk-val">{vd.confidence_pct}%</div><div class="vk-label">置信度</div></div>\n'
    html += f'    <div class="verdict-kpi"><div class="vk-val" style="color:var(--white)">{_esc(vd.position_label)}</div><div class="vk-label">建议仓位</div></div>\n'
    html += f'    <div class="verdict-kpi {risk_css}"><div class="vk-val">{vd.risk_score}/10</div><div class="vk-label">风险评分</div></div>\n'
    cleared_text = "通过" if vd.risk_cleared else "否决"
    cleared_css = "risk-ok" if vd.risk_cleared else "risk-bad"
    html += f'    <div class="verdict-kpi {cleared_css}"><div class="vk-val">{cleared_text}</div><div class="vk-label">风控审核</div></div>\n'
    html += '  </div>\n'

    # Trigger + invalidation
    if vd.trigger or vd.invalidator:
        html += '  <div class="verdict-conditions">\n'
        if vd.trigger:
            html += f'    <div class="vc-box trigger"><div class="vc-label">确认买入信号</div>{_esc(vd.trigger)}</div>\n'
        if vd.invalidator:
            html += f'    <div class="vc-box invalidator"><div class="vc-label">失效 / 止损条件</div>{_esc(vd.invalidator)}</div>\n'
        html += '  </div>\n'

    # Risk flags
    VALID_SEV = {"high", "medium", "low"}
    if vd.risk_flags:
        html += '  <div class="verdict-flags">\n'
        for fl in vd.risk_flags:
            sev = fl.get("severity", "medium")
            sev = sev if sev in VALID_SEV else "medium"
            cat = fl.get("category", "") or "未分类"
            desc = fl.get("description", "")
            html += f'    <span class="risk-flag {sev}" title="{_esc(desc)}" aria-label="{_esc(cat)}: {_esc(desc)}">{_esc(cat)}</span>\n'
        html += '  </div>\n'

    html += '</div>\n'
    return html


def _render_audit(v: DebateView) -> str:
    """Section 6: Audit trail summary."""
    conflict_css = "bad" if v.conflict_level == "high" else "warn" if v.conflict_level == "medium" else "good"
    consensus_css = "good" if v.consensus_level == "high" else "warn" if v.consensus_level == "medium" else "bad"

    html = '<div class="glass">\n'
    html += '  <div class="sec-head"><span class="sec-title">审计摘要</span>'
    html += '<span class="sec-sub">Audit Trail</span></div>\n'
    html += '  <div class="audit-grid">\n'

    cells = [
        (str(v.total_rounds), "讨论轮次", "info"),
        (str(sum(len(r.entries) for r in v.rounds)), "发言次数", "info"),
        (str(len(v.bull_claims) + len(v.bear_claims)), "论据总数", "info"),
        (str(v.total_evidence), "证据引用", "info"),
        (v.conflict_label, "分歧水平", conflict_css),
        (v.consensus_label, "收敛状态", consensus_css),
    ]

    for val, label, css in cells:
        html += f'    <div class="audit-cell {css}"><div class="av">{_esc(val)}</div><div class="al">{_esc(label)}</div></div>\n'

    html += '  </div>\n'

    if v.report_url:
        html += f'  <div style="margin-top:.8rem;text-align:center;">'
        html += f'<a href="{_esc(v.report_url)}" style="color:var(--blue);font-size:.82rem;text-decoration:none;">'
        html += f'查看完整研报 &rarr;</a></div>\n'

    html += '</div>\n'
    return html


def _render_market_wind(v: DebateView) -> str:
    """Market wind banner — shows regime alignment between market and stock."""
    if not v.market_regime:
        return ""

    wind_map = {"顺风": "wind-tailwind", "逆风": "wind-headwind", "中性": "wind-neutral"}
    wind_icon = {"顺风": "\U0001f4a8", "逆风": "\U0001f327\ufe0f", "中性": "\u2601\ufe0f"}
    wind_css = wind_map.get(v.market_wind, "wind-neutral")
    icon = wind_icon.get(v.market_wind, "\u2601\ufe0f")

    html = f'<div class="market-wind-card {wind_css}">\n'
    html += f'  <div class="wind-icon">{icon}</div>\n'
    html += f'  <div class="wind-body">\n'
    html += f'    <div class="wind-title">市场感知: {_esc(v.market_regime_label)} ({_esc(v.market_regime)}) — {_esc(v.market_wind)}</div>\n'
    if v.market_weather:
        html += f'    <div class="wind-detail">{_esc(v.market_weather)}</div>\n'
    if v.market_wind_reason:
        html += f'    <div class="wind-detail" style="color:var(--muted)">{_esc(v.market_wind_reason)}</div>\n'

    chips = v.sector_leaders or v.avoid_sectors
    if chips:
        html += '    <div class="wind-chips">\n'
        for s in v.sector_leaders[:4]:
            html += f'      <span class="wind-chip leader">{_esc(s)}</span>\n'
        for s in v.avoid_sectors[:3]:
            html += f'      <span class="wind-chip avoid">{_esc(s)}</span>\n'
        html += '    </div>\n'

    html += '  </div>\n'
    html += '</div>\n'
    return html


# ── Main renderer ────────────────────────────────────────────────────

def render_debate_page(view: DebateView) -> str:
    """Render the full AI Investment Committee HTML page.

    Returns a self-contained HTML string (all CSS inline, no external deps).
    """
    sections = [
        f'<div class="ai-banner">{AI_DISCLAIMER_BANNER}</div>',
        _render_hero(view),
        _render_market_wind(view),
        _render_timeline(view),
        _render_arena(view),
        _render_controversies(view),
        _render_verdict(view),
        _render_audit(view),
    ]

    body = '\n'.join(sections)

    title = f"{view.ticker_name} — AI投研委员会"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(title)}</title>
<style>{_BASE_CSS}{_DEBATE_CSS}</style>
</head>
<body>
<div class="debate-shell">
{body}
<div class="debate-footer">TradingAgents AI Investment Committee v0.2.0</div>
</div>
</body>
</html>"""


def generate_committee_report(
    run_trace,
    output_dir: str = "data/reports",
) -> Optional[str]:
    """Generate a static committee HTML report from a RunTrace.

    Args:
        run_trace: RunTrace object or dict.
        output_dir: Output directory.

    Returns:
        Path to generated HTML file, or None if insufficient data.
    """
    from pathlib import Path
    from .debate_view import build_debate_view

    view = build_debate_view(run_trace)
    if not view.rounds:
        return None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from .report_renderer import _safe_filename
    ticker_slug = _safe_filename(view.ticker) or "unknown"
    path = out_dir / f"{ticker_slug}-{view.run_id}-committee.html"
    path.write_text(render_debate_page(view), encoding="utf-8")
    return str(path)
