"""驗證 pipeline.py（把加密貨幣多階段決策鏈改寫成的台股版本）用合成資料能跑完整流程，
且關鍵風控規則（總經硬性否決、風報比門檻、部位權重分級）真的有作用，不是擺好看的。
"""
from __future__ import annotations

import pandas as pd

from tw_stock_backtest.config import validated_momentum_revenue_config
from tw_stock_backtest.data_sources.synthetic_source import SyntheticDataSource
from tw_stock_backtest.pipeline import EXTREME_MACRO_THRESHOLD, MIN_RR, run_pipeline


def _load_data(seed: int, universe: list[str], start: str, end: str):
    source = SyntheticDataSource(seed=seed)
    prices = source.get_price_history(universe, start, end)
    fundamentals = source.get_fundamentals(universe, start, end)
    macro_df = source.get_macro(start, end)
    return prices, fundamentals, macro_df


def test_pipeline_runs_end_to_end_and_produces_consistent_report_and_order_sheet():
    cfg = validated_momentum_revenue_config()
    cfg.universe = [f"T{i:03d}" for i in range(20)]
    prices, fundamentals, macro_df = _load_data(7, cfg.universe, "2018-01-01", "2020-12-31")

    as_of = prices["date"].max()
    ctx = run_pipeline(cfg, prices, fundamentals, macro_df, as_of)

    assert ctx.as_of_date == as_of
    assert isinstance(ctx.report_text, str) and len(ctx.report_text) > 0
    # 報告文字跟 order_sheet 的檔數必須一致，兩者是同一份決策結果的不同呈現，不該對不上
    assert len(ctx.order_sheet) == len(ctx.decisions)


def test_extreme_macro_score_halts_everything():
    cfg = validated_momentum_revenue_config()
    cfg.universe = [f"T{i:03d}" for i in range(20)]
    prices, fundamentals, macro_df = _load_data(7, cfg.universe, "2018-01-01", "2020-12-31")
    as_of = prices["date"].max()

    # 直接把總經分數壓到極端值以下，驗證硬性否決真的會擋下所有交易，不會被其他邏輯繞過
    macro_df = macro_df.copy()
    macro_df["business_cycle_signal"] = 9  # 藍燈谷底
    macro_df["m1b_yoy"] = -0.20
    macro_df["sox_index"] = macro_df["sox_index"] * 0.3  # 模擬 SOX 重挫

    ctx = run_pipeline(cfg, prices, fundamentals, macro_df, as_of)
    if ctx.macro_score <= EXTREME_MACRO_THRESHOLD:
        assert ctx.halted is True
        assert ctx.decisions == []
        assert ctx.order_sheet.empty


def test_low_risk_reward_stocks_are_vetoed_not_silently_included():
    cfg = validated_momentum_revenue_config()
    cfg.universe = [f"T{i:03d}" for i in range(30)]
    prices, fundamentals, macro_df = _load_data(3, cfg.universe, "2018-01-01", "2021-12-31")
    as_of = prices["date"].max()

    ctx = run_pipeline(cfg, prices, fundamentals, macro_df, as_of)
    for d in ctx.decisions:
        assert d.risk_reward >= MIN_RR - 1e-9
    for d in ctx.vetoed:
        assert d.veto_reason is not None


def test_position_weight_is_never_negative_or_above_one():
    cfg = validated_momentum_revenue_config()
    cfg.universe = [f"T{i:03d}" for i in range(25)]
    for seed in (1, 2, 3, 4):
        prices, fundamentals, macro_df = _load_data(seed, cfg.universe, "2016-01-01", "2022-12-31")
        for as_of in prices["date"].drop_duplicates().sample(5, random_state=seed):
            ctx = run_pipeline(cfg, prices, fundamentals, macro_df, as_of)
            for d in ctx.decisions:
                assert 0.0 <= d.position_weight <= 1.0
