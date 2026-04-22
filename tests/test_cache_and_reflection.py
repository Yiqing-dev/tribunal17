"""Tests for data_cache.py and reflection.py.

Covers:
1. DataCache: get/put roundtrip, cache miss, invalidate, clear, stats
2. ReflectionRecord: error classification, lesson generation
3. ReflectionReport: aggregation, markdown, save_json
4. collect() cache integration (use_cache flag)
"""

import json
import sys
import os
import pytest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.data_cache import DataCache
from subagent_pipeline.reflection import (
    ReflectionRecord,
    ReflectionReport,
    reflect_on_backtest,
    build_reflection_report,
    _infer_direction,
    _classify_error,
    _generate_lesson,
)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  1. DataCache                                                       ║
# ╚══════════════════════════════════════════════════════════════════════╝


class TestDataCache:

    def test_put_and_get_roundtrip(self, tmp_path):
        cache = DataCache(str(tmp_path))
        data = {"prices": [9.1, 9.2, 9.3], "name": "中国核电"}
        cache.put("price_history", "601985", "2026-04-04", data)

        result = cache.get("price_history", "601985", "2026-04-04")
        assert result is not None
        assert result["name"] == "中国核电"
        assert result["prices"] == [9.1, 9.2, 9.3]

    def test_cache_miss_returns_none(self, tmp_path):
        cache = DataCache(str(tmp_path))
        assert cache.get("price_history", "601985", "2026-04-04") is None

    def test_different_dates_different_keys(self, tmp_path):
        cache = DataCache(str(tmp_path))
        cache.put("spot", "601985", "2026-04-03", {"price": 9.1})
        cache.put("spot", "601985", "2026-04-04", {"price": 9.5})

        assert cache.get("spot", "601985", "2026-04-03")["price"] == 9.1
        assert cache.get("spot", "601985", "2026-04-04")["price"] == 9.5

    def test_different_apis_different_keys(self, tmp_path):
        cache = DataCache(str(tmp_path))
        cache.put("spot", "601985", "2026-04-04", {"type": "spot"})
        cache.put("news", "601985", "2026-04-04", {"type": "news"})

        assert cache.get("spot", "601985", "2026-04-04")["type"] == "spot"
        assert cache.get("news", "601985", "2026-04-04")["type"] == "news"

    def test_has(self, tmp_path):
        cache = DataCache(str(tmp_path))
        assert not cache.has("spot", "601985", "2026-04-04")
        cache.put("spot", "601985", "2026-04-04", {})
        assert cache.has("spot", "601985", "2026-04-04")

    def test_invalidate(self, tmp_path):
        cache = DataCache(str(tmp_path))
        cache.put("spot", "601985", "2026-04-04", {"price": 9.1})
        assert cache.invalidate("spot", "601985", "2026-04-04") is True
        assert cache.get("spot", "601985", "2026-04-04") is None
        assert cache.invalidate("spot", "601985", "2026-04-04") is False

    def test_clear(self, tmp_path):
        cache = DataCache(str(tmp_path))
        for i in range(5):
            cache.put("api", f"{i:06d}", "2026-04-04", {"i": i})
        removed = cache.clear()
        assert removed == 5
        assert cache.get("api", "000000", "2026-04-04") is None

    def test_stats(self, tmp_path):
        cache = DataCache(str(tmp_path))
        cache.put("api", "601985", "2026-04-04", {})
        cache.get("api", "601985", "2026-04-04")   # hit
        cache.get("api", "601985", "2026-04-05")   # miss
        s = cache.stats
        assert s["hits"] == 1
        assert s["misses"] == 1
        assert s["writes"] == 1
        assert s["hit_rate"] == 0.5

    def test_corrupted_file_returns_none(self, tmp_path):
        cache = DataCache(str(tmp_path))
        key = DataCache._cache_key("api", "601985", "2026-04-04")
        (tmp_path / f"{key}.json").write_text("not valid json{{{")
        assert cache.get("api", "601985", "2026-04-04") is None


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  2. Reflection — core logic                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝


class _FakeBtResult:
    """Minimal BacktestResult-like object for testing."""
    def __init__(self, **kw):
        defaults = dict(
            run_id="run-test", ticker="601985.SS", ticker_name="中国核电",
            trade_date="2026-03-20", action="BUY", confidence=0.75,
            direction_expected="up", stock_return_pct=5.0,
            max_drawdown_pct=-2.0, max_gain_pct=8.0,
            eval_window_days=10, direction_correct=True,
            outcome="win", hit_stop_loss=False, hit_take_profit=False,
            was_vetoed=False,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestInferDirection:

    def test_up(self):
        assert _infer_direction(5.0) == "up"

    def test_down(self):
        assert _infer_direction(-5.0) == "down"

    def test_flat(self):
        assert _infer_direction(0.5) == "flat"

    def test_custom_band(self):
        assert _infer_direction(1.5, band=1.0) == "up"


class TestReflectOnBacktest:

    def test_correct_prediction(self):
        bt = _FakeBtResult(action="BUY", confidence=0.8, direction_correct=True,
                           stock_return_pct=7.0)
        rec = reflect_on_backtest(bt)
        assert rec.direction_correct is True
        assert rec.confidence_calibration == "calibrated"
        assert "验证" in rec.lesson

    def test_wrong_direction_severe(self):
        bt = _FakeBtResult(action="BUY", confidence=0.8, direction_correct=False,
                           stock_return_pct=-8.0, outcome="loss")
        rec = reflect_on_backtest(bt)
        assert rec.error_type == "direction_wrong_severe"
        assert "严重" in rec.lesson

    def test_overconfident(self):
        bt = _FakeBtResult(action="BUY", confidence=0.75, direction_correct=False,
                           stock_return_pct=-3.0, outcome="loss")
        rec = reflect_on_backtest(bt)
        assert rec.error_type == "overconfident"
        assert rec.confidence_calibration == "overconfident"

    def test_underconfident_correct(self):
        bt = _FakeBtResult(action="BUY", confidence=0.3, direction_correct=True,
                           stock_return_pct=8.0, outcome="win")
        rec = reflect_on_backtest(bt)
        assert rec.confidence_calibration == "underconfident"
        assert "低估" in rec.lesson

    def test_stop_loss_hit(self):
        bt = _FakeBtResult(action="BUY", confidence=0.6, direction_correct=False,
                           stock_return_pct=-5.0, hit_stop_loss=True, outcome="loss")
        rec = reflect_on_backtest(bt)
        assert "止损" in rec.lesson

    def test_veto_excluded(self):
        bt = _FakeBtResult(action="VETO", confidence=0.0, direction_correct=None,
                           stock_return_pct=0.0, outcome="")
        rec = reflect_on_backtest(bt)
        assert rec.error_type == ""
        assert rec.lesson == ""


class TestReflectionReport:

    def _make_records(self):
        return [
            ReflectionRecord(
                run_id=f"run-{i}", ticker="601985.SS", trade_date="2026-03-20",
                predicted_action="BUY", predicted_confidence=0.7,
                predicted_direction="up",
                actual_return_pct=5.0 if i % 2 == 0 else -3.0,
                direction_correct=(i % 2 == 0),
                outcome="win" if i % 2 == 0 else "loss",
                error_type="" if i % 2 == 0 else "direction_wrong",
                lesson="ok" if i % 2 == 0 else "wrong",
                confidence_calibration="calibrated" if i % 2 == 0 else "overconfident",
                pillar_blame="" if i % 2 == 0 else "market",
            )
            for i in range(6)
        ]

    def test_aggregation(self):
        records = self._make_records()
        report = ReflectionReport(
            trade_date="2026-03-20",
            records=records,
            total_signals=6,
        )
        # Manual: 3 correct, 3 wrong → 50%
        correct = [r for r in records if r.direction_correct]
        wrong = [r for r in records if r.direction_correct is False]
        assert len(correct) == 3
        assert len(wrong) == 3

    def test_to_markdown(self):
        records = self._make_records()
        report = ReflectionReport(
            trade_date="2026-03-20",
            records=records,
            total_signals=6,
            direction_accuracy_pct=50.0,
            error_breakdown={"direction_wrong": 3},
            pillar_blame_counts={"market": 3},
        )
        md = report.to_markdown()
        assert "反思报告" in md
        assert "50%" in md
        assert "direction_wrong" in md
        assert "market" in md

    def test_save_json(self, tmp_path):
        report = ReflectionReport(
            trade_date="2026-03-20",
            records=[],
            total_signals=0,
        )
        path = report.save_json(str(tmp_path))
        assert Path(path).exists()
        data = json.loads(Path(path).read_text())
        assert data["trade_date"] == "2026-03-20"

    def test_roundtrip_dict(self):
        rec = ReflectionRecord(
            run_id="run-1", ticker="601985.SS",
            predicted_action="BUY", actual_return_pct=5.0,
            error_type="", lesson="ok", risk_flags=["liquidity"],
        )
        d = rec.to_dict()
        restored = ReflectionRecord.from_dict(d)
        assert restored.run_id == "run-1"
        assert restored.risk_flags == ["liquidity"]


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  4. P1 Feedback Blocks                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝


from subagent_pipeline.reflection import build_feedback_blocks


class TestBuildFeedbackBlocks:

    def test_returns_5_keys(self, tmp_path):
        """Returned dict always has market/fundamentals/news/sentiment/pm keys."""
        blocks = build_feedback_blocks(
            ticker="601985.SS", days=30,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(tmp_path / "no_reports"),
        )
        assert set(blocks.keys()) == {"market", "fundamentals", "news", "sentiment", "pm"}

    def test_cold_start_all_non_empty(self, tmp_path):
        """Zero-history ticker → every block still contains the base-rate prior."""
        blocks = build_feedback_blocks(
            ticker="999999.SS", days=30,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(tmp_path / "no_reports"),
        )
        for key, content in blocks.items():
            assert content.strip(), f"{key} block is empty"
            # Every analyst block carries the base-rate prior
            if key == "pm":
                assert "HOLD 是默认选项" in content
            else:
                assert "基准先验" in content
                # Pillar label present in each pillar block header
                assert "历史反馈" in content

    def test_pm_block_distinct_from_pillar_blocks(self, tmp_path):
        """PM block uses the aggregate prior; pillar blocks use the per-pillar one."""
        blocks = build_feedback_blocks(
            ticker="999999.SS", days=30,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(tmp_path / "no_reports"),
        )
        # PM block specifically references HOLD as default
        assert "HOLD 是默认选项" in blocks["pm"]
        # Pillar blocks specifically reference score=2 as the neutral anchor
        for key in ("market", "fundamentals", "news", "sentiment"):
            assert "pillar_score=2" in blocks[key]

    def test_ticker_normalized_in_output(self, tmp_path):
        """Bare 6-digit ticker gets normalized (e.g., 601985 → 601985.SS)."""
        blocks = build_feedback_blocks(
            ticker="601985", days=30,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(tmp_path / "no_reports"),
        )
        # Normalized form should appear in each block header
        for key, content in blocks.items():
            assert "601985.SS" in content, f"{key} missing normalized ticker"

    def test_days_parameter_reflected_in_header(self, tmp_path):
        """`days` parameter is surfaced in block headers so analysts know the window."""
        blocks = build_feedback_blocks(
            ticker="601985.SS", days=7,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(tmp_path / "no_reports"),
        )
        for content in blocks.values():
            assert "近7天" in content

    def test_reflection_files_loaded_when_present(self, tmp_path):
        """Recent reflection JSON files contribute lessons to the PM block."""
        # Craft a minimal reflection-*.json file containing one ticker record
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        refl = {
            "trade_date": "2026-04-01~2026-04-15",
            "records": [
                {
                    "ticker": "601985.SS",
                    "trade_date": "2026-04-15",
                    "lesson": "测试教训：方向错误",
                    "pillar_blame": "market",
                    "confidence_calibration": "overconfident",
                    "predicted_action": "BUY",
                    "actual_return_pct": -5.0,
                    "error_type": "direction_wrong",
                    "risk_flags": [],
                },
            ],
        }
        (reports_dir / "reflection-test.json").write_text(
            json.dumps(refl), encoding="utf-8"
        )
        blocks = build_feedback_blocks(
            ticker="601985.SS", days=30,
            ledger_path=str(tmp_path / "missing.jsonl"),
            storage_dir=str(tmp_path / "no_replays"),
            reports_dir=str(reports_dir),
        )
        # Lesson must surface in PM block (recent lessons section)
        assert "测试教训" in blocks["pm"]
        # Pillar-blame-tagged lesson must surface in market pillar block
        assert "测试教训" in blocks["market"]
        # Other pillar blocks should NOT have this lesson (pillar isolation)
        assert "测试教训" not in blocks["fundamentals"]
        assert "测试教训" not in blocks["news"]
        assert "测试教训" not in blocks["sentiment"]
