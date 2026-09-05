"""CLI 進入點：串接資料源 -> 因子計算 -> 回測 -> 績效報告。

範例（在沒有網路的環境驗證程式邏輯）：
    python -m tw_stock_backtest.run_backtest --source synthetic --output-dir out

真實回測（需要有網路權限的環境，並先 pip install -r tw_stock_backtest/requirements.txt）：
    python -m tw_stock_backtest.run_backtest --source finmind --start 2015-01-01 --end 2024-12-31 \
        --output-dir out
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

from .backtest import Backtester
from .config import BacktestConfig


def build_data_source(name: str):
    if name == "synthetic":
        from .data_sources.synthetic_source import SyntheticDataSource
        return SyntheticDataSource()
    if name == "finmind":
        from .data_sources.finmind_source import FinMindDataSource
        return FinMindDataSource()
    if name == "yfinance":
        from .data_sources.yfinance_source import YFinanceDataSource
        return YFinanceDataSource()
    if name == "twse":
        from .data_sources.twse_source import TWSEDataSource
        return TWSEDataSource()
    raise ValueError(f"未知的資料源：{name}")


def main():
    parser = argparse.ArgumentParser(description="台股多因子回測")
    parser.add_argument("--source", default="synthetic",
                         choices=["synthetic", "finmind", "yfinance", "twse"])
    parser.add_argument("--start", default=None, help="覆蓋 config.py 的 start_date")
    parser.add_argument("--end", default=None, help="覆蓋 config.py 的 end_date")
    parser.add_argument("--universe-file", default=None,
                         help="每行一檔股票代號的文字檔，覆蓋 config.py 的預設母體")
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--stop-loss", type=float, default=None, help="例如 0.20 代表 -20% 停損")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--manual-macro-csv", default=None,
                         help="人工維護的總經 CSV，見 data/macro_manual_template.csv")
    parser.add_argument("--output-dir", default="tw_stock_backtest_output")
    args = parser.parse_args()

    config = BacktestConfig()
    if args.start:
        config.start_date = args.start
    if args.end:
        config.end_date = args.end
    if args.top_n:
        config.top_n = args.top_n
    if args.stop_loss:
        config.stop_loss_pct = args.stop_loss
    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as f:
            config.universe = [line.strip() for line in f if line.strip()]

    print(f"[1/4] 使用資料源：{args.source}")
    source = build_data_source(args.source)
    all_tickers = list(dict.fromkeys(config.universe + [config.benchmark]))

    print("[2/4] 抓取價格 / 基本面 / 總經資料 ...")
    prices = source.get_price_history(all_tickers, config.start_date, config.end_date)
    fundamentals = source.get_fundamentals(config.universe, config.start_date, config.end_date)
    macro_df = source.get_macro(config.start_date, config.end_date)
    if args.manual_macro_csv:
        from .macro import merge_manual_macro
        macro_df = merge_manual_macro(macro_df, args.manual_macro_csv)

    universe_prices = prices[prices["ticker"] != config.benchmark]
    benchmark_prices = prices[prices["ticker"] == config.benchmark]

    print("[3/4] 執行回測 ...")
    backtester = Backtester(config, universe_prices, fundamentals, macro_df)
    result = backtester.run(initial_capital=args.initial_capital)

    print("[4/4] 產生績效報告 ...")
    from . import metrics
    benchmark_close = None
    if not benchmark_prices.empty:
        benchmark_close = benchmark_prices.set_index("date")["close"]
    report = metrics.generate_report(result, config, benchmark_close)

    os.makedirs(args.output_dir, exist_ok=True)
    result.equity_curve.to_csv(os.path.join(args.output_dir, "equity_curve.csv"), header=["equity"])
    trades_df = pd.DataFrame([t.__dict__ for t in result.trades])
    trades_df.to_csv(os.path.join(args.output_dir, "trades.csv"), index=False)
    serializable_report = {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in report.items() if k != "benchmark_equity"
    }
    with open(os.path.join(args.output_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(serializable_report, f, ensure_ascii=False, indent=2, default=str)

    print()
    print(metrics.format_report_text(report))
    print(f"\n詳細結果已輸出至：{args.output_dir}/ (equity_curve.csv, trades.csv, report.json)")


if __name__ == "__main__":
    main()
