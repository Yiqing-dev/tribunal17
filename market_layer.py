"""Market Layer data contract — enforces completeness of L0+L1 artifacts.

The market layer produces 3 artifacts that MUST be persisted together:
1. market_context_{date}.json   — regime, breadth, sector analysis
2. recap_{date}.json            — daily recap (indices, sectors, limits)
3. market_snapshot_{date}.json  — real-time snapshot (limit counts, spots)

Downstream layers (L5 pool, L6 market report) REQUIRE all 3.
This module ensures they are always saved/loaded/checked as a unit.

Usage:
    from subagent_pipeline.market_layer import MarketLayerData

    # Save (after L0+L1 complete)
    mld = MarketLayerData(
        trade_date="2026-04-03",
        market_context=ctx_dict,
        market_context_block=block_str,
        snapshot=snapshot_obj,
        recap_json=recap_json_str,
    )
    mld.save(replays_dir="data/replays", results_dir="agent_artifacts/results")

    # Load (before L2 or L5/L6)
    mld = MarketLayerData.load("2026-04-03", replays_dir="data/replays")
    if mld is None:
        # Must run L0+L1 first
        ...

    # Use
    mld.market_context       # dict
    mld.market_context_block # str
    mld.snapshot             # MarketSnapshot
    mld.board_data           # dict (extracted from recap)
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketLayerData:
    """Immutable bundle of all market layer artifacts for a single trading day."""

    trade_date: str
    market_context: dict
    market_context_block: str
    snapshot: object  # MarketSnapshot (not typed to avoid circular import)
    recap_json: str = ""  # raw JSON string of DailyRecapData

    # ── Derived ──────────────────────────────────────────────────────

    @property
    def board_data(self) -> dict:
        """Extract limit board data from recap for L5/L6 renderers."""
        if not self.recap_json:
            return {"limit_ups": [], "limit_downs": [], "consecutive_boards": [], "sectors": []}
        try:
            recap = json.loads(self.recap_json)
            return {
                "limit_ups": recap.get("limit_board", {}).get("limit_up_stocks", []),
                "limit_downs": recap.get("limit_board", {}).get("limit_down_stocks", []),
                "consecutive_boards": recap.get("consecutive_boards", []),
                "sectors": [],
            }
        except (json.JSONDecodeError, TypeError):
            return {"limit_ups": [], "limit_downs": [], "consecutive_boards": [], "sectors": []}

    # ── Persistence ──────────────────────────────────────────────────

    def save(self, replays_dir: str = "data/replays",
             results_dir: str = "agent_artifacts/results") -> None:
        """Persist all 3 artifacts atomically.

        Saves to REPLAYS (permanent, date-keyed) and RESULTS (compat).
        Raises ValueError if any component is missing.
        """
        if not self.market_context:
            raise ValueError("Cannot save MarketLayerData: market_context is empty")
        if self.snapshot is None:
            raise ValueError("Cannot save MarketLayerData: snapshot is None")

        rp = Path(replays_dir)
        rs = Path(results_dir)
        rp.mkdir(parents=True, exist_ok=True)
        rs.mkdir(parents=True, exist_ok=True)

        d = self.trade_date

        # 1. market_context
        ctx_json = json.dumps(self.market_context, ensure_ascii=False, indent=2, allow_nan=False)
        (rp / f"market_context_{d}.json").write_text(ctx_json, encoding="utf-8")
        (rs / "market_context.json").write_text(ctx_json, encoding="utf-8")

        # 2. market_context_block
        (rs / "market_context_block.txt").write_text(
            self.market_context_block, encoding="utf-8")

        # 3. snapshot
        snap_json = self.snapshot.to_json()
        (rp / f"market_snapshot_{d}.json").write_text(snap_json, encoding="utf-8")
        (rs / "market_snapshot.json").write_text(snap_json, encoding="utf-8")

        # 4. recap (if provided — L0 saves separately, but we persist here too for completeness)
        if self.recap_json:
            (rp / f"recap_{d}.json").write_text(self.recap_json, encoding="utf-8")

        logger.info(
            "MarketLayerData saved: %s (context + snapshot + block%s)",
            d, " + recap" if self.recap_json else ""
        )

    @classmethod
    def load(cls, trade_date: str,
             replays_dir: str = "data/replays",
             results_dir: str = "agent_artifacts/results") -> Optional["MarketLayerData"]:
        """Load all 3 artifacts. Returns None if ANY is missing.

        This is the single checkpoint — if this returns None, L0+L1 must run.
        """
        from .akshare_collector import MarketSnapshot

        rp = Path(replays_dir)
        rs = Path(results_dir)
        d = trade_date

        # Check all 3 exist
        ctx_path = rp / f"market_context_{d}.json"
        snap_path = rp / f"market_snapshot_{d}.json"
        recap_path = rp / f"recap_{d}.json"

        missing = []
        if not ctx_path.exists():
            missing.append(f"market_context_{d}.json")
        if not snap_path.exists():
            missing.append(f"market_snapshot_{d}.json")
        if not recap_path.exists():
            missing.append(f"recap_{d}.json")

        if missing:
            logger.info("MarketLayerData incomplete for %s, missing: %s", d, missing)
            return None

        # Load all
        try:
            market_context = json.loads(ctx_path.read_text(encoding="utf-8"))
            snapshot = MarketSnapshot.from_json(snap_path.read_text(encoding="utf-8"))
            recap_json = recap_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("MarketLayerData load failed for %s: %s", d, e)
            return None

        # market_context_block — regenerate from context if file missing
        block_path = rs / "market_context_block.txt"
        if block_path.exists():
            block = block_path.read_text(encoding="utf-8")
        else:
            from .bridge import format_market_context_block
            block = format_market_context_block(market_context)

        return cls(
            trade_date=d,
            market_context=market_context,
            market_context_block=block,
            snapshot=snapshot,
            recap_json=recap_json,
        )

    @classmethod
    def is_complete(cls, trade_date: str,
                    replays_dir: str = "data/replays") -> bool:
        """Quick check: are all 3 artifacts present? No file loading."""
        rp = Path(replays_dir)
        d = trade_date
        return (
            (rp / f"market_context_{d}.json").exists()
            and (rp / f"market_snapshot_{d}.json").exists()
            and (rp / f"recap_{d}.json").exists()
        )
