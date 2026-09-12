"""
補回日線裡整天缺掉的交易日。

怎麼會缺一整天
--------------
update_quotes.py 有兩個問題疊在一起:

1) snapshot() 對「請求失敗」和「當天不是交易日」都回 None,呼叫端一律
   印「非交易日或無資料」就跳過。網路抖一下,那一天就這樣沒了 ——
   和先前把 FinMind 402 當成「查無財報」是同一類錯:把「拿不到」
   和「沒有」混為一談。

2) 下一輪的起點是 max(所有個股的最後日期)。上櫃個股走 FinMind 補到了
   9/10,latest 就變成 9/10,於是 9/07 永遠落在回補視窗之外,不會自己好。

結果:2026-09-07 這個真實交易日,674 檔裡有 672 檔沒有。
連漲天數、均量、所有指標都是在一條有洞的序列上算出來的。

這支程式的做法
--------------
不看 max,改看「每個日期有多少檔有資料」。某天的覆蓋率遠低於鄰近日期,
就是洞,把那天重抓回來。判斷基準只用「該檔第一筆資料之後」的日期,
才不會把上市較晚的股票算成缺漏。

    python research/repair_quotes.py
"""
import json
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import update_quotes as U   # noqa: E402  沿用同一個快照與欄位對應

DEST = U.DEST
COVERAGE_MIN = 0.60        # 覆蓋率低於鄰近日期的六成就當成洞


def main():
    doc = json.load(open(DEST, encoding="utf-8"))
    dates = doc.get("dates") or []
    for s in doc["stocks"]:
        s["bars"] = [[dates[b[0]]] + list(b[1:]) for b in s["bars"]] if dates else \
                    [list(b) for b in s["bars"]]

    have = {s["id"]: {b[0] for b in s["bars"]} for s in doc["stocks"]}
    first = {s["id"]: min(b[0] for b in s["bars"]) for s in doc["stocks"] if s["bars"]}

    # 每個日期的覆蓋率:分母只算「那天之前就已經有資料」的個股
    cover = {}
    for d in dates:
        elig = sum(1 for sid, f in first.items() if f <= d)
        got = sum(1 for sid in have if d in have[sid])
        cover[d] = (got, elig, got / elig if elig else 0)

    typical = sorted(c[2] for c in cover.values())
    med = typical[len(typical) // 2] if typical else 0
    holes = [d for d in dates if cover[d][2] < med * COVERAGE_MIN]

    print(f"交易日 {len(dates)} 天,覆蓋率中位數 {med*100:.1f}%")
    if not holes:
        print("沒有整天缺漏的交易日,不需要修補")
        return 0
    print(f"\n偵測到 {len(holes)} 個缺漏日:")
    for d in holes:
        g, e, r = cover[d]
        print(f"  {d}  只有 {g}/{e} 檔({r*100:.1f}%)")

    print("\n重抓證交所全市場快照 …", flush=True)
    from datetime import datetime
    added = 0
    for d in holes:
        day = datetime.strptime(d, "%Y-%m-%d").date()
        snap = U.snapshot(day)
        time.sleep(U.TWSE_PACE)
        if not snap:
            # 這裡要講清楚:抓不到不等於那天沒開市。
            print(f"  {d} ✗ 抓不到 —— 不確定是非交易日還是請求失敗,這天維持原狀",
                  flush=True)
            continue
        n = 0
        for s in doc["stocks"]:
            if d in have[s["id"]]:
                continue
            row = snap.get(s["id"])
            if not row:
                continue
            s["bars"].append([d] + row)
            have[s["id"]].add(d)
            n += 1
        added += n
        print(f"  {d} ✓ 全市場 {len(snap)} 檔 → 補上 {n} 檔", flush=True)

    if not added:
        print("\n沒有補到任何資料,檔案不變")
        return 0

    for s in doc["stocks"]:
        s["bars"].sort(key=lambda x: x[0])
        s["bars"] = s["bars"][-U.KEEP:]

    new_dates = sorted({b[0] for s in doc["stocks"] for b in s["bars"]})
    di = {d: i for i, d in enumerate(new_dates)}
    for s in doc["stocks"]:
        s["bars"] = [[di[b[0]]] + list(b[1:]) for b in s["bars"]]
    doc["dates"] = new_dates
    doc["as_of"] = new_dates[-1]
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n共補上 {added:,} 筆,已寫回 {DEST}")

    # 補完再算一次,把結果講出來,不要只說「已完成」
    after = defaultdict(int)
    for s in doc["stocks"]:
        for b in s["bars"]:
            after[new_dates[b[0]]] += 1
    for d in holes:
        print(f"  {d} 現在 {after.get(d, 0)} 檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
