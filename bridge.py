"""Bridge module — converts subagent pipeline text outputs into RunTrace objects
for the 3-tier report renderer.

Usage:
    from subagent_pipeline.bridge import generate_report
    paths = generate_report(outputs, "601985", "中国核电", "2026-03-12")
"""

import json
import logging
import math
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .trace_models import (
    NodeTrace,
    NodeStatus,
    RunTrace,
    compute_hash,
    _now_cst,
)
from .replay_store import ReplayStore
from .shared import (
    TAG_CATALYST_OUTPUT, TAG_RISK_OUTPUT, TAG_RISK_DEBATER_OUTPUT,
    TAG_MACRO_OUTPUT, TAG_BREADTH_OUTPUT, TAG_SECTOR_OUTPUT,
    TAG_SYNTHESIS_OUTPUT, TAG_SCENARIO_OUTPUT,
    TAG_TRADECARD_JSON, TAG_TRADE_PLAN_JSON,
    TAG_ORDER_PROPOSAL_JSON,
    normalize_confidence_value,
)

logger = logging.getLogger(__name__)

# N-BRG-1: English negation pattern for BUY/SELL inference (20-char window)
_ENG_NEG = re.compile(r'\b(?:NOT|NO|DONT|DON\'T|AVOID|NEVER|AGAINST)\b')

# N-BRG-3: Chinese negation pattern for 买入/卖出 inference (12-char window).
# "谨慎" removed — "谨慎买入" means "buy cautiously", not negation.
# Window widened from 5→12 to catch multi-char modifiers like "坚决不建议".
_NEG = re.compile(r'(?:不要|不宜|不建议|切勿|勿|避免|别|禁止|不应|不可|不得|不适合)')

# Double-negation markers: when one of these appears before a _NEG match,
# the overall sentence is affirmative — e.g., "并非不建议买入" = "certainly
# recommend buying". Scanned in a wider 24-char window preceding the keyword.
_DOUBLE_NEG = re.compile(r'(?:并非|绝非|并不是|并未|并无|并没)')


def _has_positive(text: str, kw: str) -> bool:
    """Return True if *kw* appears in *text* without a preceding Chinese negation.

    A double-negation marker (并非/绝非/…) appearing before the negation
    inverts the sign back to affirmative.
    """
    for m in re.finditer(re.escape(kw), text):
        window = text[max(0, m.start() - 12):m.start()]
        neg_match = _NEG.search(window)
        if neg_match:
            # Check a wider window for a double-negation marker preceding
            # the negation match (e.g., "并非不建议买入").
            wider = text[max(0, m.start() - 24):m.start()]
            neg_start_in_wider = wider.find(neg_match.group(0))
            if neg_start_in_wider > 0 and _DOUBLE_NEG.search(wider[:neg_start_in_wider]):
                return True
            continue
        return True
    return False


# ── Agent key → NodeTrace.node_name mapping ──────────────────────────────
# Must match NODE_NAME_LABELS in dashboard/decision_labels.py

AGENT_NODE_MAP = {
    "macro_analyst":        "Macro Analyst",
    "market_breadth_agent": "Market Breadth",
    "sector_rotation_agent": "Sector Rotation",
    "verification_agent":   "Data Verification",
    "market_analyst":       "Market Analyst",
    "fundamentals_analyst": "Fundamentals Analyst",
    "news_analyst":         "News Analyst",
    "sentiment_analyst":    "Social Analyst",
    "catalyst_agent":       "Catalyst Agent",
    "bull_researcher":      "Bull Researcher",
    "bear_researcher":      "Bear Researcher",
    "scenario_agent":       "Scenario Agent",
    "research_manager":     "Research Manager",
    "aggressive_debator":   "Aggressive Debator",
    "conservative_debator": "Conservative Debator",
    "neutral_debator":      "Neutral Debator",
    "risk_manager":         "Risk Judge",
    "research_output":      "ResearchOutput",
}

# Execution order for known agents
AGENT_SEQ = {
    "macro_analyst": 0,
    "market_breadth_agent": 1,
    "sector_rotation_agent": 2,
    "verification_agent": 3,
    "market_analyst": 4,
    "fundamentals_analyst": 5,
    "news_analyst": 6,
    "sentiment_analyst": 7,
    "catalyst_agent": 8,
    "bull_researcher": 9,
    "bear_researcher": 10,
    "scenario_agent": 11,
    "research_manager": 12,
    "aggressive_debator": 13,
    "conservative_debator": 14,
    "neutral_debator": 15,
    "risk_manager": 16,
    "research_output": 17,
}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  1. Parsers — extract structured blocks from agent free-text output    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def parse_pillar_score(text: str) -> Optional[int]:
    """Extract `pillar_score = N` from analyst output."""
    m = re.search(r'pillar_score\s*=\s*(\d+)', text)
    if m:
        return min(int(m.group(1)), 4)
    return None


def parse_catalyst_json(text: str) -> List[Dict]:
    """Extract CATALYST_OUTPUT: [...] JSON block."""
    # Handle markdown code block: CATALYST_OUTPUT:\n```json\n[...]\n```
    cb_m = re.search(
        rf'{TAG_CATALYST_OUTPUT}:\s*\n\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```', text
    )
    if cb_m:
        inner = cb_m.group(1).strip()
        if inner.startswith('['):
            text = text[:cb_m.start()] + f"{TAG_CATALYST_OUTPUT}:\n" + inner + text[cb_m.end():]

    # Find start of CATALYST_OUTPUT array
    start_m = re.search(rf'{TAG_CATALYST_OUTPUT}:\s*\n?\s*\[', text)
    if not start_m:
        return []
    # Find the matching closing bracket (string-aware to skip brackets inside "...")
    arr_start = start_m.end() - 1  # position of opening [
    depth = 0
    arr_end = arr_start
    in_str = False
    escape = False
    for i in range(arr_start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_str:
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                arr_end = i + 1
                break
    if arr_end <= arr_start:
        return []
    raw = text[arr_start:arr_end]
    # Fix common JSON issues: trailing commas, Python-style literals.
    raw_fixed = re.sub(r',\s*]', ']', raw)
    raw_fixed = re.sub(r',\s*}', '}', raw_fixed)
    raw_fixed = re.sub(r'\bTrue\b', 'true', raw_fixed)
    raw_fixed = re.sub(r'\bFalse\b', 'false', raw_fixed)
    raw_fixed = re.sub(r'\bNone\b', 'null', raw_fixed)
    try:
        catalysts = json.loads(raw_fixed)
        if isinstance(catalysts, list):
            return catalysts
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse CATALYST_OUTPUT JSON: {e}; attempting per-object rescue")
    # Rescue pass: walk top-level brace-balanced {...} objects inside the array
    # and parse each individually. A single malformed item won't nuke the rest.
    items: List[Dict] = []
    depth = 0
    obj_start = -1
    in_str = False
    escape = False
    for i in range(arr_start + 1, arr_end - 1):
        c = raw[i - arr_start] if (i - arr_start) < len(raw) else ""
        # Use text[i] not raw[offset] to keep the loop simple.
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_str:
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and obj_start >= 0:
                chunk = text[obj_start:i + 1]
                chunk = re.sub(r',\s*}', '}', chunk)
                chunk = re.sub(r'\bTrue\b', 'true', chunk)
                chunk = re.sub(r'\bFalse\b', 'false', chunk)
                chunk = re.sub(r'\bNone\b', 'null', chunk)
                try:
                    parsed = json.loads(chunk)
                    if isinstance(parsed, dict):
                        items.append(parsed)
                except (json.JSONDecodeError, ValueError):
                    pass  # skip malformed item, keep others
                obj_start = -1
    if items:
        logger.warning(f"CATALYST_OUTPUT per-object rescue: recovered {len(items)} items")
    return items


def _parse_kv_block(block: str, parse_arrays: bool = False) -> Dict[str, Any]:
    """Parse a key=value block supporting multiline values.

    Keys are `[a-zA-Z_]+`, values span until the next key or end of block.
    When *parse_arrays* is True, values like ``[E1, E3]`` become lists.
    """
    result: Dict[str, Any] = {}
    for match in re.finditer(
        r'^([a-zA-Z_]\w*)\s*=\s*([\s\S]*?)(?=\n[a-zA-Z_]\w*\s*=|\Z)',
        block, re.MULTILINE,
    ):
        key = match.group(1).strip()
        val = match.group(2).strip()

        # Arrays like [E1, E3, E5] or [{"name": "x", ...}, ...]
        if parse_arrays and val.startswith('[') and val.endswith(']'):
            # If it looks like a JSON array of objects, parse with json.loads
            if val.startswith('[{'):
                try:
                    raw = val
                    raw = re.sub(r',\s*]', ']', raw)
                    raw = re.sub(r',\s*}', '}', raw)
                    raw = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', raw)
                    result[key] = json.loads(raw)
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass  # fall through to simple split
            items = [x.strip().strip('"\'') for x in val[1:-1].split(',') if x.strip()]
            result[key] = items
        else:
            # BRG-01: the LAST field's multiline value can absorb a trailing
            # prose paragraph (the value regex runs to end-of-block). For scalar
            # coercion, also try just the FIRST line, so
            # "confidence = 0.72\n<trailing prose>" → 0.72 instead of silently
            # falling back to a string (and then a default). Genuine multiline
            # string values stay strings (their first line isn't a scalar).
            first_line = val.split('\n', 1)[0].strip()
            coerced = None
            for candidate in (val, first_line):
                cu = candidate.upper()
                if cu in ('TRUE', 'YES'):
                    coerced = True
                    break
                if cu in ('FALSE', 'NO'):
                    coerced = False
                    break
                try:
                    fv = float(candidate)
                except ValueError:
                    continue
                if not (math.isnan(fv) or math.isinf(fv)):
                    coerced = fv
                    break
            result[key] = coerced if coerced is not None else val
    return result


def _extract_tagged_block(tag: str, text: str) -> str:
    """Extract content after TAG: header, handling three formats:
    1. TAG:\\n key=value lines
    2. TAG:\\n { json }
    3. TAG:\\n ```json\\n { json }\\n ```
    """
    # Format 3: TAG:\n```json\n...\n```
    m = re.search(
        rf'{tag}:\s*\n\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```',
        text,
    )
    if m:
        return m.group(1)
    # Format 1 & 2: TAG:\n content (until next ``` or end)
    m = re.search(rf'{tag}:\s*\n([\s\S]*?)(?:\n```|\Z)', text)
    if m:
        return m.group(1)
    # Inside a code block: ```\nTAG:\ncontent\n```
    m = re.search(rf'```\s*\n?\s*{tag}:\s*\n([\s\S]*?)\s*```', text)
    if m:
        return m.group(1)
    return ""


def _try_json_parse(block: str) -> Optional[Dict[str, Any]]:
    """Try to parse a block as JSON object.  Returns None on failure.

    Uses json.JSONDecoder for robust brace matching (handles braces inside strings).
    """
    stripped = block.strip()
    if not stripped.startswith('{'):
        return None
    decoder = json.JSONDecoder()
    # Try raw parse first — only apply regex fixups if raw fails
    try:
        obj, _ = decoder.raw_decode(stripped)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: fix trailing commas (may damage string contents, but
    # the raw parse above already failed, so this is best-effort)
    cleaned = re.sub(r',\s*}', '}', stripped)
    cleaned = re.sub(r',\s*]', ']', cleaned)
    try:
        obj, _ = decoder.raw_decode(cleaned)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def parse_scenario_output(text: str) -> Dict[str, Any]:
    """Extract SCENARIO_OUTPUT: key=value or JSON block."""
    block = _extract_tagged_block(TAG_SCENARIO_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_synthesis_output(text: str) -> Dict[str, Any]:
    """Extract SYNTHESIS_OUTPUT: key=value or JSON block."""
    block = _extract_tagged_block(TAG_SYNTHESIS_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block, parse_arrays=True)


def parse_risk_output(text: str) -> Dict[str, Any]:
    """Extract RISK_OUTPUT: block including risk_flags array."""
    result = {}
    block = _extract_tagged_block(TAG_RISK_OUTPUT, text)
    if not block:
        return result

    # Try JSON first — agents sometimes output full JSON objects
    j = _try_json_parse(block)
    if j is not None:
        # Normalize boolean strings
        if isinstance(j.get("risk_cleared"), str):
            j["risk_cleared"] = j["risk_cleared"].upper() in ("TRUE", "YES", "1")
        return j

    def _array_assignment(src: str, key: str) -> Tuple[Optional[str], str]:
        """Extract ``key = [...]`` from a key/value block.

        Regex is brittle for arrays of objects because it stops at the first
        ``]`` inside a value. Walk brackets instead so risk_flags and
        invalidation_conditions can both be parsed from one RISK_OUTPUT block.
        """
        m = re.search(rf'(^|\n)\s*{re.escape(key)}\s*=\s*\[', src)
        if not m:
            return None, src
        arr_start = src.find("[", m.start())
        depth = 0
        in_str = False
        escape = False
        for i in range(arr_start, len(src)):
            ch = src[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return src[arr_start:i + 1], src[:m.start()] + "\n" + src[i + 1:]
        return None, src

    def _parse_array_value(raw: str, *, key: str) -> list:
        cleaned = re.sub(r',\s*]', ']', raw)
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r'\bTrue\b', 'true', cleaned)
        cleaned = re.sub(r'\bFalse\b', 'false', cleaned)
        cleaned = re.sub(r'\bNone\b', 'null', cleaned)
        cleaned = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', cleaned)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError) as e:
            if key == "risk_flags":
                logger.warning("risk_flags JSON parse failed, defaulting to []: %s", e)
                result["_risk_flags_parse_failed"] = True
                return []
            # LLMs sometimes emit unquoted string arrays. Preserve useful text
            # rather than dropping all falsifiability triggers.
            inner = raw[1:-1] if raw.startswith("[") and raw.endswith("]") else raw
            items = []
            for line in inner.splitlines():
                item = line.strip().strip(",").strip().strip('"').strip("'")
                if item:
                    items.append(item)
            return items

    for array_key in ("risk_flags", "invalidation_conditions"):
        raw_arr, block = _array_assignment(block, array_key)
        if raw_arr is not None:
            result[array_key] = _parse_array_value(raw_arr, key=array_key)

    for line in block.strip().split('\n'):
        line = line.strip()
        if '=' not in line or line.startswith('{') or line.startswith('['):
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip()
        if key in ("risk_flags", "invalidation_conditions"):
            continue
        if val.upper() == 'TRUE':
            result[key] = True
        elif val.upper() == 'FALSE':
            result[key] = False
        else:
            try:
                result[key] = float(val) if '.' in val else int(val)
            except ValueError:
                result[key] = val
    return result


def parse_risk_debater_output(text: str) -> Dict[str, Any]:
    """Extract RISK_DEBATER_OUTPUT: key=value block from risk debater output."""
    block = _extract_tagged_block(TAG_RISK_DEBATER_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def _iter_json_code_blocks(text: str):
    """Yield (label_or_empty, json_str) for each fenced code block containing JSON."""
    # Match optional label on line before code fence, then the code block content.
    # Two patterns: labeled (label on preceding line) and bare (code fence at start).
    _JSON_TAGS = (TAG_TRADECARD_JSON, TAG_TRADE_PLAN_JSON, TAG_ORDER_PROPOSAL_JSON)
    _tags_re = "|".join(re.escape(t) for t in _JSON_TAGS)
    for m in re.finditer(
        rf'(?:(?:^|\n)\s*(?:#{{0,4}}\s*)?({_tags_re})[:\s]*\n'
        r'\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```'
        r'|(?:^|\n)\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```)',
        text,
    ):
        # group(1)+group(2) for labeled match, group(3) for bare match
        label = (m.group(1) or "").strip()
        body = (m.group(2) or m.group(3) or "").strip()
        # Some LLMs emit the tag label both *before* the fence AND on the first
        # line *inside* the fence (belt-and-suspenders). Strip a leading
        # `TAG_NAME:` / `TAG_NAME` line from the body unconditionally — covers
        # Format D (bare fence w/ label inside) and the duplicate-label case.
        for tag in _JSON_TAGS:
            if body.startswith(tag):
                if not label:
                    label = tag
                body = body[len(tag):].lstrip(":").strip()
                break
        yield label, body


def parse_tradecard_json(text: str) -> Dict[str, Any]:
    """Extract TRADECARD_JSON code block."""
    # Priority 1: labeled block
    for label, body in _iter_json_code_blocks(text):
        if label == TAG_TRADECARD_JSON and body.startswith('{'):
            try:
                raw = re.sub(r',\s*}', '}', body)
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
    # Priority 2: first unlabeled JSON block containing "symbol" — but NOT an
    # ORDER_PROPOSAL block. Order proposals also carry "symbol"/"side"; identify
    # them by their order-execution keys and skip, so an (unlabeled) order
    # proposal is never mis-read as a trade card (BRG-06).
    _ORDER_MARKERS = ('"order_type"', '"qty"', '"quantity"',
                      '"limit_price"', '"time_in_force"')
    for label, body in _iter_json_code_blocks(text):
        if not label and body.startswith('{') and '"symbol"' in body:
            if any(mk in body for mk in _ORDER_MARKERS):
                continue
            try:
                raw = re.sub(r',\s*}', '}', body)
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
    # Priority 3: key=value block with TRADECARD label
    m = re.search(r'TRADECARD[:\s]*\n((?:\s*\w+\s*=.*\n?)+)', text)
    if m:
        return _parse_kv_block(m.group(1))
    return {}


def parse_trade_plan_json(text: str) -> Dict[str, Any]:
    """Extract TRADE_PLAN_JSON code block.

    Returns the trade_plan dict (unwrapped from outer envelope if present).
    """

    def _try_parse_trade_plan(raw: str) -> Optional[Dict]:
        raw = re.sub(r',\s*}', '}', raw)
        raw = re.sub(r',\s*]', ']', raw)
        try:
            parsed = json.loads(raw)
            if "trade_plan" in parsed and isinstance(parsed["trade_plan"], dict):
                return parsed["trade_plan"]
            return parsed
        except (json.JSONDecodeError, ValueError):
            return None

    # Priority 1: labeled block
    for label, body in _iter_json_code_blocks(text):
        if label == TAG_TRADE_PLAN_JSON and body.startswith('{'):
            result = _try_parse_trade_plan(body)
            if result is not None:
                return result
    # Priority 2: unlabeled JSON block containing "trade_plan" or "bias"
    for label, body in _iter_json_code_blocks(text):
        if not label and body.startswith('{'):
            if '"trade_plan"' in body or '"bias"' in body:
                result = _try_parse_trade_plan(body)
                if result is not None:
                    return result
    # Priority 3: key=value block with TRADE_PLAN label
    m = re.search(r'TRADE_PLAN[:\s]*\n((?:\s*\w+\s*=.*\n?)+)', text)
    if m:
        return _parse_kv_block(m.group(1))
    return {}


def parse_claims(text: str, direction: str = "bullish") -> List[Dict]:
    """Extract CLAIM:/EVIDENCE:/CONFIDENCE:/INVALIDATION: blocks."""
    claims = []
    # Split on CLAIM markers — handles:
    #   "CLAIM: ...", "### CLAIM 1: ...", "## CLAIM 2: ..."
    #   "CLAIM [clm-bull-1]：..."  (bracket ID + Chinese colon)
    # Capture the LLM's own [clm-xNNN] id (group 1) alongside each block; with the
    # capturing group re.split yields [pre, id1, block1, id2, block2, ...] where
    # idN is None when no bracket id was given.
    parts = re.split(r'\n(?:#{1,4}\s*)?CLAIM(?:\s*\d+)?(?:\s*\[([\w-]+)\])?[：:]\s*', text)
    prefix = 'u' if direction == 'bullish' else 'r'
    _seen_ids: set = set()
    for k in range(1, len(parts), 2):  # (id, block) pairs after the leading pre-text
        cap_id = (parts[k] or "").strip()
        part = parts[k + 1] if k + 1 < len(parts) else ""
        pos = (k + 1) // 2  # 1-based positional index
        # AQ-04/AQ-F6: preserve the LLM's own clm-uNNN / clm-rNNN id (what
        # parse_rebuttals / parse_adjudications reference) when it is well-formed;
        # fall back to a positional id only when it is absent or malformed.
        if re.fullmatch(rf'clm-{prefix}\d+', cap_id, re.IGNORECASE):
            cid = cap_id.lower()
        else:
            cid = f"clm-{prefix}{pos:03d}"
        # R1/R2 merge can restate the SAME id for a different claim — keep unique
        # so downstream references resolve to one claim, not double-count.
        if cid in _seen_ids:
            _n = 2
            while f"{cid}-{_n}" in _seen_ids:
                _n += 1
            cid = f"{cid}-{_n}"
        _seen_ids.add(cid)
        claim = {
            "claim_id": cid,
            "direction": direction,
        }
        # Extract claim text (first line)
        lines = part.strip().split('\n')
        claim["text"] = lines[0].strip()

        # Extract evidence — multi-tier fallback:
        # 1) Bracket-list with E# IDs:        EVIDENCE: [E1, E3]
        # 2) Bracket-list with report names:   EVIDENCE: [基本面报告-ROE, 技术面报告]
        # 3) Prose with inline E# refs:        EVIDENCE: 来源 E1 ... E3
        # 4) Substantive prose (≥10 chars):    EVIDENCE: 基本面报告B3节ROE数据
        ev_m = re.search(r'(?:EVIDENCE|证据|来源)\s*[:：]\s*\[([^\]]*)\]', part, re.IGNORECASE)
        if ev_m:
            ids = [x.strip() for x in ev_m.group(1).split(',') if x.strip()]
            claim["supports"] = ids
        else:
            ev_prose = re.search(
                r'(?:EVIDENCE|证据|来源)\s*[:：]\s*(.+?)(?=\nCONFIDENCE|\nINVALIDATION|\nCLAIM|\Z)',
                part, re.DOTALL | re.IGNORECASE,
            )
            if ev_prose:
                prose_text = ev_prose.group(1).strip()
                ids = re.findall(r'\bE\d+\b', prose_text)
                if ids:
                    claim["supports"] = list(dict.fromkeys(ids))
                elif len(prose_text) >= 10:
                    claim["supports"] = [f"prose-{prefix}{pos:03d}"]
                    claim["evidence_prose"] = prose_text[:300]
                else:
                    claim["supports"] = []
            else:
                # Fallback: extract inline [E#] refs from claim text itself
                inline_ids = re.findall(r'\[E(\d+)\]', claim["text"])
                if inline_ids:
                    claim["supports"] = [f"E{eid}" for eid in inline_ids]
                else:
                    claim["supports"] = []

        # Extract confidence
        conf_m = re.search(r'CONFIDENCE:\s*([\d.]+)', part)
        if conf_m:
            claim["confidence"] = float(conf_m.group(1))
            # Normalize: if agent used 0-100 scale (>= 10 catches 10-100)
            if claim["confidence"] >= 10:
                claim["confidence"] = claim["confidence"] / 100.0
            # Normalize: if agent used 1-10 scale despite 0.0-1.0 instruction
            elif claim["confidence"] > 1.0:
                claim["confidence"] = claim["confidence"] / 10.0
            claim["confidence"] = max(0.0, min(1.0, claim["confidence"]))
        else:
            # Sentinel: agent did not provide confidence. Matches
            # normalize_confidence_value's -1.0 sentinel.
            # Downstream aggregators must filter `>= 0` to avoid polluting averages.
            claim["confidence"] = -1.0

        # Extract invalidation
        inv_m = re.search(r'INVALIDATION:\s*(.+)', part)
        if inv_m:
            claim["invalidation"] = inv_m.group(1).strip()
        else:
            claim["invalidation"] = ""

        claims.append(claim)
    return claims


def parse_evidence_citations(text: str) -> List[str]:
    """Extract CITED_EVIDENCE: [E1, E3] block."""
    m = re.search(r'CITED_EVIDENCE:\s*\[([^\]]*)\]', text)
    if m:
        return [x.strip() for x in m.group(1).split(',') if x.strip()]
    # Fallback: collect all [E#] references (preserve order)
    return list(dict.fromkeys(re.findall(r'\bE\d+\b', text)))


# ── Market-level parsers ──────────────────────────────────────────────


class StaleMarketDataError(ValueError):
    """Raised when market agent outputs contain a date that doesn't match the target trade date."""
    pass


def _extract_content_date(text: str) -> Optional[str]:
    """Extract report date from the first 500 chars of agent output text.

    Matches:
        "2026年3月24日"  → "2026-03-24"
        "2026-03-24"     → "2026-03-24"
    """
    head = text[:500] if text else ""
    # Chinese format: YYYY年M月D日
    m = re.search(r'(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5', head)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # ISO format
    m = re.search(r'(\d{4}-\d{2}-\d{2})', head)
    if m:
        return m.group(1)
    return None


def validate_market_agent_dates(
    trade_date: str,
    macro_text: str = "",
    breadth_text: str = "",
    sector_text: str = "",
) -> None:
    """Validate that market agent output dates match *trade_date*.

    Raises :class:`StaleMarketDataError` if any output contains a content date
    that doesn't match.  Silently passes when no date can be extracted.
    """
    mismatches: List[str] = []
    for label, text in [
        ("macro_analyst", macro_text),
        ("market_breadth", breadth_text),
        ("sector_rotation", sector_text),
    ]:
        if not text:
            continue
        content_date = _extract_content_date(text)
        if content_date and content_date != trade_date:
            mismatches.append(
                f"{label}: content date {content_date} != target {trade_date}"
            )
    if mismatches:
        raise StaleMarketDataError(
            f"Stale market data detected — agent outputs do not match "
            f"trade_date {trade_date}:\n  " + "\n  ".join(mismatches)
        )


def parse_macro_output(text: str) -> Dict[str, Any]:
    """Extract MACRO_OUTPUT: key=value block."""
    block = _extract_tagged_block(TAG_MACRO_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_breadth_output(text: str) -> Dict[str, Any]:
    """Extract BREADTH_OUTPUT: key=value block."""
    block = _extract_tagged_block(TAG_BREADTH_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_sector_output(text: str) -> Dict[str, Any]:
    """Extract SECTOR_OUTPUT: key=value block with array fields."""
    block = _extract_tagged_block(TAG_SECTOR_OUTPUT, text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    result = _parse_kv_block(block, parse_arrays=True)

    # Parse sector_momentum JSON array if present as string
    momentum_raw = result.get("sector_momentum")
    if isinstance(momentum_raw, str) and momentum_raw.strip().startswith("["):
        try:
            raw = momentum_raw.strip()
            raw = re.sub(r',\s*]', ']', raw)
            raw = re.sub(r',\s*}', '}', raw)
            raw = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', raw)
            result["sector_momentum"] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return result


def assemble_market_context(
    macro: Dict[str, Any],
    breadth: Dict[str, Any],
    sector: Dict[str, Any],
    trade_date: str = "",
    global_macro: Optional[Dict[str, str]] = None,
    *,
    raw_texts: Optional[Dict[str, str]] = None,
    strict_date_check: bool = False,
) -> Dict[str, Any]:
    """Combine 3 market agent outputs into a canonical market_context dict.

    Args:
        global_macro: Parsed output from web_collector.parse_global_macro_output().
            When provided, merged as ``market_context["global_macro"]`` and
            geopolitical risks are appended to ``risk_alerts``.
        raw_texts: Optional dict of raw agent output texts keyed by
            ``"macro"``, ``"breadth"``, ``"sector"``.  When provided *and*
            *trade_date* is set, each text's embedded content date is validated
            against *trade_date*.
        strict_date_check: When True, raises ``StaleMarketDataError`` on date
            mismatch instead of logging a warning.  Use this in production
            orchestration to prevent stale L1 data from poisoning downstream.
    """
    # ── Date validation guard ──
    if raw_texts and trade_date:
        try:
            validate_market_agent_dates(
                trade_date,
                macro_text=raw_texts.get("macro", ""),
                breadth_text=raw_texts.get("breadth", ""),
                sector_text=raw_texts.get("sector", ""),
            )
        except StaleMarketDataError as e:
            if strict_date_check:
                raise
            logger.warning("Date mismatch (non-fatal): %s", e)

    regime = str(macro.get("regime") or "NEUTRAL").upper()
    breadth_state = str(breadth.get("breadth_state") or "NARROW").upper()

    # Normalize position_cap_multiplier
    pcm = macro.get("position_cap_multiplier", 0.8)
    if isinstance(pcm, str):
        try:
            pcm = float(pcm)
        except ValueError:
            pcm = 0.8

    # Normalize sector lists
    leaders = sector.get("sector_leaders", [])
    if isinstance(leaders, str):
        leaders = [s.strip() for s in leaders.split(",") if s.strip()]
    avoid = sector.get("avoid_sectors", [])
    if isinstance(avoid, str):
        avoid = [s.strip() for s in avoid.split(",") if s.strip()]

    # Build client summary
    client_summary = str(macro.get("client_summary", ""))
    if not client_summary:
        weather = str(macro.get("market_weather", ""))
        client_summary = f"市场状态: {regime}。{weather}" if weather else f"市场状态: {regime}"

    result = {
        "trade_date": trade_date,
        # Macro
        "regime": regime,
        "market_weather": str(macro.get("market_weather", "")),
        "position_cap_multiplier": pcm,
        "style_bias": str(macro.get("style_bias", "均衡")),
        "risk_alerts": "，".join(macro["risk_alerts"]) if isinstance(macro.get("risk_alerts"), list) else str(macro.get("risk_alerts", "")),
        "client_summary": client_summary,
        # Breadth
        "breadth_state": breadth_state,
        "advance_decline_ratio": breadth.get("advance_decline_ratio", ""),
        "breadth_trend": str(breadth.get("breadth_trend", "")),
        "breadth_risk_note": str(breadth.get("risk_note", "")),
        # Sector
        "sector_leaders": leaders,
        "avoid_sectors": avoid,
        "rotation_phase": str(sector.get("rotation_phase", "")),
        "sector_momentum": sector.get("sector_momentum", []),
    }

    # Normalize sector_momentum flow values: LLM agents sometimes return
    # strings like "+33.92亿" instead of numeric 33.92.  Strip non-numeric
    # chars so downstream renderers can float() them safely.
    for m in result.get("sector_momentum", []):
        if isinstance(m, dict) and isinstance(m.get("flow"), str):
            raw = m["flow"]
            cleaned = re.sub(r'[^\d.\-]', '', raw)
            try:
                m["flow"] = str(float(cleaned))
            except (ValueError, TypeError):
                pass  # leave as-is if completely unparseable

    # Enrich sector_momentum: if LLM agent only returned inflow sectors,
    # the momentum list will lack outflow entries.  Detect this and flag it
    # so downstream renderers know the data is one-sided.
    momentum = result.get("sector_momentum", [])
    has_outflow = any(
        isinstance(m, dict) and m.get("direction") == "out" for m in momentum
    )
    if not has_outflow and momentum:
        result["_sector_momentum_inflow_only"] = True

    # Merge global macro web data when available
    if global_macro:
        from .web_collector import merge_global_macro_into_context
        result = merge_global_macro_into_context(result, global_macro)

    return result


def format_market_context_block(ctx: Dict[str, Any]) -> str:
    """Format market_context dict as a text block for injection into per-ticker prompts."""
    if not ctx:
        return ""
    def _safe_join(items):
        return ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in items) or "无"
    leaders = _safe_join(ctx.get("sector_leaders", []))
    avoid = _safe_join(ctx.get("avoid_sectors", []))
    block = (
        f"市场 Regime: {ctx.get('regime', 'NEUTRAL')}\n"
        f"市场天气: {ctx.get('market_weather', '')}\n"
        f"仓位乘数 (position_cap_multiplier): {ctx.get('position_cap_multiplier', 0.8)}\n"
        f"风格偏好: {ctx.get('style_bias', '均衡')}\n"
        f"宽度状态: {ctx.get('breadth_state', 'NARROW')}\n"
        f"涨跌比: {ctx.get('advance_decline_ratio', '')}\n"
        f"宽度趋势: {ctx.get('breadth_trend', '')}\n"
        f"主线板块: {leaders}\n"
        f"退潮板块: {avoid}\n"
        f"轮动阶段: {ctx.get('rotation_phase', '')}\n"
        f"风险警报: {ctx.get('risk_alerts', 'NONE')}\n"
    )

    # Append global macro intel when present
    global_macro = ctx.get("global_macro")
    if global_macro:
        from .web_collector import format_global_macro_block
        gm_block = format_global_macro_block(global_macro)
        if gm_block:
            block += gm_block

    return block


def _extract_evidence_items(
    text: str, max_items: int = 8, report_name: str = "report",
) -> List[str]:
    """Extract up to max_items factual evidence items from an analyst report.

    Extraction priority (highest first):
    1. pillar_score line (summary judgment)
    2. Structured CLAIM blocks
    3. FACT lines
    4. Table rows containing numeric data
    5. Key metric patterns in prose
    """
    items: List[str] = []

    # 1. Pillar score
    score = parse_pillar_score(text)
    if score is not None:
        items.append(f"pillar_score={score}")

    # 2. Structured CLAIM blocks
    for m in re.finditer(
        r'CLAIM(?:\s*\d+)?:\s*(.+?)(?=\nEVIDENCE|\nCONFIDENCE|\nCLAIM|\Z)',
        text, re.DOTALL,
    ):
        claim_text = m.group(1).strip().split('\n')[0].strip()
        if len(claim_text) >= 10:
            items.append(claim_text[:150])

    # 3. FACT lines
    for m in re.finditer(r'FACT\s*[:：]\s*(.+)', text):
        fact = m.group(1).strip()
        if len(fact) >= 10:
            items.append(fact[:150])

    # 4. Table rows with numbers (markdown: | key | value |)
    for m in re.finditer(
        r'\|\s*([^|]{2,30})\s*\|\s*([-\d.,]+[%亿万元倍]*)\s*\|', text,
    ):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key.startswith('-') or key in ('指标', '数值', '日期'):
            continue
        items.append(f"{key}: {val}")

    # 5. Key metric patterns in prose
    for pat in [
        r'(?:PE|市盈率)[^：:\n]*?[:：]\s*([-\d.]+)',
        r'(?:ROE|净资产收益率)[^：:\n]*?[:：]\s*([-\d.]+)%?',
        r'(?:毛利率)[^：:\n]*?[:：]\s*([-\d.]+)%',
        r'(?:RSI)[^：:\n]*?[:：]\s*([-\d.]+)',
    ]:
        m_metric = re.search(pat, text)
        if m_metric:
            start = max(0, text.rfind('\n', 0, m_metric.start()) + 1)
            end = text.find('\n', m_metric.end())
            if end == -1:
                end = len(text)
            line = text[start:end].strip()
            if len(line) >= 5:
                items.append(line[:150])

    # Deduplicate, preserving order
    seen: set = set()
    unique: List[str] = []
    for item in items:
        key = item.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if len(unique) > max_items:
        logger.warning(
            "evidence extraction: dropped %d items from %s (cap=%d) — raise max_items if dense analyst output is expected",
            len(unique) - max_items, report_name, max_items,
        )
    return unique[:max_items]


def build_evidence_block(
    market_report: str = "",
    fundamentals_report: str = "",
    news_report: str = "",
    sentiment_report: str = "",
) -> str:
    """Build a numbered Evidence Bundle from 4 analyst reports.

    Each evidence item gets an [E#] ID that downstream agents can cite.
    Returns formatted text block for prompt injection, or "" if nothing extracted.
    """
    items: List[str] = []
    counter = 1
    sources = [
        ("技术面报告", market_report),
        ("基本面报告", fundamentals_report),
        ("新闻报告", news_report),
        ("情绪报告", sentiment_report),
    ]
    for source_label, text in sources:
        if not text:
            continue
        for item_text in _extract_evidence_items(text, report_name=source_label):
            items.append(f"[E{counter}] ({source_label}) {item_text}")
            counter += 1
    if not items:
        return ""
    header = "**EVIDENCE BUNDLE（已从分析师报告提取的结构化证据）：**"
    return f"{header}\n" + "\n".join(items) + "\n"


def _extract_dimension_scores(text: str) -> Dict[str, int]:
    """Extract dimension scores like '基本面健康度: 8/10' or '(8/10)' patterns."""
    scores = {}
    dim_patterns = [
        (r'基本面[健康度]*.*?(\d+)\s*/\s*10', 'fundamentals'),
        (r'估值[合理性风险]*.*?(\d+)\s*/\s*10', 'valuation'),
        (r'技术面[信号风险]*.*?(\d+)\s*/\s*10', 'technicals'),
        (r'资金面[风险]*.*?(\d+)\s*/\s*10', 'sentiment'),
        (r'催化剂.*?(\d+)\s*/\s*10', 'catalysts'),
        (r'风险事件.*?(\d+)\s*/\s*10', 'risk_events'),
        (r'成长[性]*.*?(\d+)\s*/\s*10', 'growth'),
    ]
    for pat, dim in dim_patterns:
        m = re.search(pat, text)
        if m:
            scores[dim] = int(m.group(1))
    return scores


def _extract_overall_confidence(text: str, direction: str) -> float:
    """Extract overall confidence score like 'BUY confidence: 7/10'."""
    kw = "BUY" if direction == "bullish" else "SELL"
    patterns = [
        rf'{kw}\s*(?:confidence|置信度)\s*[:：]\s*(\d+)\s*/\s*10',
        rf'confidence\s*[:：]\s*(\d+)\s*/\s*10',
        rf'置信度\s*[:：]\s*(\d+)\s*/\s*10',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return int(m.group(1)) / 10.0
    return 0.6  # default


# Words signalling the value is a forecast/threshold/estimate, not an actual.
# A match preceded by any of these within 25 chars is rejected.
_FORECAST_PREFIXES = (
    "若", "假设", "预计", "预测", "估算", "约", "推测", "可能", "如", "倘",
    "超过", "低于", "高于", "不低于", "不超过", "至少", "至多",
    "DISPROVE", "INVALIDATION", "INVALIDATE", "threshold", "expected",
    "forecast", "fail if", "trigger", "目标", "区间下沿", "区间上沿",
)


def _is_forecast_context(text: str, pos: int) -> bool:
    """True if the match position is preceded by forecast/threshold language.

    Looks back to the start of the current sentence (last 。！？\n) within 60 chars.
    """
    sentence_start = pos
    for i in range(pos, max(0, pos - 60), -1):
        if text[i - 1] in "。！？\n":
            sentence_start = i
            break
    sentence = text[sentence_start:pos]
    return any(token.lower() in sentence.lower() for token in _FORECAST_PREFIXES)


def _value_in_range(val_str: str, lo: float, hi: float) -> bool:
    """Validate a captured numeric string against a sane range."""
    try:
        v = float(val_str)
    except (TypeError, ValueError):
        return False
    return lo <= v <= hi


def _looks_like_year(val_str: str) -> bool:
    """Reject 4-digit values in [2000, 2099] which are almost certainly years."""
    try:
        v = float(val_str)
    except (TypeError, ValueError):
        return False
    return v.is_integer() and 2000 <= v <= 2099 and "." not in val_str


def _normalize_signed_zero(val_str: str) -> str:
    """Convert signed-zero strings like ``-0.00`` / ``-0.0`` to their unsigned
    equivalent so they render cleanly in the UI. Non-zero values pass through.
    """
    try:
        v = float(val_str)
    except (TypeError, ValueError):
        return val_str
    if v == 0.0 and val_str.lstrip().startswith("-"):
        return val_str.lstrip().lstrip("-")
    return val_str


def _extract_financial_metrics(text: str) -> Dict[str, str]:
    """Scrape basic financial metrics from free-text analyst output.

    When vendor APIs are unavailable, these serve as fallback data for the
    Snapshot metrics card. Handles ``key: value`` / ``key= value`` prose and
    markdown-table ``| key | value |`` forms.

    **Hard rules** (avoid past bugs where year/threshold values leaked in):
    - Each spec must declare a ``range`` (lo, hi). Captured values outside the
      range are rejected.
    - The "亏损" sign-flip prefix only applies to ``net_profit`` and ``eps`` —
      never to ``pb`` or ``market_cap`` (those are always non-negative in
      conventional finance and the prefix triggered false negatives like
      "净亏损状态，总市值34.86亿" → -34.86).
    - Forecast/threshold context (e.g. "若净利润超过5000万", "DISPROVE: 若…",
      "区间下沿3000万") is rejected — only actuals enter the fallback.
    - 4-digit integers in [2000, 2099] are rejected as years.
    - ``market_cap`` and ``net_profit`` require an explicit 亿/万亿/万 unit —
      a bare number is too ambiguous.
    """
    metrics: Dict[str, str] = {}

    # Each spec: (output_key, ordered_patterns, range, allow_loss_prefix, require_unit)
    # Both table and prose patterns allow optional markdown bold (** or `*`)
    # around the value. Across all matches the one with the most decimal
    # places wins so that prose roundings ("PE=94倍") never trump precise
    # table values ("| PE | 94.14 |" or "PE(TTM)：**94.14**").
    specs: List[Tuple[str, List[str], Tuple[float, float], bool, bool]] = [
        ("pe", [
            r'\|\s*(?:PE|市盈率)(?:\([^)]*\))?\s*\|\s*\**(-?\d+(?:\.\d+)?)\**',
            r'(?:PE|市盈率)(?:\([^)]*\))?\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*(?:倍)?',
        ], (-1e6, 1e6), False, False),
        ("pb", [
            r'\|\s*(?:PB|市净率)\s*\|\s*\**(-?\d+(?:\.\d+)?)\**',
            r'(?:PB|市净率)\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*(?:倍)?',
        ], (0.0, 100.0), False, False),
        ("market_cap", [
            r'\|\s*(?:总市值|市值)\s*\|\s*\**(\d+(?:\.\d+)?)\**\s*(亿|万亿)',
            r'(?:总市值)\s*[:：=]?\s*\**(\d+(?:\.\d+)?)\**\s*(亿|万亿)',
        ], (0.001, 1e6), False, True),
        ("gross_margin", [
            r'\|\s*(?:毛利率)\s*\|\s*\**(-?\d+(?:\.\d+)?)\**\s*%?',
            r'(?:毛利率)\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*%?',
            # Bare "毛利率47.75%" — only valid when followed by '%' to anchor.
            r'(?:毛利率)\s*\**(-?\d+(?:\.\d+)?)\**\s*%',
        ], (-100.0, 100.0), False, False),
        ("roe", [
            r'\|\s*(?:ROE|净资产收益率)\s*\|\s*\**(-?\d+(?:\.\d+)?)\**\s*%?',
            r'(?:ROE|净资产收益率)\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*%?',
        ], (-1000.0, 1000.0), False, False),
        ("net_profit", [
            r'\|\s*(?:归母净利润|净利润)\s*\|\s*\**(-?\d+(?:\.\d+)?)\**\s*(亿|万)',
            r'(?:归母净利润|净利润)\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*(亿|万)',
        ], (-1e9, 1e9), True, True),
        ("eps", [
            r'\|\s*(?:EPS|每股收益)\s*\|\s*\**(-?\d+(?:\.\d+)?)\**\s*(?:元)?',
            r'(?:EPS|每股收益)\s*[:：=]\s*\**(-?\d+(?:\.\d+)?)\**\s*(?:元)?',
        ], (-1000.0, 1000.0), True, False),
    ]

    def _decimals(s: str) -> int:
        return len(s.split(".", 1)[1]) if "." in s else 0

    for key, patterns, value_range, allow_loss_prefix, require_unit in specs:
        best: Optional[Tuple[int, str]] = None  # (decimal_count, value)
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                val = m.group(1)
                if _looks_like_year(val):
                    continue
                if not _value_in_range(val, value_range[0], value_range[1]):
                    continue
                if _is_forecast_context(text, m.start()):
                    continue
                if require_unit:
                    try:
                        unit = m.group(2)
                    except IndexError:
                        unit = ""
                    if not unit:
                        continue
                    # RENDER-03: normalize market_cap to 亿 (the unit the renderer
                    # hard-codes via kind="mktcap_yi"). Without this, "总市值 1.5
                    # 万亿" was stored as 1.5 and shown as 1.5亿 — a 10000× shrink
                    # (工行 → micro-cap). net_profit is rendered unit-less (kind=
                    # "default"), so it is intentionally left in its raw unit.
                    _scale = ({"万亿": 10000.0, "亿": 1.0, "万": 0.0001}.get(unit.strip(), 1.0)
                              if key == "market_cap" else 1.0)
                    if _scale != 1.0:
                        try:
                            _scaled = float(val) * _scale
                            val = f"{_scaled:.4f}".rstrip("0").rstrip(".")
                        except (ValueError, TypeError):
                            pass
                if allow_loss_prefix and not val.startswith("-"):
                    sentence_start = max(0, m.start() - 30)
                    for i in range(m.start(), sentence_start, -1):
                        if text[i - 1] in "。！？\n":
                            sentence_start = i
                            break
                    prefix = text[sentence_start:m.start()]
                    if "亏损" in prefix or "亏-" in prefix:
                        val = "-" + val
                val = _normalize_signed_zero(val)
                cand = (_decimals(val), val)
                if best is None or cand[0] > best[0]:
                    best = cand
        if best is not None:
            metrics[key] = best[1]
    return metrics


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  2. Builders — assemble NodeTrace and RunTrace objects                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def build_node_trace(
    agent_key: str,
    text: str,
    run_id: str,
    seq: Optional[int] = None,
    prompt_text: Optional[str] = None,
) -> NodeTrace:
    """Build a NodeTrace from agent text output.

    Fills structured_data based on agent type, with graceful fallback
    when parsing fails (excerpt-only mode).

    When prompt_text is provided, records its hash in node.input_hash so
    that rolling monitoring and backtest analysis can stratify results
    by prompt version. Omitted → input_hash stays "" (backwards compat).
    """
    node_name = AGENT_NODE_MAP.get(agent_key, agent_key)
    if seq is None:
        seq = AGENT_SEQ.get(agent_key, 99)

    nt = NodeTrace(
        run_id=run_id,
        node_name=node_name,
        seq=seq,
        timestamp=_now_cst(),
        input_hash=compute_hash(prompt_text) if prompt_text else "",
        output_hash=compute_hash(text),
        output_excerpt=text[:150000] if text else "",
    )

    # Default parse status
    nt.parse_status = "strict_ok"
    nt.parse_confidence = 1.0

    try:
        _populate_structured_data(agent_key, text, nt)
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        logger.warning(f"Parse failed for {agent_key}: {e}")
        nt.parse_status = "failed"
        nt.parse_confidence = 0.0
        nt.parse_warnings = [str(e)]
        nt.status = NodeStatus.WARN

    return nt


def _parse_market_agent(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse market-level agents: macro_analyst, market_breadth_agent, sector_rotation_agent."""
    if agent_key == "macro_analyst":
        parsed = parse_macro_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["MACRO_OUTPUT block not found"]
            nt.status = NodeStatus.WARN

    elif agent_key == "market_breadth_agent":
        parsed = parse_breadth_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["BREADTH_OUTPUT block not found"]
            nt.status = NodeStatus.WARN

    elif agent_key == "sector_rotation_agent":
        parsed = parse_sector_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["SECTOR_OUTPUT block not found"]
            nt.status = NodeStatus.WARN


def _parse_analyst(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 1 analysts: market_analyst, fundamentals_analyst, news_analyst, sentiment_analyst."""
    score = parse_pillar_score(text)
    if score is not None:
        nt.structured_data = {"pillar_score": score}
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.5
        nt.parse_warnings = ["pillar_score not found"]
        nt.status = NodeStatus.WARN
    nt.evidence_ids_referenced = parse_evidence_citations(text)

    # Fundamentals analyst: extract financial metrics as vendor fallback
    if agent_key == "fundamentals_analyst":
        extracted = _extract_financial_metrics(text)
        if extracted:
            if nt.structured_data is None:
                nt.structured_data = {}
            nt.structured_data["metrics_fallback"] = extracted

    # News analyst: extract information_thin flag (added 2026-05-19 to let PM
    # distinguish "no news to analyze" from "neutral/mixed news" — previously both
    # collapsed to pillar_score=2 and were treated as a neutral vote).
    if agent_key == "news_analyst":
        if nt.structured_data is None:
            nt.structured_data = {}
        m_thin = re.search(
            r'information_thin\s*=\s*(true|false)',
            text, flags=re.IGNORECASE,
        )
        if m_thin:
            nt.structured_data["information_thin"] = (m_thin.group(1).lower() == "true")
        else:
            nt.structured_data["information_thin"] = None

    # Sentiment analyst: extract hot-money probability + type (added 2026-04-30
    # to mitigate the structural SELL-bias on small-cap speculative stocks).
    if agent_key == "sentiment_analyst":
        if nt.structured_data is None:
            nt.structured_data = {}
        m_prob = re.search(
            r'hot_money_probability\s*=\s*(LOW|MEDIUM|HIGH)',
            text, flags=re.IGNORECASE,
        )
        if m_prob:
            nt.structured_data["hot_money_probability"] = m_prob.group(1).upper()
        m_type = re.search(
            r'hot_money_type\s*=\s*(题材接力|一日游|中线票|妖股|N/?A)',
            text,
        )
        if m_type:
            raw = m_type.group(1)
            nt.structured_data["hot_money_type"] = "N/A" if raw.upper().replace("/", "") == "NA" else raw


def _parse_catalyst(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 2 catalyst_agent."""
    catalysts = parse_catalyst_json(text)
    if catalysts:
        nt.structured_data = {"catalysts": catalysts}
        nt.evidence_ids_referenced = parse_evidence_citations(text)
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.5
        nt.parse_warnings = ["CATALYST_OUTPUT block not found or invalid"]
        nt.status = NodeStatus.WARN


def parse_rebuttals(text: str) -> List[Dict[str, Any]]:
    """Parse REBUT blocks that target the OTHER side's claim IDs → opposing_claims.

    Format (REBUTTAL_PROTOCOL):
        REBUT [clm-uNNN]: <rebuttal text>
        REBUT_CONFIDENCE: <0.0-1.0>

    Returns [{target_claim_id, text, confidence}]. This is how the system
    measures whether the debate is a REAL clash (each side rebutting the
    other's specific claims) versus two monologues (AQ-01)."""
    rebuttals: List[Dict[str, Any]] = []
    seen = set()
    for blk in re.split(r'(?=^\s*REBUT\s*\[)', text, flags=re.MULTILINE):
        hm = re.match(
            r'\s*REBUT\s*\[?\s*(clm-[ur]\d+)\s*\]?\s*[:：]\s*(.*)',
            blk, re.IGNORECASE | re.DOTALL,
        )
        if not hm:
            continue
        cid = hm.group(1).lower()
        body = re.split(
            r'\n\s*(?:REBUT_CONFIDENCE|CLAIM\s*\[|CITED_EVIDENCE|REBUT\s*\[)',
            hm.group(2), 1,
        )[0].strip()
        if not body:
            continue
        conf = -1.0
        cm = re.search(r'REBUT_CONFIDENCE\s*[:：=]\s*([^\n]+)', blk, re.IGNORECASE)
        if cm:
            # CONF-01: tolerate an "N/10" ratio form (take the numerator) so a
            # rebuttal confidence parses the same as a CLAIM confidence does.
            _raw = re.sub(r'\s*/\s*\d+\s*$', '', cm.group(1).strip())
            conf = normalize_confidence_value(_raw)
        key = (cid, body[:40])
        if key in seen:
            continue
        seen.add(key)
        rebuttals.append({"target_claim_id": cid, "text": body[:400], "confidence": conf})
    return rebuttals


def _parse_researcher(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 3 bull_researcher / bear_researcher."""
    direction = "bullish" if agent_key == "bull_researcher" else "bearish"
    claims = parse_claims(text, direction)
    rebuttals = parse_rebuttals(text)
    evidence = parse_evidence_citations(text)
    dim_scores = _extract_dimension_scores(text)
    overall_conf = _extract_overall_confidence(text, direction)

    nt.evidence_ids_referenced = evidence

    # Build structured claims with dimension info
    supporting_claims = []
    for c in claims:
        sc = {
            "claim_id": c["claim_id"],
            "text": c["text"],
            "dimension": "",
            "dimension_score": None,
            "confidence": c["confidence"],
            "invalidation": c.get("invalidation", ""),
            "direction": direction,
            "supports": c.get("supports", []),
            "opposes": [],
        }
        # Try to match claim to a dimension by keyword
        for dim_key, dim_name in [
            ("fundamentals", "基本面"), ("valuation", "估值"),
            ("technicals", "技术"), ("sentiment", "资金"),
            ("catalysts", "催化"), ("growth", "成长"),
        ]:
            if dim_name in c.get("text", "") or dim_key in c.get("text", "").lower():
                sc["dimension"] = dim_key
                sc["dimension_score"] = dim_scores.get(dim_key)
                break
        supporting_claims.append(sc)

    # Claim attribution stats
    attributed = sum(1 for c in supporting_claims if c.get("supports"))
    total = len(supporting_claims)
    nt.claims_produced = total
    nt.claims_attributed = attributed
    nt.claims_unattributed = total - attributed
    nt.claim_ids_produced = [c["claim_id"] for c in supporting_claims]

    # Extract thesis (last sentence with confidence)
    thesis = ""
    for line in reversed(text.split('\n')):
        stripped = line.strip()
        if ('论点' in stripped or 'thesis' in stripped.lower()
                or '结论' in stripped or '总结' in stripped):
            thesis = stripped[:200]
            break
    if not thesis:
        thesis = f"{direction}方观点（{total}条论据）"

    nt.structured_data = {
        "thesis": thesis,
        "direction": direction,
        "overall_confidence": overall_conf,
        "dimension_scores": dim_scores,
        "supporting_claims": supporting_claims,
        # AQ-01: rebuttals targeting the other side's claim IDs — populated from
        # REBUT blocks so debate-quality metrics can measure real clash.
        "opposing_claims": rebuttals,
        "unresolved_conflicts": [],
        "missing_evidence": [],
    }

    if not claims:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.6
        nt.parse_warnings = ["No structured CLAIM blocks found"]
        nt.status = NodeStatus.WARN


def _parse_scenario(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 4 scenario_agent."""
    scenario = parse_scenario_output(text)
    if scenario:
        probs_defaulted = (
            "base_prob" not in scenario
            or "bull_prob" not in scenario
            or "bear_prob" not in scenario
        )
        # BRG-03: probabilities may arrive as "50%", "0.5 (base case)", "25" —
        # extract the number robustly (no raw float() that would crash the whole
        # scenario node), then treat >1 / "%" values as percentages. The sum is
        # renormalized below, so 50/25/25 and 0.5/0.25/0.25 both work.
        def _prob(key, default):
            raw = scenario.get(key, default)
            v = _safe_float(raw, default)
            if v > 1.0 or (isinstance(raw, str) and "%" in raw):
                v = v / 100.0
            return v if v >= 0 else default
        _bp = _prob("base_prob", 0.5)
        _blp = _prob("bull_prob", 0.25)
        _brp = _prob("bear_prob", 0.25)
        _ptotal = _bp + _blp + _brp
        if _ptotal > 0 and abs(_ptotal - 1.0) > 0.01:
            _bp, _blp, _brp = _bp / _ptotal, _blp / _ptotal, _brp / _ptotal
        nt.structured_data = {
            "base_prob": round(_bp, 3),
            "bull_prob": round(_blp, 3),
            "bear_prob": round(_brp, 3),
            "base_case_trigger": scenario.get("base_trigger", ""),
            "bull_case_trigger": scenario.get("bull_trigger", ""),
            "bear_case_trigger": scenario.get("bear_trigger", ""),
            "probs_defaulted": probs_defaulted,
        }
        if probs_defaulted:
            warnings = list(nt.parse_warnings or [])
            warnings.append("scenario probabilities partially defaulted (50/25/25)")
            nt.parse_warnings = warnings
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.5
        nt.parse_warnings = [f"{TAG_SCENARIO_OUTPUT} block not found"]
        nt.status = NodeStatus.WARN


def parse_adjudications(text: str) -> List[Dict[str, Any]]:
    """Parse the PM's claim-by-claim verdicts (M2a): the strict format is
    ``[clm-xNNN] ACCEPT|REJECT|DEFER — reason``.

    Returns [{claim_id, verdict, reason}], one per claim (first verdict wins).
    A REJECT IS engagement (the PM considered and dismissed it) — so all three
    verdicts count as "adjudicated", but accepted/rejected/deferred are tracked
    separately so a wall of REJECTs doesn't read as a high digestion rate."""
    adj: List[Dict[str, Any]] = []
    seen = set()
    for m in re.finditer(
        r'\[?\s*(clm-[ur]\d+)\s*\]?\s*[:：\-—\s]*?\b(ACCEPT|REJECT|DEFER)\b'
        r'\s*[—\-:：]*\s*([^\n]*)',
        text, re.IGNORECASE,
    ):
        cid = m.group(1).lower()
        if cid in seen:
            continue
        seen.add(cid)
        adj.append({
            "claim_id": cid,
            "verdict": m.group(2).upper(),
            "reason": m.group(3).strip()[:300],
        })
    return adj


def _parse_research_manager(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 5 research_manager (PM)."""
    synth = parse_synthesis_output(text)
    if synth:
        action = str(synth.get("research_action", "HOLD")).upper()
        nt.research_action = action
        _conf_defaulted = "confidence" not in synth
        nt.confidence = normalize_confidence_value(synth.get("confidence", 0.5))
        if nt.confidence < 0:
            # Present but unparseable → fall back to neutral default + warn.
            nt.confidence = 0.5
            _conf_defaulted = True
        if _conf_defaulted:
            warnings = list(nt.parse_warnings or [])
            warnings.append("confidence defaulted to 0.5 (not provided by PM)")
            nt.parse_warnings = warnings
        nt.thesis_effect = str(synth.get("thesis_effect", "unchanged"))

        # Evidence references
        supporting = synth.get("supporting_evidence", [])
        opposing = synth.get("opposing_evidence", [])
        nt.evidence_ids_referenced = list(dict.fromkeys(
            (supporting if isinstance(supporting, list) else []) +
            (opposing if isinstance(opposing, list) else [])
        ))

        # Claim consumption: PM references claims (clm-uNNN for bull, clm-rNNN for bear)
        claim_refs = list(dict.fromkeys(
            re.findall(r'\bclm-[ur]\d+\b', text)
        ))
        nt.claim_ids_referenced = claim_refs
        # AQ-03: parse the PM's per-claim verdicts (ACCEPT/REJECT/DEFER) so
        # "digestion" can mean "actually adjudicated" — not just "ID mentioned".
        adjudications = parse_adjudications(text)

        # Directional lean (research improvement #2): when action=HOLD, captures
        # which way PM would lean if forced to pick, with reason. For BUY/SELL,
        # auto-derives if missing.
        _lean_raw = synth.get("directional_lean", "")
        _lean = str(_lean_raw).strip().lower() if _lean_raw else ""
        if _lean not in ("bullish", "bearish", "neutral"):
            # Auto-derive when missing/invalid
            if action == "BUY":
                _lean = "bullish"
            elif action == "SELL":
                _lean = "bearish"
            else:
                _lean = ""  # leave blank for HOLD when PM didn't supply
        _lean_reason = str(synth.get("lean_reason", "") or "").strip()
        if _lean_reason.lower() in ("n/a", "na", "none", ""):
            _lean_reason = ""

        nt.structured_data = {
            "conclusion": synth.get("conclusion", ""),
            "base_case": synth.get("base_case", ""),
            "bull_case": synth.get("bull_case", ""),
            "bear_case": synth.get("bear_case", ""),
            "invalidation_conditions": _split_if_string(
                synth.get("invalidation", "")
            ),
            "open_questions": _split_if_string(
                synth.get("open_questions", "")
            ),
            "supporting_evidence_ids": supporting if isinstance(supporting, list) else [],
            "opposing_evidence_ids": opposing if isinstance(opposing, list) else [],
            "directional_lean": _lean,
            "lean_reason": _lean_reason,
            "adjudications": adjudications,
        }
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.4
        nt.parse_warnings = ["SYNTHESIS_OUTPUT block not found"]
        nt.status = NodeStatus.WARN
        # Try to infer action from text — uses module-level _NEG / _has_positive
        def _has_positive_en(text_upper, kw):
            for m in re.finditer(r'\b' + re.escape(kw) + r'\b', text_upper):
                window = text_upper[max(0, m.start()-20):m.start()]
                if _ENG_NEG.search(window):
                    continue
                return True
            return False
        text_up = text.upper()
        if _has_positive_en(text_up, 'BUY') or _has_positive(text, '买入'):
            nt.research_action = "BUY"
        elif _has_positive_en(text_up, 'SELL') or _has_positive(text, '卖出'):
            nt.research_action = "SELL"
        else:
            nt.research_action = "HOLD"
        nt.confidence = 0.5


def _parse_risk_debater(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 5b risk debaters: aggressive, conservative, neutral."""
    nt.evidence_ids_referenced = parse_evidence_citations(text)
    debater_data = parse_risk_debater_output(text)
    if debater_data:
        nt.structured_data = debater_data
        if debater_data.get("recommendation"):
            nt.research_action = str(debater_data["recommendation"]).upper()
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.5
        nt.parse_warnings = ["RISK_DEBATER_OUTPUT block not found"]
        nt.status = NodeStatus.WARN


def _parse_risk_manager(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 6 risk_manager (Judge)."""
    risk = parse_risk_output(text)
    if risk:
        nt.risk_score = _safe_int(risk.get("risk_score"))
        # CLAUDE.md rule #4: Risk Judge does NOT default to VETO/HOLD when
        # risk_cleared is omitted — missing flag is neutral and the PM's
        # direction is preserved. Only an explicit False triggers the gate.
        risk_cleared_explicit = "risk_cleared" in risk
        nt.risk_cleared = bool(risk.get("risk_cleared", True))
        if not risk_cleared_explicit:
            warnings = list(nt.parse_warnings or [])
            warnings.append("risk_cleared not provided; treating as neutral (PM direction preserved)")
            nt.parse_warnings = warnings
        nt.max_position_pct = _safe_float(risk.get("max_position_pct", -1.0))

        # Only set research_action if Risk Judge explicitly provides one.
        # Default was "HOLD" which silently overrode PM's BUY/SELL direction.
        raw_action = risk.get("research_action")
        action = str(raw_action).upper() if raw_action else ""
        nt.research_action = action if action else ""
        # Risk Judge may or may not provide its own confidence.
        # Use -1.0 sentinel so RunTrace.finalize() can prefer Research
        # Manager's confidence (see trace_models.py finalize(): "if
        # nt.confidence >= 0" guard).  Do NOT change to None — 7+ files
        # compare against this value numerically.
        # Canonical normalizer also returns the -1.0 sentinel for a missing
        # value, so finalize() can prefer the Research Manager's confidence.
        raw_conf = risk.get("confidence")
        nt.confidence = normalize_confidence_value(raw_conf)
        # Veto only on an explicit agent VETO or an explicit risk_cleared=False.
        nt.vetoed = action == "VETO" or (risk_cleared_explicit and not nt.risk_cleared)
        if action == "VETO":
            nt.veto_source = "agent_veto"
        elif risk_cleared_explicit and not nt.risk_cleared:
            nt.veto_source = "risk_gate"

        # Risk flags
        if risk.get("_risk_flags_parse_failed"):
            warnings = list(nt.parse_warnings or [])
            warnings.append("risk_flags JSON parse failed, flags may be incomplete")
            nt.parse_warnings = warnings
        raw_flags = risk.get("risk_flags", [])
        # P3 (reflection 2026-04-13): canonicalize + dedupe + top-6 cap.
        # Raw labels exploded to 200+ synonyms, biasing action → HOLD
        # without improving predictive power. Collapse to canonical vocabulary.
        from .shared import dedupe_and_cap_flags
        flags = dedupe_and_cap_flags(raw_flags, cap=6)
        nt.risk_flag_count = len(flags)
        nt.risk_flag_categories = [f["category"] for f in flags]
        invalidation_conditions = _split_if_string(
            risk.get("invalidation_conditions", [])
        )

        # BRG-05: render a missing score as "—/10", never "None/10".
        _rs_disp = nt.risk_score if nt.risk_score is not None else "—"
        nt.structured_data = {
            "conclusion": f"风险评分 {_rs_disp}/10，"
                          + ("审查通过" if nt.risk_cleared else "审查未通过"),
            "invalidation_conditions": invalidation_conditions,
            "risk_flags": [
                {
                    "flag_id": f"rf-{i+1:03d}",
                    "category": f["category"],
                    "severity": f["severity"],
                    "description": f.get("description", ""),
                    "bound_evidence_ids": (
                        [f.get("evidence", "")] if isinstance(f.get("evidence"), str)
                        else f.get("evidence", []) or []
                    ),
                    "mitigant": f.get("mitigant", ""),
                    "raw_category": f.get("_raw_category", ""),
                }
                for i, f in enumerate(flags)
            ],
            "raw_risk_flag_count": len([x for x in raw_flags if isinstance(x, dict)]),
        }

        nt.evidence_ids_referenced = parse_evidence_citations(text)
    else:
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.3
        nt.parse_warnings = ["RISK_OUTPUT block not found"]
        nt.status = NodeStatus.WARN
        nt.risk_score = 5
        nt.risk_cleared = False


def _parse_research_output(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Parse Stage 7 research_output (Trade Card + Trade Plan)."""
    tradecard = parse_tradecard_json(text)
    trade_plan = parse_trade_plan_json(text)
    sd: Dict[str, Any] = {}
    if tradecard:
        sd["tradecard"] = tradecard
        # Propagate action and confidence from TRADECARD to NodeTrace
        # so RunTrace.finalize() can pick them up as a fallback.
        # Prompt spec uses "side" but some agents output "action" — accept both.
        tc_action = str(
            tradecard.get("action") or tradecard.get("side", "")
        ).upper()
        if tc_action in ("BUY", "HOLD", "SELL", "VETO"):
            nt.research_action = tc_action
        tc_conf = tradecard.get("confidence")
        if tc_conf is not None:
            sd["confidence_raw"] = tc_conf  # preserve pre-normalization value
            nt.confidence = normalize_confidence_value(tc_conf)
    if trade_plan:
        sd["trade_plan"] = trade_plan
        # If TRADECARD didn't provide action/confidence, try TRADE_PLAN
        if not nt.research_action:
            tp_action = str(
                trade_plan.get("action") or trade_plan.get("bias", "")
            ).upper()
            # Normalize TRADE_PLAN bias values to action.
            # AVOID means "don't participate" (risk_cleared=FALSE or VETO),
            # NOT a directional sell.  Map to HOLD to preserve non-participation.
            _BIAS_TO_ACTION = {"LONG": "BUY", "WAIT": "HOLD", "AVOID": "HOLD"}
            tp_action = _BIAS_TO_ACTION.get(tp_action, tp_action)
            if tp_action in ("BUY", "HOLD", "SELL", "VETO"):
                nt.research_action = tp_action
        if nt.confidence < 0:
            tp_conf = trade_plan.get("confidence")
            if tp_conf is not None:
                nt.confidence = normalize_confidence_value(tp_conf)
    if sd:
        nt.structured_data = sd
    # Both JSON blocks missing → mark as degraded output
    if not tradecard and not trade_plan:
        warnings = list(nt.parse_warnings or [])
        warnings.append("TRADECARD_JSON and TRADE_PLAN_JSON both missing or unparseable")
        nt.parse_warnings = warnings
        nt.parse_status = "fallback_used"
        nt.parse_confidence = 0.1
        nt.status = NodeStatus.WARN


# ── Dispatch table for _populate_structured_data ──────────────────────────
_AGENT_PARSERS = {
    "macro_analyst": _parse_market_agent,
    "market_breadth_agent": _parse_market_agent,
    "sector_rotation_agent": _parse_market_agent,
    "market_analyst": _parse_analyst,
    "fundamentals_analyst": _parse_analyst,
    "news_analyst": _parse_analyst,
    "sentiment_analyst": _parse_analyst,
    "catalyst_agent": _parse_catalyst,
    "bull_researcher": _parse_researcher,
    "bear_researcher": _parse_researcher,
    "scenario_agent": _parse_scenario,
    "research_manager": _parse_research_manager,
    "aggressive_debator": _parse_risk_debater,
    "conservative_debator": _parse_risk_debater,
    "neutral_debator": _parse_risk_debater,
    "risk_manager": _parse_risk_manager,
    "research_output": _parse_research_output,
}


def _populate_structured_data(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Fill NodeTrace fields based on agent type."""
    handler = _AGENT_PARSERS.get(agent_key)
    if handler:
        handler(agent_key, text, nt)


def _split_if_string(val) -> list:
    """Convert string to list (split on semicolons/newlines) or pass through list."""
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val:
        return [x.strip() for x in re.split(r'[;；\n]', val) if x.strip()]
    return []


def _safe_int(val, default=None):
    """Lenient int parse: pulls the LEADING number out of strings like "5/10",
    "5分", "75%" → 5 / 5 / 75. A placeholder like "N/10" has no leading number
    → returns default (NOT the denominator 10). BRG-05."""
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return int(val)
    m = re.match(r'\s*(-?\d+)', str(val))
    if not m:
        return default
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    """Lenient float parse: pulls the LEADING number out of strings, stripping a
    trailing "/10", "%", or prose (e.g. "0.5 (base case)" → 0.5)."""
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    m = re.match(r'\s*(-?\d+(?:\.\d+)?)', str(val))
    if not m:
        return default
    try:
        return float(m.group(1))
    except (ValueError, TypeError):
        return default


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  3. RunTrace assembly                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def build_run_trace(
    outputs: Dict[str, str],
    ticker: str,
    ticker_name: str = "",
    trade_date: str = "",
    run_id: Optional[str] = None,
    prompts: Optional[Dict[str, str]] = None,
) -> RunTrace:
    """Assemble a complete RunTrace from agent outputs dict.

    Args:
        outputs: Dict mapping agent_key → agent text output.
                 Keys should be from AGENT_NODE_MAP (e.g. "market_analyst").
        ticker: Stock ticker (e.g. "601985")
        ticker_name: Human-readable name (e.g. "中国核电")
        trade_date: Analysis date (e.g. "2026-03-12")
        run_id: Optional custom run ID (auto-generated if None)
        prompts: Optional dict mapping agent_key → rendered prompt text.
                 When provided, each NodeTrace's input_hash is populated
                 with the SHA-256/16 hash of that agent's prompt, and
                 RunTrace.prompt_hashes aggregates them for fast lookup.

    Returns:
        Finalized RunTrace ready for persistence and report generation.
    """
    if run_id is None:
        run_id = f"run-{uuid.uuid4().hex[:12]}"

    # Normalize A-share ticker: bare 6-digit code → add exchange suffix
    normalized = ticker
    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    if bare.isdigit() and len(bare) == 6 and not any(
        ticker.endswith(s) for s in (".SS", ".SZ", ".BJ")
    ):
        if bare.startswith("6"):
            normalized = f"{bare}.SS"
        elif bare.startswith(("8", "4", "9")):
            normalized = f"{bare}.BJ"
        else:
            normalized = f"{bare}.SZ"

    trace = RunTrace(
        run_id=run_id,
        ticker=normalized,
        ticker_name=ticker_name,
        trade_date=trade_date or _now_cst().strftime("%Y-%m-%d"),
        as_of=_now_cst().strftime("%Y-%m-%d"),
        started_at=_now_cst(),
        market="cn",
        language="zh",
        llm_provider="subagent",
    )

    # Build NodeTraces in execution order
    prompts = prompts or {}
    for agent_key in sorted(outputs.keys(), key=lambda k: AGENT_SEQ.get(k, 99)):
        text = outputs[agent_key]
        if not text:
            continue
        prompt_text = prompts.get(agent_key)
        nt = build_node_trace(agent_key, text, run_id, prompt_text=prompt_text)
        trace.node_traces.append(nt)
        # Aggregate input_hash (prompt hash) at run level for fast stratified queries
        if nt.input_hash:
            trace.prompt_hashes[agent_key] = nt.input_hash

    # Publishing Compliance — run lightweight deterministic checks
    # (subagent_pipeline cannot import the full engine from tradingagents/)
    compliance_reasons: list = []
    compliance_status = "allow"
    rules_fired = []

    # P1: source tier — check if any node references evidence
    has_evidence = any(bool(nt.evidence_ids_referenced) for nt in trace.node_traces)
    rules_fired.append("P1_source_tier")
    if not has_evidence:
        compliance_reasons.append("P1: 无证据链引用")

    # P5: veto consistency — if vetoed, research_action must not be BUY
    pm_action = ""
    rm_action = ""
    was_vetoed = False
    for nt in trace.node_traces:
        if nt.node_name == "Research Manager" and nt.research_action:
            pm_action = nt.research_action
        if nt.node_name == "Risk Judge":
            rm_action = nt.research_action or ""
            was_vetoed = nt.vetoed
    rules_fired.append("P5_veto_consistency")
    # SIG-003: when the risk gate vetoes but RISK_OUTPUT omits research_action,
    # the Risk Judge node's action is "" — fall back to the PM's direction so a
    # vetoed BUY is still detected (previously this case slipped through).
    effective_pre_veto = rm_action or pm_action
    if was_vetoed and effective_pre_veto == "BUY":
        compliance_reasons.append("P5: BUY方向被风控否决，发布方向应为VETO")
        compliance_status = "flag"

    # P6 (AQ-06): evidence↔conclusion consistency. pillar_score is directional
    # (4=bullish … 0=bearish). If the 4 analyst pillars lean clearly bearish
    # (mean < 1.5) yet the published action is BUY — or lean clearly bullish
    # (mean > 2.5) yet SELL — that's optimistic/contrarian drift the LLM made
    # without the evidence supporting it. Surface it (a flag, not a block).
    rules_fired.append("P6_pillar_direction")
    _pillars = [
        nt.structured_data["pillar_score"]
        for nt in trace.node_traces
        if isinstance(getattr(nt, "structured_data", None), dict)
        and isinstance(nt.structured_data.get("pillar_score"), (int, float))
    ]
    _final_action = "VETO" if was_vetoed else (rm_action or pm_action)
    if len(_pillars) >= 3:
        _pmean = sum(_pillars) / len(_pillars)
        if _final_action == "BUY" and _pmean < 1.5:
            compliance_reasons.append(
                f"P6: 支柱均值 {_pmean:.1f}/4 偏空但结论 BUY，证据-结论方向背离")
            compliance_status = "flag"
        elif _final_action == "SELL" and _pmean > 2.5:
            compliance_reasons.append(
                f"P6: 支柱均值 {_pmean:.1f}/4 偏多但结论 SELL，证据-结论方向背离")
            compliance_status = "flag"

    if compliance_reasons:
        compliance_status = "flag"

    compliance_nt = NodeTrace(
        run_id=run_id,
        node_name="Publishing Compliance",
        seq=18,  # after research_output (seq=17), no conflicts
        timestamp=_now_cst(),
        compliance_status=compliance_status,
        compliance_reasons=compliance_reasons,
        compliance_rules_fired=rules_fired,
        output_excerpt="合规审查通过" if compliance_status == "allow" else f"合规标记: {'; '.join(compliance_reasons)}",
    )
    trace.node_traces.append(compliance_nt)

    # Finalize: compute run-level summary from node traces
    trace.finalize()

    return trace


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  4. Entry point — generate_report()                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def _compute_5d_return(price_history: Optional[List[float]], window: int = 5) -> Optional[float]:
    """Compute N-trading-day return from a price history list.

    Requires at least ``window + 1`` prices so that we have a start price
    ``window`` bars ago and the latest close.  Returns None if data is
    insufficient.
    """
    if not price_history or len(price_history) < window + 1:
        return None
    start_price = price_history[-(window + 1)]
    if not start_price:
        return None
    return (price_history[-1] - start_price) / start_price


def _try_fetch_prices(ticker: str, days: int = 30) -> List[float]:
    """Fetch recent close prices via akshare for sparkline rendering.

    Returns empty list on any failure (missing package, network, etc.).
    """
    try:
        import akshare as ak  # noqa: delayed import — optional dependency
        from datetime import timedelta

        bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        end = _now_cst().date()  # CST so the range includes today's bar in UTC containers
        start = end - timedelta(days=days + 10)
        df = ak.stock_zh_a_hist(
            symbol=bare, period="daily", adjust="qfq",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return df["收盘"].tail(days).tolist()
    except Exception as _e:
        logger.debug("price history fetch failed for %s: %s", ticker, _e)
        return []


def _extract_industry_compare_from_text(text: str, ticker: str = "") -> Dict[str, Any]:
    """Parse the collector-rendered industry comparison block from markdown.

    This is a no-network fallback for report generation paths that only pass
    agent text outputs. It mirrors ``AkshareBundle.render_fundamentals_analyst_md``
    and ``_build_markdown`` enough to preserve the structured card data.
    """
    if not text:
        return {}
    m = re.search(r"^##\s*行业对比[（(]([^）)]+)[）)]", text, flags=re.MULTILINE)
    if not m:
        return {}

    industry_name = m.group(1).strip()
    if not industry_name or industry_name in {"—", "-", "N/A", "NA"}:
        return {}

    start = m.end()
    next_heading = re.search(r"\n##\s+", text[start:])
    section = text[start:start + next_heading.start()] if next_heading else text[start:]

    def _num_after(pattern: str) -> Optional[float]:
        mm = re.search(pattern, section)
        if not mm:
            return None
        try:
            return float(mm.group(1))
        except (TypeError, ValueError):
            return None

    def _cell_num(value: str) -> Optional[float]:
        raw = str(value or "").strip().replace(",", "")
        if raw in ("", "—", "-", "None", "nan"):
            return None
        multiplier = 1.0
        if raw.endswith("万"):
            multiplier = 1e4
            raw = raw[:-1]
        elif raw.endswith("亿"):
            multiplier = 1.0
            raw = raw[:-1]
        try:
            return float(raw) * multiplier
        except ValueError:
            return None

    ic: Dict[str, Any] = {"industry_name": industry_name}
    for key, pattern in (
        ("pe_percentile_5y", r"PE\s*历史分位\s*([-+]?\d+(?:\.\d+)?)\s*%"),
        ("pb_percentile_5y", r"PB\s*历史分位\s*([-+]?\d+(?:\.\d+)?)\s*%"),
        ("industry_pe_median", r"行业中位\s*PE\s*([-+]?\d+(?:\.\d+)?)"),
        ("industry_pb_median", r"行业中位\s*PB\s*([-+]?\d+(?:\.\d+)?)"),
        ("industry_ps_median", r"行业中位\s*PS\s*([-+]?\d+(?:\.\d+)?)"),
        ("industry_roe_median", r"行业中位\s*ROE\s*([-+]?\d+(?:\.\d+)?)"),
        ("industry_gross_margin_median", r"行业中位\s*毛利率\s*([-+]?\d+(?:\.\d+)?)"),
        ("industry_revenue_growth_median", r"行业中位\s*营收增速\s*([-+]?\d+(?:\.\d+)?)"),
    ):
        val = _num_after(pattern)
        if val is not None:
            ic[key] = val

    size_m = re.search(r"成份股\s*(\d+)\s*只", section)
    if size_m:
        ic["industry_size"] = int(size_m.group(1))

    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    peers = []
    header_cells: List[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        code_cell = cells[0]
        if "代码" in code_cell:
            header_cells = cells
            continue
        if set(code_cell.replace(" ", "")) <= {"-"}:
            continue
        code_m = re.search(r"(\d{6})", code_cell)
        if not code_m:
            continue
        code = code_m.group(1)

        def _idx(labels: tuple, default: Optional[int] = None) -> Optional[int]:
            for i, h in enumerate(header_cells):
                if any(label in h for label in labels):
                    return i
            return default

        pe_i = _idx(("PE", "市盈率"), 2)
        pb_i = _idx(("PB", "市净率"), 3)
        roe_i = _idx(("ROE", "净资产收益率"), None)
        gm_i = _idx(("毛利率",), None)
        rev_i = _idx(("营收增速", "营收同比", "营业收入同比"), None)
        turnover_default = 7 if len(cells) >= 8 else 4
        turnover_i = _idx(("成交额", "成交金额"), turnover_default)

        def _cell_at(idx: Optional[int]) -> str:
            return cells[idx] if idx is not None and idx < len(cells) else ""

        peer = {
            "ticker": code,
            "name": cells[1],
            "pe": _cell_num(_cell_at(pe_i)),
            "pb": _cell_num(_cell_at(pb_i)),
            "turnover_yi": _cell_num(_cell_at(turnover_i)),
            "is_current": ("★" in code_cell) or (bool(bare) and code == bare),
        }
        roe_val = _cell_num(_cell_at(roe_i))
        gm_val = _cell_num(_cell_at(gm_i))
        rev_val = _cell_num(_cell_at(rev_i))
        if roe_val is not None:
            peer["roe"] = roe_val
        if gm_val is not None:
            peer["gross_margin"] = gm_val
        if rev_val is not None:
            peer["revenue_growth"] = rev_val
        peers.append(peer)
    if peers:
        ic["peers"] = peers

    return ic


def _load_cached_industry_data(ticker: str, trade_date: str) -> Dict[str, Any]:
    """Load industry comparison from local collect_bundle cache, no network."""
    bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
    dates = [trade_date or _now_cst().strftime("%Y-%m-%d")]
    try:
        from .akshare_collector import _is_cn_trading_day, _last_trading_day
        if not _is_cn_trading_day(dates[0]):
            rolled = _last_trading_day(dates[0])
            if rolled not in dates:
                dates.append(rolled)
    except Exception:
        pass

    try:
        from .data_cache import DataCache
        cache = DataCache(auto_evict=False)
        for dt in dates:
            cached = cache.get("collect_bundle", bare, dt)
            if isinstance(cached, dict):
                ic = cached.get("industry_compare") or {}
                if isinstance(ic, dict) and ic.get("industry_name"):
                    return ic
    except Exception as e:
        logger.debug("cached industry_compare lookup failed for %s: %s", ticker, e)
    return {}


def _metric_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace(",", "").replace("%", "")
    if not raw or raw in ("—", "-", "None", "nan"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _augment_metric_metadata(metrics: Dict[str, Any], text: str, trade_date: str) -> Dict[str, Any]:
    """Attach data-as-of and metric-basis hints to extracted metrics."""
    if not metrics:
        return metrics
    out = dict(metrics)
    out.setdefault("data_as_of", trade_date or _now_cst().strftime("%Y-%m-%d"))
    t = text or ""
    if re.search(r"(一季报|Q1|一季度)", t, re.IGNORECASE):
        out.setdefault("metric_period", "quarterly")
    elif re.search(r"(半年报|中报|H1)", t, re.IGNORECASE):
        out.setdefault("metric_period", "half_year")
    elif re.search(r"(三季报|Q3|三季度)", t, re.IGNORECASE):
        out.setdefault("metric_period", "three_quarter")
    elif re.search(r"(年报|年度报告)", t):
        out.setdefault("metric_period", "annual")
    elif re.search(r"\bTTM\b|PE\(TTM\)|市盈率TTM", t, re.IGNORECASE):
        out.setdefault("metric_period", "ttm")
    else:
        out.setdefault("metric_period", "unknown")

    if re.search(r"(预计|预告|指引|forecast|guidance)", t, re.IGNORECASE):
        out.setdefault("metric_basis", "forecast")
    elif re.search(r"(估算|约为|测算|estimate)", t, re.IGNORECASE):
        out.setdefault("metric_basis", "estimate")
    elif out.get("metric_period") == "ttm":
        out.setdefault("metric_basis", "ttm")
    else:
        out.setdefault("metric_basis", "reported")
    return out


def _build_data_quality_flags(metrics: Dict[str, Any], industry_data: Dict[str, Any], text: str) -> List[Dict[str, str]]:
    """Detect report-level data/metric caveats for audit rendering."""
    flags: List[Dict[str, str]] = []
    pe = _metric_float(metrics.get("pe"))
    eps = _metric_float(metrics.get("eps"))
    roe = _metric_float(metrics.get("roe"))
    net_profit = _metric_float(metrics.get("net_profit"))
    if any(v is not None and v < 0 for v in (pe, eps, roe, net_profit)):
        flags.append({
            "type": "valuation_basis",
            "severity": "high",
            "message": "盈利指标为负，PE不得作为主估值锚，应使用PB/PS/现金流和净资产修复逻辑",
        })
    if metrics.get("metric_basis") in ("forecast", "estimate"):
        flags.append({
            "type": "metric_basis",
            "severity": "medium",
            "message": f"部分财务指标口径为{metrics.get('metric_basis')}，需避免当作已披露事实",
        })
    if not industry_data or not industry_data.get("industry_name"):
        flags.append({
            "type": "industry_context",
            "severity": "medium",
            "message": "行业对比数据不足，估值贵/便宜判断置信度下降",
        })

    pe_values = []
    for m in re.finditer(r"(?:PE|市盈率)[^\n|：:=]{0,12}[：:=]?\s*(-?\d+(?:\.\d+)?)", text or "", re.IGNORECASE):
        val = _metric_float(m.group(1))
        if val is not None and abs(val) < 1000:
            pe_values.append(val)
    if len(pe_values) >= 2:
        lo, hi = min(pe_values), max(pe_values)
        if hi - lo > max(10.0, abs(hi) * 0.25):
            flags.append({
                "type": "metric_conflict",
                "severity": "medium",
                "message": "文本中存在多个PE口径且差异较大，需人工确认TTM/扣非/滚动口径",
            })

    return flags[:6]


def _augment_industry_compare(industry_data: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Add relative valuation/quality labels to industry comparison data."""
    if not industry_data:
        return {}
    ic = dict(industry_data)
    pe = _metric_float(metrics.get("pe"))
    pb = _metric_float(metrics.get("pb"))
    ps = _metric_float(metrics.get("ps"))
    roe = _metric_float(metrics.get("roe"))
    gm = _metric_float(metrics.get("gross_margin"))
    rev_g = _metric_float(metrics.get("revenue_growth") or metrics.get("revenue_yoy"))

    basis = ""
    current = median = None
    if pe is not None and pe > 0 and ic.get("industry_pe_median"):
        current, median, basis = pe, _metric_float(ic.get("industry_pe_median")), "PE"
    elif pb is not None and pb > 0 and ic.get("industry_pb_median"):
        current, median, basis = pb, _metric_float(ic.get("industry_pb_median")), "PB"
    elif ps is not None and ps > 0 and ic.get("industry_ps_median"):
        current, median, basis = ps, _metric_float(ic.get("industry_ps_median")), "PS"
    if current is not None and median:
        ratio = current / median
        ic["relative_valuation_ratio"] = round(ratio, 3)
        ic["relative_valuation_basis"] = basis
        if ratio >= 1.3:
            ic["relative_valuation_label"] = "premium"
        elif ratio <= 0.7:
            ic["relative_valuation_label"] = "discount"
        else:
            ic["relative_valuation_label"] = "fair"
    else:
        ic.setdefault("relative_valuation_label", "unavailable")

    quality_pairs = [
        (roe, _metric_float(ic.get("industry_roe_median"))),
        (gm, _metric_float(ic.get("industry_gross_margin_median"))),
        (rev_g, _metric_float(ic.get("industry_revenue_growth_median"))),
    ]
    scored = [(a, b) for a, b in quality_pairs if a is not None and b is not None]
    if scored:
        better = sum(1 for a, b in scored if a >= b)
        worse = sum(1 for a, b in scored if a < b)
        if better >= 2:
            ic["relative_quality_label"] = "quality_premium"
        elif worse >= 2:
            ic["relative_quality_label"] = "weak_quality"
        else:
            ic["relative_quality_label"] = "mixed"
    else:
        ic.setdefault("relative_quality_label", "unavailable")
    return ic


def _load_calibration_summary(
    ticker: str,
    *,
    action: str = "",
    confidence: float = -1.0,
    storage_dir: str = "data/replays",
) -> Dict[str, Any]:
    """Load latest calibration report next to replay data, if present."""
    try:
        from .calibration import load_latest_calibration_report, calibration_summary_for_ticker
        candidates = []
        replay_parent = Path(storage_dir).parent
        candidates.append(replay_parent / "monitoring")
        candidates.append(Path("data/monitoring"))
        seen = set()
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            report = load_latest_calibration_report(str(path))
            if report is not None:
                return calibration_summary_for_ticker(
                    report,
                    ticker,
                    action=action,
                    confidence=confidence,
                )
    except Exception as e:
        logger.debug("calibration summary load failed for %s: %s", ticker, e)
    return {}


def generate_report(
    outputs: Dict[str, str],
    ticker: str,
    ticker_name: str = "",
    trade_date: str = "",
    output_dir: Optional[str] = None,
    storage_dir: Optional[str] = None,
    run_id: Optional[str] = None,
    price_history: Optional[List[float]] = None,
    market_context_block: str = "",
    market_context: Optional[Dict] = None,
    run_config=None,
    prompts: Optional[Dict[str, str]] = None,
    industry_data: Optional[Dict] = None,
    stock_profile_data: Optional[Dict] = None,
    calibration_data: Optional[Dict] = None,
) -> Dict[str, str]:
    """Convert subagent outputs to 3-tier HTML reports.

    Args:
        outputs: Dict mapping agent_key → agent text output.
        ticker: Stock ticker
        ticker_name: Human-readable company name
        trade_date: Analysis date
        output_dir: Where to write HTML reports
        storage_dir: Where to persist RunTrace (for dashboard)
        run_id: Optional custom run ID
        price_history: Optional list of recent close prices for sparklines.
                       Auto-fetched via akshare if None.
        market_context_block: Formatted market context text for prompt injection.
        market_context: Dict from assemble_market_context() — persisted into RunTrace.
        prompts: Optional dict mapping agent_key → rendered prompt text. When
                 provided, RunTrace.prompt_hashes is populated for stratified
                 backtest analysis across prompt versions.
        industry_data: Optional structured industry comparison dict. If omitted,
                       report generation tries the fundamentals markdown and
                       local collect_bundle cache, without network calls.
        stock_profile_data: Optional stock-type classification dict. If omitted,
                            derived from available metrics and text.
        calibration_data: Optional historical calibration summary dict. If
                          omitted, the newest local calibration report is used.

    Returns:
        Dict of {"snapshot": path, "research": path, "audit": path, "run_id": id}
    """
    # Anchor unspecified output/storage to the single canonical data root
    # (CWD-independent) so a caller that omits these never writes a CWD-relative
    # split-brain store (N-ORC-02).
    if output_dir is None or storage_dir is None:
        from .signal_ledger import _data_root
        _root = _data_root()
        output_dir = str(_root / "data" / "reports") if output_dir is None else output_dir
        storage_dir = str(_root / "data" / "replays") if storage_dir is None else storage_dir

    # 1. Build RunTrace
    trace = build_run_trace(outputs, ticker, ticker_name, trade_date, run_id, prompts=prompts)

    # 1a. Inject market context into RunTrace for downstream rendering
    if market_context is not None:
        trace.market_context = market_context

    # 1b. Inject price history into Market Analyst node for sparklines
    if price_history is None:
        price_history = _try_fetch_prices(ticker)
    if price_history:
        for nt in trace.node_traces:
            if nt.node_name == "Market Analyst":
                if nt.structured_data is None:
                    nt.structured_data = {}
                nt.structured_data["price_history"] = price_history
                try:
                    nt.structured_data["current_price"] = float(price_history[-1])
                except (TypeError, ValueError, IndexError):
                    pass
                break

    # 1c. Inject industry comparison data into Fundamentals Analyst node so
    # the snapshot/research views can render a peer-comparison card without
    # round-tripping through the LLM.
    if not industry_data:
        industry_data = _extract_industry_compare_from_text(
            outputs.get("fundamentals_analyst", ""),
            ticker,
        )
    if not industry_data:
        industry_data = _load_cached_industry_data(ticker, trace.trade_date)

    fund_node = next(
        (nt for nt in trace.node_traces if nt.node_name == "Fundamentals Analyst"),
        None,
    )
    fund_text = outputs.get("fundamentals_analyst", "")
    fund_metrics: Dict[str, Any] = {}
    if fund_node is not None:
        if fund_node.structured_data is None:
            fund_node.structured_data = {}
        fund_metrics = dict(fund_node.structured_data.get("metrics_fallback", {}) or {})
        if fund_metrics:
            fund_metrics = _augment_metric_metadata(fund_metrics, fund_text, trace.trade_date)
            fund_node.structured_data["metrics_fallback"] = fund_metrics

    industry_data = _augment_industry_compare(industry_data or {}, fund_metrics)
    data_quality_flags = _build_data_quality_flags(fund_metrics, industry_data, fund_text)

    if not stock_profile_data:
        try:
            from .stock_profile import infer_stock_profile
            stock_profile_data = infer_stock_profile(
                ticker=ticker,
                ticker_name=ticker_name,
                sector=str((industry_data or {}).get("industry_name", "")),
                metrics=fund_metrics,
                industry_compare=industry_data,
                text=fund_text,
            ).to_dict()
        except Exception as e:
            logger.debug("stock_profile inference failed for %s: %s", ticker, e)
            stock_profile_data = {}

    if not calibration_data:
        calibration_data = _load_calibration_summary(
            ticker,
            action=trace.research_action,
            confidence=trace.final_confidence,
            storage_dir=storage_dir,
        )

    if fund_node is not None:
        if industry_data:
            fund_node.structured_data["industry_compare"] = industry_data
        if stock_profile_data:
            fund_node.structured_data["stock_profile"] = stock_profile_data
        if calibration_data:
            fund_node.structured_data["calibration_summary"] = calibration_data
        if data_quality_flags:
            fund_node.structured_data["data_quality_flags"] = data_quality_flags

    # Share report-level context with PM / Risk / final output nodes so all
    # renderers can find it even when a view does not inspect Fundamentals.
    for nt in trace.node_traces:
        if nt.node_name in ("Research Manager", "Risk Judge", "ResearchOutput"):
            if nt.structured_data is None:
                nt.structured_data = {}
            if stock_profile_data:
                nt.structured_data.setdefault("stock_profile", stock_profile_data)
            if calibration_data:
                nt.structured_data.setdefault("calibration_summary", calibration_data)
            if data_quality_flags:
                nt.structured_data.setdefault("data_quality_flags", data_quality_flags)

    # 1d. Trend override — downgrade pillar scores when recent trend is strongly negative
    from .config import PipelineRunConfig
    _rc = run_config if isinstance(run_config, PipelineRunConfig) else PipelineRunConfig.from_defaults()
    _tw = _rc.trend_override_window
    _thr = _rc.trend_override_threshold
    _td = _rc.trend_override_downgrade
    five_day_ret = _compute_5d_return(price_history, window=_tw)
    if five_day_ret is not None and five_day_ret < _thr:
        logger.info(
            f"Trend override triggered: {_tw}d return={five_day_ret:.2%} "
            f"< {_thr:.0%}, downgrading pillar scores by {_td}"
        )
        for nt in trace.node_traces:
            if nt.node_name in (
                "Market Analyst", "Fundamentals Analyst",
                "News Analyst", "Social Analyst",
            ):
                sd = nt.structured_data or {}
                if "pillar_score" in sd and isinstance(sd["pillar_score"], (int, float)):
                    old = sd["pillar_score"]
                    sd["pillar_score"] = max(0, old - _td)
                    logger.debug(
                        f"  {nt.node_name}: pillar_score {old} → {sd['pillar_score']}"
                    )

    logger.info(f"Built RunTrace {trace.run_id}: {trace.total_nodes} nodes, "
                f"action={trace.research_action}")

    # 2. Persist to replay store
    store = ReplayStore(storage_dir=storage_dir)
    store.save(trace)

    # 3. Generate 3-tier reports
    from .renderers.report_renderer import generate_all_tiers
    results = generate_all_tiers(
        run_id=trace.run_id,
        output_dir=output_dir,
        storage_dir=storage_dir,
        skip_vendors=True,  # subagent data comes from WebSearch, not vendors
    )

    results["run_id"] = trace.run_id
    logger.info(f"Reports generated: {results}")
    return results
