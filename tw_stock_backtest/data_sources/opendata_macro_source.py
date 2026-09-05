"""全自動抓取「沒有股票代號」的總經指標，取代原本要你手動維護的 CSV。

用政府開放資料平台（data.gov.tw / NDC 景氣指標查詢系統）與中央銀行開放資料平台
（cpx.cbc.gov.tw）的公開端點，抓：
  - 景氣對策信號（燈號 + 綜合分數）與貨幣總計數 M1B、出口訂單動向指數
    → data.gov.tw dataset id 6099（國發會「景氣指標及燈號」，每月更新的 CSV/ZIP 檔）
  - 央行重貼現率
    → cpx.cbc.gov.tw 中央銀行開放資料 API，dataset id 6022（央行貼放利率）

**寫作限制（誠實列出）**：這支程式是在網路出口被沙盒政策封鎖、完全無法連線
data.gov.tw / cpx.cbc.gov.tw 驗證真實回傳格式的情況下寫的。程式邏輯用了「盡量寬鬆解析」
的寫法（找檔名關鍵字、找欄位關鍵字，而非寫死固定欄位順序），目的是提高存活率，但**你在有
網路的環境第一次執行時，仍務必檢查印出的欄位/欄名是否合理**；若平台格式已變更導致解析失敗，
程式會丟出清楚的錯誤訊息（列出它實際抓到的欄位/檔名），而不是靜默回傳錯誤數字。

呼叫端不需要準備任何 CSV，直接呼叫 `fetch_full_macro_automatically()` 即可。
"""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd
import requests

DATA_GOV_TW_DATASET_API = "https://data.gov.tw/api/v1/rest/dataset/{dataset_id}"
NDC_BUSINESS_CYCLE_DATASET_ID = "6099"   # 景氣指標及燈號（含景氣對策信號、M1B、出口訂單動向指數）
CBC_POLICY_RATE_URL = "https://cpx.cbc.gov.tw/api/OpenData/DataSet?set_id=6022&index=0"  # 央行貼放利率


def _find_resource_url(dataset_id: str, format_keywords: tuple[str, ...]) -> str:
    """查 data.gov.tw 資料集的中繼資料，找出目前實際的檔案下載網址。

    不要把下載網址寫死在程式裡——data.gov.tw 上的檔案網址常常包含版本日期，平台更新資料
    後網址會換掉，透過中繼資料 API 動態查詢才不會每個月都要改程式碼。
    """
    resp = requests.get(DATA_GOV_TW_DATASET_API.format(dataset_id=dataset_id), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    result = payload.get("result", payload)
    distributions = result.get("distribution", result.get("resources", []))
    for dist in distributions:
        fmt = str(dist.get("resourceFormat", dist.get("format", ""))).lower()
        if any(kw in fmt for kw in format_keywords):
            url = dist.get("resourceDownloadUrl") or dist.get("url") or dist.get("download_url")
            if url:
                return url
    raise RuntimeError(
        f"在 data.gov.tw dataset {dataset_id} 的中繼資料裡找不到格式含 {format_keywords} 的檔案，"
        f"該資料集目前的 distribution 內容為：{distributions}。"
        f"請到 https://data.gov.tw/dataset/{dataset_id} 確認資料集是否已改版。"
    )


def _read_table_from_bytes(raw: bytes) -> pd.DataFrame:
    """檔案可能是 CSV 也可能是 ZIP 包 CSV，且編碼可能是 UTF-8 或 Big5，這裡都嘗試看看。"""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise RuntimeError(f"ZIP 檔案內找不到 CSV，內容檔名為：{zf.namelist()}")
            raw = zf.read(csv_names[0])
    for encoding in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise RuntimeError("嘗試 utf-8 / big5 / cp950 都無法解析這份 CSV，請人工檢查檔案編碼。")


def _find_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    for col in df.columns:
        col_str = str(col)
        if all(kw in col_str for kw in keywords):
            return col
    return None


def fetch_business_cycle_and_money_supply(start: str, end: str) -> pd.DataFrame:
    """抓景氣對策信號綜合分數 + M1B（用來算年增率）+ 出口訂單動向指數，回傳月頻 DataFrame。"""
    url = _find_resource_url(NDC_BUSINESS_CYCLE_DATASET_ID, format_keywords=("csv", "zip"))
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    df = _read_table_from_bytes(resp.content)

    date_col = _find_column(df, ["年"]) or df.columns[0]
    signal_col = _find_column(df, ["對策", "分數"]) or _find_column(df, ["綜合", "分數"])
    m1b_col = _find_column(df, ["M1B"])
    export_order_col = _find_column(df, ["出口訂單"])
    missing = [name for name, col in [("景氣對策信號分數", signal_col), ("M1B", m1b_col)] if col is None]
    if missing:
        raise RuntimeError(
            f"在景氣指標資料集裡找不到欄位：{missing}，實際欄位為：{list(df.columns)}，"
            "請對照 https://data.nat.gov.tw/dataset/6099 調整關鍵字。"
        )

    def parse_roc_yyymm(v) -> pd.Timestamp | None:
        s = str(v).strip()
        m = re.match(r"(\d{2,3})[/\-年](\d{1,2})", s)
        if not m:
            return None
        roc_year, month = int(m.group(1)), int(m.group(2))
        return pd.Timestamp(year=roc_year + 1911, month=month, day=1) + pd.offsets.MonthEnd(0)

    out = pd.DataFrame({
        "date": df[date_col].map(parse_roc_yyymm),
        "business_cycle_signal": pd.to_numeric(df[signal_col], errors="coerce"),
        "m1b_level": pd.to_numeric(df[m1b_col], errors="coerce"),
    })
    if export_order_col is not None:
        out["export_order_index"] = pd.to_numeric(df[export_order_col], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")
    out["m1b_yoy"] = out["m1b_level"].pct_change(12)
    if "export_order_index" in out:
        out["export_orders_yoy"] = out["export_order_index"].pct_change(12)
    return out[(out["date"] >= start) & (out["date"] <= end)].set_index("date")


def fetch_policy_rate(start: str, end: str) -> pd.Series:
    """抓央行重貼現率，回傳以「調整日期」為 index 的 Series（事件序列，之後用 ffill 補到每日）。"""
    resp = requests.get(CBC_POLICY_RATE_URL, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    records = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("result") or payload.get("records") or []
    )
    if not records:
        raise RuntimeError(f"央行貼放利率 API 沒有回傳可解析的資料列，原始回應：{payload}")
    df = pd.DataFrame(records)
    date_col = _find_column(df, ["日期"]) or _find_column(df, ["date"]) or df.columns[0]
    rate_col = _find_column(df, ["重貼現"]) or _find_column(df, ["rate"])
    if rate_col is None:
        raise RuntimeError(f"央行貼放利率資料裡找不到重貼現率欄位，實際欄位為：{list(df.columns)}")
    series = pd.Series(
        pd.to_numeric(df[rate_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col], errors="coerce"),
    ).dropna().sort_index()
    return series[(series.index >= start) & (series.index <= end)]


def fetch_full_macro_automatically(start: str, end: str) -> pd.DataFrame:
    """完全自動、不需要任何手動 CSV 的總經面板。sox_index / usdtwd 建議另外用
    YFinanceDataSource.get_macro() 抓，再用本函式的結果去補其餘欄位（見 macro.py 的
    `merge_manual_macro` 已被 `merge_opendata_macro` 取代）。
    """
    daily_index = pd.bdate_range(start, end)
    out = pd.DataFrame(index=daily_index)

    business = fetch_business_cycle_and_money_supply(start, end)
    for col in ["business_cycle_signal", "m1b_yoy", "export_orders_yoy"]:
        if col in business:
            out[col] = business[col].reindex(out.index, method="ffill")

    policy_rate = fetch_policy_rate(start, end)
    out["policy_rate"] = policy_rate.reindex(out.index, method="ffill")

    out["cpi_yoy"] = float("nan")  # 目前尚未接上 CPI 來源；compute_macro_score 未使用此欄位
    return out
