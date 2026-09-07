"""
查代號:使用者要加入的個股,先確認代號、市場別與資料可得性。

不從記憶猜代號 —— 猜錯會把別人的股票畫成你的。
用 FinMind 的 TaiwanStockInfo(涵蓋上市與上櫃)反查名稱。

用法:python probe_lookup.py 亞電 美達
"""
import json
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
NAMES = sys.argv[1:] or ["亞電", "美達"]


def get(url, tries=3, timeout=40):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"    {getattr(e, 'code', None) or type(e).__name__},重試", flush=True)
            time.sleep(6 * (i + 1))
    return None


print("=== 取得台股代號對照表 ===", flush=True)
j = get(f"{FINMIND}?dataset=TaiwanStockInfo")
data = (j or {}).get("data") or []
print(f"共 {len(data)} 筆", flush=True)
if not data:
    raise SystemExit("✗ 取不到對照表")

seen = {}
for r in data:
    sid, nm = r.get("stock_id"), r.get("stock_name")
    if sid and nm and sid not in seen:
        seen[sid] = (nm, r.get("type"), r.get("industry_category"))

print(f"去重後 {len(seen)} 檔\n", flush=True)

for key in NAMES:
    hits = [(sid, v) for sid, v in seen.items() if key in v[0]]
    print(f"=== 「{key}」 命中 {len(hits)} 檔 ===", flush=True)
    for sid, (nm, typ, ind) in sorted(hits):
        print(f"  {sid}  {nm:<12} 市場 {typ:<8} 產業 {ind}", flush=True)
    if not hits:
        print("  沒有名稱含這兩個字的個股", flush=True)
    print(flush=True)

# 對命中的四碼個股確認日線拿不拿得到
print("=== 確認日線可得性 ===", flush=True)
cands = sorted({sid for key in NAMES for sid, v in seen.items()
                if key in v[0] and len(sid) == 4 and sid.isdigit()})
for sid in cands:
    time.sleep(2)
    u = (f"{FINMIND}?dataset=TaiwanStockPrice&data_id={sid}"
         f"&start_date=2024-01-01&end_date=2026-12-31")
    jj = get(u)
    rows = (jj or {}).get("data") or []
    if rows:
        print(f"  ✓ {sid} {seen[sid][0]}:{len(rows)} 筆,{rows[0]['date']} ~ {rows[-1]['date']},"
              f"最新收盤 {rows[-1]['close']}", flush=True)
    else:
        print(f"  ✗ {sid} {seen[sid][0]}:取不到日線", flush=True)
