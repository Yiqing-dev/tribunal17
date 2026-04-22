"""Tests for P3: NodeTrace.input_hash and RunTrace.prompt_hashes wiring."""

from subagent_pipeline.bridge import build_node_trace, build_run_trace
from subagent_pipeline.trace_models import RunTrace, compute_hash


def test_input_hash_populated_with_prompt():
    """When prompt_text is provided, node.input_hash is the SHA-16 of the prompt."""
    nt = build_node_trace(
        agent_key="market_analyst",
        text="some output",
        run_id="test-run-1",
        prompt_text="hello world prompt",
    )
    assert nt.input_hash == compute_hash("hello world prompt")
    assert len(nt.input_hash) == 16


def test_input_hash_empty_when_prompt_none():
    """When prompt_text is omitted, node.input_hash stays empty for back-compat."""
    nt = build_node_trace(
        agent_key="market_analyst",
        text="some output",
        run_id="test-run-1",
    )
    assert nt.input_hash == ""


def test_input_hash_different_prompts_differ():
    """Different prompts produce different hashes."""
    nt_a = build_node_trace("market_analyst", "out", "r1", prompt_text="version A")
    nt_b = build_node_trace("market_analyst", "out", "r1", prompt_text="version B")
    assert nt_a.input_hash != nt_b.input_hash


def test_prompt_hashes_aggregated_to_runtrace():
    """RunTrace.prompt_hashes is populated from per-node input_hash when prompts given."""
    outputs = {
        "market_analyst": "market output text",
        "fundamentals_analyst": "fund output text",
    }
    prompts = {
        "market_analyst": "market prompt v1",
        "fundamentals_analyst": "fund prompt v1",
    }
    rt = build_run_trace(
        outputs=outputs,
        ticker="601985",
        trade_date="2026-04-21",
        prompts=prompts,
    )
    assert "market_analyst" in rt.prompt_hashes
    assert "fundamentals_analyst" in rt.prompt_hashes
    assert rt.prompt_hashes["market_analyst"] == compute_hash("market prompt v1")
    assert rt.prompt_hashes["fundamentals_analyst"] == compute_hash("fund prompt v1")


def test_prompt_hashes_empty_when_no_prompts_passed():
    """RunTrace.prompt_hashes defaults to empty dict when prompts not provided."""
    outputs = {"market_analyst": "out"}
    rt = build_run_trace(outputs=outputs, ticker="601985", trade_date="2026-04-21")
    assert rt.prompt_hashes == {}


def test_prompt_hashes_partial_fill():
    """Only agents with provided prompt_text appear in prompt_hashes dict."""
    outputs = {"market_analyst": "a", "news_analyst": "b"}
    prompts = {"market_analyst": "only market prompt"}  # news missing
    rt = build_run_trace(
        outputs=outputs,
        ticker="601985",
        trade_date="2026-04-21",
        prompts=prompts,
    )
    assert "market_analyst" in rt.prompt_hashes
    assert "news_analyst" not in rt.prompt_hashes


def test_from_dict_old_trace_no_prompt_hashes():
    """Loading an old RunTrace JSON lacking prompt_hashes → default empty dict."""
    old_trace_dict = {
        "run_id": "run-old",
        "ticker": "601985.SS",
        "ticker_name": "核电",
        "trade_date": "2026-01-01",
        "node_traces": [],
        # Intentionally no prompt_hashes key — simulates pre-P3 trace JSON
    }
    rt = RunTrace.from_dict(old_trace_dict)
    assert rt.prompt_hashes == {}
    assert rt.run_id == "run-old"


def test_to_dict_from_dict_roundtrip_preserves_prompt_hashes():
    """to_dict → from_dict preserves prompt_hashes content."""
    rt = RunTrace(
        run_id="run-1",
        ticker="601985.SS",
        trade_date="2026-04-21",
        prompt_hashes={"market_analyst": "abc123", "news_analyst": "def456"},
    )
    d = rt.to_dict()
    assert d["prompt_hashes"] == {"market_analyst": "abc123", "news_analyst": "def456"}
    rt2 = RunTrace.from_dict(d)
    assert rt2.prompt_hashes == rt.prompt_hashes
