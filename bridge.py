"""Bridge module — converts subagent pipeline text outputs into RunTrace objects
for the 3-tier report renderer.

Usage:
    from subagent_pipeline.bridge import generate_report
    paths = generate_report(outputs, "601985", "中国核电", "2026-03-12")
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .trace_models import (
    NodeTrace,
    NodeStatus,
    RunTrace,
    compute_hash,
)
from .replay_store import ReplayStore

logger = logging.getLogger(__name__)

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
        r'CATALYST_OUTPUT:\s*\n\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```', text
    )
    if cb_m:
        inner = cb_m.group(1).strip()
        if inner.startswith('['):
            text = text[:cb_m.start()] + "CATALYST_OUTPUT:\n" + inner + text[cb_m.end():]

    # Find start of CATALYST_OUTPUT array
    start_m = re.search(r'CATALYST_OUTPUT:\s*\n?\s*\[', text)
    if not start_m:
        return []
    # Find the matching closing bracket (handle nested arrays)
    arr_start = start_m.end() - 1  # position of opening [
    depth = 0
    arr_end = arr_start
    for i in range(arr_start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                arr_end = i + 1
                break
    if arr_end <= arr_start:
        return []
    try:
        raw = text[arr_start:arr_end]
        # Fix common JSON issues: trailing commas
        raw = re.sub(r',\s*]', ']', raw)
        raw = re.sub(r',\s*}', '}', raw)
        catalysts = json.loads(raw)
        if isinstance(catalysts, list):
            return catalysts
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse CATALYST_OUTPUT JSON: {e}")
    return []


def _parse_kv_block(block: str, parse_arrays: bool = False) -> Dict[str, Any]:
    """Parse a key=value block supporting multiline values.

    Keys are `[a-zA-Z_]+`, values span until the next key or end of block.
    When *parse_arrays* is True, values like ``[E1, E3]`` become lists.
    """
    result: Dict[str, Any] = {}
    for match in re.finditer(
        r'^([a-zA-Z_]+)\s*=\s*([\s\S]*?)(?=\n[a-zA-Z_]+\s*=|\Z)',
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
            # Try boolean first, then float
            if val.upper() in ('TRUE', 'YES'):
                result[key] = True
            elif val.upper() in ('FALSE', 'NO'):
                result[key] = False
            else:
                try:
                    result[key] = float(val)
                except ValueError:
                    result[key] = val
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
    # Fix trailing commas before attempting parse
    cleaned = re.sub(r',\s*}', '}', stripped)
    cleaned = re.sub(r',\s*]', ']', cleaned)
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(cleaned)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def parse_scenario_output(text: str) -> Dict[str, Any]:
    """Extract SCENARIO_OUTPUT: key=value or JSON block."""
    block = _extract_tagged_block("SCENARIO_OUTPUT", text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_synthesis_output(text: str) -> Dict[str, Any]:
    """Extract SYNTHESIS_OUTPUT: key=value or JSON block."""
    block = _extract_tagged_block("SYNTHESIS_OUTPUT", text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block, parse_arrays=True)


def parse_risk_output(text: str) -> Dict[str, Any]:
    """Extract RISK_OUTPUT: block including risk_flags array."""
    result = {}
    block = _extract_tagged_block("RISK_OUTPUT", text)
    if not block:
        return result

    # Try JSON first — agents sometimes output full JSON objects
    j = _try_json_parse(block)
    if j is not None:
        # Normalize boolean strings
        if isinstance(j.get("risk_cleared"), str):
            j["risk_cleared"] = j["risk_cleared"].upper() in ("TRUE", "YES", "1")
        return j

    # Fallback: key=value format with separate risk_flags array
    flags_m = re.search(r'risk_flags\s*=\s*(\[[\s\S]*?\])\s*$', block, re.MULTILINE)
    if not flags_m:
        flags_m = re.search(r'risk_flags\s*=\s*(\[[\s\S]*?\n\s*\])', block)

    if flags_m:
        try:
            raw = flags_m.group(1)
            raw = re.sub(r',\s*]', ']', raw)
            raw = re.sub(r',\s*}', '}', raw)
            raw = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', raw)
            result["risk_flags"] = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("risk_flags JSON parse failed, defaulting to []: %s", e)
            result["risk_flags"] = []
            result["_risk_flags_parse_failed"] = True
        block = block[:flags_m.start()] + block[flags_m.end():]

    for line in block.strip().split('\n'):
        line = line.strip()
        if '=' not in line or line.startswith('{') or line.startswith('['):
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip()
        if key == "risk_flags":
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
    block = _extract_tagged_block("RISK_DEBATER_OUTPUT", text)
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
    for m in re.finditer(
        r'(?:(?:^|\n)\s*(?:#{0,4}\s*)?(TRADECARD_JSON|TRADE_PLAN_JSON|ORDER_PROPOSAL_JSON)[:\s]*\n'
        r'\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```'
        r'|(?:^|\n)\s*```(?:json)?\s*\n([\s\S]*?)\n\s*```)',
        text,
    ):
        # group(1)+group(2) for labeled match, group(3) for bare match
        label = (m.group(1) or "").strip()
        body = (m.group(2) or m.group(3) or "").strip()
        # Handle label inside code block (Format D)
        if not label:
            for tag in ("TRADECARD_JSON", "TRADE_PLAN_JSON", "ORDER_PROPOSAL_JSON"):
                if body.startswith(tag):
                    label = tag
                    body = body[len(tag):].lstrip(":").strip()
                    break
        yield label, body


def parse_tradecard_json(text: str) -> Dict[str, Any]:
    """Extract TRADECARD_JSON code block."""
    # Priority 1: labeled block
    for label, body in _iter_json_code_blocks(text):
        if label == "TRADECARD_JSON" and body.startswith('{'):
            try:
                raw = re.sub(r',\s*}', '}', body)
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
    # Priority 2: first unlabeled JSON block containing "symbol"
    for label, body in _iter_json_code_blocks(text):
        if not label and body.startswith('{') and '"symbol"' in body:
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
        if label == "TRADE_PLAN_JSON" and body.startswith('{'):
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
    parts = re.split(r'\n(?:#{1,4}\s*)?CLAIM(?:\s*\d+|\s*\[[\w-]+\])?[：:]\s*', text)
    for i, part in enumerate(parts[1:], start=1):  # skip text before first CLAIM
        claim = {
            "claim_id": f"clm-{direction[0]}{i:03d}",
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
                    claim["supports"] = [f"prose-{direction[0]}{i:03d}"]
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
            # Normalize: if agent used 1-10 scale despite 0.0-1.0 instruction
            if claim["confidence"] > 1.0:
                claim["confidence"] = claim["confidence"] / 10.0
        else:
            claim["confidence"] = 0.5

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
    block = _extract_tagged_block("MACRO_OUTPUT", text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_breadth_output(text: str) -> Dict[str, Any]:
    """Extract BREADTH_OUTPUT: key=value block."""
    block = _extract_tagged_block("BREADTH_OUTPUT", text)
    if not block:
        return {}
    j = _try_json_parse(block)
    if j is not None:
        return j
    return _parse_kv_block(block)


def parse_sector_output(text: str) -> Dict[str, Any]:
    """Extract SECTOR_OUTPUT: key=value block with array fields."""
    block = _extract_tagged_block("SECTOR_OUTPUT", text)
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
) -> Dict[str, Any]:
    """Combine 3 market agent outputs into a canonical market_context dict.

    Args:
        global_macro: Parsed output from web_collector.parse_global_macro_output().
            When provided, merged as ``market_context["global_macro"]`` and
            geopolitical risks are appended to ``risk_alerts``.
        raw_texts: Optional dict of raw agent output texts keyed by
            ``"macro"``, ``"breadth"``, ``"sector"``.  When provided *and*
            *trade_date* is set, each text's embedded content date is validated
            against *trade_date*.  Raises :class:`StaleMarketDataError` on
            mismatch.
    """
    # ── Date validation guard ──
    if raw_texts and trade_date:
        validate_market_agent_dates(
            trade_date,
            macro_text=raw_texts.get("macro", ""),
            breadth_text=raw_texts.get("breadth", ""),
            sector_text=raw_texts.get("sector", ""),
        )

    regime = str(macro.get("regime", "NEUTRAL")).upper()
    breadth_state = str(breadth.get("breadth_state", "NARROW")).upper()

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
        "risk_alerts": str(macro.get("risk_alerts", "")),
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
    leaders = ", ".join(ctx.get("sector_leaders", [])) or "无"
    avoid = ", ".join(ctx.get("avoid_sectors", [])) or "无"
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


def _extract_evidence_items(text: str, max_items: int = 8) -> List[str]:
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
        for item_text in _extract_evidence_items(text):
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


def _extract_financial_metrics(text: str) -> Dict[str, str]:
    """Scrape basic financial metrics from free-text analyst output.

    When vendor APIs are unavailable, these can serve as fallback data
    for the Snapshot metrics card.  Handles both ``key: value`` prose and
    markdown-table ``| key | value |`` formats.
    """
    metrics: Dict[str, str] = {}

    # Each entry: (output_key, list of (pattern, group_index) to try in order)
    # A = "key: value" prose;  B = "| key | value |" table;  C = inline "key为/仅N" prose
    specs: List[Tuple[str, List[Tuple[str, int]]]] = [
        ("pe", [
            (r'(?:PE|市盈率)(?:\([^)]*\))?\s*[:：]\s*([-\d.]+)', 1),
            (r'\|\s*(?:PE|市盈率)(?:\([^)]*\))?\s*\|\s*([-\d.]+)', 1),
            (r'(?:PE|市盈率)(?:\([^)]*\))?\s*[^\d]*?([-\d.]+)\s*(?:倍|%|元)?', 1),
        ]),
        ("pb", [
            (r'(?:PB|市净率)\s*[:：]\s*([\d.]+)', 1),
            (r'\|\s*(?:PB|市净率)\s*\|\s*([\d.]+)', 1),
            (r'(?:PB|市净率)\s*[^\d]*?([\d.]+)\s*(?:倍|%)?', 1),
        ]),
        ("market_cap", [
            (r'(?:总市值|市值)\s*[:：]\s*([\d.]+)\s*(?:亿|万亿)?', 1),
            (r'\|\s*(?:总市值|市值)\s*\|\s*([\d.]+)\s*(?:亿|万亿)?', 1),
            (r'(?:总市值)\s*[^\d]*?([\d.]+)\s*(?:亿|万亿)', 1),
        ]),
        ("gross_margin", [
            (r'(?:毛利率)\s*[:：]\s*([\d.]+)%?', 1),
            (r'\|\s*(?:毛利率)\s*\|\s*([\d.]+)%?', 1),
            (r'(?:毛利率)\s*[^\d]*?([\d.]+)%', 1),
        ]),
        ("roe", [
            (r'(?:ROE|净资产收益率)\s*[:：]\s*([-\d.]+)%?', 1),
            (r'\|\s*(?:ROE|净资产收益率)\s*\|\s*([-\d.]+)%?', 1),
            (r'(?:ROE|净资产收益率)\s*[^\d-]*?([-\d.]+)%', 1),
        ]),
        ("net_profit", [
            (r'(?:净利润|归母净利润)\s*[:：]\s*([-\d.]+)\s*(?:亿|万)?', 1),
            (r'\|\s*(?:净利润|归母净利润)\s*\|\s*([-\d.]+)\s*(?:亿|万)?', 1),
            (r'(?:归母净利润|净利润)\s*[^\d-]*?([-\d.]+)\s*(?:亿|万)', 1),
        ]),
        ("eps", [
            (r'(?:EPS|每股收益)\s*[:：]\s*([-\d.]+)', 1),
            (r'\|\s*(?:EPS|每股收益)\s*\|\s*([-\d.]+)', 1),
            (r'(?:EPS|每股收益)\s*[^\d-]*?([-\d.]+)\s*(?:元)?', 1),
        ]),
    ]

    for key, pats in specs:
        for pat, grp in pats:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(grp)
                # Negate if "亏损" appears between the keyword and the number
                if not val.startswith('-'):
                    prefix = text[max(0, m.start() - 5):m.start(grp)]
                    if '亏损' in prefix:
                        val = '-' + val
                metrics[key] = val
                break
    return metrics


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  2. Builders — assemble NodeTrace and RunTrace objects                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def build_node_trace(
    agent_key: str,
    text: str,
    run_id: str,
    seq: Optional[int] = None,
) -> NodeTrace:
    """Build a NodeTrace from agent text output.

    Fills structured_data based on agent type, with graceful fallback
    when parsing fails (excerpt-only mode).
    """
    node_name = AGENT_NODE_MAP.get(agent_key, agent_key)
    if seq is None:
        seq = AGENT_SEQ.get(agent_key, 99)

    nt = NodeTrace(
        run_id=run_id,
        node_name=node_name,
        seq=seq,
        timestamp=datetime.now(),
        output_hash=compute_hash(text),
        output_excerpt=text[:500] if text else "",
    )

    # Default parse status
    nt.parse_status = "strict_ok"
    nt.parse_confidence = 1.0

    try:
        _populate_structured_data(agent_key, text, nt)
    except Exception as e:
        logger.warning(f"Parse failed for {agent_key}: {e}")
        nt.parse_status = "failed"
        nt.parse_confidence = 0.0
        nt.parse_warnings = [str(e)]
        nt.status = NodeStatus.WARN

    return nt


def _populate_structured_data(agent_key: str, text: str, nt: NodeTrace) -> None:
    """Fill NodeTrace fields based on agent type."""

    # ── Stage 0.8: Market Agents ──
    if agent_key == "macro_analyst":
        parsed = parse_macro_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["MACRO_OUTPUT block not found"]
            nt.status = NodeStatus.WARN
        return

    elif agent_key == "market_breadth_agent":
        parsed = parse_breadth_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["BREADTH_OUTPUT block not found"]
            nt.status = NodeStatus.WARN
        return

    elif agent_key == "sector_rotation_agent":
        parsed = parse_sector_output(text)
        if parsed:
            nt.structured_data = parsed
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["SECTOR_OUTPUT block not found"]
            nt.status = NodeStatus.WARN
        return

    # ── Stage 1: Analysts (pillar_score) ──
    if agent_key in ("market_analyst", "fundamentals_analyst",
                      "news_analyst", "sentiment_analyst"):
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

    # ── Stage 2: Catalyst Agent ──
    elif agent_key == "catalyst_agent":
        catalysts = parse_catalyst_json(text)
        if catalysts:
            nt.structured_data = {"catalysts": catalysts}
            nt.evidence_ids_referenced = parse_evidence_citations(text)
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.5
            nt.parse_warnings = ["CATALYST_OUTPUT block not found or invalid"]
            nt.status = NodeStatus.WARN

    # ── Stage 3: Bull/Bear Researchers ──
    elif agent_key in ("bull_researcher", "bear_researcher"):
        direction = "bullish" if agent_key == "bull_researcher" else "bearish"
        claims = parse_claims(text, direction)
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
            "opposing_claims": [],
            "unresolved_conflicts": [],
            "missing_evidence": [],
        }

        if not claims:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.6
            nt.parse_warnings = ["No structured CLAIM blocks found"]
            nt.status = NodeStatus.WARN

    # ── Stage 4: Scenario Agent ──
    elif agent_key == "scenario_agent":
        scenario = parse_scenario_output(text)
        if scenario:
            probs_defaulted = (
                "base_prob" not in scenario
                or "bull_prob" not in scenario
                or "bear_prob" not in scenario
            )
            nt.structured_data = {
                "base_prob": scenario.get("base_prob", 0.5),
                "bull_prob": scenario.get("bull_prob", 0.25),
                "bear_prob": scenario.get("bear_prob", 0.25),
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
            nt.parse_warnings = ["SCENARIO_OUTPUT block not found"]
            nt.status = NodeStatus.WARN

    # ── Stage 5: Research Manager (PM) ──
    elif agent_key == "research_manager":
        synth = parse_synthesis_output(text)
        if synth:
            action = str(synth.get("research_action", "HOLD")).upper()
            nt.research_action = action
            _conf_defaulted = "confidence" not in synth
            try:
                nt.confidence = float(synth.get("confidence", 0.5))
            except (ValueError, TypeError):
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
            }
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.4
            nt.parse_warnings = ["SYNTHESIS_OUTPUT block not found"]
            nt.status = NodeStatus.WARN
            # Try to infer action from text
            if '买入' in text or 'BUY' in text.upper():
                nt.research_action = "BUY"
            elif '卖出' in text or 'SELL' in text.upper():
                nt.research_action = "SELL"
            else:
                nt.research_action = "HOLD"
            nt.confidence = 0.5

    # ── Stage 5b: Risk Debators ──
    elif agent_key in ("aggressive_debator", "conservative_debator", "neutral_debator"):
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

    # ── Stage 6: Risk Manager (Judge) ──
    elif agent_key == "risk_manager":
        risk = parse_risk_output(text)
        if risk:
            nt.risk_score = _safe_int(risk.get("risk_score"))
            nt.risk_cleared = risk.get("risk_cleared", False)
            if "risk_cleared" not in risk:
                warnings = list(nt.parse_warnings or [])
                warnings.append("risk_cleared not explicitly provided, defaulted to False")
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
            raw_conf = risk.get("confidence")
            nt.confidence = _safe_float(raw_conf) if raw_conf is not None else -1.0
            nt.vetoed = action == "VETO" or not nt.risk_cleared
            if action == "VETO":
                nt.veto_source = "agent_veto"
            elif not nt.risk_cleared:
                nt.veto_source = "risk_gate"

            # Risk flags
            if risk.get("_risk_flags_parse_failed"):
                warnings = list(nt.parse_warnings or [])
                warnings.append("risk_flags JSON parse failed, flags may be incomplete")
                nt.parse_warnings = warnings
            flags = risk.get("risk_flags", [])
            nt.risk_flag_count = len(flags)
            nt.risk_flag_categories = list(dict.fromkeys(
                f.get("category", "") for f in flags if f.get("category")
            ))

            nt.structured_data = {
                "conclusion": f"风险评分 {nt.risk_score}/10，"
                              + ("审查通过" if nt.risk_cleared else "审查未通过"),
                "invalidation_conditions": [],
                "risk_flags": [
                    {
                        "flag_id": f"rf-{i+1:03d}",
                        "category": f.get("category", ""),
                        "severity": f.get("severity", "medium").lower()
                               if str(f.get("severity", "medium")).lower()
                               in ("low", "medium", "high", "critical")
                               else "medium",
                        "description": f.get("description", ""),
                        "bound_evidence_ids": (
                            [f.get("evidence", "")] if isinstance(f.get("evidence"), str)
                            else f.get("evidence", [])
                        ),
                        "mitigant": f.get("mitigant", ""),
                    }
                    for i, f in enumerate(flags)
                ],
            }

            nt.evidence_ids_referenced = parse_evidence_citations(text)
        else:
            nt.parse_status = "fallback_used"
            nt.parse_confidence = 0.3
            nt.parse_warnings = ["RISK_OUTPUT block not found"]
            nt.status = NodeStatus.WARN
            nt.risk_score = 5
            nt.risk_cleared = False

    # ── Stage 7: Research Output (Trade Card + Trade Plan) ──
    elif agent_key == "research_output":
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
                nt.confidence = _confidence_to_float(tc_conf)
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
                    nt.confidence = _confidence_to_float(tp_conf)
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

    return


def _split_if_string(val) -> list:
    """Convert string to list (split on semicolons/newlines) or pass through list."""
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val:
        return [x.strip() for x in re.split(r'[;；\n]', val) if x.strip()]
    return []


_CONFIDENCE_MAP = {
    "high": 0.8, "med": 0.5, "medium": 0.5, "low": 0.2,
    "高": 0.8, "中": 0.5, "低": 0.2,
}


def _confidence_to_float(val, default: float = -1.0) -> float:
    """Convert confidence value to float.

    Handles numeric values, numeric strings, AND word labels
    ("High"/"Med"/"Low") that the TRADECARD_JSON prompt spec uses.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        mapped = _CONFIDENCE_MAP.get(val.strip().lower())
        if mapped is not None:
            return mapped
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    return default


def _safe_int(val, default=None):
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    try:
        return float(val)
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
) -> RunTrace:
    """Assemble a complete RunTrace from agent outputs dict.

    Args:
        outputs: Dict mapping agent_key → agent text output.
                 Keys should be from AGENT_NODE_MAP (e.g. "market_analyst").
        ticker: Stock ticker (e.g. "601985")
        ticker_name: Human-readable name (e.g. "中国核电")
        trade_date: Analysis date (e.g. "2026-03-12")
        run_id: Optional custom run ID (auto-generated if None)

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
        trade_date=trade_date or datetime.now().strftime("%Y-%m-%d"),
        as_of=datetime.now().strftime("%Y-%m-%d"),
        started_at=datetime.now(),
        market="cn",
        language="zh",
        llm_provider="subagent",
    )

    # Build NodeTraces in execution order
    for agent_key in sorted(outputs.keys(), key=lambda k: AGENT_SEQ.get(k, 99)):
        text = outputs[agent_key]
        if not text:
            continue
        nt = build_node_trace(agent_key, text, run_id)
        trace.node_traces.append(nt)

    # Publishing Compliance — run lightweight deterministic checks
    # (subagent_pipeline cannot import the full engine from tradingagents/)
    compliance_reasons: list = []
    compliance_status = "allow"
    rules_fired = []

    # P1: source tier — check if evidence block was produced
    has_evidence = any(nt.node_name in ("Evidence Block",) or
                       bool(nt.evidence_ids_referenced) for nt in trace.node_traces)
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
    if was_vetoed and rm_action == "BUY":
        compliance_reasons.append("P5: VETO后仍为BUY，方向不一致")
        compliance_status = "flag"

    if compliance_reasons:
        compliance_status = "flag"

    compliance_nt = NodeTrace(
        run_id=run_id,
        node_name="Publishing Compliance",
        seq=18,  # after research_output (seq=17), no conflicts
        timestamp=datetime.now(),
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
    return (price_history[-1] - price_history[-(window + 1)]) / price_history[-(window + 1)]


def _try_fetch_prices(ticker: str, days: int = 30) -> List[float]:
    """Fetch recent close prices via akshare for sparkline rendering.

    Returns empty list on any failure (missing package, network, etc.).
    """
    try:
        import akshare as ak  # noqa: delayed import — optional dependency
        from datetime import date, timedelta

        bare = ticker.replace(".SS", "").replace(".SZ", "").replace(".BJ", "")
        end = date.today()
        start = end - timedelta(days=days + 10)
        df = ak.stock_zh_a_hist(
            symbol=bare, period="daily", adjust="qfq",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        return df["收盘"].tail(days).tolist()
    except Exception:
        return []


def generate_report(
    outputs: Dict[str, str],
    ticker: str,
    ticker_name: str = "",
    trade_date: str = "",
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    run_id: Optional[str] = None,
    price_history: Optional[List[float]] = None,
    market_context_block: str = "",
    market_context: Optional[Dict] = None,
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

    Returns:
        Dict of {"snapshot": path, "research": path, "audit": path, "run_id": id}
    """
    # 1. Build RunTrace
    trace = build_run_trace(outputs, ticker, ticker_name, trade_date, run_id)

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
                break
    # 1c. Trend override — downgrade pillar scores when recent trend is strongly negative
    from .config import PIPELINE_CONFIG
    _tw = PIPELINE_CONFIG.get("trend_override_window", 5)
    _thr = PIPELINE_CONFIG.get("trend_override_threshold", -0.05)
    _td = PIPELINE_CONFIG.get("trend_override_downgrade", 1)
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
