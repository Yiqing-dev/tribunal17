"""Local data cache for akshare API calls.

Avoids redundant API calls when the same ticker+date+api combination
has already been collected in the current session or a previous run.

Cache key = SHA1(api_name + "|" + ticker + "|" + trade_date).
Storage: one JSON file per key in ``data/cache/``.

Usage:
    from subagent_pipeline.data_cache import DataCache

    cache = DataCache()                         # default: data/cache/
    cache = DataCache("custom/cache/dir")

    # Check + store
    hit = cache.get("price_history", "601985", "2026-04-04")
    if hit is not None:
        return hit  # cached data

    data = expensive_api_call()
    cache.put("price_history", "601985", "2026-04-04", data)
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DIR = "data/cache"


class DataCache:
    """File-backed data cache keyed by (api_name, ticker, trade_date).

    Thread-safe. Each entry is a standalone JSON file.
    """

    _DEFAULT_TTL_DAYS = 7

    def __init__(self, cache_dir: str = _DEFAULT_DIR, *, auto_evict: bool = True):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "writes": 0}
        if auto_evict:
            self.evict_older_than(self._DEFAULT_TTL_DAYS)

    # ── Key generation ───────────────────────────────────────────────

    @staticmethod
    def _cache_key(api_name: str, ticker: str, trade_date: str) -> str:
        """Stable SHA1 hash of (api_name, ticker, trade_date)."""
        raw = f"{api_name}|{ticker}|{trade_date}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    # ── Read ─────────────────────────────────────────────────────────

    def get(self, api_name: str, ticker: str, trade_date: str) -> Optional[Any]:
        """Return cached data or None on miss."""
        key = self._cache_key(api_name, ticker, trade_date)
        path = self._path(key)
        if not path.exists():
            self._stats["misses"] += 1
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._stats["hits"] += 1
            logger.debug("Cache HIT: %s %s %s", api_name, ticker, trade_date)
            return data.get("payload")
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Cache read error for %s: %s", key[:12], e)
            self._stats["misses"] += 1
            return None

    # ── Write ────────────────────────────────────────────────────────

    def put(self, api_name: str, ticker: str, trade_date: str, payload: Any) -> None:
        """Store data in cache.

        Atomic: write to a temp file in the same directory, then rename onto
        the target. Two concurrent writers to the same key end up with one
        intact file, never a half-truncated one. ``allow_nan=False`` makes
        invalid floats fail loudly here instead of poisoning future reads.
        """
        key = self._cache_key(api_name, ticker, trade_date)
        path = self._path(key)
        envelope = {
            "api_name": api_name,
            "ticker": ticker,
            "trade_date": trade_date,
            "payload": payload,
        }
        with self._lock:
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(
                    dir=str(path.parent), prefix=f".{key[:12]}-", suffix=".tmp",
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(envelope, f, ensure_ascii=False, default=str,
                              allow_nan=False)
                os.replace(tmp, str(path))
                tmp = None
                self._stats["writes"] += 1
            except (OSError, ValueError) as e:
                logger.debug("Cache write error for %s: %s", key[:12], e)
            finally:
                if tmp is not None:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    # ── Utilities ────────────────────────────────────────────────────

    def has(self, api_name: str, ticker: str, trade_date: str) -> bool:
        """Check if entry exists without loading."""
        return self._path(self._cache_key(api_name, ticker, trade_date)).exists()

    def invalidate(self, api_name: str, ticker: str, trade_date: str) -> bool:
        """Remove a single cache entry. Returns True if removed."""
        path = self._path(self._cache_key(api_name, ticker, trade_date))
        if path.exists():
            path.unlink()
            return True
        return False

    def evict_older_than(self, days: int = 7) -> int:
        """Remove cache files older than *days*. Returns count removed."""
        import time as _time
        cutoff = _time.time() - days * 86400
        count = 0
        for f in self._dir.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    count += 1
            except OSError:
                pass
        if count:
            logger.debug("Evicted %d cache files older than %d days", count, days)
        return count

    def clear(self) -> int:
        """Remove all cache files. Returns count removed."""
        count = 0
        for f in self._dir.glob("*.json"):
            f.unlink()
            count += 1
        self._stats = {"hits": 0, "misses": 0, "writes": 0}
        return count

    @property
    def stats(self) -> dict:
        """Return hit/miss/write counts."""
        total = self._stats["hits"] + self._stats["misses"]
        rate = self._stats["hits"] / total if total > 0 else 0.0
        return {**self._stats, "hit_rate": round(rate, 3)}

    def __repr__(self) -> str:
        return f"DataCache(dir={self._dir}, stats={self.stats})"
