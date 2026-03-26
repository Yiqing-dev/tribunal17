"""Tests for daily recap collector + renderer + route."""

import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

def _make_index_points(n=30, base=3200):
    pts = []
    for i in range(n):
        c = base + i * 2.5 + (i % 5 - 2) * 3
        o = c - 5
        h = c + 8
        l = c - 10
        pts.append({
            "date": f"2026-03-{i+1:02d}",
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": 10000 + i * 100,
            "amount": (5000 + i * 200) * 1e8,
            "change_pct": round(2.5 / base * 100, 2) if i > 0 else 0,
            "ma5": round(c - 3, 2) if i >= 4 else None,
            "ma14": round(c - 8, 2) if i >= 13 else None,
            "ma30": round(c - 15, 2) if i >= 29 else None,
            "rsi": 55.0 + (i % 10),
            "macd_dif": round(i * 0.3 - 4, 4),
            "macd_dea": round(i * 0.2 - 3, 4),
            "macd_hist": round((i * 0.3 - 4) - (i * 0.2 - 3), 4) * 2,
        })
    return pts


def _make_index_info(code="sh000001", name="上证指数"):
    pts = _make_index_points()
    return {
        "code": code, "name": name,
        "points": pts,
        "close": pts[-1]["close"],
        "pct_change": pts[-1]["change_pct"],
        "turnover_yi": 5400.0,
    }


def _make_sector_node(sector="半导体", pct=2.5, turnover=120.0, mcap=5000.0):
    return {
        "sector": sector, "pct_change": pct, "turnover_yi": turnover,
        "market_cap_yi": mcap, "index_contrib": 0,
        "leaders": [
            {"ticker": "600000", "name": "领涨A", "pct_change": 8.5},
            {"ticker": "600001", "name": "领涨B", "pct_change": 6.2},
        ],
        "laggards": [
            {"ticker": "600010", "name": "领跌A", "pct_change": -3.1},
        ],
        "resonance_stocks": [
            {"ticker": "600000", "name": "领涨A", "pct_change": 8.5},
        ],
    }


def _make_limit_stock(name="测试股", ticker="600123", pct=10.0, boards=1, is_up=True):
    return {
        "ticker": ticker, "name": name, "sector": "测试",
        "boards": boards, "pct_change": pct, "amount_yi": 5.2,
        "is_limit_up": is_up,
    }


def _make_recap_data():
    return {
        "date": "2026-03-13",
        "index_summary": {
            "date": "2026-03-13",
            "indices": [
                _make_index_info("sh000001", "上证指数"),
                _make_index_info("sz399001", "深证成指"),
                _make_index_info("sh000300", "沪深300"),
                _make_index_info("sz399006", "创业板指"),
                _make_index_info("sh000688", "科创50"),
            ],
            "turnover_total_yi": 12500.0,
            "turnover_delta_yi": 200.0,
            "northbound_flow_yi": 45.3,
            "advancers": 2800,
            "decliners": 1900,
            "flat": 300,
        },
        "sector_heatmap": {
            "date": "2026-03-13",
            "nodes": [
                _make_sector_node("半导体", 3.5, 200),
                _make_sector_node("新能源", 1.2, 150),
                _make_sector_node("银行", -0.5, 180),
                _make_sector_node("医药", -2.1, 90),
                _make_sector_node("白酒", 0.3, 120),
            ],
        },
        "limit_board": {
            "limit_up_count": 45,
            "limit_down_count": 8,
            "limit_up_stocks": [
                _make_limit_stock("涨停A", "600111", 10.0, 3),
                _make_limit_stock("涨停B", "600222", 9.98, 1),
                _make_limit_stock("涨停C", "300333", 20.0, 2),
            ],
            "limit_down_stocks": [
                _make_limit_stock("跌停A", "600444", -10.0, 1, False),
            ],
        },
        "consecutive_boards": [
            {"level": 1, "label": "首板", "count": 35, "prev_count": 0, "promotion_rate": 0,
             "stocks": [_make_limit_stock("首板A"), _make_limit_stock("首板B")]},
            {"level": 2, "label": "一进二 (8/30=27%)", "count": 8, "prev_count": 30, "promotion_rate": 26.7,
             "stocks": [_make_limit_stock("二板A", boards=2)]},
            {"level": 3, "label": "二进三 (2/6=33%)", "count": 2, "prev_count": 6, "promotion_rate": 33.3,
             "stocks": [_make_limit_stock("三板A", boards=3)]},
        ],
        "red_close": {
            "window_natural_days": 14,
            "window_trade_days": 10,
            "red_close_6": [
                {"ticker": "601985", "name": "中国核电", "red_days": 8, "total_days": 10},
                {"ticker": "600529", "name": "山东药玻", "red_days": 7, "total_days": 10},
            ],
            "red_close_8": [
                {"ticker": "601985", "name": "中国核电", "red_days": 8, "total_days": 10},
            ],
        },
        "market_weather": "上涨",
        "position_advice": "进攻",
        "risk_note": "",
        "one_line_summary": "上证+0.85%，2800涨/1900跌，北向+45.3亿",
        "collection_seconds": 12.5,
    }


# ────────────────────────────────────────────────────────────────────
# 1. Collector unit tests
# ────────────────────────────────────────────────────────────────────

class TestTechnicalIndicators:
    """Test _sma, _ema, _compute_rsi, _compute_macd."""

    def test_sma_basic(self):
        from subagent_pipeline.recap_collector import _sma
        result = _sma([1, 2, 3, 4, 5], 3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)

    def test_sma_single(self):
        from subagent_pipeline.recap_collector import _sma
        result = _sma([10], 1)
        assert result == [10]

    def test_ema_basic(self):
        from subagent_pipeline.recap_collector import _ema
        result = _ema([10, 20, 30], 2)
        assert len(result) == 3
        assert result[0] == 10
        assert result[1] > 10  # should move toward 20

    def test_ema_empty(self):
        from subagent_pipeline.recap_collector import _ema
        assert _ema([], 5) == []

    def test_rsi_basic(self):
        from subagent_pipeline.recap_collector import _compute_rsi
        closes = [100 + i for i in range(30)]  # monotonically increasing
        result = _compute_rsi(closes, 14)
        assert len(result) == 30
        # All gains, RSI should be high
        assert result[-1] > 90

    def test_rsi_short_series(self):
        from subagent_pipeline.recap_collector import _compute_rsi
        result = _compute_rsi([100], 14)
        assert result == [50.0]

    def test_macd_basic(self):
        from subagent_pipeline.recap_collector import _compute_macd
        closes = [100 + i * 0.5 for i in range(30)]
        dif, dea, hist = _compute_macd(closes)
        assert len(dif) == 30
        assert len(dea) == 30
        assert len(hist) == 30

    def test_macd_empty(self):
        from subagent_pipeline.recap_collector import _compute_macd
        assert _compute_macd([]) == ([], [], [])


class TestSafeFloat:
    def test_normal(self):
        from subagent_pipeline.recap_collector import _safe_float
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_none(self):
        from subagent_pipeline.recap_collector import _safe_float
        assert _safe_float(None) is None

    def test_nan(self):
        from subagent_pipeline.recap_collector import _safe_float
        assert _safe_float(float("nan")) is None

    def test_string(self):
        from subagent_pipeline.recap_collector import _safe_float
        assert _safe_float("abc") is None


class TestDataContracts:
    """Test dataclass serialization."""

    def test_daily_recap_data_to_dict(self):
        from subagent_pipeline.recap_collector import DailyRecapData
        d = DailyRecapData(date="2026-03-13", market_weather="上涨")
        result = d.to_dict()
        assert result["date"] == "2026-03-13"
        assert result["market_weather"] == "上涨"
        assert "index_summary" in result

    def test_daily_recap_data_to_json(self):
        from subagent_pipeline.recap_collector import DailyRecapData
        d = DailyRecapData(date="2026-03-13")
        j = d.to_json()
        parsed = json.loads(j)
        assert parsed["date"] == "2026-03-13"

    def test_index_point_fields(self):
        from subagent_pipeline.recap_collector import IndexPoint
        p = IndexPoint(date="2026-03-13", close=3200.5, rsi=65.3)
        assert p.close == 3200.5
        assert p.rsi == 65.3
        assert p.ma5 is None

    def test_limit_stock_fields(self):
        from subagent_pipeline.recap_collector import LimitStock
        s = LimitStock(ticker="600111", name="测试", boards=3, is_limit_up=True)
        assert s.boards == 3
        d = asdict(s)
        assert d["is_limit_up"] is True

    def test_sector_node_fields(self):
        from subagent_pipeline.recap_collector import SectorNode
        n = SectorNode(sector="半导体", pct_change=3.5)
        d = asdict(n)
        assert d["sector"] == "半导体"

    def test_consecutive_board_level(self):
        from subagent_pipeline.recap_collector import ConsecutiveBoardLevel
        lv = ConsecutiveBoardLevel(level=2, label="一进二", count=5, prev_count=20, promotion_rate=25.0)
        d = asdict(lv)
        assert d["level"] == 2
        assert d["prev_count"] == 20
        assert d["promotion_rate"] == 25.0


class TestBuildConsecutiveLevels:
    def test_groups_by_boards(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        stocks = [
            {"name": "A", "boards": 1},
            {"name": "B", "boards": 1},
            {"name": "C", "boards": 2},
            {"name": "D", "boards": 3},
        ]
        levels = build_consecutive_levels(stocks)
        assert len(levels) == 3
        assert levels[0]["level"] == 1
        assert levels[0]["count"] == 2
        assert levels[1]["level"] == 2
        assert levels[1]["count"] == 1

    def test_empty(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        assert build_consecutive_levels([]) == []

    def test_label_no_prev(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        stocks = [{"name": "A", "boards": 4}]
        levels = build_consecutive_levels(stocks)
        assert "连板" in levels[0]["label"]

    def test_promotion_rate_with_prev_dist(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        stocks = [
            {"name": "A", "boards": 1},
            {"name": "B", "boards": 1},
            {"name": "C", "boards": 2},
        ]
        prev_dist = {1: 10, 2: 3}
        levels = build_consecutive_levels(stocks, prev_dist)
        # Level 2: 1 stock promoted from yesterday's 10 首板
        lvl2 = next(lv for lv in levels if lv["level"] == 2)
        assert lvl2["prev_count"] == 10
        assert lvl2["promotion_rate"] == 10.0  # 1/10 * 100

    def test_promotion_label_format(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        stocks = [
            {"name": "A", "boards": 2},
            {"name": "B", "boards": 2},
            {"name": "C", "boards": 2},
        ]
        prev_dist = {1: 20}
        levels = build_consecutive_levels(stocks, prev_dist)
        assert "一进二" in levels[0]["label"]
        assert "3/20" in levels[0]["label"]

    def test_no_prev_dist_no_rate(self):
        from subagent_pipeline.recap_collector import build_consecutive_levels
        stocks = [{"name": "A", "boards": 2}]
        levels = build_consecutive_levels(stocks)
        assert levels[0]["promotion_rate"] == 0
        assert levels[0]["prev_count"] == 0


class TestDeriveMarketWeather:
    def test_bullish(self):
        from subagent_pipeline.recap_collector import _derive_market_weather, IndexSummary
        idx = IndexSummary(
            indices=[
                {"code": "sh000001", "pct_change": 1.5},
                {"code": "sz399001", "pct_change": 1.2},
                {"code": "sh000300", "pct_change": 0.8},
            ],
            advancers=3000, decliners=1500,
        )
        weather, advice, risk, summary = _derive_market_weather(idx)
        assert weather == "上涨"
        assert advice == "进攻"

    def test_bearish(self):
        from subagent_pipeline.recap_collector import _derive_market_weather, IndexSummary
        idx = IndexSummary(
            indices=[
                {"code": "sh000001", "pct_change": -1.5},
                {"code": "sz399001", "pct_change": -1.2},
                {"code": "sh000300", "pct_change": -0.8},
            ],
            advancers=800, decliners=3500,
        )
        weather, advice, risk, summary = _derive_market_weather(idx)
        assert weather == "下跌"
        assert advice == "防守"

    def test_neutral(self):
        from subagent_pipeline.recap_collector import _derive_market_weather, IndexSummary
        idx = IndexSummary(
            indices=[
                {"code": "sh000001", "pct_change": 0.1},
                {"code": "sz399001", "pct_change": -0.1},
            ],
            advancers=2200, decliners=2300,
        )
        weather, advice, risk, summary = _derive_market_weather(idx)
        assert weather == "震荡"
        assert advice == "中性"

    def test_empty_indices(self):
        from subagent_pipeline.recap_collector import _derive_market_weather, IndexSummary
        idx = IndexSummary()
        w, a, r, s = _derive_market_weather(idx)
        assert w == "震荡"

    def test_risk_notes(self):
        from subagent_pipeline.recap_collector import _derive_market_weather, IndexSummary
        idx = IndexSummary(
            indices=[{"code": "sh000001", "pct_change": -0.5}],
            advancers=1000, decliners=3500,
            northbound_flow_yi=-50,
            turnover_delta_yi=-600,
        )
        w, a, risk, s = _derive_market_weather(idx)
        assert "北向资金" in risk
        assert "萎缩" in risk


class TestRecapConfig:
    def test_config_keys(self):
        from subagent_pipeline.recap_collector import RECAP_CONFIG
        assert "resonance_threshold_pct" in RECAP_CONFIG
        assert "red_close_window_days" in RECAP_CONFIG
        assert "red_close_thresholds" in RECAP_CONFIG
        assert len(RECAP_CONFIG["indices"]) == 5

    def test_index_codes(self):
        from subagent_pipeline.recap_collector import RECAP_CONFIG
        codes = [c for c, _ in RECAP_CONFIG["indices"]]
        assert "sh000001" in codes
        assert "sz399001" in codes


# ────────────────────────────────────────────────────────────────────
# 2. Renderer tests
# ────────────────────────────────────────────────────────────────────

class TestRecapRenderer:
    """Test recap_renderer functions."""

    def test_render_daily_recap_returns_html(self):
        from dashboard.recap_renderer import render_daily_recap
        data = _make_recap_data()
        html = render_daily_recap(data)
        assert "<!DOCTYPE html>" in html
        assert "每日复盘" in html

    def test_hero_section(self):
        from dashboard.recap_renderer import _render_recap_hero
        data = _make_recap_data()
        html = _render_recap_hero(data)
        assert "2026-03-13" in html
        assert "市场复盘" in html
        assert "上涨" in html
        assert "进攻" in html

    def test_hero_risk_note(self):
        from dashboard.recap_renderer import _render_recap_hero
        data = {"date": "2026-03-13", "risk_note": "北向大幅流出", "market_weather": "下跌",
                "position_advice": "防守", "one_line_summary": "test"}
        html = _render_recap_hero(data)
        assert "北向大幅流出" in html
        assert "risk-banner" in html

    def test_hero_no_risk(self):
        from dashboard.recap_renderer import _render_recap_hero
        data = {"date": "2026-03-13", "risk_note": "", "market_weather": "震荡",
                "position_advice": "中性", "one_line_summary": ""}
        html = _render_recap_hero(data)
        assert "risk-banner" not in html

    def test_kpi_ribbon(self):
        from dashboard.recap_renderer import _render_index_kpi_ribbon
        data = _make_recap_data()
        html = _render_index_kpi_ribbon(data)
        assert "上证指数" in html
        assert "成交额" in html
        assert "北向" in html
        assert "上涨" in html
        # Index close points should be shown
        close = data["index_summary"]["indices"][0]["close"]
        assert f"{close:.2f}" in html

    def test_kpi_ribbon_turnover_delta(self):
        from dashboard.recap_renderer import _render_index_kpi_ribbon
        data = _make_recap_data()
        data["index_summary"]["turnover_delta_yi"] = 500
        html = _render_index_kpi_ribbon(data)
        assert "放量" in html

    def test_kpi_ribbon_shrink(self):
        from dashboard.recap_renderer import _render_index_kpi_ribbon
        data = _make_recap_data()
        data["index_summary"]["turnover_delta_yi"] = -300
        html = _render_index_kpi_ribbon(data)
        assert "缩量" in html

    def test_index_chart_panel(self):
        from dashboard.recap_renderer import _render_index_chart_panel
        data = _make_recap_data()
        html = _render_index_chart_panel(data)
        assert "idx-tab" in html
        assert "chart-panel" in html
        assert '<svg' in html
        assert "toggle-btn" in html

    def test_index_chart_empty(self):
        from dashboard.recap_renderer import _render_index_chart_panel
        data = {"index_summary": {"indices": []}}
        html = _render_index_chart_panel(data)
        assert "暂无指数数据" in html

    def test_index_svg_rendering(self):
        from dashboard.recap_renderer import _render_index_svg
        points = _make_index_points(10)
        svg = _render_index_svg(points)
        assert '<svg' in svg
        assert 'rect' in svg  # candle bodies
        assert 'line' in svg  # wicks
        assert 'ma-line' in svg  # MA polylines

    def test_index_svg_empty(self):
        from dashboard.recap_renderer import _render_index_svg
        html = _render_index_svg([])
        assert "暂无数据" in html

    def test_sector_heatmap(self):
        from dashboard.recap_renderer import _render_sector_heatmap
        data = _make_recap_data()
        html = _render_sector_heatmap(data)
        assert "板块热力图" in html
        assert '<svg' in html
        assert "shm-node" in html
        assert "半导体" in html
        # With market_cap_yi > 0, label should say "面积=市值"
        assert "面积=市值" in html

    def test_sector_heatmap_fallback_turnover(self):
        from dashboard.recap_renderer import _render_sector_heatmap
        data = {"sector_heatmap": {"nodes": [
            {"sector": "测试", "pct_change": 1.0, "turnover_yi": 100, "market_cap_yi": 0},
        ]}}
        html = _render_sector_heatmap(data)
        assert "面积=成交额" in html

    def test_sector_heatmap_empty(self):
        from dashboard.recap_renderer import _render_sector_heatmap
        data = {"sector_heatmap": {"nodes": []}}
        html = _render_sector_heatmap(data)
        assert "暂无板块数据" in html

    def test_sector_drawer_html(self):
        from dashboard.recap_renderer import _render_sector_drawer
        html = _render_sector_drawer()
        assert "sector-drawer" in html
        assert "sector-overlay" in html
        assert "sd-leaders" in html
        assert "sd-resonance" in html

    def test_limit_board(self):
        from dashboard.recap_renderer import _render_limit_board
        data = _make_recap_data()
        html = _render_limit_board(data)
        assert "涨跌停板" in html
        assert "涨停A" in html
        assert "3连板" in html
        assert "跌停A" in html

    def test_limit_board_empty(self):
        from dashboard.recap_renderer import _render_limit_board
        data = {"limit_board": {"limit_up_stocks": [], "limit_down_stocks": [],
                                "limit_up_count": 0, "limit_down_count": 0}}
        html = _render_limit_board(data)
        assert "暂无涨停" in html

    def test_consecutive_board_flow(self):
        from dashboard.recap_renderer import _render_consecutive_board_flow
        data = _make_recap_data()
        html = _render_consecutive_board_flow(data)
        assert "连板晋级" in html
        assert "首板" in html
        assert "一进二" in html
        assert "ladder-bar" in html
        # Promotion rate shown
        assert "8/30" in html

    def test_consecutive_board_promo_badge(self):
        from dashboard.recap_renderer import _render_consecutive_board_flow
        data = {
            "consecutive_boards": [
                {"level": 1, "label": "首板", "count": 20, "prev_count": 0, "promotion_rate": 0, "stocks": []},
                {"level": 2, "label": "一进二 (5/18=28%)", "count": 5, "prev_count": 18, "promotion_rate": 27.8, "stocks": []},
            ],
        }
        html = _render_consecutive_board_flow(data)
        assert "5/18" in html
        assert "promo-rate" in html

    def test_consecutive_board_empty(self):
        from dashboard.recap_renderer import _render_consecutive_board_flow
        data = {"consecutive_boards": []}
        html = _render_consecutive_board_flow(data)
        assert html == ""

    def test_red_close_panel(self):
        from dashboard.recap_renderer import _render_red_close_panel
        data = _make_recap_data()
        html = _render_red_close_panel(data)
        assert "强势延续观察" in html
        assert "中国核电" in html
        assert "rc-table" in html
        assert "csv-copy-btn" in html

    def test_red_close_empty(self):
        from dashboard.recap_renderer import _render_red_close_panel
        data = {"red_close": {"red_close_6": [], "red_close_8": []}}
        html = _render_red_close_panel(data)
        assert html == ""

    def test_recap_js(self):
        from dashboard.recap_renderer import _render_recap_js
        data = _make_recap_data()
        js = _render_recap_js(data)
        assert "<script>" in js
        assert "SECTOR_DATA" in js
        assert "openSectorDrawer" in js
        assert "idx-tab" in js
        assert "clipboard" in js

    def test_full_page_structure(self):
        from dashboard.recap_renderer import render_daily_recap
        data = _make_recap_data()
        html = render_daily_recap(data)
        # Check all major sections are present
        assert "recap-hero" in html
        assert "kpi-ribbon" in html
        assert "指数走势" in html
        assert "板块热力图" in html
        assert "涨跌停板" in html
        assert "连板晋级" in html
        assert "强势延续观察" in html
        assert "recap-footer" in html

    def test_neon_css_theme(self):
        from dashboard.recap_renderer import _RECAP_CSS
        assert "#070e1b" in _RECAP_CSS  # deep navy
        assert "#34d399" in _RECAP_CSS  # emerald green
        assert "#f87171" in _RECAP_CSS  # rose red
        assert "#fbbf24" in _RECAP_CSS  # amber gold
        assert "#60a5fa" in _RECAP_CSS  # sky blue
        assert "backdrop-filter" in _RECAP_CSS  # glass effect
        assert "fadeSlideUp" in _RECAP_CSS  # entry animation
        assert "monospace" in _RECAP_CSS  # mono numbers
        assert "@media" in _RECAP_CSS  # responsive

    def test_responsive_breakpoints(self):
        from dashboard.recap_renderer import _RECAP_CSS
        assert "min-width: 1200px" in _RECAP_CSS
        assert "min-width: 768px" in _RECAP_CSS
        assert "max-width: 767px" in _RECAP_CSS


class TestSectorColor:
    def test_strong_up(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(5.0) == "#34d399"

    def test_moderate_up(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(2.0) == "#2aac7e"

    def test_mild_up(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(0.5) == "#1d7a5a"

    def test_flat(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(0.0) == "#3d5068"

    def test_mild_down(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(-1.0) == "#b04040"

    def test_strong_down(self):
        from dashboard.recap_renderer import _sector_color
        assert _sector_color(-5.0) == "#f87171"


class TestPctHelpers:
    def test_pct_class(self):
        from dashboard.recap_renderer import _pct_class
        assert _pct_class(1.5) == "up"
        assert _pct_class(-0.3) == "down"
        assert _pct_class(0) == "neu"

    def test_pct_str(self):
        from dashboard.recap_renderer import _pct_str
        assert _pct_str(1.5) == "+1.50%"
        assert _pct_str(-0.3) == "-0.30%"
        assert _pct_str(0) == "0.00%"


class TestEsc:
    def test_escapes_html(self):
        from dashboard.recap_renderer import _esc
        assert _esc('<script>') == "&lt;script&gt;"
        assert _esc('a&b') == "a&amp;b"

    def test_empty(self):
        from dashboard.recap_renderer import _esc
        assert _esc("") == ""
        assert _esc(None) == ""


# ────────────────────────────────────────────────────────────────────
# 3. Static export test
# ────────────────────────────────────────────────────────────────────

class TestStaticExport:
    def test_generate_report(self):
        from dashboard.recap_renderer import generate_daily_recap_report
        data = _make_recap_data()
        with tempfile.TemporaryDirectory() as td:
            path = generate_daily_recap_report(data, output_dir=td)
            assert path is not None
            assert Path(path).exists()
            content = Path(path).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
            assert "每日复盘" in content
            assert "recap-20260313" in Path(path).name

    def test_generate_report_empty(self):
        from dashboard.recap_renderer import generate_daily_recap_report
        assert generate_daily_recap_report({}) is None
        assert generate_daily_recap_report(None) is None

    def test_generate_creates_dir(self):
        from dashboard.recap_renderer import generate_daily_recap_report
        data = _make_recap_data()
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "nested", "output")
            path = generate_daily_recap_report(data, output_dir=sub)
            assert Path(path).exists()


# ────────────────────────────────────────────────────────────────────
# 3b. Market Context Panel tests
# ────────────────────────────────────────────────────────────────────

class TestMarketContextPanel:
    """Test _render_market_context_panel in recap renderer."""

    def _ctx(self, **overrides):
        base = {
            "regime": "RISK_ON",
            "breadth_state": "HEALTHY",
            "position_cap_multiplier": 1.2,
            "style_bias": "成长",
            "sector_leaders": ["新能源", "半导体", "军工"],
            "avoid_sectors": ["房地产"],
            "client_summary": "市场进攻态势，建议积极布局成长股。",
        }
        base.update(overrides)
        return base

    def test_renders_regime_badge(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "进攻" in html
        assert "RISK_ON" not in html  # English code should not be displayed
        assert "mkt-badge" in html

    def test_renders_breadth_badge(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "健康" in html
        assert "HEALTHY" not in html  # English code should not be displayed

    def test_renders_sector_chips(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "新能源" in html
        assert "半导体" in html
        assert "房地产" in html
        assert "mkt-chip leader" in html
        assert "mkt-chip avoid" in html

    def test_renders_client_summary(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "积极布局成长股" in html

    def test_renders_position_cap(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "1.2x" in html

    def test_renders_style_bias(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "成长" in html

    def test_empty_context_returns_empty(self):
        from dashboard.recap_renderer import _render_market_context_panel
        assert _render_market_context_panel({}) == ""
        assert _render_market_context_panel({"market_context": {}}) == ""

    def test_no_regime_or_breadth_returns_empty(self):
        from dashboard.recap_renderer import _render_market_context_panel
        ctx = {"client_summary": "test", "sector_leaders": ["A"]}
        assert _render_market_context_panel({"market_context": ctx}) == ""

    def test_regime_only(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": {"regime": "RISK_OFF"}})
        assert "防御" in html
        assert "RISK_OFF" not in html  # English code not displayed
        assert "市场宽度" not in html

    def test_breadth_only(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": {"breadth_state": "NARROW"}})
        assert "分化" in html
        assert "市场研判" not in html

    def test_risk_off_sell_class(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx(regime="RISK_OFF")})
        assert "mkt-badge sell" in html

    def test_neutral_hold_class(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx(regime="NEUTRAL")})
        assert "mkt-badge hold" in html

    def test_cap_1_hidden(self):
        """Position cap of 1.0 (default) should not show multiplier text."""
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx(position_cap_multiplier=1.0)})
        assert "1.0x" not in html

    def test_section_title(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx()})
        assert "AI 综合研判" in html
        assert "市场环境评估" in html

    def test_integrated_in_full_render(self):
        """Market context panel appears in full render_daily_recap output."""
        from dashboard.recap_renderer import render_daily_recap
        data = _make_recap_data()
        data["market_context"] = self._ctx()
        html = render_daily_recap(data)
        assert "AI 综合研判" in html
        assert "进攻" in html
        assert "新能源" in html

    def test_full_render_without_context(self):
        """Full render without market_context should not contain the panel."""
        from dashboard.recap_renderer import render_daily_recap
        data = _make_recap_data()
        data.pop("market_context", None)
        html = render_daily_recap(data)
        assert "AI 综合研判" not in html

    def test_dict_sector_leaders(self):
        """Sector leaders as list of dicts (not strings)."""
        from dashboard.recap_renderer import _render_market_context_panel
        ctx = self._ctx(sector_leaders=[{"name": "新能源"}, {"name": "AI"}])
        html = _render_market_context_panel({"market_context": ctx})
        assert "新能源" in html
        assert "AI" in html

    def test_deteriorating_breadth(self):
        from dashboard.recap_renderer import _render_market_context_panel
        html = _render_market_context_panel({"market_context": self._ctx(breadth_state="DETERIORATING")})
        assert "恶化" in html


# ────────────────────────────────────────────────────────────────────
# 4. Route tests
# ────────────────────────────────────────────────────────────────────

class TestRecapRoute:
    def test_load_recap_data_by_date(self):
        from dashboard.routes.recap import _load_recap_data
        data = _make_recap_data()
        with tempfile.TemporaryDirectory() as td:
            Path(td, "recap_2026-03-13.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            result = _load_recap_data(td, "2026-03-13")
            assert result["date"] == "2026-03-13"

    def test_load_recap_data_latest(self):
        from dashboard.routes.recap import _load_recap_data
        data = _make_recap_data()
        with tempfile.TemporaryDirectory() as td:
            Path(td, "recap_2026-03-12.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
            Path(td, "recap_2026-03-13.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
            result = _load_recap_data(td)
            assert result is not None

    def test_load_recap_data_missing(self):
        from dashboard.routes.recap import _load_recap_data
        with tempfile.TemporaryDirectory() as td:
            result = _load_recap_data(td, "2026-01-01")
            assert result == {}

    def test_load_recap_data_empty_dir(self):
        from dashboard.routes.recap import _load_recap_data
        with tempfile.TemporaryDirectory() as td:
            result = _load_recap_data(td)
            assert result == {}


# ────────────────────────────────────────────────────────────────────
# 5. Integration: collector → renderer round-trip
# ────────────────────────────────────────────────────────────────────

class TestRoundTrip:
    """Test that collector data flows correctly through renderer."""

    def test_to_dict_roundtrip(self):
        """DailyRecapData.to_dict() → render_daily_recap → valid HTML."""
        from subagent_pipeline.recap_collector import DailyRecapData
        from dashboard.recap_renderer import render_daily_recap

        data = DailyRecapData(
            date="2026-03-13",
            market_weather="上涨",
            position_advice="进攻",
            one_line_summary="测试摘要",
        )
        html = render_daily_recap(data.to_dict())
        assert "<!DOCTYPE html>" in html
        assert "测试摘要" in html

    def test_json_roundtrip(self):
        """to_json() → json.loads() → render_daily_recap."""
        from subagent_pipeline.recap_collector import DailyRecapData
        from dashboard.recap_renderer import render_daily_recap

        data = DailyRecapData(date="2026-03-13")
        j = data.to_json()
        loaded = json.loads(j)
        html = render_daily_recap(loaded)
        assert "<!DOCTYPE html>" in html

    def test_full_fixture_render(self):
        """Full fixture data renders without errors."""
        from dashboard.recap_renderer import render_daily_recap
        data = _make_recap_data()
        html = render_daily_recap(data)
        # All sections present
        for keyword in [
            "recap-hero", "kpi-ribbon", "idx-tab", "shm-node",
            "limit-stock", "ladder-bar", "rc-table", "<script>",
        ]:
            assert keyword in html, f"Missing: {keyword}"

    def test_static_export_roundtrip(self):
        """Full data → generate_daily_recap_report → file exists and valid."""
        from dashboard.recap_renderer import generate_daily_recap_report
        data = _make_recap_data()
        with tempfile.TemporaryDirectory() as td:
            path = generate_daily_recap_report(data, output_dir=td)
            content = Path(path).read_text(encoding="utf-8")
            assert len(content) > 5000
            assert "每日复盘" in content
            assert "sector-drawer" in content
