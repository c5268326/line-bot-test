"""
校正 stocks.json 的 market 欄位。

market 來自 FinMind 的 TaiwanStockInfo,那是「宣告」的分類,會過期:
藥華藥、保瑞、鴻勁這些從興櫃／上櫃轉上市的公司,欄位還停在舊的。

籌碼資料是「觀察」到的事實 —— 個股出現在證交所 T86(有外資／投信／自營
分項)就是上市;只出現在櫃買日報(只有三大法人合計)就是上櫃。
觀察勝過宣告,所以用 chips.json 回頭校正 stocks.json。

只改對得出來的,對不出來的保持原狀,不猜。

    python research/fix_market.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCKS = os.path.join(ROOT, "docs", "data", "stocks.json")
CHIPS = os.path.join(ROOT, "docs", "data", "chips.json")


def main():
    if not os.path.exists(CHIPS):
        print("找不到 chips.json,請先執行 fetch_chips.py")
        return 1
    chips = json.load(open(CHIPS, encoding="utf-8"))
    doc = json.load(open(STOCKS, encoding="utf-8"))

    observed = {}
    for sid, r in chips.get("stocks", {}).items():
        vals = [v for v in (r.get("inst") or {}).values() if v]
        if not vals:
            continue
        # 有任何一天拿到外資分項 → 那天它在證交所日報裡 → 上市
        observed[sid] = "twse" if any(v.get("foreign") is not None for v in vals) else "tpex"

    changed = []
    for s in doc["stocks"]:
        o = observed.get(s["id"])
        if o and s.get("market") != o:
            changed.append((s["id"], s.get("name"), s.get("market"), o))
            s["market"] = o

    print(f"籌碼資料涵蓋 {len(observed)} 檔,其中 {len(changed)} 檔的 market 需要校正")
    for sid, name, old, new in changed:
        print(f"  {sid} {name}: {old} → {new}")
    if not changed:
        return 0

    with open(STOCKS, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n已寫回 {STOCKS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
