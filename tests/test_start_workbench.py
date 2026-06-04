import importlib.util
from pathlib import Path


def _load_launcher():
    path = Path(__file__).resolve().parents[1] / "start_workbench.py"
    spec = importlib.util.spec_from_file_location("start_workbench_launcher", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_start_workbench_parser_defaults():
    mod = _load_launcher()
    args = mod.build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.no_generate is False
    assert args.output_dir.endswith("data/reports")
    assert args.storage_dir.endswith("data/replays")


def test_start_workbench_parser_accepts_agent_friendly_options():
    mod = _load_launcher()
    args = mod.build_parser().parse_args(["--port", "8770", "--no-generate"])

    assert args.port == 8770
    assert args.no_generate is True


def test_start_workbench_parser_accepts_daily_watchlist_options(tmp_path):
    mod = _load_launcher()
    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text("600519 贵州茅台\n", encoding="utf-8")

    args = mod.build_parser().parse_args([
        "--tickers", "000858,002594",
        "--tickers-file", str(watchlist),
    ])

    assert args.tickers == ["000858,002594"]
    assert args.tickers_file == str(watchlist)


def test_start_workbench_warns_when_no_generate_has_no_html(tmp_path, capsys):
    mod = _load_launcher()

    warned = mod.warn_missing_workbench(str(tmp_path))
    out = capsys.readouterr().out

    assert warned is True
    assert "Warning: --no-generate" in out
    assert "workbench.html" in out


def test_start_workbench_no_warning_when_existing_html(tmp_path, capsys):
    mod = _load_launcher()
    tmp_path.joinpath("workbench.html").write_text("ok", encoding="utf-8")

    warned = mod.warn_missing_workbench(str(tmp_path))
    out = capsys.readouterr().out

    assert warned is False
    assert out == ""


def test_start_workbench_parser_accepts_court_launch_phrase():
    mod = _load_launcher()
    phrase = "论衡十七司，升堂！【600519，000858，002594】"

    args = mod.build_parser().parse_args([phrase])

    assert args.command_text == [phrase]


def test_watchlist_loader_normalizes_cli_and_file(tmp_path):
    from subagent_pipeline.watchlist import load_watchlist

    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text(
        "# daily list\n600519 贵州茅台\n000858,五粮液\n",
        encoding="utf-8",
    )

    items = load_watchlist(tickers=["000858,002594"], tickers_file=watchlist)

    assert [item.ticker for item in items] == ["000858.SZ", "002594.SZ", "600519.SS"]
    assert {item.ticker: item.name for item in items}["000858.SZ"] == "五粮液"


def test_watchlist_loader_parses_lunheng_court_phrase():
    from subagent_pipeline.watchlist import load_watchlist, parse_court_command

    phrase = "论衡十七司，升堂！【600519 贵州茅台，000858 五粮液，002594】"

    items = parse_court_command(phrase)
    assert [item.ticker for item in items] == ["600519.SS", "000858.SZ", "002594.SZ"]
    assert {item.ticker: item.name for item in items}["600519.SS"] == "贵州茅台"
    assert {item.ticker: item.name for item in items}["000858.SZ"] == "五粮液"

    loaded = load_watchlist(command_text=phrase)
    assert [item.ticker for item in loaded] == ["600519.SS", "000858.SZ", "002594.SZ"]


def test_watchlist_loader_parses_pipe_separated_lunheng_phrase():
    from subagent_pipeline.watchlist import parse_court_command

    phrase = """论衡十七司升堂！603065 宿迁联盛 | 000710 贝瑞基因 | 920344 三元生物 |
      688298
        东方生物 | 002131 利欧股份 | 002370"""

    items = parse_court_command(phrase)

    assert [(item.ticker, item.name) for item in items] == [
        ("603065.SS", "宿迁联盛"),
        ("000710.SZ", "贝瑞基因"),
        ("920344.BJ", "三元生物"),
        ("688298.SS", "东方生物"),
        ("002131.SZ", "利欧股份"),
        ("002370.SZ", ""),
    ]


def test_watchlist_loader_resolves_known_stock_names():
    from subagent_pipeline.watchlist import load_watchlist

    items = load_watchlist(command_text="论衡十七司，升堂！【贵州茅台，五粮液，比亚迪】")

    assert [(item.ticker, item.name) for item in items] == [
        ("600519.SS", "贵州茅台"),
        ("000858.SZ", "五粮液"),
        ("002594.SZ", "比亚迪"),
    ]


def test_lunheng_court_runbook_writes_watchlist_and_markdown(tmp_path):
    from subagent_pipeline.lunheng_court import prepare_runbook

    path = prepare_runbook(
        command_text="论衡十七司，升堂！【贵州茅台，000858 五粮液】",
        output_dir=str(tmp_path),
    )

    text = path.read_text(encoding="utf-8")
    watchlist_json = tmp_path.joinpath("daily_watchlist.json").read_text(encoding="utf-8")
    assert "600519.SS 贵州茅台" in text
    assert "000858.SZ 五粮液" in text
    assert "由当前 Claude Code / Codex 大语言模型调用 subagent" in text
    assert "默认使用多角色 subagent" in text
    assert "batch_process --tickers 600519:贵州茅台,000858:五粮液" in text
    assert "start_workbench.py --tickers 600519:贵州茅台,000858:五粮液" in text
    assert "600519.SS" in watchlist_json
