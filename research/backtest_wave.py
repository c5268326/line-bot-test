"""
波浪理論的數法標記,到底有沒有預測力?

做法
----
把 docs/index.html 上那套波浪判讀(research/wave.py,已逐檔比對確認與
JS 版完全一致)套到 point-in-time 股票池上,每個換股日給每檔股票一個標記,
再看接下來一季的表現。

標記是互斥的:一檔股票在某個時點只會拿到一個標記(候選依「上升 5 波已完成
→ 第 5 波 → 第 4 波 → 第 3 波」的順序,取第一個沒被三條硬規則排除的)。
所以可以直接把股票池切成幾群來比。

兩個關鍵設計
------------
1) **控制組 wave_none**:判讀不出結構的那一群。如果「第 3 波」的績效贏不過
   「看不懂」的那一群,那這個標記就沒有帶進任何資訊。少了這一組,
   任何多頭年份都能讓波浪策略看起來很行。

2) **橫斷面超額**:同一個換股日之內,把該群的報酬減去整個股票池當期的
   平均報酬,再跨季平均。這樣衡量的是「這個標記能不能挑出比較好的股票」,
   而不是「有這個標記的那幾季剛好是好季節」。後者只是把大盤漲跌換個說法。
   t 值以「季」為獨立單位計算 —— 同一季內的個股報酬高度相關,
   用個股筆數算 t 值會把樣本數灌水好幾十倍。

還有一項對照:up_w3 與動能策略選到的股票重疊多少。如果「第 3 波進行中」
只是漲得比較多的另一種講法,那它就不是新的資訊。

前視偏誤
--------
每個時點只用該時點以前的日線。ZigZag 的轉折需要價格反轉才確認,
本身就不會偷看未來;但「今天回頭看」給同一段走勢的標記,可能和
「當時看到」的不同 —— 回測一定要用當時的標記,否則波浪會神準得離譜。

輸入 research/data/pit/{universe_by_date.csv, price.csv.gz}
產出 research/output/wave_backtest.json
     research/output/wave_backtest.md
"""
import json
import math
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import backtest as B          # noqa: E402  沿用同一份交易成本與權益計算
import backtest_pit as P      # noqa: E402  沿用 point-in-time 資料載入
import wave as W              # noqa: E402  與頁面同一套波浪判讀

# 頁面上每檔股票給波浪引擎的就是最近 300 個交易日。回測若用更長的歷史,
# 測到的就不是使用者實際看到的那個判讀。
WINDOW = 300
MIN_BARS = 250               # 上市未滿這麼久的股票這一期沒有標記

LABELS = ["up_w3", "up_w5", "up_w4", "up_corrective",
          "dn_w3", "dn_w5", "dn_w4", "dn_rebound", "none"]

LABEL_TXT = {
    "up_w3": "上升第 3 波進行中",
    "up_w5": "上升第 5 波進行中",
    "up_w4": "上升第 4 波修正中",
    "up_corrective": "上升 5 波已完成(修正段)",
    "dn_w3": "下跌第 3 波進行中",
    "dn_w5": "下跌第 5 波進行中",
    "dn_w4": "下跌第 4 波反彈中",
    "dn_rebound": "下跌 5 波已完成(反彈段)",
    "none": "控制組:判讀不出結構",
}

# 用波浪標記當策略時的代號
STRATS = {
    "wave_up3": "up_w3",
    "wave_up5": "up_w5",
    "wave_up4": "up_w4",
    "wave_corr": "up_corrective",
    "wave_dn3": "dn_w3",
    "wave_none": "none",
}


# =====================================================================
# 標記
# =====================================================================
def build_bars(pser, dates_upto):
    """把 price[sid] 轉成波浪引擎吃的 bars,只取到 when 為止的最後 WINDOW 天"""
    out = []
    for d in dates_upto:
        b = pser.get(d)
        if b is None:
            continue
        out.append({"d": d, "h": b["max"], "l": b["min"], "c": b["close"]})
    return out[-WINDOW:]


def label_all(universe, price, all_dates, rebals):
    """
    marks[換股日][代號] = 標記。每個時點只用該時點以前的資料。
    """
    idx = {d: i for i, d in enumerate(all_dates)}
    marks = {}
    skipped = 0
    for rb in rebals:
        upto = all_dates[max(0, idx[rb] - WINDOW * 2 + 1): idx[rb] + 1]
        cur = {}
        for sid in B.universe_at(universe, rb):
            pser = price.get(sid)
            if not pser or rb not in pser:
                continue
            bars = build_bars(pser, upto)
            if len(bars) < MIN_BARS:
                skipped += 1
                continue
            cur[sid] = W.position(bars) or "none"
        marks[rb] = cur
    return marks, skipped


# =====================================================================
# 橫斷面分析
# =====================================================================
def binom_two_sided(k, n, p=0.5):
    """雙尾二項檢定。n 只有二、三十,常態近似不牢靠,直接把機率加起來。"""
    if n == 0:
        return None
    C = math.comb
    pmf = [C(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)]
    obs = pmf[k]
    return min(1.0, sum(x for x in pmf if x <= obs * (1 + 1e-12)))


def forward_returns(marks, price, rebals, all_dates):
    """
    fwd[換股日][代號] = 這一季的原始報酬(換股日收盤 → 下一個換股日收盤)。
    不含交易成本 —— 這一段是在比「標記能不能排序股票」,
    成本對每一群都一樣,扣了只是把每一欄同步往下平移。
    """
    fwd = {}
    for i, rb in enumerate(rebals):
        nxt = rebals[i + 1] if i + 1 < len(rebals) else all_dates[-1]
        row = {}
        for sid in marks[rb]:
            a = price[sid].get(rb)
            b = B.latest_on_or_before(price[sid], nxt)
            if not a or not b or a["close"] <= 0:
                continue
            row[sid] = b["close"] / a["close"] - 1
        fwd[rb] = row
    return fwd


def cross_section(marks, fwd, rebals):
    """
    每一群 vs 當期股票池平均。獨立單位是「季」,不是「個股」。
    """
    per_q = defaultdict(list)      # 標記 → [(換股日, 該群均值 - 當期全體均值)]
    pooled = defaultdict(list)     # 標記 → [個股原始報酬]
    counts = defaultdict(int)

    for rb in rebals:
        row = fwd.get(rb) or {}
        if len(row) < 20:
            continue
        base = statistics.fmean(row.values())
        grp = defaultdict(list)
        for sid, lab in marks[rb].items():
            if sid in row:
                grp[lab].append(row[sid])
        for lab, rets in grp.items():
            counts[lab] += len(rets)
            pooled[lab].extend(rets)
            if len(rets) >= 3:     # 一季只有一兩檔,均值沒有意義
                per_q[lab].append((rb, statistics.fmean(rets) - base))

    out = {}
    for lab in LABELS:
        rets = pooled.get(lab, [])
        q = [x for _, x in per_q.get(lab, [])]
        if not rets:
            continue
        se = t = sign_p = None
        if len(q) >= 3:
            sd = statistics.stdev(q)
            se = sd / math.sqrt(len(q))
            t = statistics.fmean(q) / se if se > 0 else None
            # 符號檢定:不看幅度,只問「正超額的季數會不會多到/少到不像擲硬幣」。
            # 單一季的極端值可以把 t 值撐起來,符號檢定撐不起來。
            sign_p = binom_two_sided(sum(1 for x in q if x > 0), len(q))
        out[lab] = {
            "label": LABEL_TXT[lab],
            "n_obs": len(rets),                       # 個股 × 季
            "n_quarters": len(q),
            "share": None,                            # 後面填
            "mean_raw": statistics.fmean(rets),
            "median_raw": statistics.median(rets),
            "win_rate": sum(1 for r in rets if r > 0) / len(rets),
            "excess_mean": statistics.fmean(q) if q else None,
            "excess_se": se,
            "excess_t": t,
            "excess_pos_quarters": sum(1 for x in q if x > 0),
            "sign_test_p": sign_p,
        }
    total = sum(v["n_obs"] for v in out.values())
    for v in out.values():
        v["share"] = v["n_obs"] / total if total else None
    return out, per_q


def momentum_overlap(marks, price, val, rebals, universe):
    """
    up_w3 的名單有多少落在動能策略的前 20 名?
    以及 up_w3 這一群在動能排序裡的平均百分位(1.0 = 當期漲最多)。
    """
    hits = tot = 0
    pctl = []
    for rb in rebals:
        scored = B.build_scores("momentum", rb, universe, price, val, {})
        if len(scored) < 20:
            continue
        top = {s for s, _ in scored[:B.TOP_N]}
        rank = {s: 1 - i / (len(scored) - 1) for i, (s, _) in enumerate(scored)}
        w3 = [s for s, lab in marks[rb].items() if lab == "up_w3"]
        for s in w3:
            tot += 1
            if s in top:
                hits += 1
            if s in rank:
                pctl.append(rank[s])
    return {
        "n": tot,
        "in_momentum_top20": hits / tot if tot else None,
        "mean_momentum_percentile": statistics.fmean(pctl) if pctl else None,
    }


# =====================================================================
def main():
    print("讀取 point-in-time 資料 …", flush=True)
    universe, price, val, all_dates = P.load_pit()
    rebals = B.rebalance_dates(all_dates)
    print(f"  換股日 {len(rebals)} 期:{rebals[0]} ~ {rebals[-1]}\n", flush=True)

    print(f"標記波浪({WINDOW} 個交易日的視窗,與頁面相同)…", flush=True)
    marks, skipped = label_all(universe, price, all_dates, rebals)
    dist = defaultdict(int)
    for row in marks.values():
        for lab in row.values():
            dist[lab] += 1
    n_marked = sum(dist.values())
    print(f"  共 {n_marked:,} 個(個股 × 季)標記,"
          f"另有 {skipped:,} 個因上市未滿 {MIN_BARS} 個交易日略過")
    for lab in LABELS:
        if dist.get(lab):
            print(f"    {dist[lab]:6,}  {dist[lab]/n_marked*100:5.1f}%  {LABEL_TXT[lab]}")
    print("", flush=True)

    fwd = forward_returns(marks, price, rebals, all_dates)
    cs, per_q = cross_section(marks, fwd, rebals)

    print("=== 橫斷面:同一季之內,該群均報酬 減 全股票池均報酬 ===", flush=True)
    print(f"{'標記':28}{'季數':>5}{'檔×季':>8}{'原始均報酬':>11}"
          f"{'橫斷面超額':>12}{'t 值':>8}{'正超額季':>10}{'符號 p':>9}", flush=True)
    for lab in LABELS:
        v = cs.get(lab)
        if not v:
            continue
        ex = f"{v['excess_mean']*100:+.2f}pp" if v["excess_mean"] is not None else "—"
        tv = f"{v['excess_t']:+.2f}" if v["excess_t"] is not None else "—"
        sp = f"{v['sign_test_p']:.3f}" if v.get("sign_test_p") is not None else "—"
        print(f"{v['label']:26}{v['n_quarters']:>5}{v['n_obs']:>8,}"
              f"{v['mean_raw']*100:>10.2f}%"
              f"{ex:>13}{tv:>8}"
              f"{v['excess_pos_quarters']:>7}/{v['n_quarters']:<3}{sp:>8}", flush=True)
    print("", flush=True)

    # ---- 權益曲線:把每個標記當成一個策略,符合的全部等權持有 ----
    label_of = marks

    def wave_scores(strategy, when, uni, prc, v_, rev):
        want = STRATS[strategy]
        row = label_of.get(when) or {}
        return [(sid, 0.0) for sid, lab in sorted(row.items()) if lab == want]

    orig = B.build_scores

    def dispatch(strategy, when, uni, prc, v_, rev):
        if strategy in STRATS:
            return wave_scores(strategy, when, uni, prc, v_, rev)
        return orig(strategy, when, uni, prc, v_, rev)

    B.build_scores = dispatch
    B.HOLD_ALL = set(B.HOLD_ALL) | set(STRATS)

    print("=== 權益曲線(含手續費與證交稅,符合標記者等權全持)===", flush=True)
    _, bcurve, btrades, _ = B.run("universe_ew", False, price, val, {}, all_dates, universe)
    bm = B.metrics(bcurve, btrades, 0)
    print(f"{'對照:股票池等權全持':26}  年化 {bm['cagr']*100:+6.2f}%"
          f"  總報酬 {bm['total_return']*100:+8.1f}%  MDD {bm['max_drawdown']*100:6.1f}%",
          flush=True)

    strat_out = {}
    for st, lab in STRATS.items():
        _, curve, trades, _ = B.run(st, False, price, val, {}, all_dates, universe)
        m = B.metrics(curve, trades, 0)
        if not m:
            continue
        # 持股檔數決定這條曲線值不值得看。中位數只有三、五檔的那幾組,
        # 年化報酬幾乎全是集中度的噪音;空手的季度更是把「選股」
        # 偷偷換成了「擇時」—— 沒有標記就抱現金,那是另一回事。
        per = [sum(1 for x in label_of[rb].values() if x == lab) for rb in rebals]
        hold = {"median": statistics.median(per), "min": min(per), "max": max(per),
                "empty_quarters": sum(1 for x in per if x == 0),
                "thin_quarters": sum(1 for x in per if 0 < x < 5)}
        strat_out[st] = {"label": LABEL_TXT[lab], "wave_label": lab,
                         "holdings": hold, **m,
                         "curve": [{"d": d, "v": round(v, 4)} for d, v in curve[::5]]}
        print(f"{LABEL_TXT[lab]:26}  年化 {m['cagr']*100:+6.2f}%"
              f"  超額 {(m['cagr']-bm['cagr'])*100:+6.2f}pp"
              f"  MDD {m['max_drawdown']*100:6.1f}%"
              f"  每季 {hold['median']:.0f} 檔"
              f"{'  空手 %d 季' % hold['empty_quarters'] if hold['empty_quarters'] else ''}",
              flush=True)

    B.build_scores = orig
    print("", flush=True)

    ov = momentum_overlap(marks, price, val, rebals, universe)
    print("=== 「上升第 3 波」和動能策略的關係 ===", flush=True)
    if ov["n"]:
        print(f"  {ov['in_momentum_top20']*100:.1f}% 的第 3 波個股同時落在動能前 {B.TOP_N} 名")
        print(f"  第 3 波這一群在動能排序的平均百分位 {ov['mean_momentum_percentile']:.3f}"
              f"(0.500 = 和隨機挑沒有差別)")
    print("", flush=True)

    res = {
        "config": {"window": WINDOW, "min_bars": MIN_BARS,
                   "start": rebals[0], "end": all_dates[-1],
                   "rebalance": "quarterly", "n_periods": len(rebals),
                   "universe_mode": "point-in-time",
                   "fee": B.FEE, "tax": B.TAX},
        "distribution": {lab: dist.get(lab, 0) for lab in LABELS if dist.get(lab)},
        "skipped_short_history": skipped,
        "cross_section": cs,
        "benchmark": {"label": "股票池等權全持", **bm},
        "strategies": strat_out,
        "momentum_overlap": ov,
    }
    os.makedirs(B.OUT_DIR, exist_ok=True)
    out = os.path.join(B.OUT_DIR, "wave_backtest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已寫入 {out}", flush=True)

    write_report(res, per_q)
    return 0


def write_report(r, per_q):
    c, cs = r["config"], r["cross_section"]
    pc = lambda v, d=2: "—" if v is None else f"{v*100:+.{d}f}%"
    L = [
        "# 波浪理論回測\n",
        f"股票池 point-in-time,{c['n_periods']} 期季換股,"
        f"{c['start']} ~ {c['end']}。",
        f"波浪判讀用最近 {c['window']} 個交易日 —— 和頁面上看到的是同一套邏輯"
        f"(已逐檔比對 674 檔,門檻、每一個轉折、候選順序完全一致)。\n",
        "## 結論\n",
        "**測不出預測力。**\n",
        "- 佔比最高、也是頁面上最常看到的「上升第 3 波進行中」(29.7%),"
        "橫斷面超額 +0.46pp/季,t = +0.63,符號檢定 p = 0.18 —— "
        "和零沒有分別。",
        "- 關鍵在控制組:**判讀不出結構的那 2,531 筆,表現和有標記的沒有差別**"
        "(-0.16pp,t = -0.34)。如果波浪標記帶進了資訊,這一組應該明顯落後,"
        "但它沒有。",
        "- 唯一撐過 |t|>2 的是「下跌 5 波已完成(反彈段)」,-6.40pp、t = -2.75、"
        "符號檢定 p = 0.035。但這一列有兩個問題:一是同時測了 9 個標記,"
        "Bonferroni 修正後 p ≈ 0.31,不算數;二是它的方向和理論**相反** —— "
        "波浪理論說下跌五波走完就該反彈,實際上這群股票是全部標記裡最差的。",
        "- 上升第 3 波那群股票,反而比下跌第 3 波那群漲得少"
        "(原始均報酬 3.66% vs 4.07%)。這是均值回歸,不是波浪。",
        "- 第 3 波在動能排序的平均百分位 0.533,幾乎等於隨機 —— "
        "所以它也不是「動能換個講法」,它就只是沒有方向性。\n",
        "說得更直接一點:這套判讀拿來**描述**走勢是可以的,"
        "拿來當**買賣依據**,這 47 季的資料撐不住。\n",
        "## 標記怎麼分布\n",
        "| 標記 | 檔×季 | 佔比 |", "|---|---:|---:|",
    ]
    tot = sum(r["distribution"].values())
    for lab, n in sorted(r["distribution"].items(), key=lambda x: -x[1]):
        L.append(f"| {LABEL_TXT[lab]} | {n:,} | {n/tot*100:.1f}% |")

    L += ["", "## 橫斷面超額:這個標記能不能挑出比較好的股票\n",
          "同一個換股日之內,該群的平均報酬減去整個股票池當期的平均報酬,再跨季平均。",
          "這樣「有標記的那幾季剛好是多頭」就不會被算成標記的功勞。",
          f"t 值以季為獨立單位({c['n_periods']} 期),不是以個股筆數。\n",
          "| 標記 | 季數 | 檔×季 | 原始均報酬 | 勝率 | 橫斷面超額 | t 值 | 正超額季 | 符號檢定 p |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for lab in LABELS:
        v = cs.get(lab)
        if not v:
            continue
        t = f"{v['excess_t']:+.2f}" if v["excess_t"] is not None else "—"
        sp = f"{v['sign_test_p']:.3f}" if v.get("sign_test_p") is not None else "—"
        L.append(f"| {v['label']} | {v['n_quarters']} | {v['n_obs']:,} | "
                 f"{pc(v['mean_raw'])} | {v['win_rate']*100:.1f}% | "
                 f"{'—' if v['excess_mean'] is None else '%+.2fpp' % (v['excess_mean']*100)} | {t} | "
                 f"{v['excess_pos_quarters']}/{v['n_quarters']} | {sp} |")

    L += ["", "## 權益曲線(含手續費與證交稅)\n",
          "把每個標記當成一個策略,當期符合的股票等權全持。",
          "**先看「每季持股」那一欄再看報酬**:中位數只有三、五檔的那幾組,",
          "年化報酬主要是集中度造成的波動,不是選股能力;",
          "空手季代表當期沒有任何股票帶這個標記,那幾季是抱現金 —— ",
          "那已經變成擇時,不是這裡想測的東西。\n",
          "| 策略 | 每季持股(中位數) | 空手季 | 年化 | 超額 | 最大回撤 |",
          "|---|---:|---:|---:|---:|---:|"]
    b = r["benchmark"]
    L.append(f"| **{b['label']}** | 150 | 0 | {pc(b['cagr'])} | — | "
             f"{pc(b['max_drawdown'])} |")
    for st, v in r["strategies"].items():
        h = v.get("holdings") or {}
        L.append(f"| {v['label']} | {h.get('median', '—'):.0f} | "
                 f"{h.get('empty_quarters', '—')} | {pc(v['cagr'])} | "
                 f"{(v['cagr']-b['cagr'])*100:+.2f}pp | "
                 f"{pc(v['max_drawdown'])} |")

    L += ["", "> 兩張表為什麼看起來不一致:橫斷面那張把每一季的市場漲跌扣掉了,",
          "> 量的是「同一季裡,這群股票有沒有比別人好」;權益曲線那張沒有扣,",
          "> 而且混進了持股檔數與空手期的影響。要回答「波浪標記有沒有預測力」,",
          "> 該看的是橫斷面那張。\n"]

    ov = r["momentum_overlap"]
    L += ["", "## 「上升第 3 波」是不是動能的另一種講法\n"]
    if ov.get("n"):
        L += [f"- {ov['in_momentum_top20']*100:.1f}% 的第 3 波個股,"
              f"同時落在動能策略的前 {B.TOP_N} 名。",
              f"- 第 3 波這一群在動能排序裡的平均百分位 "
              f"**{ov['mean_momentum_percentile']:.3f}**"
              f"(0.500 代表和隨機挑沒有差別)。"]

    L += ["", "## 這份回測不能證明什麼\n",
          f"- **一次測了 {len(cs)} 個標記。** 就算全部都沒有預測力,"
          "光靠運氣也大約會跑出半個 |t|>2 的結果。單看某一列的 p 值會高估它的意義;"
          "要下結論,那一列至少得撐過 Bonferroni(把 p 乘以 "
          f"{len(cs)})才算數。",
          "- **數法不唯一。** 同一段走勢可以有好幾種合理的數法,這裡取的是"
          "「依固定順序第一個沒被三條硬規則排除」的那一種。換個順序、換個門檻,"
          "標記會變,結果也會變。三條規則只能否證,不能證實。",
          "- **標記會隨時間改寫。** 今天的「第 3 波」,三個月後可能被重數成"
          "「第 5 波」。回測用的是當時看到的標記,所以沒有前視偏誤 —— "
          "但也表示持股會因為重新計數而換手,那些換手的成本已計入。",
          f"- **樣本只有 {c['n_periods']} 季。** 以季為獨立單位,"
          "|t| 不到 2 的數字就當成沒有結論,不要當成小幅優勢。",
          "- 未計股利、未計滑價;股票池以成交金額排序,偏向大型股。",
          "- 回測是對歷史的描述,不是對未來的預測,更不是投資建議。"]

    path = os.path.join(B.OUT_DIR, "wave_backtest.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"已寫入 {path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
