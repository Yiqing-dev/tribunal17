"""Daily ticker watchlist parsing helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .signal_ledger import normalize_ticker
from .trace_models import _now_cst

logger = logging.getLogger(__name__)


WATCHLIST_FILENAME = "daily_watchlist.json"
_TICKER_RE = re.compile(r"^\d{6}(?:\.(?:SS|SZ|BJ|SH|XSHG|XSHE))?$", re.IGNORECASE)
_KNOWN_STOCK_ALIASES = {
    "中国核电": "601985",
    "华测导航": "300627",
    "利欧股份": "002131",
    "宿迁联盛": "603065",
    "华大基因": "300676",
    "山东药玻": "600529",
    "贝瑞基因": "000710",
    "东方生物": "688298",
    "比亚迪": "002594",
    "贵州茅台": "600519",
    "茅台": "600519",
    "五粮液": "000858",
}


@dataclass(frozen=True)
class WatchlistItem:
    ticker: str
    name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_watchlist_ticker(value: str) -> str:
    """Normalize a user-supplied A-share code to the repo's ticker format."""
    raw = str(value or "").strip().strip("\"'")
    raw = raw.upper().replace(".SH", ".SS").replace(".XSHG", ".SS").replace(".XSHE", ".SZ")
    return normalize_ticker(raw)


def is_valid_watchlist_ticker(value: str) -> bool:
    return bool(re.match(r"^\d{6}\.(?:SS|SZ|BJ)$", str(value or "").strip().upper()))


def resolve_stock_name(name: str) -> str:
    """Resolve a Chinese stock name to a normalized ticker using local aliases.

    This deliberately avoids network calls.  Users can extend resolution by
    placing a JSON mapping in ``stock_aliases.json`` or
    ``data/stock_aliases.json``.
    """
    key = _name_key(name)
    if not key:
        return ""
    aliases = _load_stock_aliases()
    ticker = aliases.get(key)
    return normalize_watchlist_ticker(ticker) if ticker else ""


def parse_ticker_args(values: Optional[str | Sequence[str]]) -> List[WatchlistItem]:
    """Parse command-line ticker arguments.

    Accepted forms:
      - "600519,000858,002594"
      - "600519 000858 002594"
      - ["600519", "000858"]
      - "600519:贵州茅台,000858:五粮液"
    """
    if not values:
        return []
    parts: List[str] = []
    raw_values = [values] if isinstance(values, str) else list(values)
    for value in raw_values:
        parts.extend(x for x in re.split(r"[\s,;，；|｜]+", str(value or "")) if x.strip())
    return _dedupe(_parse_token(p) for p in parts)


def parse_court_command(text: str) -> List[WatchlistItem]:
    """Parse ``论衡十七司，升堂！【...】`` into a daily watchlist.

    The command is intended for Claude Code / Codex conversations, but accepting
    it here also lets local scripts consume the same phrase directly.
    """
    raw = str(text or "").strip()
    if not raw or "论衡十七司" not in raw or "升堂" not in raw:
        return []

    body = ""
    m = re.search(r"[【\[](?P<body>.*?)[】\]]", raw)
    if m:
        body = m.group("body")
    elif "升堂" in raw:
        body = raw.split("升堂", 1)[1]
        body = body.lstrip("!！:：,，;；、 \t")
    if not body:
        return []

    chunks = [x.strip() for x in re.split(r"[,，、;；|｜\n]+", body) if x.strip()]
    items = []
    for chunk in chunks:
        item = _parse_court_chunk(chunk)
        if item:
            items.append(item)
    return _dedupe(items)


def parse_tickers_file(path: str | Path) -> List[WatchlistItem]:
    """Parse a watchlist file.

    Each non-empty line may be one of:
      - 600519
      - 600519 贵州茅台
      - 600519,贵州茅台
      - 600519:贵州茅台
    Lines starting with ``#`` are ignored.
    """
    p = Path(path)
    items: List[WatchlistItem] = []
    for raw_line in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        items.append(_parse_line(line))
    return _dedupe(items)


def load_watchlist(
    *,
    tickers: Optional[str | Sequence[str]] = None,
    tickers_file: str | Path | None = None,
    command_text: str = "",
) -> List[WatchlistItem]:
    """Load and de-duplicate a daily watchlist from CLI args and/or a file."""
    items: List[WatchlistItem] = []
    items.extend(parse_court_command(command_text))
    items.extend(parse_ticker_args(tickers))
    if tickers_file:
        items.extend(parse_tickers_file(tickers_file))
    return _dedupe(items)


def save_watchlist(items: Sequence[WatchlistItem], output_dir: str | Path) -> Path:
    """Persist the daily watchlist next to generated workbench artifacts."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / WATCHLIST_FILENAME
    payload = {
        "generated_at": _now_cst().isoformat(),
        "tickers": [item.to_dict() for item in items],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix=".daily-watchlist-")
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


def watchlist_names(items: Iterable[WatchlistItem]) -> dict[str, str]:
    return {item.ticker: item.name for item in items if item.name}


def _parse_token(token: str) -> WatchlistItem:
    code, name = _split_code_name(token)
    if not _looks_like_ticker(code):
        resolved = resolve_stock_name(code)
        if resolved:
            return WatchlistItem(resolved, name.strip() or code.strip())
    return WatchlistItem(normalize_watchlist_ticker(code), name.strip())


def _parse_line(line: str) -> WatchlistItem:
    code, name = _split_code_name(line)
    if not _looks_like_ticker(code):
        resolved = resolve_stock_name(code)
        if resolved:
            return WatchlistItem(resolved, name.strip() or code.strip())
    return WatchlistItem(normalize_watchlist_ticker(code), name.strip())


def _parse_court_chunk(chunk: str) -> WatchlistItem | None:
    m = re.search(r"(?<!\d)(\d{6})(?:\.(?:SS|SZ|BJ|SH|XSHG|XSHE))?(?!\d)", chunk, re.IGNORECASE)
    if not m:
        resolved = resolve_stock_name(chunk)
        return WatchlistItem(resolved, chunk.strip()) if resolved else None
    code = m.group(0)
    name = (chunk[:m.start()] + " " + chunk[m.end():]).strip(" \t-_/|:：()（）[]【】")
    return WatchlistItem(normalize_watchlist_ticker(code), name)


def _split_code_name(text: str) -> tuple[str, str]:
    text = str(text or "").strip()
    for sep in (":", "=", ",", "，", "\t"):
        if sep in text:
            code, name = text.split(sep, 1)
            return code.strip(), name.strip()
    parts = text.split(None, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text, ""


def _dedupe(items: Iterable[WatchlistItem]) -> List[WatchlistItem]:
    out: List[WatchlistItem] = []
    positions: dict[str, int] = {}
    dropped: List[str] = []
    for item in items:
        ticker = normalize_watchlist_ticker(item.ticker)
        if not ticker or not is_valid_watchlist_ticker(ticker):
            # Don't silently swallow names that couldn't resolve to a ticker —
            # the user asked for them, so warn (e.g. a 中文名 not in the alias
            # table), otherwise "N requested, M researched" goes unnoticed.
            label = (item.name or item.ticker or "").strip()
            if label:
                dropped.append(label)
            continue
        name = item.name.strip()
        if ticker in positions:
            idx = positions[ticker]
            if name and not out[idx].name:
                out[idx] = WatchlistItem(ticker, name)
            continue
        positions[ticker] = len(out)
        out.append(WatchlistItem(ticker, name))
    if dropped:
        logger.warning(
            "watchlist: dropped %d unresolved entr%s (no valid ticker): %s",
            len(dropped), "y" if len(dropped) == 1 else "ies", ", ".join(dropped),
        )
    return out


def _looks_like_ticker(value: str) -> bool:
    return bool(_TICKER_RE.match(str(value or "").strip()))


def _name_key(value: str) -> str:
    return re.sub(r"[\s·・（）()【】\[\]{}<>《》,，;；:：]+", "", str(value or "").strip())


def _load_stock_aliases() -> dict[str, str]:
    aliases = {_name_key(k): v for k, v in _KNOWN_STOCK_ALIASES.items()}
    aliases.update(_read_alias_file(Path(__file__).resolve().parent / "stock_aliases.json"))
    aliases.update(_read_alias_file(Path.cwd() / "stock_aliases.json"))
    aliases.update(_read_alias_file(Path.cwd() / "data" / "stock_aliases.json"))
    aliases.update(_read_alias_file(Path.cwd() / "data" / "stock_name_aliases.json"))
    return aliases


def _read_alias_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    items: list[tuple[str, str]] = []
    if isinstance(data, dict):
        items = [(str(k), str(v)) for k, v in data.items()]
    elif isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("ticker_name") or row.get("名称") or "")
            ticker = str(row.get("ticker") or row.get("code") or row.get("代码") or "")
            if name and ticker:
                items.append((name, ticker))
    out: dict[str, str] = {}
    for name, ticker in items:
        nt = normalize_watchlist_ticker(ticker)
        if _name_key(name) and is_valid_watchlist_ticker(nt):
            out[_name_key(name)] = nt
    return out
