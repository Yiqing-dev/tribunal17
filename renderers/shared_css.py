"""Shared CSS tokens, JS helpers, and brand assets used across all renderers.

Each HTML report embeds full CSS inline for self-contained static export (no external stylesheets needed).
"""

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
  /* V4: Typography scale */
  --t-xs: .72rem;  --t-sm: .82rem;  --t-md: .95rem;
  --t-lg: 1.1rem;  --t-xl: 1.4rem;  --t-2xl: 1.9rem;  --t-3xl: 2.4rem;
  --lh-tight: 1.15;  --lh-snug: 1.35;  --lh-normal: 1.55;  --lh-loose: 1.75;
  /* V4: Color-blind副色 (deuteranopia-safe; layered with red/green via icon/pattern redundancy) */
  --cb-up: #f59e0b;   --cb-down: #60a5fa;
  /* V4: Severity tiers */
  --sev-hot: #f87171;  --sev-warm: #fbbf24;  --sev-cool: #60a5fa;  --sev-mute: #64748b;
  /* V4: Confidence tiers */
  --conf-hi: #34d399;  --conf-md: #fbbf24;  --conf-lo: #f87171;  --conf-na: #64748b;
  /* V4: Z-scale */
  --z-base: 1;  --z-card: 10;  --z-nav: 40;  --z-modal: 90;
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
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
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
/* box-shadow set via S4 elevation system (var(--elev-1/2/3)) */
.card {
  position: relative;
  background: linear-gradient(180deg, rgba(12, 23, 35, 0.94), rgba(8, 16, 25, 0.92));
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 20px;
  padding: 1.25rem 1.3rem;
  margin-bottom: 1rem;
  backdrop-filter: blur(12px);
}
.card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.1);
}

/* ── Glass Panel (recap / debate / pool) ── */
.glass {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px; padding: 1.25rem;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: transform 280ms ease, box-shadow 280ms ease, border-color 280ms ease;
}
.glass:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.18);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255,255,255,0.04);
}

/* ── Section Head ── */
.sec-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: .8rem; }
.sec-title {
  font-size: 1.15rem; font-weight: 700;
  background: linear-gradient(90deg, var(--blue), var(--green));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.sec-sub { color: var(--muted); font-size: .78rem; }

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
  .bp-body { grid-template-columns: 1fr !important; }
  .bp-body-right { order: -1; display: flex; justify-content: center; }
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

/* ── V1: Card hierarchy — now handled by S4 elevation system ── */

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
.empty-state-icon--svg svg { width: 3rem; height: 3rem; stroke: var(--muted); fill: none; stroke-width: 1.5; }
.empty-state-icon--svg { animation: icon-pulse 2.5s ease-in-out infinite; }
@keyframes icon-pulse { 0%,100% { opacity: .45; transform: scale(1); } 50% { opacity: .75; transform: scale(1.06); } }
.empty-state-title { font-size: .88rem; font-weight: 600; margin-bottom: .25rem; }
.empty-state-hint { font-size: .78rem; opacity: .8; }

/* ── Trend arrows ── */
.trend-arrow { font-size: .7em; margin-left: .2em; font-weight: 700; vertical-align: super; }
.trend-up { color: var(--green, #34d399); }
.trend-down { color: var(--red, #f87171); }
.trend-neutral { color: var(--muted, #8fa3b8); }

/* ── Hero sparkline ── */
.hero-sparkline { margin-bottom: .5rem; }
.hero-sparkline svg { width: 100%; max-width: 220px; height: auto; }

/* ── Cross-report nav ── */
.cross-nav {
  position: sticky; top: 0; z-index: 100;
  display: flex; gap: 0; margin: -2.2rem -1.5rem 1.5rem;
  background: rgba(7, 14, 27, 0.95); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 1.5rem;
}
.cross-nav a {
  display: flex; align-items: center; padding: .7rem 1.2rem;
  color: var(--muted); text-decoration: none; font-size: .82rem;
  font-weight: 600; letter-spacing: .04em; border-bottom: 2px solid transparent;
  transition: color 180ms ease, border-color 180ms ease;
}
.cross-nav a:hover { color: var(--fg); }
.cross-nav a.active { color: var(--accent, #f59e0b); border-bottom-color: var(--accent, #f59e0b); }
@media (max-width: 760px) {
  .cross-nav { margin: -1.25rem -.75rem 1rem; padding: 0 .75rem; overflow-x: auto; }
  .cross-nav a { padding: .5rem .8rem; font-size: .78rem; white-space: nowrap; }
}

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

/* ── V4: Visualization primitives (score_pill / priority_chip / heat_cell / conf_dots / conf_ring / ridge_bar / delta_arrow / section_divider) ── */
.score-pill {
  display: inline-flex; align-items: center; gap: 3px;
  font-family: var(--mono); font-size: var(--t-xs); letter-spacing: 0;
  vertical-align: middle;
}
.score-pill .sp-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15);
}
.score-pill .sp-dot.on { border-color: transparent; box-shadow: 0 0 4px currentColor; }
.score-pill.conf-hi .sp-dot.on { background: var(--conf-hi); color: var(--conf-hi); }
.score-pill.conf-md .sp-dot.on { background: var(--conf-md); color: var(--conf-md); }
.score-pill.conf-lo .sp-dot.on { background: var(--conf-lo); color: var(--conf-lo); }
.score-pill.conf-na .sp-dot.on { background: var(--conf-na); color: var(--conf-na); }
.score-pill .sp-lab { color: var(--muted); margin-left: .3rem; font-size: var(--t-xs); }

.prio-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 9px; border-radius: 999px;
  font-size: var(--t-xs); font-weight: 600; letter-spacing: .02em;
  border: 1px solid transparent;
}
.prio-chip .pc-ico { font-size: .8em; line-height: 1; }
.prio-chip.hot  { background: rgba(248,113,113,0.14); color: var(--sev-hot);  border-color: rgba(248,113,113,0.3); }
.prio-chip.warm { background: rgba(251,191,36,0.14); color: var(--sev-warm); border-color: rgba(251,191,36,0.3); }
.prio-chip.cool { background: rgba(96,165,250,0.12); color: var(--sev-cool); border-color: rgba(96,165,250,0.28); }
.prio-chip.mute { background: rgba(255,255,255,0.04); color: var(--sev-mute); border-color: rgba(255,255,255,0.08); }

.conf-ring { position: relative; display: inline-block; }
.conf-ring svg { display: block; }
.conf-ring .cr-val {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-family: var(--mono); font-weight: 800; line-height: 1;
}
.conf-ring .cr-pct { font-size: var(--t-lg); color: var(--white); }
.conf-ring .cr-lab { font-size: var(--t-xs); color: var(--muted); margin-top: 2px; letter-spacing: .05em; }

.ridge-bar { display: flex; align-items: flex-end; gap: 2px; height: 28px; }
.ridge-bar .rb-seg {
  flex: 1; min-width: 3px; border-radius: 2px 2px 0 0;
  background: linear-gradient(180deg, var(--conf-hi), rgba(52,211,153,0.3));
  transition: transform 180ms var(--ease-out);
}
.ridge-bar .rb-seg.neg { background: linear-gradient(180deg, var(--conf-lo), rgba(248,113,113,0.3)); }
.ridge-bar .rb-seg:hover { transform: scaleY(1.05); }
.ridge-bar .rb-labels { display: flex; gap: 2px; font-size: var(--t-xs); color: var(--muted); margin-top: 4px; }

.delta-arr { display: inline-flex; align-items: center; gap: 2px; font-size: var(--t-xs); font-family: var(--mono); font-weight: 600; }
.delta-arr.up { color: var(--green); }
.delta-arr.down { color: var(--red); }
.delta-arr.flat { color: var(--muted); }

.v-heat-cell {
  display: inline-block; position: relative;
  border-radius: 4px; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
  font-family: var(--mono); font-size: var(--t-xs); font-weight: 600;
  text-align: center; line-height: 1;
}
.v-heat-cell::after {
  content: attr(data-label); position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,0.92); text-shadow: 0 1px 2px rgba(0,0,0,0.4);
  font-size: var(--t-xs);
}
.v-heat-cell[data-pattern="diag"] { background-image: var(--pat-diag); }
.v-heat-cell[data-pattern="dot"]  { background-image: var(--pat-dot); }

.conf-dots { display: inline-flex; gap: 2px; align-items: center; }
.conf-dots .cd-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255,255,255,0.08);
}
.conf-dots .cd-dot.on { background: var(--conf-hi); box-shadow: 0 0 4px var(--conf-hi); }
.conf-dots[data-tier="md"] .cd-dot.on { background: var(--conf-md); box-shadow: 0 0 4px var(--conf-md); }
.conf-dots[data-tier="lo"] .cd-dot.on { background: var(--conf-lo); box-shadow: 0 0 4px var(--conf-lo); }

/* ── V5: Price ladder ── */
.price-ladder { display: block; overflow: visible; max-width: 100%; }
.price-ladder text { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }

/* ── V5: Stacked probability bar ── */
.stacked-prob { margin: .4rem 0; }
.stacked-prob .spb-track {
  display: flex; border-radius: 8px; overflow: hidden;
  background: rgba(255,255,255,0.04);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
}
.stacked-prob .spb-seg {
  display: flex; align-items: center; justify-content: center;
  min-width: 28px; color: rgba(9,20,32,0.88);
  font-size: var(--t-xs); font-weight: 700; letter-spacing: .02em;
  transition: filter 180ms var(--ease-out);
}
.stacked-prob .spb-seg:hover { filter: brightness(1.15); }
.stacked-prob .spb-seg-label { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.stacked-prob .spb-legend {
  display: flex; gap: 1rem; margin-top: .35rem; flex-wrap: wrap;
  font-size: var(--t-xs);
}
.stacked-prob .spb-legend-item { display: inline-flex; align-items: center; gap: .3rem; }
.stacked-prob .spb-legend-swatch {
  width: 10px; height: 10px; border-radius: 2px; display: inline-block;
}
.stacked-prob .spb-legend-label { color: var(--muted); }
.stacked-prob .spb-legend-value { color: var(--white); font-weight: 600; }

/* ── V5: Pillar score mini-bar (horizontal segmented) ── */
.pillar-bar { display: inline-flex; align-items: center; gap: .35rem; }
.pillar-bar .pb-seg {
  width: 14px; height: 6px; border-radius: 2px;
  background: rgba(255,255,255,0.10);
  transition: background 180ms var(--ease-out), box-shadow 180ms var(--ease-out);
}
.pillar-bar .pb-seg.on { background: var(--conf-hi); box-shadow: 0 0 4px rgba(52,211,153,0.35); }
.pillar-bar[data-tier="md"] .pb-seg.on { background: var(--conf-md); box-shadow: 0 0 4px rgba(251,191,36,0.35); }
.pillar-bar[data-tier="lo"] .pb-seg.on { background: var(--conf-lo); box-shadow: 0 0 4px rgba(248,113,113,0.35); }
.pillar-bar .pb-text { font-size: var(--t-xs); color: var(--muted); margin-left: .15rem; }

/* ── V5: History sparkline ── */
.hist-spark { display: block; width: 100%; height: auto; }
.hist-spark circle { transition: r 160ms var(--ease-out); }
.hist-spark circle:hover { r: 4.5; }

.sec-div {
  display: flex; align-items: center; gap: .6rem;
  margin: var(--sp-3) 0 var(--sp-2);
}
.sec-div .sd-line {
  flex: 1; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent);
}
.sec-div .sd-title {
  font-size: var(--t-md); font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--white); display: inline-flex; align-items: center; gap: .4rem;
}
.sec-div .sd-count {
  font-family: var(--mono); font-size: var(--t-xs); color: var(--muted);
  background: rgba(255,255,255,0.04); padding: 1px 8px; border-radius: 999px;
}

/* V4: Claim card confidence tiering (used by research_renderer upgrade) */
.claim-card.conf-hi { border-left: 3px solid var(--conf-hi); }
.claim-card.conf-md { border-left: 2px solid var(--conf-md); }
.claim-card.conf-lo { border-left: 1px solid var(--conf-lo); }

/* V4: Audit node-group accordion */
.audit-group { margin-bottom: var(--sp-2); }
.audit-group-head {
  display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
  padding: .6rem .85rem; border-radius: 14px;
  background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.06);
  cursor: pointer; transition: background var(--dur-fast) var(--ease-out);
}
.audit-group-head:hover { background: rgba(255,255,255,0.055); }
.audit-group-head .agh-name { font-weight: 700; color: var(--white); min-width: 8em; }
.audit-group-head .agh-cells { display: flex; gap: 4px; }
.audit-group-head .agh-spark { opacity: .85; }
.audit-group-head .agh-chip { margin-left: auto; }
.audit-group-body { padding: .5rem .85rem 0; }
details.audit-group > summary { list-style: none; }
details.audit-group > summary::-webkit-details-marker { display: none; }
details.audit-group[open] .audit-group-head { border-radius: 14px 14px 0 0; }
@media print {
  details.audit-group { open: true; }
  details.audit-group > .audit-group-body { display: block !important; }
}

/* ── Print — consolidated from all renderers ──────────────── */
@media print {
  @page { margin: 15mm; }
  :root{--bg:#fff;--fg:#111;--card:#fff;--border:#ddd;--muted:#666;--white:#111;--accent:#333}
  *{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}
  body{background:#fff!important;color:#111!important}
  body::before,.hero::after{display:none!important}
  /* Cards & glass */
  .card,.hero,.glass,.debate-hero,.verdict-card{
    background:#fff!important;box-shadow:none!important;backdrop-filter:none!important;
    border:1px solid #ddd!important;border-radius:4px!important}
  /* Page breaks */
  .card,.glass,.stock-card,.insight-card{page-break-inside:avoid;break-inside:avoid}
  .cover-page{page-break-after:always}
  .board-card{page-break-before:always}
  /* Disable all animations */
  .reveal,.animate-in,.conf-fill,.bb-bull,.bb-bear,.strength-bull,.strength-bear,
  .verdict-card,.empty-state-icon--svg{animation:none!important;opacity:1!important;transform:none!important}
  /* Layout */
  .container,.debate-shell{max-width:100%;padding:0}
  details[open]>div,.chart-panel,.rc-panel{display:block!important}
  /* Hide interactive elements */
  .toggle-btn,.csv-btn,.sd-close,.idx-tabs,.rc-tabs,.anchor-nav,.filter-bar,
  .sector-drawer,.sector-overlay,.shm-tooltip,.cross-nav{display:none!important}
  /* Typography */
  h2,.sec-title{color:#333!important}
  .kpi-val{-webkit-text-fill-color:#111!important;background:none!important;color:#111!important}
  /* SVG visibility */
  svg text{fill:#333!important}
  svg polyline,svg line{stroke:#555!important}
  .bb-bull{background:#34d399!important} .bb-bear{background:#f87171!important}
  .strength-bull{background:#34d399!important} .strength-bear{background:#f87171!important}
}
"""

# Only included in snapshot/research reports. Other report types display KPI values statically.
_COUNTUP_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('.kpi-val').forEach(function(el){
    var raw=el.textContent.trim();
    var m=raw.match(/([+-]?[\\d.]+)/);
    if(!m)return;
    var target=parseFloat(m[1]);
    if(isNaN(target)||!isFinite(target))return;
    var suffix=raw.replace(m[1],''),
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


# V4: Shared SVG defs (patterns + gradients) injected once per HTML page by _html_wrap.
# Enables `fill="url(#pat-diag)"` etc. in all renderers without per-component duplication.
# Also removes Recap's ~50KB of inlined gradient defs.
_SHARED_SVG_DEFS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
    '<defs>'
    '<pattern id="pat-diag" width="6" height="6" patternUnits="userSpaceOnUse">'
    '<path d="M 0 6 L 6 0" stroke="currentColor" stroke-width="1" opacity="0.35"/>'
    '</pattern>'
    '<pattern id="pat-dot" width="4" height="4" patternUnits="userSpaceOnUse">'
    '<circle cx="2" cy="2" r="0.8" fill="currentColor" opacity="0.45"/>'
    '</pattern>'
    '<pattern id="pat-cross" width="6" height="6" patternUnits="userSpaceOnUse">'
    '<path d="M 0 3 L 6 3 M 3 0 L 3 6" stroke="currentColor" stroke-width="0.5" opacity="0.4"/>'
    '</pattern>'
    '<linearGradient id="grad-conf" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0%" stop-color="#f87171"/>'
    '<stop offset="50%" stop-color="#fbbf24"/>'
    '<stop offset="100%" stop-color="#34d399"/>'
    '</linearGradient>'
    '<linearGradient id="grad-green" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#34d399" stop-opacity="0.85"/>'
    '<stop offset="100%" stop-color="#34d399" stop-opacity="0.25"/>'
    '</linearGradient>'
    '<linearGradient id="grad-red" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#f87171" stop-opacity="0.85"/>'
    '<stop offset="100%" stop-color="#f87171" stop-opacity="0.25"/>'
    '</linearGradient>'
    '<linearGradient id="grad-blue" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0%" stop-color="#60a5fa" stop-opacity="0.85"/>'
    '<stop offset="100%" stop-color="#60a5fa" stop-opacity="0.25"/>'
    '</linearGradient>'
    '</defs>'
    '</svg>'
)
