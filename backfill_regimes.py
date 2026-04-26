"""One-shot backfill: derive market_regime for historical SignalRecords.

The signal ledger is append-only JSONL (no in-place edits), so we write a
*supplement* file mapping run_id → regime. The monitoring module reads the
supplement to enrich SignalRecords whose `market_regime` is empty.

Usage:
    python -m subagent_pipeline.backfill_regimes

The script is idempotent: it merges into any existing supplement file,
preserving previously-backfilled entries.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


def backfill_regime_supplement(
    ledger_path: str = "data/signals/signals.jsonl",
    storage_dir: str = "data/replays",
    output_path: str = "data/signals/regime_supplement.json",
) -> int:
    """Walk existing SignalRecords, derive regime from RunTrace.market_context,
    and write a supplement dict {run_id → regime} to output_path.

    Returns the count of records newly enriched (excluding prior supplement).
    Idempotent: merges into existing supplement.
    """
    from .signal_ledger import SignalLedger
    from .replay_store import ReplayStore

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing supplement (if any)
    existing: Dict[str, str] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read existing supplement %s: %s", out_path, e)
            existing = {}

    # Walk ledger records that lack market_regime
    ledger = SignalLedger(path=ledger_path)
    try:
        records = ledger.read()
    except FileNotFoundError:
        logger.info("No ledger at %s — nothing to backfill.", ledger_path)
        return 0

    store = ReplayStore(storage_dir=storage_dir)
    enriched = dict(existing)
    newly_added = 0
    for rec in records:
        if rec.market_regime:
            continue  # ledger already has it
        if rec.run_id in enriched and enriched[rec.run_id]:
            continue  # supplement already has it
        trace = store.load(rec.run_id)
        if trace is None:
            continue
        mctx = getattr(trace, "market_context", {}) or {}
        regime = str(mctx.get("regime", "") or "").upper()
        if regime:
            enriched[rec.run_id] = regime
            newly_added += 1

    # Atomic write via temp+rename
    content = json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp", prefix=".regime-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(out_path))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    logger.info(
        "Regime supplement: %d total entries (%d newly added). Written to %s",
        len(enriched), newly_added, out_path
    )
    return newly_added


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    added = backfill_regime_supplement()
    print(f"Backfill complete: {added} records newly enriched.")


if __name__ == "__main__":
    main()
