"""
Three-tier HTML report renderer — facade module.

Same evidence chain, three compression levels:
- Tier 1 (Snapshot): Conclusion + signals + risk — single screen
- Tier 2 (Research): Bull/bear + evidence + scenarios + thesis — 3-6 pages
- Tier 3 (Audit):    Evidence chains + replay + parser + compliance — deep dive

Renderers are implemented in snapshot_renderer.py, research_renderer.py,
and audit_renderer.py. This module re-exports them for backward compatibility
and contains the cross-tier orchestration functions (generate_all_tiers,
generate_brief_report, generate_brief_report_file).

All user-facing text is in Chinese (A-share product).
"""

import logging
import re as _re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_UNSAFE_PATH_RE = _re.compile(r'[^A-Za-z0-9._\-]')


def _safe_filename(part: str) -> str:
    """Sanitize a user-supplied string for safe use in file names."""
    return _UNSAFE_PATH_RE.sub("_", str(part))

from .views import (
    SnapshotView, ResearchView, AuditView, MarketView,
    _strip_internal_tokens,
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
from .shared_css import _COUNTUP_JS, _BRAND_LOGO_SM
from .shared_utils import (
    _esc, _html_wrap, _ticker_display, _status_light, _strip_preamble,
    _empty_state, _format_price_zone, _evidence_strength_label,
    _degraded_banner, _bull_bear_bar, _direction_badge, _radar_svg,
    _squarify,
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Tier 1: Snapshot — extracted to snapshot_renderer.py                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .snapshot_renderer import (  # noqa: E402 — re-export for backward compat
    _render_checklist,
    _render_risk_debate_summary,
    _render_battle_plan,
    _render_signal_history,
    render_snapshot,
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Tier 2: Research — extracted to research_renderer.py                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .research_renderer import (  # noqa: E402 — re-export for backward compat
    _render_research_degraded,
    _render_trade_plan_card,
    render_research,
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Tier 3: Audit — extracted to audit_renderer.py                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .audit_renderer import (  # noqa: E402 — re-export for backward compat
    render_audit,
)


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
        path = out_dir / f"{_safe_filename(snap.ticker)}-run-{short_id}-snapshot.html"
        path.write_text(render_snapshot(snap, skip_vendors=skip_vendors),
                        encoding="utf-8")
        results["snapshot"] = str(path)

    # Tier 2
    res = ResearchView.build(svc, run_id)
    if res:
        path = out_dir / f"{_safe_filename(res.ticker)}-run-{short_id}-research.html"
        path.write_text(render_research(res, skip_vendors=skip_vendors),
                        encoding="utf-8")
        results["research"] = str(path)

    # Tier 3
    audit = AuditView.build(svc, run_id)
    if audit:
        path = out_dir / f"{_safe_filename(audit.ticker)}-run-{short_id}-audit.html"
        path.write_text(render_audit(audit), encoding="utf-8")
        results["audit"] = str(path)

    return results



# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Pool Page — extracted to pool_renderer.py                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .pool_renderer import (  # noqa: E402 — re-export for backward compat
    _POOL_CSS,
    _pool_action_color,
    _pool_severity_class,
    _pool_badge,
    _pool_spotlight_card,
    _render_pool_mix_chart,
    _render_pool_conviction_chart,
    _render_pool_risk_chart,
    _render_pool_table,
    _render_claim_panel,
    _render_sparkline,
    _render_cover_page,
    render_divergence_pool,
    generate_pool_report,
)



# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Market Page — extracted to market_renderer.py                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from .market_renderer import (  # noqa: E402 — re-export for backward compat
    _MARKET_CSS,
    _TREEMAP_ENGINE_JS,
    _heatmap_color,
    _heatmap_risk_color,
    _render_heatmap_legend,
    _render_svg_heatmap,
    _render_detail_drawer,
    _render_heatmap_js,
    _render_inline_treemap,
    _render_plotly_sector_treemap,
    _render_plotly_stock_treemap,
    _regime_color,
    _mkt_regime_icon,
    _css_cls,
    _render_mkt_hero,
    _render_idx_battle_cards,
    _render_sentiment_ecosystem,
    _render_sector_engine,
    _render_limit_universe,
    _render_battle_brief,
    render_market_page,
    generate_market_report,
)



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


def rotate_reports(output_dir: str = "data/reports", keep_days: int = 30) -> int:
    """Delete report files older than *keep_days*. Returns count removed.

    Scans HTML, JSON, and MD files in output_dir.
    Safe to call daily — skips non-report files.
    """
    import time as _time
    out = Path(output_dir)
    if not out.exists():
        return 0
    cutoff = _time.time() - keep_days * 86400
    count = 0
    for f in out.iterdir():
        if f.suffix not in (".html", ".json", ".md"):
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        except OSError:
            pass
    if count:
        logger.info("Rotated %d report files older than %d days", count, keep_days)
    return count
