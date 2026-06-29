"""CI-level color-contract guard (the test promised last round but never written).

A-share convention is 红涨绿跌 (red = up/bullish, green = down/bearish). These
tests are pure text scans over the renderer sources — no heavy imports — so they
run in this repo and fail loudly if a future edit reintroduces a reversed color.

Covers: the --up/--down token contract, direction-neutral confidence tokens, the
.delta-arr arrows, the radar legend, and a grep ban on `var(--green) if pct>0`.
"""
import os
import re
import glob

HERE = os.path.dirname(__file__)
RENDERERS = os.path.normpath(os.path.join(HERE, "..", "..", "renderers"))


def _read(name: str) -> str:
    with open(os.path.join(RENDERERS, name), encoding="utf-8") as f:
        return f.read()


def test_up_down_tokens_defined():
    css = _read("shared_css.py")
    assert "--up: var(--red)" in css, "missing A-share --up (涨=红) token"
    assert "--down: var(--green)" in css, "missing A-share --down (跌=绿) token"


def test_delta_arr_is_ashare_direction():
    css = _read("shared_css.py")
    assert re.search(r"\.delta-arr\.up\s*\{\s*color:\s*var\(--(up|red)\)", css), \
        ".delta-arr.up must be red (涨=红)"
    assert re.search(r"\.delta-arr\.down\s*\{\s*color:\s*var\(--(down|green)\)", css), \
        ".delta-arr.down must be green (跌=绿)"


def test_conf_tokens_are_direction_neutral():
    """Confidence strength must not reuse the 涨跌/buy-sell red & green (AQ-F1)."""
    css = _read("shared_css.py")
    m_hi = re.search(r"--conf-hi:\s*(#[0-9a-fA-F]{6})", css)
    m_lo = re.search(r"--conf-lo:\s*(#[0-9a-fA-F]{6})", css)
    assert m_hi and m_hi.group(1).lower() not in ("#34d399", "#f87171"), \
        "--conf-hi must not be the green/red 涨跌 color"
    assert m_lo and m_lo.group(1).lower() not in ("#34d399", "#f87171"), \
        "--conf-lo must not be the green/red 涨跌 color"


def _strip_comments(src: str) -> str:
    """Drop /* … */ CSS block comments and #… Python line comments so the grep
    bans the reversed-color pattern in CODE, not in the explanatory comments that
    deliberately *name* the anti-pattern to warn future editors."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"#[^\n]*", "", src)
    return src


def test_no_reversed_pct_color_ternary():
    """Ban `var(--green) ... if <pct-like> > 0` — that paints a rising value green."""
    pat = re.compile(
        r'var\(--green\)["\']?\s+if\s+[\w.\[\]"\']*?(pct|change|chg|delta|ret|return)[\w.\[\]"\']*?\s*>\s*0',
        re.IGNORECASE,
    )
    offenders = []
    for path in glob.glob(os.path.join(RENDERERS, "*.py")):
        if pat.search(_strip_comments(_read(os.path.basename(path)))):
            offenders.append(os.path.basename(path))
    assert not offenders, f"reversed 涨跌 color ternary (涨涂绿) found in: {offenders}"


def test_radar_legend_red_is_bull():
    """Legend order must be red→看多, green→看空 (match the polygons). N-DEB-01.

    Anchor on the actual legend SVG (the first y=190 <line>), NOT the `# Legend`
    comment — the comment itself names the colors (看多 = 红 …) and would poison a
    positional search.
    """
    src = _read("debate_renderer.py")
    start = src.find('x1="10" y1="190"')
    assert start > 0
    leg = src[start:start + 800]
    i_red, i_bull = leg.find("#f87171"), leg.find("看多")
    i_green, i_bear = leg.find("#34d399"), leg.find("看空")
    assert -1 < i_red < i_bull < i_green < i_bear, \
        "radar legend colors/labels are not red→看多, green→看空"
