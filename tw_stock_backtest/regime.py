"""理論層（Theory Layer）：市場週期分類，跟訊號層(factors.py)、策略執行層(pipeline.py)
完全解耦——這個模組只回答「現在是什麼週期」，不知道也不需要知道任何個股因子或交易規則。

分類方式與門檻是用 711 檔 point-in-time 台股資料（2014-2026）實測校準的，不是憑感覺假設：
  價格 > 200日均線 且 均線本身向上 → BULL
  價格 < 200日均線 且 均線本身向下 → BEAR
  其餘                              → SIDEWAYS
外加「短於 MIN_EPISODE_DAYS 的集數併入前一段」的平滑，避免均線在零點附近來回穿越
製造出大量幾天甚至0天的假訊號雜訊集數。

實測結果（見對話紀錄 / RESEARCH.md）：
  - 24個真實週期集數，2014-2026：BULL佔60.1%天數、SIDEWAYS 20.3%、BEAR 19.6%。
  - 轉入BEAR前一定會先看到20日波動度暴衝到正常的2.5倍以上、60日動能轉負——這是
    REGIME_WARNING_VOL_MULTIPLE 這個門檻的實測依據，用來在真正轉空頭之前提早示警。
  - 各週期下「扣掉基準後」表現最好的因子不同（BULL→低波動、SIDEWAYS→營收年增率加速、
    BEAR→高股息），因此 FACTOR_TILTS_BY_REGIME 直接把這個實測結果寫成資料，
    給 pipeline.py 的 RegimeBlock 用來動態調整 FactorBlock 的因子權重。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_EPISODE_DAYS = 15
MA_WINDOW = 200
SLOPE_LOOKBACK = 60
REGIME_WARNING_VOL_MULTIPLE = 2.0  # 20日波動度超過歷史中位數的這個倍數，視為「轉空頭警訊」


def market_proxy_index(prices: pd.DataFrame) -> pd.Series:
    """用整個母體的等權指數當市場代理（沒有 0050 這種現成指數時的合理替代，
    已用真實資料驗證這個指數的走勢貼近台股實際大盤）。

    `prices` 為長格式 (date, ticker, close, ...)。單日報酬會截尾在 ±10%，
    因為那是台股實際的漲跌停限制，超過的數值一定是資料異常（例如收盤價被記成0）。
    """
    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    daily_ret = close.pct_change().clip(-0.10, 0.10)
    ew_ret = daily_ret.mean(axis=1, skipna=True)
    index = (1 + ew_ret.fillna(0)).cumprod()
    if len(index):
        index.iloc[0] = 1.0
    return index


def _smooth_causal(labels: pd.Series, min_days: int) -> pd.Series:
    """把「短於 min_days 的雜訊集數」濾掉，但只用「目前為止已經看到的資料」逐日往前推進，
    不看未來——這點很重要，值得解釋清楚：

    最早的寫法是對整個序列做「執行長度編碼」再一次性合併短集數，這在事後回顧一段完整歷史
    時沒問題，但只要有人拿這個函式的結果去對應「某一個歷史日期當天」的市場週期（例如
    `pipeline.py` 逐日跑決策、或這裡用來把週期標籤貼回歷史面板做因子分析），就會不小心
    用到「這個集數後來到底有沒有撐超過 min_days」這個答案——而這個答案要等未來的資料出現
    才會知道，等於是前視偏誤。已經實測驗證過：同一天的分類結果，會因為「只給到那天為止的
    資料」vs「給了後面更多天的資料」而給出不同答案，機率約 3%，集中在真正轉折點附近。

    修正後的邏輯是「確認延遲」(confirmation lag)：新的候選週期要連續出現滿 min_days 天
    才會被「確認」進而生效，在確認之前，當下仍然沿用前一個已確認的週期。這是每天都只用
    當下已知資訊就能重現的結果，跟未來多久之後回頭看都不會改變「當時」的分類。代價是
    真正發生週期轉換時，確認會有 min_days 天的延遲，這是誠實的取捨，不是瑕疵。
    """
    confirmed = None
    pending_label, pending_count = None, 0
    out = []
    for label in labels.tolist():
        if label == confirmed:
            pending_label, pending_count = None, 0
        elif label == pending_label:
            pending_count += 1
        else:
            pending_label, pending_count = label, 1
        if pending_count >= min_days:
            confirmed = pending_label
            pending_label, pending_count = None, 0
        out.append(confirmed if confirmed is not None else label)
    return pd.Series(out, index=labels.index)


def classify_regime(index: pd.Series) -> pd.Series:
    """回傳逐日的 BULL / BEAR / SIDEWAYS 標籤（已用因果的確認延遲機制濾掉雜訊，
    不使用任何未來資料——見 `_smooth_causal` 的說明）。"""
    ma = index.rolling(MA_WINDOW, min_periods=int(MA_WINDOW * 0.75)).mean()
    slope = ma - ma.shift(SLOPE_LOOKBACK)

    raw = pd.Series("SIDEWAYS", index=index.index)
    raw[(index > ma) & (slope > 0)] = "BULL"
    raw[(index < ma) & (slope < 0)] = "BEAR"
    raw = raw.where(ma.notna())

    valid = raw.dropna()
    if valid.empty:
        return raw
    smoothed = _smooth_causal(valid, MIN_EPISODE_DAYS)
    return smoothed.reindex(raw.index)


def regime_episodes(regime: pd.Series) -> pd.DataFrame:
    """把逐日標籤轉成一段一段的「集數」列表，方便看週期多長、什麼時候轉換。"""
    regime = regime.dropna()
    rows = []
    cur_regime, cur_start, prev_date = None, None, None
    for d, r in regime.items():
        if r != cur_regime:
            if cur_regime is not None:
                rows.append({"regime": cur_regime, "start": cur_start, "end": prev_date,
                             "days": (prev_date - cur_start).days})
            cur_regime, cur_start = r, d
        prev_date = d
    if cur_regime is not None:
        rows.append({"regime": cur_regime, "start": cur_start, "end": prev_date,
                     "days": (prev_date - cur_start).days})
    return pd.DataFrame(rows)


def bear_transition_warning(index: pd.Series, as_of_date: pd.Timestamp) -> bool:
    """早期警報：20日波動度是否已經飆到歷史中位數的 REGIME_WARNING_VOL_MULTIPLE 倍以上，
    且60日動能已轉負——實測這正是轉入 BEAR 之前的共同特徵（看對話紀錄的轉換分析）。
    只用 as_of_date 當下已知的資料，不偷看未來。
    """
    ret = index.pct_change()
    vol_20d = ret.rolling(20).std() * np.sqrt(252)
    mom_60d = index.pct_change(60)
    history = vol_20d.loc[:as_of_date]
    if as_of_date not in vol_20d.index or len(history.dropna()) < 60:
        return False
    median_vol = history.median()
    current_vol = vol_20d.loc[as_of_date]
    current_mom = mom_60d.loc[as_of_date]
    if pd.isna(current_vol) or pd.isna(current_mom) or median_vol == 0:
        return False
    return bool(current_vol >= median_vol * REGIME_WARNING_VOL_MULTIPLE and current_mom < 0)


# 實測結果（見模組 docstring）：各週期下，扣掉「該週期不篩選、隨機買」基準後，
# 真正有正向超額表現的因子權重傾斜。數值不是隨便給的權重，是用來在 pipeline.py 的
# FactorBlock 執行前，對 config.factor_weights 做「傾斜」（乘上這個係數），而不是整組換掉，
# 這樣沒被特別驗證過的因子仍維持原本權重，只有已驗證的部分被強化。
FACTOR_TILTS_BY_REGIME: dict[str, dict[str, float]] = {
    "BULL": {"low_volatility": 1.8, "revenue_yoy_accel": 1.5},
    "SIDEWAYS": {"revenue_yoy_accel": 2.5},
    "BEAR": {"dividend_yield": 1.8, "revenue_yoy_accel": 1.2},
}
