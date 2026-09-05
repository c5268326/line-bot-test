"""
抓取台股日線資料,產生 docs/data/stocks.json 供檢測站網頁讀取。

由 .github/workflows/update_stocks.yml 排程執行,產出的 JSON 會 commit 回 repo,
GitHub Pages 上的網頁再從同源讀取 —— 這樣就繞開了瀏覽器的跨網域限制,
網頁本身不需要任何 API key。

=======================================================================
 要接上真實行情,只需要實作 fetch_daily_bars() 一個函式。
 其他部分(輸出格式、去重、排序、寫檔)都已經處理好了。
=======================================================================
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

TW = timezone(timedelta(hours=8))

OUT_FILE = os.path.join(os.path.dirname(__file__), "docs", "data", "stocks.json")

# 要監測的標的。代號請用證交所的格式,名稱只是顯示用。
WATCHLIST = [
    ("2330", "台積電"),
    ("2317", "鴻海"),
    ("2454", "聯發科"),
    ("0050", "元大台灣50"),
]

# 每檔要保留幾個交易日(檢測站至少需要 30 筆才算得出季線,建議 250 以上)
KEEP_DAYS = 260

# 兩次請求之間的間隔秒數,避免對來源站台造成負擔
REQUEST_INTERVAL = 3.0


def fetch_daily_bars(symbol: str) -> list:
    """
    ===================================================================
     ★ 這裡就是要填入抓取邏輯的地方 ★
    ===================================================================

    參數
        symbol: 股票代號字串,例如 "2330"

    必須回傳
        一個 list,每個元素是一根日 K,格式為:

            [日期, 開盤, 最高, 最低, 收盤, 成交量]

        其中日期是 "YYYY-MM-DD" 字串,其餘五個是數字(int 或 float)。
        由舊到新或由新到舊都可以,main() 會自動排序與去重。

        例:
            [
                ["2026-08-01", 1050.0, 1070.0, 1040.0, 1060.0, 32145],
                ["2026-08-04", 1060.0, 1080.0, 1055.0, 1075.0, 28000],
            ]

        抓不到資料時回傳空 list 即可,該檔會被略過,不會讓整個流程失敗。

    注意
        這支程式跑在 GitHub Actions 的機器上,對外網路是通的,
        所以 requests / urllib 都可以正常使用。若需要額外套件,
        記得一併加進 .github/workflows/update_stocks.yml 的 pip install。
    """
    raise NotImplementedError(
        "尚未實作 fetch_daily_bars():請在 fetch_stocks.py 填入抓取邏輯。"
    )


# ---------------------------------------------------------------------
# 以下為輸出處理,通常不需要改動
# ---------------------------------------------------------------------

def normalise(rows: list) -> list:
    """排序、去重、限制筆數,並確保數值型別正確。"""
    clean = {}
    for row in rows or []:
        if not row or len(row) < 5:
            continue
        date = str(row[0]).strip()
        if len(date) != 10 or date[4] != "-":
            continue
        try:
            o, h, l, c = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
            v = float(row[5]) if len(row) > 5 and row[5] is not None else 0.0
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        # 同一天出現多次時以後出現者為準
        clean[date] = [date, round(o, 4), round(h, 4), round(l, 4), round(c, 4), int(v)]

    out = [clean[d] for d in sorted(clean)]
    return out[-KEEP_DAYS:]


def build_payload() -> dict:
    stocks = []
    failures = []

    for idx, (symbol, name) in enumerate(WATCHLIST):
        if idx:
            time.sleep(REQUEST_INTERVAL)
        try:
            bars = normalise(fetch_daily_bars(symbol))
        except NotImplementedError:
            raise
        except Exception as exc:                      # noqa: BLE001 - 單檔失敗不該中斷整批
            print(f"✗ {symbol} {name}:抓取失敗 —— {exc}")
            failures.append(symbol)
            continue

        if len(bars) < 30:
            print(f"✗ {symbol} {name}:只取得 {len(bars)} 筆,少於 30 筆,略過")
            failures.append(symbol)
            continue

        print(f"✓ {symbol} {name}:{len(bars)} 筆({bars[0][0]} ~ {bars[-1][0]})")
        stocks.append({"id": symbol, "name": name, "bars": bars})

    return {
        "updated_at": datetime.now(TW).isoformat(timespec="seconds"),
        "source": "fetch_stocks.py",
        "failures": failures,
        "stocks": stocks,
    }


def main() -> int:
    try:
        payload = build_payload()
    except NotImplementedError as exc:
        # 抓取邏輯還沒填上:正常結束,不要讓排程一直亮紅燈
        print(f"⚠ {exc}")
        print("  網頁會繼續顯示示範資料,直到這個函式實作完成為止。")
        return 0

    if not payload["stocks"]:
        print("⚠ 沒有任何標的成功取得資料,保留現有的 stocks.json 不覆寫。")
        return 0

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_FILE) / 1024
    print(f"\n已寫入 {OUT_FILE}({len(payload['stocks'])} 檔,{size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
