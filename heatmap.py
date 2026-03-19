"""Heatmap data module — pure data aggregation, no LLM.

Transforms DivergencePoolView rows + MarketSnapshot spots + market_context
into a HeatmapData structure for treemap visualization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HeatmapNode:
    """One stock in the heatmap treemap."""
    id: str = ""                   # "601985.SS"
    ticker: str = ""
    name: str = ""
    sector: str = ""
    market_cap: float = 0.0        # raw value (亿元)
    pct_change: float = 0.0        # 当日涨跌幅
    action: str = ""               # BUY/SELL/HOLD/VETO
    confidence: float = 0.0
    risk_state: str = ""           # PASS / PASS_WITH_FLAGS / VETO
    bull_score: float = 0.0
    bear_score: float = 0.0
    size_score: float = 0.0        # log(market_cap) normalized 0-1
    color_score: float = 0.0       # action+confidence mapped to -1..+1
    detail_ref: str = ""           # run_id
    # Drawer detail fields
    action_label: str = ""
    bull_claims_top3: List[Dict] = field(default_factory=list)
    bear_claims_top3: List[Dict] = field(default_factory=list)
    risk_flags: List[Dict] = field(default_factory=list)
    market_wind: str = ""          # "顺风" / "逆风" / "中性"
    sector_status: str = ""        # "主线板块" / "退潮板块" / "中性"


@dataclass
class HeatmapData:
    """Complete heatmap data for rendering."""
    view_mode: str = "pool"
    trade_date: str = ""
    nodes: List[HeatmapNode] = field(default_factory=list)
    sectors: List[Dict] = field(default_factory=list)
    market_context: Dict = field(default_factory=dict)

    @classmethod
    def build_from_pool(
        cls,
        pool_view,
        market_context: Dict = None,
        spot_data: Dict = None,
    ) -> "HeatmapData":
        """Build heatmap data from DivergencePoolView + market data.

        Args:
            pool_view: DivergencePoolView instance with rows
            market_context: market_context dict from assemble_market_context
            spot_data: MarketSnapshot.stock_spots dict {ticker: {name, price, ...}}
        """
        market_context = market_context or {}
        spot_data = spot_data or {}
        leaders = market_context.get("sector_leaders", [])
        avoid = market_context.get("avoid_sectors", [])
        regime = market_context.get("regime", "NEUTRAL")

        nodes = []
        all_caps = []

        for row in pool_view.rows:
            bare = row.ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
            spot = spot_data.get(bare, {})

            # Market cap: prefer spot data, fall back to view metrics
            cap = spot.get("market_cap", 0) or 0
            if cap and cap > 1e8:
                cap = cap / 1e8  # convert to 亿
            if not cap and row.market_cap:
                try:
                    cap = float(row.market_cap)
                except (ValueError, TypeError):
                    cap = 10.0  # default
            cap = max(cap, 1.0)  # minimum for sizing
            all_caps.append(cap)

            # Pct change from spot
            pct = spot.get("pct_change", 0) or 0

            # Sector detection
            sector = spot.get("sector", "") or ""

            # Risk state
            if row.was_vetoed:
                risk_state = "VETO"
            elif row.risk_cleared and row.risk_flags:
                risk_state = "PASS_WITH_FLAGS"
            elif row.risk_cleared:
                risk_state = "PASS"
            else:
                risk_state = "FAIL"

            # Market wind (alignment with regime)
            if regime == "RISK_ON" and row.action.upper() == "BUY":
                market_wind = "顺风"
            elif regime == "RISK_OFF" and row.action.upper() in ("SELL", "VETO"):
                market_wind = "顺风"
            elif regime == "RISK_OFF" and row.action.upper() == "BUY":
                market_wind = "逆风"
            elif regime == "RISK_ON" and row.action.upper() in ("SELL", "VETO"):
                market_wind = "逆风"
            else:
                market_wind = "中性"

            # Sector status
            sector_status = "中性"
            if sector:
                for leader in leaders:
                    if leader in sector or sector in leader:
                        sector_status = "主线板块"
                        break
                for av in avoid:
                    if av in sector or sector in av:
                        sector_status = "退潮板块"
                        break

            node = HeatmapNode(
                id=row.ticker,
                ticker=row.ticker,
                name=row.ticker_name or bare,
                sector=sector,
                market_cap=cap,
                pct_change=pct,
                action=row.action.upper(),
                confidence=row.confidence,
                risk_state=risk_state,
                bull_score=row.bull_score,
                bear_score=row.bear_score,
                detail_ref=row.run_id,
                action_label=row.action_label,
                bull_claims_top3=row.bull_claims[:3],
                bear_claims_top3=row.bear_claims[:3],
                risk_flags=row.risk_flags,
                market_wind=market_wind,
                sector_status=sector_status,
            )
            nodes.append(node)

        # Compute size_score and color_score
        for node in nodes:
            node.size_score = compute_size_score(node.market_cap, all_caps)
            node.color_score = compute_color_score(
                node.action, node.confidence, node.risk_state
            )

        sectors = build_sector_aggregates(nodes)

        return cls(
            view_mode="pool",
            trade_date=pool_view.trade_date,
            nodes=nodes,
            sectors=sectors,
            market_context=market_context,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JavaScript consumption."""
        return {
            "view_mode": self.view_mode,
            "trade_date": self.trade_date,
            "nodes": [
                {
                    "id": n.id,
                    "ticker": n.ticker,
                    "name": n.name,
                    "sector": n.sector,
                    "market_cap": n.market_cap,
                    "pct_change": n.pct_change,
                    "action": n.action,
                    "confidence": n.confidence,
                    "risk_state": n.risk_state,
                    "bull_score": n.bull_score,
                    "bear_score": n.bear_score,
                    "size_score": n.size_score,
                    "color_score": n.color_score,
                    "detail_ref": n.detail_ref,
                    "action_label": n.action_label,
                    "bull_claims_top3": n.bull_claims_top3,
                    "bear_claims_top3": n.bear_claims_top3,
                    "risk_flags": n.risk_flags,
                    "market_wind": n.market_wind,
                    "sector_status": n.sector_status,
                }
                for n in self.nodes
            ],
            "sectors": self.sectors,
            "market_context": self.market_context,
        }


def compute_size_score(cap: float, all_caps: List[float]) -> float:
    """Log-normalize market cap to 0-1 range across the pool."""
    if not all_caps or cap <= 0:
        return 0.5
    log_caps = [math.log10(max(c, 1)) for c in all_caps]
    log_val = math.log10(max(cap, 1))
    min_log = min(log_caps)
    max_log = max(log_caps)
    if max_log <= min_log:
        return 0.5
    return (log_val - min_log) / (max_log - min_log)


def compute_color_score(action: str, confidence: float, risk_state: str) -> float:
    """Map action + confidence + risk_state to -1..+1 color score.

    Color mapping:
      +0.8..+1.0  deep green   #1a7f37  (high-confidence BUY)
      +0.4..+0.8  green        #3fb950  (low-confidence BUY)
      -0.2..+0.4  yellow       #d29922  (HOLD)
      -0.6..-0.2  red-orange   #da3633  (SELL)
      -1.0..-0.6  deep red     #8b1325  (VETO)
    """
    action = action.upper()
    conf = max(0.0, min(confidence, 1.0))  # clamp to [0, 1]
    if action == "VETO":
        return -0.8 - 0.2 * conf
    elif action == "SELL":
        return -0.2 - 0.4 * conf
    elif action == "HOLD":
        base = 0.1
        if risk_state == "PASS":
            base = 0.2
        return base
    elif action == "BUY":
        return 0.4 + 0.6 * conf
    return 0.0


def color_score_to_hex(score: float) -> str:
    """Convert color_score (-1..+1) to hex color string."""
    if score >= 0.8:
        return "#1a7f37"
    elif score >= 0.4:
        return "#3fb950"
    elif score >= -0.2:
        return "#d29922"
    elif score >= -0.6:
        return "#da3633"
    else:
        return "#8b1325"


def build_sector_aggregates(nodes: List[HeatmapNode]) -> List[Dict]:
    """Aggregate heatmap nodes by sector."""
    sector_map: Dict[str, Dict] = {}
    for node in nodes:
        sector = node.sector or "其他"
        if sector not in sector_map:
            sector_map[sector] = {
                "name": sector,
                "count": 0,
                "total_cap": 0.0,
                "avg_pct_change": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "hold_count": 0,
                "veto_count": 0,
            }
        s = sector_map[sector]
        s["count"] += 1
        s["total_cap"] += node.market_cap
        s["avg_pct_change"] += node.pct_change
        action = node.action.upper()
        if action == "BUY":
            s["buy_count"] += 1
        elif action == "SELL":
            s["sell_count"] += 1
        elif action == "HOLD":
            s["hold_count"] += 1
        elif action == "VETO":
            s["veto_count"] += 1

    result = []
    for s in sector_map.values():
        if s["count"] > 0:
            s["avg_pct_change"] = round(s["avg_pct_change"] / s["count"], 2)
        result.append(s)

    result.sort(key=lambda x: x["total_cap"], reverse=True)
    return result
