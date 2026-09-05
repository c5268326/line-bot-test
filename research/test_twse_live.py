"""
以真實資料驗證 twse_quotes.fetch_today() 的解析正確性。

本地沙箱連不出去,所以在 GitHub Actions 上跑。這段邏輯直接影響 Render
上的即時 API,不能只靠讀程式碼確認。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twse_quotes import fetch_today, roc_to_iso  # noqa: E402

print("=== 民國年轉換 ===")
cases = [("1150904", "2026-09-04"), ("1140101", "2025-01-01"),
         ("115090", None), ("abcdefg", None), ("1151304", None)]
for raw, want in cases:
    got = roc_to_iso(raw)
    print(f"{'✓' if got == want else '✗'} {raw!r:12} → {got}")

print("\n=== 抓取證交所當日全市場 ===")
data = fetch_today()
print(f"取得 {len(data)} 檔\n")
if not data:
    sys.exit("✗ 沒有取得任何資料")

for sid in ("2330", "2317", "2454", "1301", "3231"):
    print(f"  {sid}: {data.get(sid)}")

bad = []
for sid, (d, o, h, lo, c, v) in data.items():
    if len(d) != 10 or d[4] != "-":
        bad.append((sid, "日期格式", d))
    elif not (lo <= c <= h and lo <= o <= h):
        bad.append((sid, "OHLC 不一致", [o, h, lo, c]))
    elif c <= 0 or v < 0:
        bad.append((sid, "數值異常", [c, v]))

print(f"\n一致性檢查:{len(data) - len(bad)} 檔通過,{len(bad)} 檔異常")
for b in bad[:10]:
    print(f"  ✗ {b}")

dates = {v[0] for v in data.values()}
print(f"資料日期:{sorted(dates)}")
print("\n✓ 全部通過" if not bad and len(dates) == 1 else "\n⚠ 有異常")
sys.exit(1 if bad else 0)
