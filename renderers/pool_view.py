"""
Multi-stock divergence pool view models.

StockDivergenceRow: one row summarising a single stock's bull/bear.
DivergencePoolView: multi-stock comparison pool.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..replay_service import ReplayService
from ..trace_models import RunTrace

from .views import BannerView, _strip_internal_tokens


@dataclass
class StockDivergenceRow:
    """One row in the divergence pool — summarises a single stock's bull/bear."""
    run_id: str = ""
    ticker: str = ""
    ticker_name: str = ""
    trade_date: str = ""

    # Verdict
    action: str = ""         # BUY/SELL/HOLD/VETO
    action_label: str = ""   # 建议关注/回避/...
    action_class: str = ""   # buy/sell/hold/veto (CSS)
    confidence: float = 0.0
    risk_cleared: bool = False
    was_vetoed: bool = False
    veto_source: str = ""

    # Top bull claims (sorted by confidence desc, max 3)
    bull_claims: List[Dict] = field(default_factory=list)
    # Top bear claims (sorted by confidence desc, max 3)
    bear_claims: List[Dict] = field(default_factory=list)

    # Risk flags (category + severity)
    risk_flags: List[Dict] = field(default_factory=list)

    # Key metrics (from metrics_fallback)
    pe: str = ""
    pb: str = ""
    market_cap: str = ""

    # Sparkline close prices (last ~30 days, for mini chart)
    sparkline_prices: List[float] = field(default_factory=list)

    # Trade plan (public entry/exit framework)
    trade_plan: Dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Human-readable stock label for card/table display."""
        if self.ticker_name:
            return f"{self.ticker} {self.ticker_name}"
        return self.ticker

    @property
    def short_ticker(self) -> str:
        """Ticker without exchange suffix for compact badges."""
        return self.ticker.split(".", 1)[0]

    @property
    def conviction_pct(self) -> int:
        """Confidence as rounded percentage for dashboards."""
        return int(round(max(self.confidence, 0.0) * 100))

    @property
    def bull_score(self) -> float:
        """Aggregate confidence of top bull claims."""
        return sum(float(c.get("confidence", 0) or 0) for c in self.bull_claims)

    @property
    def bear_score(self) -> float:
        """Aggregate confidence of top bear claims."""
        return sum(float(c.get("confidence", 0) or 0) for c in self.bear_claims)

    @property
    def bull_ratio(self) -> float:
        """Bull share in the bull/bear debate intensity."""
        total = self.bull_score + self.bear_score
        return self.bull_score / total if total > 0 else 0.5

    @property
    def bear_ratio(self) -> float:
        """Bear share in the bull/bear debate intensity."""
        return 1.0 - self.bull_ratio

    @property
    def signal_gap(self) -> float:
        """Net bull minus bear intensity for ranking/summary."""
        return self.bull_score - self.bear_score

    @property
    def risk_flag_count(self) -> int:
        """How many explicit risk flags this stock carries."""
        return len(self.risk_flags)

    @property
    def primary_risk_categories(self) -> List[str]:
        """Top risk categories for compact display."""
        return [rf.get("category", "") for rf in self.risk_flags if rf.get("category")][:2]

    @property
    def risk_state_label(self) -> str:
        """Readable risk state for customers."""
        if self.was_vetoed:
            return "风控否决"
        if self.risk_cleared and self.risk_flags:
            return "风控通过，附带风险"
        if self.risk_cleared:
            return "风控通过"
        if self.risk_flags:
            return "风险待跟踪"
        return "待校验"

    @property
    def risk_state_class(self) -> str:
        """CSS class for risk state badges."""
        if self.was_vetoed:
            return "veto"
        if self.risk_cleared and not self.risk_flags:
            return "buy"
        if self.risk_cleared:
            return "hold"
        return "sell"

    @classmethod
    def build(cls, service: ReplayService, run_id: str) -> Optional["StockDivergenceRow"]:
        from .decision_labels import get_action_label, get_action_class

        trace = service.load_run(run_id)
        if not trace:
            return None

        action = trace.research_action or "HOLD"
        bull_out = service.show_node_output(run_id, "Bull Researcher")
        bear_out = service.show_node_output(run_id, "Bear Researcher")
        risk_out = service.show_node_output(run_id, "Risk Judge")

        def _top_claims(node_out: Optional[Dict], max_n: int = 3) -> List[Dict]:
            if not node_out:
                return []
            sd = node_out.get("structured_data") or {}
            raw = sd.get("supporting_claims") or sd.get("opposing_claims") or []
            items = [
                {
                    "text": _strip_internal_tokens(c.get("text", "")[:120]),
                    "confidence": c.get("confidence", 0),
                    "supports": c.get("supports", []),
                }
                for c in raw if c.get("text")
            ]
            items.sort(key=lambda x: x["confidence"], reverse=True)
            return items[:max_n]

        # Risk flags
        risk_flags = []
        if risk_out:
            rsd = risk_out.get("structured_data") or {}
            for rf in rsd.get("risk_flags") or []:
                risk_flags.append({
                    "category": rf.get("category", ""),
                    "severity": rf.get("severity", ""),
                })

        # Metrics fallback
        fund_out = service.show_node_output(run_id, "Fundamentals Analyst")
        mf = {}
        if fund_out:
            fsd = fund_out.get("structured_data") or {}
            mf = fsd.get("metrics_fallback", {})

        # Sparkline prices (stored in Market Analyst structured_data)
        mkt_out = service.show_node_output(run_id, "Market Analyst")
        sparkline = []
        if mkt_out:
            msd = mkt_out.get("structured_data") or {}
            raw_prices = msd.get("price_history", [])
            sparkline = [float(p) for p in raw_prices if p is not None][:30]

        # Trade plan (from ResearchOutput structured_data)
        ro_out = service.show_node_output(run_id, "ResearchOutput")
        trade_plan_data = {}
        if ro_out:
            ro_sd = ro_out.get("structured_data") or {}
            trade_plan_data = ro_sd.get("trade_plan") or {}

        return cls(
            run_id=run_id,
            ticker=trace.ticker,
            ticker_name=getattr(trace, "ticker_name", ""),
            trade_date=trace.trade_date,
            action=action,
            action_label=get_action_label(action),
            action_class=get_action_class(action),
            confidence=trace.final_confidence,
            risk_cleared=risk_out.get("risk_cleared") if risk_out else False,
            was_vetoed=trace.was_vetoed,
            veto_source=getattr(trace, "veto_source", ""),
            bull_claims=_top_claims(bull_out),
            bear_claims=_top_claims(bear_out),
            risk_flags=risk_flags,
            pe=mf.get("pe", ""),
            pb=mf.get("pb", ""),
            market_cap=mf.get("market_cap", ""),
            sparkline_prices=sparkline,
            trade_plan=trade_plan_data,
        )


@dataclass
class DivergencePoolView:
    """Multi-stock comparison — the divergence pool / war room."""
    trade_date: str = ""
    rows: List[StockDivergenceRow] = field(default_factory=list)
    total_stocks: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    veto_count: int = 0

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all covered stocks."""
        if not self.rows:
            return 0.0
        return sum(r.confidence for r in self.rows) / len(self.rows)

    @property
    def risk_alert_count(self) -> int:
        """Total number of visible risk flags across the pool."""
        return sum(r.risk_flag_count for r in self.rows)

    @property
    def top_risk_categories(self) -> List[Tuple[str, int]]:
        """Most common risk categories across all rows."""
        counts: Dict[str, int] = {}
        for row in self.rows:
            for risk in row.risk_flags:
                cat = risk.get("category", "")
                if cat:
                    counts[cat] = counts.get(cat, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    @property
    def featured_long(self) -> Optional[StockDivergenceRow]:
        """Highest-conviction BUY idea."""
        for row in self.rows:
            if row.action.upper() == "BUY":
                return row
        return self.rows[0] if self.rows else None

    @property
    def featured_short(self) -> Optional[StockDivergenceRow]:
        """Highest-priority avoid/veto idea."""
        for row in self.rows:
            if row.action.upper() in ("SELL", "VETO"):
                return row
        return None

    @property
    def featured_watch(self) -> Optional[StockDivergenceRow]:
        """Most representative HOLD idea."""
        for row in self.rows:
            if row.action.upper() == "HOLD":
                return row
        return None

    @classmethod
    def build(cls, service: ReplayService, run_ids: List[str],
              trade_date: str = "") -> "DivergencePoolView":
        rows = []
        for rid in run_ids:
            row = StockDivergenceRow.build(service, rid)
            if row:
                rows.append(row)

        # Sort: BUY first (by confidence desc), then HOLD, then SELL, VETO last
        action_order = {"BUY": 0, "HOLD": 1, "SELL": 2, "VETO": 3}
        rows.sort(key=lambda r: (action_order.get(r.action.upper(), 9), -r.confidence))

        return cls(
            trade_date=trade_date or (rows[0].trade_date if rows else ""),
            rows=rows,
            total_stocks=len(rows),
            buy_count=sum(1 for r in rows if r.action.upper() == "BUY"),
            sell_count=sum(1 for r in rows if r.action.upper() == "SELL"),
            hold_count=sum(1 for r in rows if r.action.upper() == "HOLD"),
            veto_count=sum(1 for r in rows if r.action.upper() == "VETO"),
        )
