"""A11y regression tests — ensure V4 primitives expose aria-label on all interactive SVGs.

Guards against future renderer edits that bypass the primitives or strip the aria layer.
"""
import re

from subagent_pipeline.renderers.shared_utils import (
    _score_pill, _priority_chip, _confidence_ring_svg, _ridge_bar,
    _delta_arrow, _heat_cell, _conf_dots, _section_divider,
)


PRIMITIVE_OUTPUTS = [
    ("score_pill", _score_pill(3, 4, "tech")),
    ("score_pill_0", _score_pill(0, 4)),
    ("priority_chip_hot", _priority_chip("hot", "critical")),
    ("confidence_ring_62", _confidence_ring_svg(0.62, 72)),
    ("confidence_ring_none", _confidence_ring_svg(None)),
    ("ridge_bar", _ridge_bar([1.0, -0.5, 2.0], ["A", "B", "C"])),
    ("delta_arrow_up", _delta_arrow(0.5, 0.62, "%")),
    ("delta_arrow_flat", _delta_arrow(5.0, 5.0001)),
    ("heat_cell", _heat_cell(0.7, 0, 1, label="0.70")),
    ("heat_cell_none", _heat_cell(None)),
    ("conf_dots", _conf_dots(0.62)),
    ("section_divider", _section_divider("BUY", "🟢", count=3)),
]


def test_all_primitives_have_aria_label():
    missing = [name for name, out in PRIMITIVE_OUTPUTS if 'aria-label' not in out]
    assert not missing, f"primitives missing aria-label: {missing}"


def test_all_svg_elements_in_primitives_are_role_img_or_aria_hidden():
    """SVGs must be either interactive (role='img' + aria-label) or aria-hidden='true'."""
    for name, out in PRIMITIVE_OUTPUTS:
        svgs = re.findall(r'<svg[^>]*>', out)
        for svg_tag in svgs:
            has_role = 'role="img"' in svg_tag
            has_hidden = 'aria-hidden="true"' in svg_tag
            # SVGs inside primitives should be interactive (role=img with label on parent or svg)
            assert has_role or has_hidden, (
                f"{name}: svg missing role='img' or aria-hidden='true': {svg_tag}"
            )


def test_decorative_dots_are_aria_hidden():
    """Individual dots inside score_pill / conf_dots should be aria-hidden."""
    for name in ("score_pill", "conf_dots"):
        out = dict(PRIMITIVE_OUTPUTS)[name]
        # Each dot should be aria-hidden so screen-readers only announce the parent aria-label
        dots = re.findall(r'class="(sp-dot|cd-dot)[^"]*"[^>]*>', out)
        assert len(dots) >= 4, f"{name}: expected dots, got {len(dots)}"
        for dot_tag in re.findall(r'<span class="(?:sp-dot|cd-dot)[^>]*/?>', out):
            assert 'aria-hidden="true"' in dot_tag, f"dot tag missing aria-hidden: {dot_tag}"
