"""
艾略特波浪的機械式判讀 —— 與 docs/index.html 的 JS 版本同一套邏輯。

回測的前提:不能偷看未來
------------------------
ZigZag 的轉折點是「事後」才確認的:某個高點要等價格反轉超過門檻,才算數。
這裡的實作只在反轉真的發生時才把轉折推入清單,所以在時點 t 呼叫時,
拿到的轉折只依賴 t 以前的資料 —— 沒有前視偏誤。

但要注意一件事:同一段走勢在 t 的標記,和在 t+90 天回頭看的標記,可能不同。
那不是 bug,是波浪理論本身的性質。回測必須用「當時看到的標記」,
不能用今天回頭看的結果 —— 後者會讓任何波浪策略都變得神準。

三條硬規則(規則,不是指引)
  R1  第 2 波不會回到第 1 波的起點以下
  R2  第 3 波不會是 1、3、5 之中最短的一段
  R3  第 4 波不會跌進第 1 波的價格區間
規則只能否證,不能證實。
"""

LEVEL_MIN, LEVEL_MAX = 0.05, 0.15


def zigzag(bars, pct):
    """
    bars 為 [{d,h,l,c}, …](需已按日期遞增)。回傳已確認的轉折
    [{i, p, t}],t 為 'H'/'L'。最後一個未被反轉確認的極值另外回傳。

    方向未定時必須同時追蹤最高與最低兩個候選:用同一個變數輪流存會
    互相覆蓋,每天先被設成當日高、再被設成當日低,累積不出任何極值。
    """
    piv = []
    if len(bars) < 3:
        return piv, None
    hi_i, hi_p = 0, bars[0]["h"]
    lo_i, lo_p = 0, bars[0]["l"]
    direction = 0
    for i in range(1, len(bars)):
        hi, lo = bars[i]["h"], bars[i]["l"]
        if direction >= 0 and hi > hi_p:
            hi_p, hi_i = hi, i
        if direction <= 0 and lo < lo_p:
            lo_p, lo_i = lo, i
        if direction != -1 and lo <= hi_p * (1 - pct):
            piv.append({"i": hi_i, "p": hi_p, "t": "H"})
            direction, lo_p, lo_i = -1, lo, i
        elif direction != 1 and hi >= lo_p * (1 + pct):
            piv.append({"i": lo_i, "p": lo_p, "t": "L"})
            direction, hi_p, hi_i = 1, hi, i
    tentative = ({"i": hi_i, "p": hi_p, "t": "H"} if direction >= 0
                 else {"i": lo_i, "p": lo_p, "t": "L"})
    return piv, tentative


def threshold(bars, window=120):
    """門檻依真實區間自動調整:高波動的股票需要更大的門檻才不會把雜訊當轉折"""
    n = min(window, len(bars) - 1)
    if n < 20:
        return 0.08
    total = 0.0
    for i in range(len(bars) - n, len(bars)):
        prev_c = bars[i - 1]["c"]
        tr = max(bars[i]["h"] - bars[i]["l"],
                 abs(bars[i]["h"] - prev_c), abs(bars[i]["l"] - prev_c))
        total += tr / bars[i]["c"] if bars[i]["c"] else 0
    return min(LEVEL_MAX, max(LEVEL_MIN, total / n * 4))


def _alternates(points, up):
    """檢查高低是否交替:第 1、3、5… 段往 up 的方向走"""
    for k in range(1, len(points)):
        rising = points[k]["p"] > points[k - 1]["p"]
        if rising != (up if k % 2 == 1 else not up):
            return False
    return True


def _impulse_rules(pts, up):
    sgn = 1 if up else -1
    w1 = abs(pts[1]["p"] - pts[0]["p"])
    w3 = abs(pts[3]["p"] - pts[2]["p"])
    w5 = abs(pts[5]["p"] - pts[4]["p"])
    return [
        ("R1", sgn * (pts[2]["p"] - pts[0]["p"]) > 0),
        ("R2", not (w3 < w1 and w3 < w5)),
        ("R3", sgn * (pts[4]["p"] - pts[1]["p"]) > 0),
    ]


def label(bars):
    """
    回傳目前落在哪一段的候選清單,每項為
      {"wave": 名稱, "up": 方向, "ok": 三條規則是否都通過}
    依 ok 排序,第一項是「還沒被排除」的那個數法。
    """
    pct = threshold(bars)
    conf, _tent = zigzag(bars, pct)
    out = {"pct": pct, "pivots": len(conf), "candidates": []}
    if len(conf) < 3:
        return out

    last = bars[-1]["c"]
    cur = {"i": len(bars) - 1, "p": last}
    tail = conf[-6:]

    def add(wave, up, pts, rules):
        out["candidates"].append({
            "wave": wave, "up": up, "ok": all(ok for _, ok in rules),
            "rules": rules,
        })

    # 完整 5 波已走完,目前在其後的修正
    if len(tail) >= 6:
        p6 = tail[-6:]
        up = p6[1]["p"] > p6[0]["p"]
        if _alternates(p6, up):
            add("corrective" if up else "rebound", up, p6, _impulse_rules(p6, up))
    # 進行中的第 5 波
    if len(tail) >= 5:
        p5 = tail[-5:]
        up = p5[1]["p"] > p5[0]["p"]
        pts = p5 + [dict(cur, t="H" if up else "L")]
        if _alternates(pts, up):
            add("w5", up, pts, _impulse_rules(pts, up))
    # 進行中的第 4 波(修正)
    if len(tail) >= 4:
        p4 = tail[-4:]
        up = p4[1]["p"] > p4[0]["p"]
        seq = p4 + [dict(cur, t="L" if up else "H")]
        if _alternates(seq, up):
            sgn = 1 if up else -1
            add("w4", up, seq, [
                ("R1", sgn * (p4[2]["p"] - p4[0]["p"]) > 0),
                ("R3", sgn * (cur["p"] - p4[1]["p"]) > 0),
            ])
    # 進行中的第 3 波
    if len(tail) >= 3:
        p3 = tail[-3:]
        up = p3[1]["p"] > p3[0]["p"]
        seq = p3 + [dict(cur, t="H" if up else "L")]
        if _alternates(seq, up):
            sgn = 1 if up else -1
            add("w3", up, seq, [("R1", sgn * (p3[2]["p"] - p3[0]["p"]) > 0)])

    out["candidates"].sort(key=lambda c: not c["ok"])
    return out


def position(bars):
    """把判讀壓成一個標籤,給回測用。沒有未被排除的數法就回 None。"""
    r = label(bars)
    for c in r["candidates"]:
        if c["ok"]:
            return ("up_" if c["up"] else "dn_") + c["wave"]
    return None
