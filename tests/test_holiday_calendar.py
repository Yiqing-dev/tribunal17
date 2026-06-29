"""Regression tests for the CN holiday calendar (N-DATA-01).

The Spring Festival tables were off by a full year: the 2025 set held the 2024
dates and the 2026 set held the 2025 dates, so trading-day / date-rollback /
due-date logic was systematically wrong. These pin the corrected dates.

Only depends on subagent_pipeline (akshare must be importable — it is a declared
prerequisite). No dashboard/tradingagents imports, so it runs in this repo.
"""
from subagent_pipeline.akshare_collector import _is_cn_trading_day


def test_2026_spring_festival_day_is_not_trading():
    # 农历正月初一 2026 = 2026-02-17 (Tuesday)
    assert _is_cn_trading_day("2026-02-17") is False


def test_2025_spring_festival_day_is_not_trading():
    # 农历正月初一 2025 = 2025-01-29 (Wednesday)
    assert _is_cn_trading_day("2025-01-29") is False


def test_old_wrong_2026_dates_are_trading_again():
    # 2026-01-30 (Friday) was wrongly marked as Spring Festival (it was the 2025
    # holiday). After the fix it must be treated as a normal trading day.
    assert _is_cn_trading_day("2026-01-30") is True


def test_old_wrong_2025_dates_are_trading_again():
    # 2025-02-13 (Thursday) was wrongly marked as Spring Festival (it was the 2024
    # holiday). After the fix it must be a normal trading day.
    assert _is_cn_trading_day("2025-02-13") is True


def test_2026_spring_festival_full_range_closed():
    # 2026 春节 is 9 days (Feb 15–23, 复市 Feb 24) per 上证公告〔2025〕45号. The
    # 正月初七 closure (Feb 23, Monday) was previously missing from the set — pin it.
    assert _is_cn_trading_day("2026-02-23") is False  # 周一·正月初七, was wrongly trading
    assert _is_cn_trading_day("2026-02-24") is True   # 周二·复市


def test_2026_new_year_three_days_closed():
    # 2026 元旦 is 3 days (Jan 1–3, 复市 Jan 5). 01-02 (Friday) was previously
    # missing — it must be closed; the next weekday 01-05 (Monday) reopens.
    assert _is_cn_trading_day("2026-01-02") is False  # 周五, was wrongly trading
    assert _is_cn_trading_day("2026-01-05") is True   # 周一·复市


def test_regular_weekday_is_trading():
    assert _is_cn_trading_day("2026-06-10") is True  # Wednesday, no holiday


def test_weekend_is_not_trading():
    assert _is_cn_trading_day("2026-06-13") is False  # Saturday
