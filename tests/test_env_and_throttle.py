"""Tests for environment variable config and API throttle.

Covers:
1. PipelineRunConfig.from_env() — reads TA_* env vars
2. Model env overrides — TA_MODEL_DEFAULT, TA_MODEL_{AGENT}
3. get_env_bool / get_env_float helpers
4. _throttle() — enforces minimum interval
"""

import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.config import (
    PipelineRunConfig, PIPELINE_CONFIG,
    _apply_model_env_overrides, get_env_bool, get_env_float,
)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. from_env()                                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestFromEnv:

    def test_defaults_without_env(self):
        """Without env vars, from_env() returns same as from_defaults()."""
        cfg = PipelineRunConfig.from_env()
        assert cfg.market == "CN_A"
        assert cfg.bull_bear_rounds == 2

    def test_trade_date_from_env(self):
        with patch.dict(os.environ, {"TA_TRADE_DATE": "2026-05-01"}):
            cfg = PipelineRunConfig.from_env()
            assert cfg.current_date == "2026-05-01"

    def test_capital_from_env(self):
        with patch.dict(os.environ, {"TA_CAPITAL": "500000"}):
            cfg = PipelineRunConfig.from_env()
            assert cfg.capital == 500_000.0

    def test_int_from_env(self):
        with patch.dict(os.environ, {"TA_BULL_BEAR_ROUNDS": "3"}):
            cfg = PipelineRunConfig.from_env()
            assert cfg.bull_bear_rounds == 3

    def test_float_from_env(self):
        with patch.dict(os.environ, {"TA_TREND_THRESHOLD": "-0.10"}):
            cfg = PipelineRunConfig.from_env()
            assert cfg.trend_override_threshold == -0.10

    def test_invalid_env_value_ignored(self):
        with patch.dict(os.environ, {"TA_CAPITAL": "not_a_number"}):
            cfg = PipelineRunConfig.from_env()
            assert cfg.capital == 200_000  # default preserved

    def test_explicit_overrides_beat_env(self):
        with patch.dict(os.environ, {"TA_TRADE_DATE": "2026-05-01"}):
            cfg = PipelineRunConfig.from_env(current_date="2026-06-01")
            assert cfg.current_date == "2026-06-01"

    def test_multiple_env_vars(self):
        env = {
            "TA_TICKER": "000001",
            "TA_TICKER_NAME": "平安银行",
            "TA_TRADE_DATE": "2026-04-04",
            "TA_MODE": "NOVICE",
        }
        with patch.dict(os.environ, env):
            cfg = PipelineRunConfig.from_env()
            assert cfg.ticker == "000001"
            assert cfg.ticker_name == "平安银行"
            assert cfg.current_date == "2026-04-04"
            assert cfg.mode == "NOVICE"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. Model env overrides                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestModelEnvOverrides:

    @pytest.fixture(autouse=True)
    def _save_restore_models(self):
        """Save and restore PIPELINE_CONFIG["models"] for test isolation."""
        saved = dict(PIPELINE_CONFIG["models"])
        yield
        PIPELINE_CONFIG["models"].update(saved)

    def test_default_model_override(self):
        with patch.dict(os.environ, {"TA_MODEL_DEFAULT": "haiku"}):
            _apply_model_env_overrides()
            assert PIPELINE_CONFIG["models"]["research_manager"] == "haiku"
            assert PIPELINE_CONFIG["models"]["market_analyst"] == "haiku"

    def test_per_agent_override(self):
        with patch.dict(os.environ, {"TA_MODEL_RESEARCH_MANAGER": "sonnet"}):
            _apply_model_env_overrides()
            assert PIPELINE_CONFIG["models"]["research_manager"] == "sonnet"
            assert PIPELINE_CONFIG["models"]["market_analyst"] == "sonnet"  # unchanged

    def test_per_agent_beats_default(self):
        with patch.dict(os.environ, {
            "TA_MODEL_DEFAULT": "haiku",
            "TA_MODEL_RESEARCH_MANAGER": "opus",
        }):
            _apply_model_env_overrides()
            assert PIPELINE_CONFIG["models"]["research_manager"] == "opus"
            assert PIPELINE_CONFIG["models"]["market_analyst"] == "haiku"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  3. Helper functions                                                ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestGetEnvBool:

    def test_true_values(self):
        for val in ("true", "True", "TRUE", "1", "yes", "YES"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert get_env_bool("TEST_BOOL") is True

    def test_false_values(self):
        for val in ("false", "False", "0", "no"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert get_env_bool("TEST_BOOL") is False

    def test_missing_returns_default(self):
        assert get_env_bool("NONEXISTENT_KEY", default=True) is True
        assert get_env_bool("NONEXISTENT_KEY", default=False) is False

    def test_garbage_returns_default(self):
        with patch.dict(os.environ, {"TEST_BOOL": "maybe"}):
            assert get_env_bool("TEST_BOOL", default=True) is True


class TestGetEnvFloat:

    def test_valid_float(self):
        with patch.dict(os.environ, {"TEST_FLOAT": "0.5"}):
            assert get_env_float("TEST_FLOAT") == 0.5

    def test_invalid_returns_default(self):
        with patch.dict(os.environ, {"TEST_FLOAT": "abc"}):
            assert get_env_float("TEST_FLOAT", default=1.5) == 1.5

    def test_missing_returns_default(self):
        assert get_env_float("NONEXISTENT", default=3.14) == 3.14


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. Throttle                                                        ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestThrottle:

    def test_throttle_enforces_interval(self):
        from subagent_pipeline.akshare_collector import _throttle, _throttle_lock
        import subagent_pipeline.akshare_collector as ac

        # Set very short interval for testing
        with patch.dict(os.environ, {"TA_API_MIN_INTERVAL": "0.05", "TA_API_JITTER": "0.0"}):
            # Reset last call time
            ac._last_api_call = 0.0

            t0 = time.time()
            _throttle()
            _throttle()
            elapsed = time.time() - t0
            # Second call should wait ~0.05s
            assert elapsed >= 0.04  # allow small tolerance

    def test_throttle_no_wait_after_long_gap(self):
        from subagent_pipeline.akshare_collector import _throttle
        import subagent_pipeline.akshare_collector as ac

        with patch.dict(os.environ, {"TA_API_MIN_INTERVAL": "0.05", "TA_API_JITTER": "0.0"}):
            ac._last_api_call = time.time() - 10.0  # long ago
            t0 = time.time()
            _throttle()
            elapsed = time.time() - t0
            assert elapsed < 0.05  # no wait needed

    def test_retry_call_uses_throttle(self):
        """_retry_call should invoke _throttle before each attempt."""
        from subagent_pipeline.akshare_collector import _retry_call
        calls = []

        def mock_fn():
            calls.append(time.time())
            return "ok"

        with patch.dict(os.environ, {"TA_API_MIN_INTERVAL": "0.0", "TA_API_JITTER": "0.0"}):
            result = _retry_call(mock_fn)
            assert result == "ok"
            assert len(calls) == 1
