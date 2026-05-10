from subagent_pipeline.stock_profile import infer_stock_profile, stock_profile_prompt_block


def test_loss_making_profile_warns_against_pe_anchor():
    profile = infer_stock_profile(
        ticker="688298",
        ticker_name="东方生物",
        sector="生物制品",
        metrics={"pe": "-15.58", "pb": "0.69", "roe": "-8.2", "market_cap": "44.17"},
        text="公司净亏损，仍处于持续经营压力下。",
    )

    assert profile.primary == "loss_making"
    assert "loss_making" in profile.labels
    assert any("PE" in w for w in profile.warnings)

    block = stock_profile_prompt_block(profile.to_dict())
    assert "个股类型" in block
    assert "亏损股不得以PE作为主估值锚" in block


def test_cyclical_profile_prioritizes_cycle_checks():
    profile = infer_stock_profile(
        ticker="600000",
        ticker_name="煤化工样本",
        sector="煤炭化工",
        metrics={"revenue_growth": "28", "roe": "12", "market_cap": "250"},
    )

    assert profile.primary == "cyclical"
    assert "growth" in profile.labels
    assert "产品价格周期" in profile.key_checks


def test_theme_small_cap_profile_from_size_and_hot_money_text():
    profile = infer_stock_profile(
        ticker="920344",
        ticker_name="小票样本",
        sector="机器人概念",
        metrics={"market_cap": "25.53", "gross_margin": "18"},
        text="近期涨停并登上龙虎榜，游资参与明显。",
    )

    assert profile.primary == "theme_small_cap"
    assert "龙虎榜/游资" in profile.key_checks

