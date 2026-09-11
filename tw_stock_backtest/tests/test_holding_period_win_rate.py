"""驗證「持有期間正報酬機率」這個新指標的計算邏輯本身正確（用人造、確定性的權益曲線），
不依賴任何市場資料。這個指標的意義與限制（重疊窗口、非獨立樣本）見 metrics.py 的 docstring。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tw_stock_backtest.metrics import holding_period_win_rate, holding_period_win_rates


def _daily_index(start: str, n_days: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n_days, freq="D")


def test_monotonic_uptrend_has_100pct_win_rate():
    idx = _daily_index("2015-01-01", 365 * 6)
    curve = pd.Series(np.linspace(1.0, 3.0, len(idx)), index=idx)
    result = holding_period_win_rate(curve, years=3)
    assert result["windows"] > 0
    assert result["win_rate"] == 1.0


def test_monotonic_downtrend_has_0pct_win_rate():
    idx = _daily_index("2015-01-01", 365 * 6)
    curve = pd.Series(np.linspace(3.0, 1.0, len(idx)), index=idx)
    result = holding_period_win_rate(curve, years=3)
    assert result["windows"] > 0
    assert result["win_rate"] == 0.0


def test_flat_curve_is_neither_win_nor_loss_zero_rate():
    idx = _daily_index("2015-01-01", 365 * 6)
    curve = pd.Series(1.0, index=idx)
    result = holding_period_win_rate(curve, years=3)
    # 相等視為「非正報酬」（win 定義是嚴格大於），所以應為 0%
    assert result["win_rate"] == 0.0


def test_horizon_longer_than_available_span_returns_none():
    idx = _daily_index("2015-01-01", 365)  # 只有 1 年資料
    curve = pd.Series(np.linspace(1.0, 1.2, len(idx)), index=idx)
    result = holding_period_win_rate(curve, years=10)
    assert result["windows"] == 0
    assert result["win_rate"] is None


def test_holding_period_win_rates_returns_all_requested_horizons():
    idx = _daily_index("2015-01-01", 365 * 6)
    curve = pd.Series(np.linspace(1.0, 2.0, len(idx)), index=idx)
    results = holding_period_win_rates(curve, horizons_years=(1, 3, 10))
    assert set(results.keys()) == {1, 3, 10}
    assert results[1]["win_rate"] == 1.0
    assert results[3]["win_rate"] == 1.0
    assert results[10]["win_rate"] is None  # 資料只有 6 年


def test_known_win_rate_on_synthetic_cycle():
    """建構一條「規律漲跌循環」的曲線,讓 3 年持有期的勝率可以手算出精確值,交叉驗證函式邏輯。"""
    idx = _daily_index("2010-01-01", 365 * 20)
    n = len(idx)
    t = np.arange(n)
    # 6 年一循環的正弦波 + 微幅長期向上漂移,確保有漲有跌、且非退化成單調曲線
    curve_vals = 1.0 + 0.5 * np.sin(2 * np.pi * t / (365 * 6)) + 0.01 * t / 365
    curve = pd.Series(curve_vals, index=idx)
    result = holding_period_win_rate(curve, years=3)
    assert result["windows"] > 1000
    assert 0.0 < result["win_rate"] < 1.0  # 循環曲線的 3 年持有期勝率必須嚴格介於 0~1 之間
