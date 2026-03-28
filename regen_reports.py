"""Re-generate L3-L8 reports after L1 market context correction.

Usage: python agent_artifacts/regen_reports.py
"""
import json
import sys
import os

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagent_pipeline.bridge import (
    parse_macro_output, parse_breadth_output, parse_sector_output,
    assemble_market_context, format_market_context_block,
    generate_report, validate_market_agent_dates,
)
from subagent_pipeline.renderers.report_renderer import (
    generate_pool_report, generate_market_report,
)
from subagent_pipeline.renderers.debate_renderer import generate_committee_report
from subagent_pipeline.replay_store import ReplayStore
from subagent_pipeline.akshare_collector import collect_market_snapshot

RESULTS = "agent_artifacts/results"
REPORTS = "data/reports"
REPLAYS = "data/replays"
TRADE_DATE = "2026-03-26"

TICKERS = [
    ("688114", "\u534e\u5927\u667a\u9020"),
    ("300627", "\u534e\u6d4b\u5bfc\u822a"),
    ("601985", "\u4e2d\u56fd\u6838\u7535"),
    ("300676", "\u534e\u5927\u57fa\u56e0"),
    ("600529", "\u5c71\u4e1c\u836f\u73bb"),
    ("603065", "\u5bbf\u8fc1\u8054\u76db"),
    ("000710", "\u8d1d\u745e\u57fa\u56e0"),
    ("920344", "\u4e09\u5143\u751f\u7269"),
    ("688298", "\u4e1c\u65b9\u751f\u7269"),
    ("002131", "\u5229\u6b27\u80a1\u4efd"),
]

RUN_IDS = json.load(open(f"{RESULTS}/run_ids.json"))


def read(name):
    with open(f"{RESULTS}/{name}", "r") as f:
        return f.read()


def main():
    # ── Step 1: Parse L1 agent outputs ──
    print("=== Step 1: Parse L1 agent outputs ===")
    macro_text = read("macro_analyst_output.txt")
    breadth_text = read("market_breadth_agent_output.txt")
    sector_text = read("sector_rotation_agent_output.txt")

    # Date validation — this is the P0 fix in action
    validate_market_agent_dates(
        TRADE_DATE,
        macro_text=macro_text,
        breadth_text=breadth_text,
        sector_text=sector_text,
    )
    print("  \u2713 Date validation passed")

    macro = parse_macro_output(macro_text)
    breadth = parse_breadth_output(breadth_text)
    sector = parse_sector_output(sector_text)
    print(f"  regime={macro.get('regime')}, breadth={breadth.get('breadth_state')}")

    # Parse global macro if available
    global_macro = None
    try:
        gm_text = read("global_macro_output.txt")
        if gm_text.strip():
            from subagent_pipeline.web_collector import parse_global_macro_output
            global_macro = parse_global_macro_output(gm_text)
            print("  \u2713 Global macro parsed")
    except FileNotFoundError:
        print("  (no global macro output)")

    # ── Step 2: Assemble market context ──
    print("\n=== Step 2: Assemble market context ===")
    market_context = assemble_market_context(
        macro, breadth, sector, TRADE_DATE,
        global_macro=global_macro,
        raw_texts={
            "macro": macro_text,
            "breadth": breadth_text,
            "sector": sector_text,
        },
    )
    market_context_block = format_market_context_block(market_context)

    # Save updated files
    with open(f"{RESULTS}/market_context.json", "w") as f:
        json.dump(market_context, f, ensure_ascii=False, indent=2)
    with open(f"{RESULTS}/market_context_block.txt", "w") as f:
        f.write(market_context_block)
    print(f"  regime={market_context['regime']}, pcm={market_context['position_cap_multiplier']}")
    print(f"  breadth_state={market_context['breadth_state']}, adr={market_context['advance_decline_ratio']}")
    print("  \u2713 market_context.json + market_context_block.txt saved")

    # ── Step 3: Regenerate L3 reports (10 stocks) ──
    print("\n=== Step 3: Regenerate L3 reports (10 stocks) ===")
    store = ReplayStore(storage_dir=REPLAYS)
    new_run_ids = []

    for (ticker, name), old_run_id in zip(TICKERS, RUN_IDS):
        outputs = {}
        agent_map = {
            "market_analyst": f"{ticker}_market_report.txt",
            "fundamentals_analyst": f"{ticker}_fundamentals_report.txt",
            "news_analyst": f"{ticker}_news_report.txt",
            "sentiment_analyst": f"{ticker}_sentiment_report.txt",
            "catalyst_agent": f"{ticker}_catalyst_report.txt",
            "bull_researcher": f"{ticker}_bull_merged.txt",
            "bear_researcher": f"{ticker}_bear_merged.txt",
            "scenario_agent": f"{ticker}_scenario_report.txt",
            "research_manager": f"{ticker}_research_manager.txt",
            "aggressive_debator": f"{ticker}_risk_aggressive.txt",
            "conservative_debator": f"{ticker}_risk_conservative.txt",
            "neutral_debator": f"{ticker}_risk_neutral.txt",
            "risk_manager": f"{ticker}_risk_manager.txt",
            "research_output": f"{ticker}_research_output.txt",
        }
        for key, fname in agent_map.items():
            try:
                outputs[key] = read(fname)
            except FileNotFoundError:
                print(f"  WARNING: missing {fname}")

        paths = generate_report(
            outputs=outputs,
            ticker=ticker,
            ticker_name=name,
            trade_date=TRADE_DATE,
            output_dir=REPORTS,
            storage_dir=REPLAYS,
            market_context_block=market_context_block,
            market_context=market_context,
        )
        new_run_ids.append(paths["run_id"])
        print(f"  \u2713 {ticker} {name} -> {paths['run_id']}")

    # Save new run_ids
    with open(f"{RESULTS}/run_ids.json", "w") as f:
        json.dump(new_run_ids, f, indent=2)

    # ── Step 4: Regenerate L4 committee reports ──
    print("\n=== Step 4: Regenerate L4 committee reports ===")
    for rid in new_run_ids:
        trace = store.load(rid)
        generate_committee_report(trace, output_dir=REPORTS)
        print(f"  \u2713 committee for {rid}")

    # ── Step 5: Regenerate L5 pool report ──
    print("\n=== Step 5: Regenerate L5 pool report ===")
    try:
        snap = collect_market_snapshot(
            trade_date=TRADE_DATE,
            watchlist=[t[0] for t in TICKERS],
        )
        snap_dict = {
            "indices": getattr(snap, "indices", {}),
            "breadth": getattr(snap, "breadth", {}),
            "northbound": getattr(snap, "northbound", {}),
            "sector_flow": getattr(snap, "sector_flow", []),
            "watchlist_spots": getattr(snap, "watchlist_spots", {}),
        }
    except Exception as e:
        print(f"  (snapshot fetch failed: {e}, using None)")
        snap_dict = None

    generate_pool_report(
        run_ids=new_run_ids,
        output_dir=REPORTS,
        storage_dir=REPLAYS,
        trade_date=TRADE_DATE,
        market_context=market_context,
        market_snapshot=snap_dict,
    )
    print("  \u2713 pool report generated")

    # ── Step 6: Regenerate L6 market report ──
    print("\n=== Step 6: Regenerate L6 market report ===")
    generate_market_report(
        market_context=market_context,
        market_snapshot=snap_dict,
        output_dir=REPORTS,
        trade_date=TRADE_DATE,
    )
    print("  \u2713 market report generated")

    # ── Step 7: Regenerate brief ──
    print("\n=== Step 7: Regenerate brief ===")
    lines = [f"# \u6bcf\u65e5\u7814\u7a76\u7b80\u62a5 \u2014 {TRADE_DATE}\n"]
    lines.append("## \u5e02\u573a\u73af\u5883\n")
    lines.append(f"- \u4f53\u5236: {market_context['regime']}")
    lines.append(f"- \u5929\u6c14: {market_context['market_weather']}")
    lines.append(f"- \u98ce\u683c\u504f\u5411: {market_context['style_bias']}")
    lines.append(f"- \u4ed3\u4f4d\u7cfb\u6570: {market_context['position_cap_multiplier']}")
    lines.append(f"- \u98ce\u9669\u8b66\u793a: {market_context.get('risk_alerts', 'NONE')}\n")

    lines.append("## \u4e2a\u80a1\u4fe1\u53f7\u6c47\u603b\n")
    lines.append("| \u80a1\u7968 | \u4fe1\u53f7 | \u7f6e\u4fe1\u5ea6 | \u6280\u672f | \u57fa\u672c\u9762 | \u6d88\u606f | \u60c5\u7eea | \u98ce\u9669 |")
    lines.append("|------|------|--------|------|--------|------|------|------|")

    def fmt_conf(c):
        if c is None or c < 0:
            return "\u2014"
        if c <= 1.0:
            return f"{c*100:.0f}%"
        return f"{c:.0f}%"

    def fmt_score(v):
        if v is None or v == -1 or v == -1.0:
            return "\u2014"
        return str(v)

    signal_dist = {}
    for rid, (ticker, name) in zip(new_run_ids, TICKERS):
        trace = store.load(rid)
        action = trace.research_action or "UNKNOWN"
        if trace.was_vetoed:
            action = "VETO"
        conf = trace.final_confidence

        # Get pillar scores — check analyst nodes first, then tradecard fallback
        scores = {"market": -1, "fundamental": -1, "news": -1, "sentiment": -1, "risk": -1}
        _analyst_node_map = {
            "Market Analyst": "market",
            "Fundamentals Analyst": "fundamental",
            "News Analyst": "news",
            "Social Analyst": "sentiment",
        }
        for nt in trace.node_traces:
            if nt.node_name in _analyst_node_map:
                sd = nt.structured_data or {}
                ps = sd.get("pillar_score")
                if ps is not None:
                    try:
                        scores[_analyst_node_map[nt.node_name]] = int(ps)
                    except (ValueError, TypeError):
                        pass
            if nt.node_name == "ResearchOutput":
                sd = nt.structured_data or {}
                tc = sd.get("tradecard", {})
                p = tc.get("pillars", {})
                if p:
                    # Only fill in missing scores
                    if scores["market"] < 0:
                        scores["market"] = p.get("market_score", -1)
                    if scores["fundamental"] < 0:
                        scores["fundamental"] = p.get("fundamental_score", -1)
                    if scores["news"] < 0:
                        scores["news"] = p.get("news_score", p.get("macro_score", -1))
                    if scores["sentiment"] < 0:
                        scores["sentiment"] = p.get("sentiment_score", -1)
            if nt.node_name == "Risk Judge":
                if nt.risk_score is not None and nt.risk_score >= 0:
                    scores["risk"] = nt.risk_score

        # Signal emoji — VETO distinguishes risk_gate vs agent_veto
        veto_source = getattr(trace, "veto_source", "")
        if action == "VETO":
            if veto_source == "risk_gate":
                emoji = "\u26d4"
                action_label = "VETO(风控)"
            elif veto_source == "agent_veto":
                emoji = "\u26d4"
                action_label = "VETO(研究)"
            else:
                emoji = "\u26d4"
                action_label = "VETO"
        elif action == "BUY":
            emoji = "\U0001f7e2"
            action_label = action
        elif action == "SELL":
            emoji = "\U0001f534"
            action_label = action
        else:
            emoji = "\U0001f7e1"
            action_label = action

        label = signal_dist.get(action, 0)
        signal_dist[action] = label + 1

        lines.append(
            f"| {name} | {emoji} {action_label} | {fmt_conf(conf)} "
            f"| {fmt_score(scores['market'])} | {fmt_score(scores['fundamental'])} "
            f"| {fmt_score(scores['news'])} | {fmt_score(scores['sentiment'])} "
            f"| {fmt_score(scores['risk'])} |"
        )

    lines.append("\n## \u4fe1\u53f7\u5206\u5e03\n")
    label_map = {
        "BUY": "\u5efa\u8bae\u5173\u6ce8 (BUY)",
        "HOLD": "\u6301\u6709\u89c2\u5bdf (HOLD)",
        "SELL": "\u5efa\u8bae\u56de\u907f (SELL)",
        "VETO": "\u98ce\u63a7\u5426\u51b3 (VETO)",
    }
    for act in ["BUY", "HOLD", "SELL", "VETO"]:
        if act in signal_dist:
            lines.append(f"- {label_map.get(act, act)}: {signal_dist[act]} \u53ea")

    with open(f"{REPORTS}/brief-{TRADE_DATE}.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("  \u2713 brief generated")

    print(f"\n=== DONE: {len(new_run_ids)} stocks regenerated with corrected market context ===")
    print(f"  Regime: {market_context['regime']}")
    print(f"  Position cap: {market_context['position_cap_multiplier']}")


if __name__ == "__main__":
    main()
