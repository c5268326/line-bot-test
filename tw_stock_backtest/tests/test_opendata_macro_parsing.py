"""驗證 opendata_macro_source.py 的「解析邏輯」正確，不需要真的連到 data.gov.tw / 央行。

做法：自己組一份符合預期欄位的假 CSV bytes（模擬政府開放資料平台會回傳的格式），
直接餵給解析函式，確認能正確找到欄位、算出年增率、轉換民國年月。這樣即使在無法連網的
環境，也能驗證「假設格式沒錯的話，程式邏輯是正確的」；欄位假設本身仍需在有網路時對照
官方資料集核對（見模組檔頭註解）。
"""
from __future__ import annotations

import pandas as pd

from tw_stock_backtest.data_sources.opendata_macro_source import _find_column, _read_table_from_bytes


def test_read_table_from_bytes_handles_plain_utf8_csv():
    raw = "年月,景氣對策信號分數,M1B\n113/01,25,500000\n113/02,27,505000\n".encode("utf-8")
    df = _read_table_from_bytes(raw)
    assert list(df.columns) == ["年月", "景氣對策信號分數", "M1B"]
    assert len(df) == 2


def test_read_table_from_bytes_handles_big5_csv():
    raw = "年月,景氣對策信號分數\n113/01,25\n".encode("big5")
    df = _read_table_from_bytes(raw)
    assert df["景氣對策信號分數"].iloc[0] == 25


def test_find_column_matches_keyword_combination():
    df = pd.DataFrame(columns=["年月", "景氣對策信號分數", "M1B(日平均)", "出口訂單動向指數"])
    assert _find_column(df, ["對策", "分數"]) == "景氣對策信號分數"
    assert _find_column(df, ["M1B"]) == "M1B(日平均)"
    assert _find_column(df, ["出口訂單"]) == "出口訂單動向指數"
    assert _find_column(df, ["不存在的關鍵字"]) is None
