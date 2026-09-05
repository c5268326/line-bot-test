"""
把 research/output 的回測結果轉成網頁用的 docs/data/backtest.json。

網頁只需要畫線和列表,不需要逐日的權益曲線 —— 研究產出的曲線點數會讓
內嵌檔案膨脹好幾倍,而畫在 900px 寬的圖上根本看不出差別,所以在這裡降頻。

同時把「舊的固定股票池」年化併成 prior 區塊,網頁才能直接呈現
倖存者偏誤的規模(對照組 +25.38% → +10.40%,那 15pp 全是偏誤)。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "research", "output")
DEST = os.path.join(HERE, "docs", "data", "backtest.json")
MAX_POINTS = 150


def thin(curve, n=MAX_POINTS):
    """降頻但保留首尾 —— 尾點決定總報酬,不能被抽掉"""
    if len(curve) <= n:
        return curve
    step = len(curve) / n
    out = [curve[int(i * step)] for i in range(n)]
    if out[-1] is not curve[-1]:
        out.append(curve[-1])
    return out


def main():
    src = os.path.join(OUT_DIR, "backtest_pit.json")
    if not os.path.exists(src):
        raise SystemExit(f"找不到 {src},請先執行 research/backtest_pit.py")
    new = json.load(open(src, encoding="utf-8"))

    web = {"config": new["config"], "benchmark": dict(new["benchmark"]), "strategies": {}}
    web["benchmark"]["curve"] = thin(new["benchmark"]["curve"])

    for k, s in new["strategies"].items():
        entry = {"label": s["label"]}
        for mode in ("no_stop", "with_stop"):
            m = dict(s[mode])
            m["curve"] = thin(s[mode + "_curve"])
            entry[mode] = m
        web["strategies"][k] = entry

    old_path = os.path.join(OUT_DIR, "backtest_results.json")
    if os.path.exists(old_path):
        old = json.load(open(old_path, encoding="utf-8"))
        web["prior"] = {
            "universe_size": old["config"]["universe_size"],
            "benchmark": {"label": old["benchmark"]["label"], "cagr": old["benchmark"]["cagr"]},
            "strategies": {k: {"label": v["label"], "cagr": v["no_stop"]["cagr"]}
                           for k, v in old["strategies"].items()},
        }

    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(web, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已寫入 {DEST}({os.path.getsize(DEST)/1024:.0f} KB),"
          f"策略 {len(web['strategies'])} 個,曲線各 {len(web['benchmark']['curve'])} 點")
    return 0


if __name__ == "__main__":
    sys.exit(main())
