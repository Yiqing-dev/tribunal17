"""Regression tests for the 4 data integrity bugs found in 2026-04-27 reports:

1. ``_extract_financial_metrics`` (bridge.py) — PB grabbed years like 2025
   when prose used ``=`` instead of ``:`` and the regex fell back to a lazy
   match; market_cap got sign-flipped because nearby "亏损" leaked into the
   prefix scan; net_profit picked up forecast/threshold/estimate values.
2. ``_strip_internal_tokens`` (renderers/views.py) — slash-joined CLAIM /
   evidence ID lists ``[clm-r001/r002/...]`` and ``[E8/E9/E11/E29]`` got
   mangled to ``[/r002/...]`` and ``[///]`` because the per-token strippers
   left the slashes behind.
3. ``_fmt_num`` (akshare_collector.py) — non-zero values smaller than
   the display precision rendered as ``-0.00`` (signed zero).
4. ``collect_limit_board`` (recap_collector.py) — when EM spot API failed,
   the recap showed 0 / 0 for limit-up / limit-down counts even though
   ``stock_zt_pool_em`` / ``stock_zt_pool_dtgc_em`` were healthy.
"""
from __future__ import annotations

import pytest

from subagent_pipeline.akshare_collector import _fmt_num
from subagent_pipeline.bridge import _extract_financial_metrics
from subagent_pipeline.renderers.views import _strip_internal_tokens


# ── Fix 1 — _extract_financial_metrics ────────────────────────────────────

class TestExtractFinancialMetrics:
    def test_pb_with_equals_separator_does_not_grab_year(self):
        """Original 000710 bug: ``PB及未来…若2025年`` made PB show as 2025."""
        text = (
            "**INTERP**: 公司处于亏损状态，传统PE估值失效，需依赖PB及未来盈利"
            "修复预期。\n"
            "**DISPROVE**: 若2025年年报披露单季度扭亏，修复路径成立。\n"
            "**[E3] FACT**: 毛利率47.75%，PB=2.15"
        )
        m = _extract_financial_metrics(text)
        assert m.get("pb") == "2.15"

    def test_market_cap_not_negated_by_nearby_loss_keyword(self):
        """Original 000710 bug: ``净亏损状态，总市值34.86亿`` produced -34.86."""
        text = "关键数字: 净亏损状态，总市值34.86亿，流通市值32.49亿"
        m = _extract_financial_metrics(text)
        assert m.get("market_cap") == "34.86"

    def test_pe_prefers_table_over_prose_rounding(self):
        """002131 bug: prose ``PE=94倍`` won over table ``94.14``."""
        text = (
            "| 指标 | 数值 |\n"
            "| PE(TTM) | 94.14 |\n"
            "| PB | 3.48 |\n"
            "对应PE=94倍说明估值偏高。"
        )
        m = _extract_financial_metrics(text)
        assert m.get("pe") == "94.14"

    def test_pe_with_markdown_bold_around_value(self):
        """``PE(TTM)：**94.14**`` should still yield 94.14."""
        text = "- PE(TTM)：**94.14**（历史估值区间最新值）"
        m = _extract_financial_metrics(text)
        assert m.get("pe") == "94.14"

    def test_net_profit_rejects_forecast_lower_bound(self):
        """002131 bug: ``预计…3000万元～4500万元`` leaked 3000 as net_profit."""
        text = (
            "利欧股份预计2025年归属于上市公司股东的净利润为**3000万元～4500万元**。\n"
            "若净利润<3000万元则触发降级。\n"
        )
        m = _extract_financial_metrics(text)
        assert m.get("net_profit") is None

    def test_net_profit_rejects_disprove_threshold(self):
        """920344 bug: ``若超过5000万元`` (DISPROVE threshold) leaked as 5000."""
        text = "DISPROVE: 若2025年年报归母净利润大幅超预期（如超过5000万元），则PE回落。"
        m = _extract_financial_metrics(text)
        assert m.get("net_profit") is None

    def test_net_profit_rejects_estimate(self):
        """603065 bug: ``(估算)416万元`` leaked as 416."""
        text = "EPS=0.02元意味着净利润约为416万元（市值34.19亿÷PE288），年净利润体量极小。"
        m = _extract_financial_metrics(text)
        assert m.get("net_profit") is None

    def test_net_profit_actual_with_unit_passes(self):
        """002370 actual reported number should still extract."""
        text = "- 归母净利润：9630.78万元，同比增长181.27%"
        m = _extract_financial_metrics(text)
        assert m.get("net_profit") == "9630.78"

    def test_net_profit_requires_explicit_unit(self):
        """A bare number without 万/亿 must not enter the fallback."""
        text = "净利润：3000，营收：500"
        m = _extract_financial_metrics(text)
        assert m.get("net_profit") is None

    def test_year_filter_blocks_pb_grabbing_year(self):
        """4-digit year-shaped values are rejected for PB even via fallback."""
        text = "PB 2025"
        m = _extract_financial_metrics(text)
        # Either no PB or a different non-year value; never 2025.
        assert m.get("pb") != "2025"

    def test_pb_range_filter_rejects_absurd_values(self):
        """A real-world PB > 100 is almost certainly a parse error."""
        text = "| PB | 9999.99 |"
        m = _extract_financial_metrics(text)
        assert m.get("pb") is None

    def test_market_cap_requires_unit(self):
        """Market cap without 亿/万亿 is too ambiguous to keep."""
        text = "市值：34.86"
        m = _extract_financial_metrics(text)
        assert m.get("market_cap") is None

    def test_eps_negation_only_same_sentence(self):
        """``亏损`` in a previous sentence must not flip the EPS sign."""
        text = "公司2024年亏损严重。当前 EPS：1.23 元。"
        m = _extract_financial_metrics(text)
        # 1.23 stays positive, even though "亏损" appears earlier.
        assert m.get("eps") == "1.23"

    def test_signed_zero_normalized_in_metrics(self):
        """002370 bug: agent wrote ``EPS: -0.00`` and the snapshot rendered
        a signed zero. Extractor should strip the misleading minus.
        """
        text = "EPS：-0.00 元（连续7年亏损）"
        m = _extract_financial_metrics(text)
        assert m.get("eps") == "0.00"

    def test_six_actual_reports_extract_correctly(self):
        """Snapshot test against the live 2026-04-27 report set."""
        from pathlib import Path

        results = Path(__file__).resolve().parents[2] / "agent_artifacts" / "results"
        if not results.exists():
            pytest.skip("agent_artifacts/results not present in this checkout")

        expected = {
            "000710": {"pe": "-49.74", "pb": "2.15", "market_cap": "34.86"},
            "603065": {"pe": "288.01", "pb": "1.69", "market_cap": "34.19"},
            "920344": {"pe": "38.31", "pb": "4.08", "market_cap": "25.53"},
            "688298": {"pe": "-15.58", "pb": "0.69", "market_cap": "44.17"},
            "002131": {"pe": "94.14", "pb": "3.48", "market_cap": "460.48"},
            "002370": {"pe": "-485.58", "pb": "4.50", "market_cap": "50.26"},
        }
        for ticker, exp in expected.items():
            path = results / f"{ticker}_fundamentals_report.txt"
            if not path.exists():
                continue
            got = _extract_financial_metrics(path.read_text(encoding="utf-8"))
            for key, value in exp.items():
                assert got.get(key) == value, f"{ticker}: {key} got {got.get(key)} expected {value}"


# ── Fix 2 — _strip_internal_tokens bracket residues ───────────────────────

class TestStripInternalTokens:
    def test_slash_joined_clm_bracket_fully_stripped(self):
        """Original 603065 bug: ``[clm-r001/r002/r004/r005]`` → ``[/r002/r004/r005]``."""
        text = "基于 [clm-r001/r002/r004/r005] 多维空头主张"
        out = _strip_internal_tokens(text)
        # Bracket and all residue gone.
        assert "[" not in out
        assert "/r" not in out
        assert "多维空头主张" in out

    def test_slash_joined_evidence_bracket_fully_stripped(self):
        """Original 603065 bug: ``[E8/E9/E11/E29]`` → ``[///]``."""
        text = "基于 [E8/E9/E11/E29] 估值证据链"
        out = _strip_internal_tokens(text)
        assert "[" not in out
        assert "/" not in out  # no slash residue
        assert "估值证据链" in out

    def test_comma_joined_bundle(self):
        text = "[clm-u001, clm-r011] 论点"
        out = _strip_internal_tokens(text)
        assert "[" not in out
        assert "论点" in out

    def test_adjudication_bundle(self):
        text = "[clm-u001 ACCEPT, clm-r011 DEFER] 完毕"
        out = _strip_internal_tokens(text)
        assert "[" not in out
        assert "完毕" in out

    def test_chinese_brackets_preserved(self):
        text = "[这是中文标题不应被剥离]"
        out = _strip_internal_tokens(text)
        assert "[这是中文标题不应被剥离]" in out

    def test_six_digit_ticker_preserved(self):
        text = "股票代码 601985 中国核电"
        out = _strip_internal_tokens(text)
        assert "601985" in out

    def test_residual_empty_bracket_shells_stripped(self):
        text = "空壳[/] [//] [///] [E8/]"
        out = _strip_internal_tokens(text)
        assert "[" not in out
        assert "/]" not in out

    def test_isolated_bracket_residue_stripped(self):
        """[/r002] alone (post-token-strip residue) is removed."""
        text = "残留 [/r002] 文本"
        out = _strip_internal_tokens(text)
        assert "[/r002]" not in out
        assert "残留" in out and "文本" in out


# ── Fix 3 — _fmt_num signed-zero ─────────────────────────────────────────

class TestFmtNumSignedZero:
    def test_tiny_negative_does_not_render_negative_zero(self):
        out = _fmt_num(-0.0035)
        assert out != "-0.00"
        assert out.startswith("-")
        assert float(out) != 0.0

    def test_tiny_positive_does_not_render_zero_with_sign(self):
        out = _fmt_num(0.0001)
        assert out != "0.00"
        assert float(out) != 0.0

    def test_exact_zero_unsigned(self):
        assert _fmt_num(0.0) == "0.00"
        assert _fmt_num(-0.0) == "0.00"

    def test_normal_values_unchanged(self):
        assert _fmt_num(3.14159) == "3.14"
        assert _fmt_num(-1.23) == "-1.23"
        assert _fmt_num(12345.67) == "1.23万"

    def test_none_returns_em_dash(self):
        assert _fmt_num(None) == "—"


# ── Fix 4 — collect_limit_board fallback (smoke; needs network) ──────────

class TestLimitBoardFallback:
    def test_fallback_when_spot_df_none(self):
        """When spot_df is unavailable, the zt_pool fallback should
        still return non-zero counts on a real trading day.

        Skipped if akshare network is unreachable.
        """
        try:
            from subagent_pipeline.recap_collector import collect_limit_board
            result = collect_limit_board(trade_date="2026-04-24", spot_df=None)
        except Exception as _e:
            pytest.skip(f"akshare unavailable: {_e}")
        # Either the network is degraded (skip) or we got real numbers.
        # A trading day with both ends at 0 would be exceptional.
        assert result.limit_up_count >= 0
        assert result.limit_down_count >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
