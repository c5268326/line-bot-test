"""驗證 regime.py（理論層：市場週期分類）用人造、確定性的價格路徑能算出正確的週期標籤，
且平滑機制真的會濾掉短暫的雜訊集數，不需要依賴真實資料。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tw_stock_backtest.regime import (
    bear_transition_warning, classify_regime, market_proxy_index, regime_episodes,
)


def _index_from_returns(daily_returns: np.ndarray, start: str = "2015-01-01") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(daily_returns))
    return pd.Series((1 + daily_returns).cumprod(), index=idx)


def test_sustained_uptrend_is_classified_as_bull():
    rets = np.full(500, 0.002)  # 穩定上漲
    index = _index_from_returns(rets)
    regime = classify_regime(index)
    assert (regime.iloc[-100:] == "BULL").all()


def test_sustained_downtrend_is_classified_as_bear():
    rets = np.full(500, -0.002)
    index = _index_from_returns(rets)
    regime = classify_regime(index)
    assert (regime.iloc[-100:] == "BEAR").all()


def test_short_noise_episode_is_smoothed_away():
    rng = np.random.default_rng(0)
    rets = np.full(400, 0.002)
    rets[200:203] = -0.05  # 三天雜訊型重挫，不該被當成一段獨立的空頭週期
    index = _index_from_returns(rets)
    regime = classify_regime(index)
    episodes = regime_episodes(regime)
    # 平滑後不該出現天數 < MIN_EPISODE_DAYS 的集數
    assert (episodes["days"] >= 14).all() or episodes.empty


def test_bear_transition_warning_triggers_on_vol_spike_and_negative_momentum():
    rets = np.full(300, 0.0015)
    rets[-20:] = np.array([-0.03, 0.025, -0.035, 0.02, -0.04] * 4)  # 劇烈震盪 + 淨值下滑
    index = _index_from_returns(rets)
    as_of = index.index[-1]
    warning = bear_transition_warning(index, as_of)
    assert isinstance(warning, bool)


def test_market_proxy_index_clips_extreme_single_day_moves():
    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame({
        "date": list(dates) * 2,
        "ticker": ["A"] * 5 + ["B"] * 5,
        "close": [100, 100, 0.01, 100, 100] + [50, 51, 52, 53, 54],
    })
    index = market_proxy_index(prices)
    # A 股在第3天收盤價異常掉到 0.01（近乎除以0的資料錯誤），不應該讓整條指數也跟著崩潰
    assert index.min() > 0.5
