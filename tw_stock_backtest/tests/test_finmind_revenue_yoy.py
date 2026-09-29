"""驗證 FinMindDataSource._get_revenue_yoy 對「公告可用日」與「年增率對齊」的計算邏輯，
用模擬的 FinMind 回應（不連網，monkeypatch `_request`）重現另一個 session 實測發現的兩個問題：
1. FinMind 的 date 欄是「營收月份的次月 1 日」，不是公告日，不能直接拿來用。
2. 用 pct_change(12) 算年增率，遇到中間缺月份會位置錯位；改用 (year, month) 對齊。
"""
from __future__ import annotations

import pandas as pd
import pytest

from tw_stock_backtest.data_sources.finmind_source import FinMindDataSource


def _make_source(monkeypatch, canned: pd.DataFrame) -> FinMindDataSource:
    source = FinMindDataSource(request_interval_sec=0)
    monkeypatch.setattr(source, "_request", lambda dataset, data_id, start, end: canned)
    return source


def test_announce_date_is_not_taken_directly_from_finmind_date_field(monkeypatch):
    # 模擬 2330 的實測情況：2022-12 營收，FinMind 的 date 卻是 2023-01-01（次月1日）,
    # 而不是公告日（次月10日前）。修正後不該直接沿用這個 date。
    canned = pd.DataFrame({
        "date": ["2023-01-01"],
        "revenue_year": [2022],
        "revenue_month": [12],
        "revenue": [1_000_000],
    })
    source = _make_source(monkeypatch, canned)
    out = source._get_revenue_yoy("2330", "2022-01-01", "2023-12-31")

    assert len(out) == 1
    announce_date = out.iloc[0]["date"]
    # 應該是「營收月份(2022-12) + 1個月 + 10天」= 2023-01-11，而不是 FinMind 給的 2023-01-01
    assert announce_date == pd.Timestamp("2023-01-11")
    assert announce_date != pd.Timestamp("2023-01-01")


def test_yoy_aligns_by_year_month_even_with_missing_months(monkeypatch):
    # 中間缺一個月（2023-03 沒有資料），用 pct_change(12) 這種位置對齊的算法會把
    # 2024-01 的 YoY 錯配到 2023-02 的營收；用 (year, month) 對齊則不受影響。
    canned = pd.DataFrame({
        "date": [
            "2023-02-01", "2023-04-01",  # 缺 2023-03
            "2024-01-01", "2024-02-01",
        ],
        "revenue_year": [2023, 2023, 2024, 2024],
        "revenue_month": [1, 3, 1, 2],  # 分別代表 2023-01, 2023-03, 2024-01, 2024-02
        "revenue": [100.0, 120.0, 150.0, 180.0],
    })
    source = _make_source(monkeypatch, canned)
    out = source._get_revenue_yoy("2330", "2023-01-01", "2024-12-31")

    row_2024_01 = out[(out["date"] == pd.Timestamp("2024-02-11"))]
    assert len(row_2024_01) == 1
    # 2024-01 營收 150 對 2023-01 營收 100 的年增率，應為 +50%，不是拿去對到 2023-03 的 120
    assert row_2024_01.iloc[0]["revenue_yoy"] == pytest.approx(0.5)

    row_2024_02 = out[(out["date"] == pd.Timestamp("2024-03-11"))]
    assert len(row_2024_02) == 1
    # 2024-02 營收 180 對 2023-02（不存在）的年增率，應為 NaN，不能亂配到別的月份
    assert pd.isna(row_2024_02.iloc[0]["revenue_yoy"])
