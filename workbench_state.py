"""Persistent state helpers for the static workbench.

The HTML workbench can run fully static with ``localStorage``.  When served by
``workbench_server.py`` it can also write the same state back to
``workbench_state.json`` through a small local API.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict


STATE_FILENAME = "workbench_state.json"
_STATE_LOCK = threading.RLock()


def state_path(output_dir: str | Path = "data/reports") -> Path:
    return Path(output_dir) / STATE_FILENAME


def load_workbench_state(output_dir: str | Path = "data/reports") -> Dict[str, Any]:
    """Load persisted workbench state, returning ``{}`` if absent/invalid."""
    path = state_path(output_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return _sanitize_state(data)


def save_workbench_state(state: Dict[str, Any], output_dir: str | Path = "data/reports") -> Path:
    """Write workbench state atomically."""
    with _STATE_LOCK:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = state_path(out)
        clean = _sanitize_state(state)
        content = json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False)
        fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".workbench-state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return path


def merge_workbench_state(
    incoming: Dict[str, Any],
    output_dir: str | Path = "data/reports",
) -> Dict[str, Any]:
    """Merge incoming browser state into persisted state and save."""
    with _STATE_LOCK:
        current = load_workbench_state(output_dir)
        for run_id, value in _sanitize_state(incoming).items():
            cur = dict(current.get(run_id) or {})
            cur.update(value)
            current[run_id] = cur
        save_workbench_state(current, output_dir)
        return current


def _sanitize_state(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for run_id, raw in data.items():
        rid = str(run_id or "")[:160]
        if not rid or not isinstance(raw, dict):
            continue
        item: Dict[str, Any] = {}
        for key in ("favorite", "read", "review", "ignore"):
            if key in raw:
                item[key] = bool(raw.get(key))
        if "note" in raw:
            item["note"] = str(raw.get("note") or "")[:1000]
        out[rid] = item
    return out
