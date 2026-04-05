"""Vendored report renderers (self-contained, no dashboard dependency).

Public API — import from here or from report_renderer (facade).
"""

__all__ = [
    # Tier 1-3 renderers
    "render_snapshot",
    "render_research",
    "render_audit",
    # Cross-tier orchestration
    "generate_all_tiers",
    "generate_brief_report",
    "generate_brief_report_file",
    # Pool / market / debate / recap
    "generate_pool_report",
    "generate_market_report",
    "generate_committee_report",
    # Facade re-export
    "report_renderer",
    # Views (data contracts)
    "SnapshotView",
    "ResearchView",
    "AuditView",
    "MarketView",
    # Utilities
    "_safe_filename",
]
