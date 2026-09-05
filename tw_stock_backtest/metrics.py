"""績效分析：把 equity curve + 交易紀錄轉成標準的回測績效指標。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import BacktestResult

TRADING_DAYS_PER_YEAR = 252


def daily_returns(equity_curve: pd.Series) -> pd.Series:
    return equity_curve.pct_change().dropna()


def cagr(equity_curve: pd.Series) -> float:
    if len(equity_curve) < 2:
        return float("nan")
    n_years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
    if n_years <= 0:
        return float("nan")
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    return total_return ** (1 / n_years) - 1


def annualized_volatility(rets: pd.Series) -> float:
    return rets.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_ratio(rets: pd.Series, risk_free_rate_annual: float) -> float:
    rf_daily = (1 + risk_free_rate_annual) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = rets - rf_daily
    denom = excess.std(ddof=0)
    if denom == 0 or np.isnan(denom):
        return float("nan")
    return excess.mean() / denom * np.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(rets: pd.Series, risk_free_rate_annual: float) -> float:
    rf_daily = (1 + risk_free_rate_annual) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = rets - rf_daily
    downside = excess[excess < 0]
    denom = downside.std(ddof=0)
    if denom == 0 or np.isnan(denom):
        return float("nan")
    return excess.mean() / denom * np.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(equity_curve: pd.Series) -> dict:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    trough_date = drawdown.idxmin()
    mdd = drawdown.min()
    peak_date = equity_curve.loc[:trough_date].idxmax()
    recovery = equity_curve.loc[trough_date:]
    recovered = recovery[recovery >= equity_curve.loc[peak_date]]
    recovery_date = recovered.index[0] if len(recovered) else None
    return {"max_drawdown": mdd, "peak_date": peak_date, "trough_date": trough_date,
            "recovery_date": recovery_date}


def calmar_ratio(equity_curve: pd.Series) -> float:
    mdd = max_drawdown(equity_curve)["max_drawdown"]
    if mdd == 0 or np.isnan(mdd):
        return float("nan")
    return cagr(equity_curve) / abs(mdd)


def round_trip_pnl(result: BacktestResult) -> pd.DataFrame:
    """把買/賣配對成一筆筆完整交易（本框架每檔股票同時最多一個持倉，配對是簡單的先進先出）。"""
    open_trades: dict[str, list] = {}
    rows = []
    for t in result.trades:
        if t.action == "buy":
            open_trades.setdefault(t.ticker, []).append(t)
        else:
            buys = open_trades.get(t.ticker, [])
            if not buys:
                continue
            buy = buys.pop(0)
            pnl = t.amount - buy.amount
            rows.append({
                "ticker": t.ticker, "buy_date": buy.date, "sell_date": t.date,
                "entry_price": buy.price, "exit_price": t.price,
                "exit_reason": t.reason, "pnl": pnl, "pnl_pct": pnl / buy.amount if buy.amount else np.nan,
            })
    return pd.DataFrame(rows)


def trade_stats(result: BacktestResult) -> dict:
    rt = round_trip_pnl(result)
    if rt.empty:
        return {"num_round_trips": 0, "win_rate": float("nan"), "avg_win_pct": float("nan"),
                "avg_loss_pct": float("nan"), "profit_factor": float("nan"),
                "num_stop_loss_exits": 0, "num_rebalance_exits": 0}
    wins = rt[rt["pnl"] > 0]
    losses = rt[rt["pnl"] <= 0]
    gross_profit = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    return {
        "num_round_trips": len(rt),
        "win_rate": len(wins) / len(rt),
        "avg_win_pct": wins["pnl_pct"].mean() if len(wins) else float("nan"),
        "avg_loss_pct": losses["pnl_pct"].mean() if len(losses) else float("nan"),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("nan"),
        "num_stop_loss_exits": int((rt["exit_reason"] == "stop_loss").sum()),
        "num_rebalance_exits": int((rt["exit_reason"] == "rebalance").sum()),
    }


def benchmark_comparison(equity_curve: pd.Series, benchmark_close: pd.Series) -> dict:
    bench = benchmark_close.reindex(equity_curve.index).ffill()
    bench_equity = bench / bench.iloc[0] * equity_curve.iloc[0]
    strat_rets = daily_returns(equity_curve)
    bench_rets = daily_returns(bench_equity)
    aligned = pd.concat([strat_rets, bench_rets], axis=1, keys=["strategy", "benchmark"]).dropna()
    if aligned.empty or aligned["benchmark"].var() == 0:
        beta = float("nan")
    else:
        beta = aligned["strategy"].cov(aligned["benchmark"]) / aligned["benchmark"].var()
    alpha_cagr = cagr(equity_curve) - cagr(bench_equity)
    tracking_error = (aligned["strategy"] - aligned["benchmark"]).std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR)
    info_ratio = ((aligned["strategy"] - aligned["benchmark"]).mean() * TRADING_DAYS_PER_YEAR) / tracking_error \
        if tracking_error else float("nan")
    return {
        "benchmark_cagr": cagr(bench_equity), "benchmark_equity": bench_equity,
        "alpha_vs_benchmark_cagr": alpha_cagr, "beta_vs_benchmark": beta,
        "tracking_error": tracking_error, "information_ratio": info_ratio,
    }


def generate_report(result: BacktestResult, config, benchmark_close: pd.Series | None = None) -> dict:
    equity_curve = result.equity_curve
    rets = daily_returns(equity_curve)
    mdd = max_drawdown(equity_curve)
    report = {
        "start_date": equity_curve.index[0], "end_date": equity_curve.index[-1],
        "initial_value": equity_curve.iloc[0], "final_value": equity_curve.iloc[-1],
        "total_return_pct": equity_curve.iloc[-1] / equity_curve.iloc[0] - 1,
        "cagr": cagr(equity_curve),
        "annualized_volatility": annualized_volatility(rets),
        "sharpe_ratio": sharpe_ratio(rets, config.risk_free_rate_annual),
        "sortino_ratio": sortino_ratio(rets, config.risk_free_rate_annual),
        "calmar_ratio": calmar_ratio(equity_curve),
        **mdd,
        **trade_stats(result),
    }
    if benchmark_close is not None:
        report.update(benchmark_comparison(equity_curve, benchmark_close))
    return report


def format_report_text(report: dict) -> str:
    lines = [
        "===== 回測績效報告 =====",
        f"期間：{report['start_date'].date()} ~ {report['end_date'].date()}",
        f"期初資產：{report['initial_value']:,.0f}　期末資產：{report['final_value']:,.0f}",
        f"總報酬率：{report['total_return_pct']:.2%}　CAGR：{report['cagr']:.2%}",
        f"年化波動度：{report['annualized_volatility']:.2%}",
        f"Sharpe：{report['sharpe_ratio']:.2f}　Sortino：{report['sortino_ratio']:.2f}　"
        f"Calmar：{report['calmar_ratio']:.2f}",
        f"最大回撤：{report['max_drawdown']:.2%}"
        f"（{report['peak_date'].date()} → {report['trough_date'].date()}，"
        f"回復日：{report['recovery_date'].date() if report['recovery_date'] is not None else '尚未回復'}）",
        f"交易次數：{report['num_round_trips']}　勝率：{report['win_rate']:.2%}"
        if report['num_round_trips'] else "交易次數：0",
        f"平均獲利：{report.get('avg_win_pct', float('nan')):.2%}　"
        f"平均虧損：{report.get('avg_loss_pct', float('nan')):.2%}　"
        f"獲利因子：{report.get('profit_factor', float('nan')):.2f}",
        f"停損出場次數：{report.get('num_stop_loss_exits', 0)}　"
        f"換股出場次數：{report.get('num_rebalance_exits', 0)}",
    ]
    if "benchmark_cagr" in report:
        lines += [
            "----- 對比基準 -----",
            f"基準 CAGR：{report['benchmark_cagr']:.2%}　"
            f"Alpha(CAGR差)：{report['alpha_vs_benchmark_cagr']:.2%}　Beta：{report['beta_vs_benchmark']:.2f}",
            f"追蹤誤差：{report['tracking_error']:.2%}　資訊比率：{report['information_ratio']:.2f}",
        ]
    return "\n".join(lines)
