"""Regression tests for the single direction-reconcile gate (N-RSTK-01/02, N-DEB-05).

`reconcile_side` is the single source of truth for the direction shown on a card.
The key invariant: an AVOID ("do not participate") is never silently upgraded to
the more bullish HOLD/BUY — which previously killed the AVOID confidence/price
suppression in the snapshot Battle Plan.

Only depends on subagent_pipeline.renderers.shared_utils (no akshare /
dashboard / tradingagents imports), so it runs in this repo.
"""
from subagent_pipeline.renderers.shared_utils import reconcile_side


def test_avoid_not_overwritten_by_hold():
    # The exact bug: research_action=HOLD must NOT overwrite an AVOID card side.
    assert reconcile_side(card_side="AVOID", research_action="HOLD", was_vetoed=False) == "AVOID"


def test_avoid_not_overwritten_by_buy():
    assert reconcile_side(card_side="AVOID", research_action="BUY", was_vetoed=False) == "AVOID"


def test_avoid_overridden_by_sell():
    # A bearish trace direction may override AVOID (more risk-protective).
    assert reconcile_side(card_side="AVOID", research_action="SELL", was_vetoed=False) == "SELL"


def test_veto_dominates_everything():
    assert reconcile_side(card_side="BUY", research_action="BUY", was_vetoed=True) == "VETO"


def test_explicit_veto_action():
    assert reconcile_side(card_side="LONG", research_action="VETO", was_vetoed=False) == "VETO"


def test_trace_action_wins_over_stale_card():
    assert reconcile_side(card_side="LONG", research_action="SELL", was_vetoed=False) == "SELL"


def test_plain_buy_passthrough():
    assert reconcile_side(card_side="BUY", research_action="BUY", was_vetoed=False) == "BUY"


def test_empty_research_keeps_card_side():
    assert reconcile_side(card_side="LONG", research_action="", was_vetoed=False) == "LONG"


def test_case_insensitive():
    assert reconcile_side(card_side="avoid", research_action="hold", was_vetoed=False) == "AVOID"
