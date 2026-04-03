"""
Market-level view model for the /market page.

Includes helper functions for normalizing board data and extracting
breadth counts from market context.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def _normalize_consecutive_boards(raw) -> Dict:
    """Normalize consecutive_boards to Dict[str, List[Dict]].

    Accepts two schemas:
    - Dict[str, List[Dict]] — board_data format ({"1": [...], "2": [...]})
    - List[Dict] — recap format ([{"boards": 2, "stocks": [...]}])
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        result = {}
        for entry in raw:
            if isinstance(entry, dict):
                level = str(entry.get("boards", entry.get("level", 1)))
                stocks = entry.get("stocks", [])
                if isinstance(stocks, list):
                    result[level] = stocks
                else:
                    result[level] = []
        return result
    return {}


def _extract_breadth_counts(
    ctx: Dict, total_hint: int = 0,
) -> Tuple[int, int]:
    """Extract advance/decline counts from market_context when snapshot is missing.

    Fallback chain:
    1. Parse raw counts from breadth_risk_note (e.g. "505涨/4955跌")
    2. Estimate from advance_decline_ratio + total
    """
    # Try parsing from risk_note text
    note = str(ctx.get("breadth_risk_note", ""))
    m = re.search(r"(\d+)\s*涨\s*[/／]\s*(\d+)\s*跌", note)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Fallback: ratio-based estimation
    ratio = ctx.get("advance_decline_ratio")
    if ratio is not None:
        try:
            ratio = float(ratio)
        except (ValueError, TypeError):
            return 0, 0
        if ratio <= 0:
            return 0, 0
        total = total_hint or 5460  # A-share market default
        adv = int(ratio / (1 + ratio) * total)
        dec = total - adv
        return adv, dec

    return 0, 0


@dataclass
class MarketView:
    """Market-level view for /market page."""
    trade_date: str = ""
    # Macro
    regime: str = ""
    regime_label: str = ""
    regime_class: str = ""
    position_cap: float = 1.0
    style_bias: str = ""
    client_summary: str = ""
    risk_alerts: str = ""
    market_weather: str = ""
    # Breadth
    breadth_state: str = ""
    breadth_label: str = ""
    breadth_class: str = ""
    advance_count: int = 0
    decline_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    breadth_trend: str = ""
    # Sector
    sector_leaders: List[str] = field(default_factory=list)
    avoid_sectors: List[str] = field(default_factory=list)
    rotation_phase: str = ""
    sector_momentum: list = field(default_factory=list)
    # Heatmap
    heatmap_data: Optional[Dict] = None
    # Index
    index_sparklines: Dict = field(default_factory=dict)
    # Board data (sector heatmap, limit stocks, consecutive boards)
    board_sectors: list = field(default_factory=list)          # [{sector, pct_change, ...}]
    limit_up_stocks: list = field(default_factory=list)        # [{ticker, name, sector, boards, ...}]
    limit_down_stocks: list = field(default_factory=list)      # [{ticker, name, sector, ...}]
    consecutive_boards: Dict = field(default_factory=dict)     # {"1": [...], "2": [...]}
    limit_sector_attribution: Dict = field(default_factory=dict)  # {sector: {count, stocks}}
    sector_stocks: Dict = field(default_factory=dict)  # {sector: [{ticker,name,pct_change,market_cap_yi}]}
    breadth_estimated: bool = False  # True when advance/decline derived from ratio fallback

    @classmethod
    def build(
        cls,
        market_context: Dict,
        market_snapshot=None,
        heatmap_data=None,
        board_data: Optional[Dict] = None,
    ) -> "MarketView":
        from .decision_labels import (
            get_regime_label, get_regime_class,
            get_breadth_label, get_breadth_class,
        )
        ctx = market_context or {}
        regime = ctx.get("regime", "NEUTRAL")
        breadth = ctx.get("breadth_state", "NARROW")

        # Extract snapshot data
        advance = 0
        decline = 0
        limit_up = 0
        limit_down = 0
        index_data = {}
        if market_snapshot:
            advance = getattr(market_snapshot, "advance_count", 0)
            decline = getattr(market_snapshot, "decline_count", 0)
            limit_up = getattr(market_snapshot, "limit_up_count", 0)
            limit_down = getattr(market_snapshot, "limit_down_count", 0)
            index_data = getattr(market_snapshot, "index_data", {})

        # Adaptive fallback: when snapshot breadth APIs failed, derive from
        # market_context (LLM agents always extract real numbers)
        breadth_estimated = False
        if advance == 0 and decline == 0 and ctx:
            total_hint = getattr(market_snapshot, "total_stocks", 0) if market_snapshot else 0
            advance, decline = _extract_breadth_counts(ctx, total_hint)
            if advance > 0 or decline > 0:
                breadth_estimated = True

        pcm = ctx.get("position_cap_multiplier", 1.0)
        if isinstance(pcm, str):
            try:
                pcm = float(pcm)
            except ValueError:
                pcm = 1.0

        return cls(
            trade_date=ctx.get("trade_date", ""),
            regime=regime,
            regime_label=get_regime_label(regime),
            regime_class=get_regime_class(regime),
            position_cap=pcm,
            style_bias=ctx.get("style_bias", ""),
            client_summary=ctx.get("client_summary", ""),
            risk_alerts=ctx.get("risk_alerts", ""),
            market_weather=ctx.get("market_weather", ""),
            breadth_state=breadth,
            breadth_label=get_breadth_label(breadth),
            breadth_class=get_breadth_class(breadth),
            advance_count=advance,
            decline_count=decline,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            breadth_trend=ctx.get("breadth_trend", ""),
            sector_leaders=ctx.get("sector_leaders", []),
            avoid_sectors=ctx.get("avoid_sectors", []),
            rotation_phase=ctx.get("rotation_phase", ""),
            sector_momentum=ctx.get("sector_momentum", []),
            heatmap_data=heatmap_data.to_dict() if hasattr(heatmap_data, "to_dict") else heatmap_data,
            index_sparklines=index_data,
            board_sectors=(board_data or {}).get("sectors", []),
            limit_up_stocks=(board_data or {}).get("limit_ups", []),
            limit_down_stocks=(board_data or {}).get("limit_downs", []),
            consecutive_boards=_normalize_consecutive_boards(
                (board_data or {}).get("consecutive_boards", {})),
            limit_sector_attribution=(board_data or {}).get("limit_sector_attribution", {}),
            sector_stocks=(board_data or {}).get("sector_stocks", {}),
            breadth_estimated=breadth_estimated,
        )
