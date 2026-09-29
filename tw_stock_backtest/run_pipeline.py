"""CLI 進入點：跑一次「每日選股決策管線」（見 pipeline.py 開頭的架構對照表），
輸出中文報告與建議清單，不會自動下單。

範例（合成資料，驗證程式邏輯）：
    python -m tw_stock_backtest.run_pipeline --source synthetic

真實使用（需要有網路權限的環境）：
    python -m tw_stock_backtest.run_pipeline --source finmind --preset validated_momentum_revenue \
        --as-of-date 2026-09-05
"""
from __future__ import annotations

import argparse

import pandas as pd

from .config import BacktestConfig, long_term_config, short_term_config, validated_momentum_revenue_config
from .pipeline import run_pipeline
from .run_backtest import build_data_source


def main():
    parser = argparse.ArgumentParser(description="台股每日選股決策管線")
    parser.add_argument("--source", default="synthetic",
                         choices=["synthetic", "finmind", "yfinance", "twse"])
    parser.add_argument("--preset", default="validated_momentum_revenue",
                         choices=["default", "long_term", "short_term", "validated_momentum_revenue"])
    parser.add_argument("--as-of-date", default=None, help="決策日 (YYYY-MM-DD)，預設用資料最後一天")
    parser.add_argument("--lookback-days", type=int, default=400, help="抓多少天的歷史資料來算因子")
    args = parser.parse_args()

    config = {
        "default": BacktestConfig,
        "long_term": long_term_config,
        "short_term": short_term_config,
        "validated_momentum_revenue": validated_momentum_revenue_config,
    }[args.preset]()

    as_of = pd.Timestamp(args.as_of_date) if args.as_of_date else pd.Timestamp.today().normalize()
    start = (as_of - pd.Timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    end = as_of.strftime("%Y-%m-%d")

    print(f"[1/2] 使用資料源：{args.source}　策略預設：{args.preset}　決策日：{end}")
    source = build_data_source(args.source)
    prices = source.get_price_history(config.universe, start, end)
    fundamentals = source.get_fundamentals(config.universe, start, end)
    macro_df = source.get_macro(start, end)
    if not prices.empty:
        as_of = prices["date"].max()

    print("[2/2] 執行決策管線 ...")
    ctx = run_pipeline(config, prices, fundamentals, macro_df, as_of)

    print()
    print(ctx.report_text)
    if not ctx.order_sheet.empty:
        print("\n建議清單（結構化）：")
        print(ctx.order_sheet.to_string(index=False))


if __name__ == "__main__":
    main()
