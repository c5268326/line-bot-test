"""
驗證 app.py 的 _fetch_twse_today() 能正確解析證交所當日全市場資料。

本地沙箱連不出去,所以在 GitHub Actions 上跑。這段解析邏輯會直接影響
Render 上的即時 API,不能只靠讀程式碼確認。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "dummy")
os.environ.setdefault("LINE_CHANNEL_SECRET", "dummy")

import app as A  # noqa: E402

print("呼叫 _fetch_twse_today() …")
data = A._fetch_twse_today()
print(f"取得 {len(data)} 檔\n")

if not data:
    sys.exit("✗ 沒有取得任何資料")

for sid in ("2330", "2317", "2454", "1301"):
    print(f"  {sid}: {data.get(sid)}")

bad = []
for sid, bar in data.items():
    d, o, h, l, c, v = bar
    if len(d) != 10 or d[4] != "-":
        bad.append((sid, "日期格式", d))
    elif not (l <= c <= h and l <= o <= h):
        bad.append((sid, "OHLC 不一致", bar))
    elif c <= 0 or v < 0:
        bad.append((sid, "數值異常", bar))

print(f"\n欄位一致性檢查:{len(data) - len(bad)} 檔通過,{len(bad)} 檔異常")
for b in bad[:10]:
    print(f"  ✗ {b}")

dates = {b[0] for b in data.values()}
print(f"資料日期:{sorted(dates)}")
print("\n✓ 解析正常" if not bad and len(dates) == 1 else "\n⚠ 有異常,見上方")
