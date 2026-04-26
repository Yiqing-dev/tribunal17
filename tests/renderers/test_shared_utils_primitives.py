"""Unit tests for V4 visual primitives in shared_utils.

Each primitive must:
1. Produce non-empty output for normal inputs
2. Include role="img" + aria-label (accessibility)
3. Tolerate None / NaN / negative / empty inputs without crashing
4. Use new V4 tokens (not hardcoded colors)
"""
import math

import pytest

from subagent_pipeline.renderers.shared_utils import (
    _score_pill, _priority_chip, _confidence_ring_svg, _ridge_bar,
    _delta_arrow, _heat_cell, _conf_dots, _section_divider,
    _empty_state_v2, _svg_minify, _conf_tier,
)


class TestScorePill:
    def test_normal(self):
        out = _score_pill(3, 4, "tech")
        assert out
        assert 'aria-label' in out
        assert 'conf-hi' in out  # 3/4 >= 0.75 → hi

    def test_low_tier(self):
        out = _score_pill(1, 4)
        assert 'conf-lo' in out

    def test_mid_tier(self):
        out = _score_pill(2, 4)
        assert 'conf-md' in out

    def test_none_doesnt_crash(self):
        out = _score_pill(None, 4)
        assert out
        assert 'aria-label' in out

    def test_clamps_out_of_range(self):
        out = _score_pill(99, 4)
        # Should render 4 filled dots (clamped)
        assert out.count("sp-dot on") == 4

    def test_negative_clamps_to_zero(self):
        out = _score_pill(-5, 4)
        assert out.count("sp-dot on") == 0


class TestPriorityChip:
    @pytest.mark.parametrize("level", ["hot", "warm", "cool", "mute"])
    def test_all_levels(self, level):
        out = _priority_chip(level, "test")
        assert f'prio-chip {level}' in out
        assert 'aria-label' in out

    def test_unknown_level_defaults_to_mute(self):
        out = _priority_chip("unknown", "x")
        assert 'mute' in out

    def test_empty_text(self):
        out = _priority_chip("hot", "")
        assert out  # still renders with just icon
        assert 'aria-label' in out


class TestConfidenceRing:
    def test_normal(self):
        out = _confidence_ring_svg(0.62, 72, "conf")
        assert 'aria-label="confidence 62% (conf)"' in out
        assert 'stroke-dasharray' in out

    def test_boundary_0(self):
        out = _confidence_ring_svg(0.0, 72)
        assert 'aria-label' in out

    def test_boundary_1(self):
        out = _confidence_ring_svg(1.0, 72)
        assert '100%' in out

    def test_none_renders_em_dash(self):
        out = _confidence_ring_svg(None, 72)
        assert '—' in out or '—' in out

    def test_nan_renders_em_dash(self):
        out = _confidence_ring_svg(float('nan'), 72)
        assert '—' in out or '—' in out

    def test_clamps_above_1(self):
        out = _confidence_ring_svg(1.5, 72)
        assert '100%' in out

    def test_clamps_below_0(self):
        out = _confidence_ring_svg(-0.3, 72)
        assert '0%' in out


class TestRidgeBar:
    def test_normal(self):
        out = _ridge_bar([1.2, -0.5, 2.1])
        assert 'aria-label' in out
        assert 'ridge-bar' in out

    def test_empty_returns_empty(self):
        assert _ridge_bar([]) == ""

    def test_negative_values_use_neg_class(self):
        out = _ridge_bar([-1.0, -2.0, 1.0])
        assert 'rb-seg neg' in out

    def test_labels_rendered(self):
        out = _ridge_bar([1.0, 2.0], ["A", "B"])
        assert '<span' in out
        assert 'A' in out and 'B' in out

    def test_nan_values_become_zero(self):
        # Should not crash
        out = _ridge_bar([float('nan'), 1.0])
        assert out


class TestDeltaArrow:
    def test_up(self):
        out = _delta_arrow(0.50, 0.62, "%")
        assert 'up' in out
        assert '▲' in out

    def test_down(self):
        out = _delta_arrow(0.62, 0.50, "%")
        assert 'down' in out
        assert '▼' in out

    def test_flat_below_threshold(self):
        out = _delta_arrow(5.0, 5.0001, threshold=0.001)
        assert 'flat' in out
        assert '—' in out

    def test_none_returns_dash(self):
        assert 'flat' in _delta_arrow(None, 1.0)
        assert 'flat' in _delta_arrow(1.0, None)


class TestHeatCell:
    def test_normal(self):
        out = _heat_cell(0.5, 0, 1)
        assert 'v-heat-cell' in out
        assert 'aria-label' in out

    def test_none(self):
        out = _heat_cell(None)
        assert 'v-heat-cell' in out
        assert 'aria-label="no value"' in out

    def test_pattern_sets_data_attr(self):
        out = _heat_cell(0.5, 0, 1, pattern="diag")
        assert 'data-pattern="diag"' in out

    def test_sequential_scale(self):
        out = _heat_cell(0.5, 0, 1, scale="sequential")
        assert 'v-heat-cell' in out

    def test_vmax_equals_vmin(self):
        # Should not crash
        out = _heat_cell(5.0, 5.0, 5.0)
        assert 'v-heat-cell' in out


class TestConfDots:
    def test_high_confidence(self):
        # 0.95 → round(4.75) = 5 (avoids banker's rounding of 0.9*5=4.5 → 4)
        out = _conf_dots(0.95, n=5)
        assert out.count("cd-dot on") == 5
        assert 'data-tier="hi"' in out

    def test_low_confidence(self):
        out = _conf_dots(0.2, n=5)
        assert 'data-tier="lo"' in out

    def test_none(self):
        out = _conf_dots(None)
        assert 'aria-label' in out

    def test_clamps_above_1(self):
        out = _conf_dots(1.5, n=5)
        assert out.count("cd-dot on") == 5


class TestSectionDivider:
    def test_normal(self):
        out = _section_divider("BUY", icon="🟢", count=3)
        assert 'BUY' in out
        assert 'role="separator"' in out
        assert 'aria-label' in out

    def test_no_count(self):
        out = _section_divider("Plain")
        assert 'Plain' in out

    def test_no_icon(self):
        out = _section_divider("NoIcon")
        assert 'NoIcon' in out


class TestEmptyStateV2:
    def test_inline(self):
        out = _empty_state_v2("📊", "no data", "", variant="inline")
        assert 'role="status"' in out

    def test_error(self):
        out = _empty_state_v2("⚠", "err", "details", variant="error")
        assert 'role="alert"' in out

    def test_block_default(self):
        out = _empty_state_v2("📊", "no data")
        # Falls back to _empty_state which uses empty-state class
        assert 'empty-state' in out


class TestSvgMinify:
    def test_basic(self):
        assert _svg_minify('<svg  ><rect  />  </svg>') == '<svg><rect/></svg>'

    def test_empty(self):
        assert _svg_minify("") == ""

    def test_preserves_attribute_values(self):
        out = _svg_minify('<rect x="10" y="20" />')
        assert 'x="10"' in out and 'y="20"' in out


class TestConfTier:
    def test_hi(self):
        assert _conf_tier(0.80) == "hi"
        assert _conf_tier(0.65) == "hi"

    def test_md(self):
        assert _conf_tier(0.55) == "md"
        assert _conf_tier(0.50) == "md"

    def test_lo(self):
        assert _conf_tier(0.30) == "lo"
        assert _conf_tier(0.0) == "lo"

    def test_na(self):
        assert _conf_tier(None) == "na"
        assert _conf_tier(float('nan')) == "na"


# ── V5: new visualization primitives ─────────────────────────────────────


class TestPriceLadder:
    def test_normal(self):
        from subagent_pipeline.renderers.shared_utils import _price_ladder_svg
        out = _price_ladder_svg(
            stop_loss=8.10,
            entries=[[9.00, 9.30], [8.60, 8.80]],
            targets=[[10.00, 10.50], [11.20, 11.80]],
            current=9.16,
        )
        assert out
        assert '<svg' in out
        assert 'role="img"' in out
        assert 'aria-label' in out
        assert '止损' in out and '现价' in out and '目标' in out

    def test_missing_data_returns_empty(self):
        from subagent_pipeline.renderers.shared_utils import _price_ladder_svg
        assert _price_ladder_svg() == ""
        # Single price point can't form a range
        assert _price_ladder_svg(current=9.16) == ""

    def test_scalar_entry(self):
        from subagent_pipeline.renderers.shared_utils import _price_ladder_svg
        out = _price_ladder_svg(
            stop_loss=8.0, entries=[9.0], targets=[10.0], current=9.2,
        )
        assert out and '<svg' in out

    def test_none_and_negative_inputs(self):
        from subagent_pipeline.renderers.shared_utils import _price_ladder_svg
        out = _price_ladder_svg(
            stop_loss=0, entries=[None, []], targets=["garbage"], current=None,
        )
        # All inputs invalid → empty string (not a crash)
        assert out == ""


class TestStackedProbBar:
    def test_normal_fractions(self):
        from subagent_pipeline.renderers.shared_utils import _stacked_prob_bar
        out = _stacked_prob_bar([
            {"label": "乐观", "value": 0.35, "color": "var(--green)"},
            {"label": "基准", "value": 0.45, "color": "var(--blue)"},
            {"label": "悲观", "value": 0.20, "color": "var(--red)"},
        ])
        assert out
        assert 'stacked-prob' in out
        assert 'aria-label' in out
        assert '乐观' in out and '基准' in out and '悲观' in out

    def test_percent_inputs(self):
        from subagent_pipeline.renderers.shared_utils import _stacked_prob_bar
        out = _stacked_prob_bar([
            {"label": "Up", "value": 55, "color": "var(--green)"},
            {"label": "Dn", "value": 45, "color": "var(--red)"},
        ])
        assert out and 'Up' in out and 'Dn' in out

    def test_empty_input(self):
        from subagent_pipeline.renderers.shared_utils import _stacked_prob_bar
        assert _stacked_prob_bar([]) == ""

    def test_zero_values_filtered(self):
        from subagent_pipeline.renderers.shared_utils import _stacked_prob_bar
        out = _stacked_prob_bar([
            {"label": "A", "value": 0},
            {"label": "B", "value": 0.0},
        ])
        assert out == ""

    def test_unparseable_value(self):
        from subagent_pipeline.renderers.shared_utils import _stacked_prob_bar
        out = _stacked_prob_bar([
            {"label": "A", "value": "garbage", "color": "var(--green)"},
            {"label": "B", "value": 0.5, "color": "var(--red)"},
        ])
        # Garbage row dropped; B alone still renders
        assert out and 'B' in out
        assert 'A' not in out.split('stacked-prob')[1]


class TestPillarBar:
    def test_normal(self):
        from subagent_pipeline.renderers.shared_utils import _pillar_bar
        out = _pillar_bar(3, 4, "技术面")
        assert out
        assert 'pillar-bar' in out
        assert 'data-tier="hi"' in out
        # 3 filled, 1 empty
        assert out.count('pb-seg on') == 3

    def test_low(self):
        from subagent_pipeline.renderers.shared_utils import _pillar_bar
        out = _pillar_bar(1, 4)
        assert 'data-tier="lo"' in out

    def test_clamp(self):
        from subagent_pipeline.renderers.shared_utils import _pillar_bar
        out = _pillar_bar(99, 4)
        # clamped to max
        assert out.count('pb-seg on') == 4

    def test_none_and_garbage(self):
        from subagent_pipeline.renderers.shared_utils import _pillar_bar
        for bad in (None, "x", float('nan')):
            out = _pillar_bar(bad, 4)
            assert out
            assert 'aria-label' in out


class TestHistorySparkline:
    def test_normal(self):
        from subagent_pipeline.renderers.shared_utils import _history_sparkline
        pts = [
            {"date": "2026-03-10", "action": "HOLD", "value": 0.6},
            {"date": "2026-03-11", "action": "BUY",  "value": 0.75},
            {"date": "2026-03-12", "action": "BUY",  "value": 0.80},
        ]
        out = _history_sparkline(pts)
        assert out
        assert '<svg' in out
        assert 'hist-spark' in out
        # Color-coded dots per action
        assert 'var(--green)' in out  # BUY
        assert 'var(--yellow)' in out  # HOLD

    def test_single_point_returns_empty(self):
        from subagent_pipeline.renderers.shared_utils import _history_sparkline
        assert _history_sparkline([{"value": 0.5, "action": "BUY"}]) == ""

    def test_empty(self):
        from subagent_pipeline.renderers.shared_utils import _history_sparkline
        assert _history_sparkline([]) == ""

    def test_clamps_values_out_of_range(self):
        from subagent_pipeline.renderers.shared_utils import _history_sparkline
        pts = [
            {"value": -0.5, "action": "HOLD"},
            {"value": 1.5, "action": "BUY"},
        ]
        out = _history_sparkline(pts)
        assert out and '<svg' in out
