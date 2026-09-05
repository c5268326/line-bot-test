"""總體經濟濾網：把總經面板轉成一個「多空燈號分數」，用來決定要不要縮減持股檔數（防禦模式）。

所有標準化都用「擴張窗（expanding window）」而非用全樣本的 mean/std，避免用到當下還不知道
的未來資訊（look-ahead bias）——這點在總經濾網尤其重要，因為總經數據容易被拿來「事後諸葛」。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def merge_manual_macro(macro_df: pd.DataFrame, manual_csv_path: str) -> pd.DataFrame:
    """把程式化抓到的總經面板（如 SOX、匯率），跟人工維護的 CSV（景氣燈號、央行利率等）合併。

    manual_csv_path 的格式請參考 data/macro_manual_template.csv。
    """
    manual = pd.read_csv(manual_csv_path, parse_dates=["date"]).set_index("date")
    merged = macro_df.combine_first(manual.reindex(macro_df.index, method="ffill"))
    for col in manual.columns:
        if col in macro_df.columns:
            merged[col] = macro_df[col].combine_first(manual[col].reindex(macro_df.index, method="ffill"))
    return merged


def expanding_zscore(series: pd.Series, min_periods: int = 60) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean()
    std = series.expanding(min_periods=min_periods).std(ddof=0)
    z = (series - mean) / std.replace(0, np.nan)
    return z.fillna(0.0)


def compute_macro_score(macro_df: pd.DataFrame) -> pd.Series:
    """組合出一個逐日的總經多空分數：SOX 動能 + M1B年增率 - 政策利率年增 + 景氣燈號位階。

    分數越低代表總經環境越差（適合啟動防禦模式），越高代表越適合積極持股。
    任一輸入指標缺值時，該項貢獻視為 0（中性），不會讓整個分數變成 NaN。
    """
    score = pd.Series(0.0, index=macro_df.index)

    if "sox_index" in macro_df:
        sox_mom = macro_df["sox_index"].pct_change(63)  # 約 3 個月動能
        score = score + expanding_zscore(sox_mom)

    if "m1b_yoy" in macro_df:
        score = score + expanding_zscore(macro_df["m1b_yoy"])

    if "policy_rate" in macro_df:
        rate_change = macro_df["policy_rate"].diff(252)  # 年度利率變動
        score = score - expanding_zscore(rate_change)

    if "business_cycle_signal" in macro_df:
        # 景氣對策信號 9~45 分，用 23~31 綠燈區間置中做標準化，過熱(紅燈)與低迷(藍燈)都視為風險
        centered = -(macro_df["business_cycle_signal"] - 27).abs()
        score = score + expanding_zscore(centered)

    return score.fillna(0.0)
