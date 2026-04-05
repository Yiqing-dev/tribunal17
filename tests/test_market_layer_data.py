"""Tests for market_layer.py — MarketLayerData contract enforcement.

Covers:
1. save() persists all 3 files to REPLAYS
2. load() returns None if any file missing
3. is_complete() quick check
4. board_data extraction from recap
5. save() rejects None snapshot
6. Round-trip: save → load preserves data
"""

import json
import sys
import pytest
from pathlib import Path
from dataclasses import dataclass

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from subagent_pipeline.market_layer import MarketLayerData


@dataclass
class _FakeSnapshot:
    """Minimal MarketSnapshot-like for testing."""
    limit_up_count: int = 40
    limit_down_count: int = 50
    trade_date: str = "2026-04-03"

    def to_json(self):
        return json.dumps({
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "trade_date": self.trade_date,
        })


class TestSave:

    def test_saves_all_3_files(self, tmp_path):
        replays = tmp_path / "replays"
        results = tmp_path / "results"
        mld = MarketLayerData(
            trade_date="2026-04-03",
            market_context={"regime": "RISK_OFF"},
            market_context_block="regime=RISK_OFF",
            snapshot=_FakeSnapshot(),
        )
        mld.save(str(replays), str(results))

        assert (replays / "market_context_2026-04-03.json").exists()
        assert (replays / "market_snapshot_2026-04-03.json").exists()
        assert (results / "market_context_block.txt").exists()
        assert (results / "market_snapshot.json").exists()

    def test_rejects_none_snapshot(self, tmp_path):
        mld = MarketLayerData(
            trade_date="2026-04-03",
            market_context={"regime": "RISK_OFF"},
            market_context_block="test",
            snapshot=None,
        )
        with pytest.raises(ValueError, match="snapshot is None"):
            mld.save(str(tmp_path / "r"), str(tmp_path / "s"))

    def test_rejects_empty_context(self, tmp_path):
        mld = MarketLayerData(
            trade_date="2026-04-03",
            market_context={},
            market_context_block="test",
            snapshot=_FakeSnapshot(),
        )
        with pytest.raises(ValueError, match="market_context is empty"):
            mld.save(str(tmp_path / "r"), str(tmp_path / "s"))


class TestLoad:

    def _save_complete(self, replays, results, date="2026-04-03"):
        mld = MarketLayerData(
            trade_date=date,
            market_context={"regime": "RISK_OFF", "trade_date": date},
            market_context_block="regime=RISK_OFF",
            snapshot=_FakeSnapshot(trade_date=date),
            recap_json=json.dumps({
                "limit_board": {
                    "limit_up_stocks": [{"ticker": "000001", "name": "test"}],
                    "limit_down_stocks": [],
                },
                "consecutive_boards": [{"ticker": "000002", "boards": 3}],
            }),
        )
        mld.save(str(replays), str(results))
        return mld

    def test_load_complete(self, tmp_path):
        replays = tmp_path / "replays"
        results = tmp_path / "results"
        self._save_complete(replays, results)

        loaded = MarketLayerData.load("2026-04-03", str(replays), str(results))
        assert loaded is not None
        assert loaded.market_context["regime"] == "RISK_OFF"
        assert loaded.market_context_block == "regime=RISK_OFF"

    def test_load_missing_snapshot_returns_none(self, tmp_path):
        replays = tmp_path / "replays"
        results = tmp_path / "results"
        self._save_complete(replays, results)
        # Delete snapshot
        (replays / "market_snapshot_2026-04-03.json").unlink()

        loaded = MarketLayerData.load("2026-04-03", str(replays), str(results))
        assert loaded is None

    def test_load_missing_context_returns_none(self, tmp_path):
        replays = tmp_path / "replays"
        results = tmp_path / "results"
        self._save_complete(replays, results)
        (replays / "market_context_2026-04-03.json").unlink()

        assert MarketLayerData.load("2026-04-03", str(replays), str(results)) is None

    def test_load_missing_recap_returns_none(self, tmp_path):
        replays = tmp_path / "replays"
        results = tmp_path / "results"
        self._save_complete(replays, results)
        (replays / "recap_2026-04-03.json").unlink()

        assert MarketLayerData.load("2026-04-03", str(replays), str(results)) is None


class TestIsComplete:

    def test_complete(self, tmp_path):
        replays = tmp_path / "replays"
        replays.mkdir()
        for name in ["market_context_2026-04-03.json",
                     "market_snapshot_2026-04-03.json",
                     "recap_2026-04-03.json"]:
            (replays / name).write_text("{}")
        assert MarketLayerData.is_complete("2026-04-03", str(replays)) is True

    def test_incomplete(self, tmp_path):
        replays = tmp_path / "replays"
        replays.mkdir()
        (replays / "market_context_2026-04-03.json").write_text("{}")
        assert MarketLayerData.is_complete("2026-04-03", str(replays)) is False


class TestBoardData:

    def test_extracts_board_data(self):
        recap = {
            "limit_board": {
                "limit_up_stocks": [{"ticker": "000001"}],
                "limit_down_stocks": [{"ticker": "000002"}],
            },
            "consecutive_boards": [{"ticker": "000003", "boards": 2}],
        }
        mld = MarketLayerData(
            trade_date="2026-04-03",
            market_context={}, market_context_block="",
            snapshot=None, recap_json=json.dumps(recap),
        )
        bd = mld.board_data
        assert len(bd["limit_ups"]) == 1
        assert len(bd["limit_downs"]) == 1
        assert len(bd["consecutive_boards"]) == 1

    def test_empty_recap(self):
        mld = MarketLayerData(
            trade_date="2026-04-03",
            market_context={}, market_context_block="",
            snapshot=None, recap_json="",
        )
        bd = mld.board_data
        assert bd["limit_ups"] == []
