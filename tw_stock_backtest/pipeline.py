"""把使用者提供的加密貨幣槓桿交易系統（多階段 LLM 決策鏈：情緒→技術→決策→報告→下單）
改寫成台股版本的每日選股決策管線。

對照表（原始加密貨幣設計 -> 這裡的台股改寫）：

| 原始 Block                          | 台股改寫                                                    |
|-------------------------------------|--------------------------------------------------------------|
| SentimentBlock（FG逆向指標+幣種輪動+BTC主導率） | MacroBlock + RegimeBlock：總經燈號 + 用真實資料驗證過的多空週期分類 |
| TechnicalBlock（威科夫階段+SMC結構，兩個LLM）    | FactorBlock：factors.composite_score() 因子排名             |
| DecisionBlock（硬性否決→數學計算→分類→LLM裁決）  | DecisionBlock：同樣三層，但裁決層是純規則，不是 LLM           |
| VerdictBlock（LLM寫中文報告）             | ReportBlock：格式化中文報告（純樣板，不需要 LLM）              |
| ExecutionBlock（自動下單）                | OrderSheetBlock：只產生建議清單，**不自動下單**               |

**理論 / 訊號 / 執行三層解耦**（對應「decouple 理論、訊號、策略執行」的要求）：
  - **理論層**（`regime.py`）：只回答「現在是 BULL/BEAR/SIDEWAYS 哪個週期、有沒有轉空頭警訊」，
    完全不知道任何個股或因子的存在。這裡的週期分類與「哪個週期該傾向哪個因子」都是用真實資料
    （711檔 point-in-time 台股，2014-2026）反覆驗證過的結果，不是憑感覺假設。
  - **訊號層**（`factors.py`）：只負責「給定一組權重，算出每檔股票的複合分數」，不知道現在
    是什麼週期，也不知道分數算出來之後會拿去做什麼決策——理論層透過 `ctx.factor_weights`
    把「這個週期該強調什麼」傳給訊號層，訊號層不需要認識 `regime.py`。
  - **執行層**（`DecisionBlock` / `OrderSheetBlock`）：只負責「給定分數，該不該進場、進多少、
    停損停利設哪裡」，不知道分數是怎麼算出來的。

三個刻意的設計差異，及原因：

1. **執行頻率**：原系統每小時跑一次；台股基本面/營收資訊本來就是日頻以下更新，這裡改成
   「每個交易日收盤後」跑一次，沒有小時級的必要。
2. **判斷邏輯換成已驗證的規則，不是新的 LLM 判斷**：原系統靠三個 LLM（情緒模型、技術模型、
   裁決模型）做定性判斷。這裡沒有導入新的、未經驗證的 AI 判斷邏輯——FactorBlock 用的
   `revenue_yoy_accel + momentum_12_1` 組合，是全對話過程中唯一撐過訓練期/驗證期/測試期
   三段樣本外驗證的因子組合（見 RESEARCH.md「反向推論」章節，測試期勝率 63.6%、真正歸因於
   選股的超額只有 +2.2 個百分點）。換句話說：架構模仿了對方的多階段風控設計，但決策內容
   全部誠實地建立在我們自己已經驗證過的基礎上，不會為了「看起來更像那套系統」而加入沒驗證
   過的技術面判斷（例如威科夫階段、SMC結構在台股完全沒有驗證過，故意沒有照抄）。
3. **沒有槓桿**：台股現貨不開槓桿（融資融券是另一回事，這裡沒有支援），原系統的「信心度→
   槓桿倍數」改成「信心度→部位權重（0% / 50% / 100%）」，風險分級的精神一樣，但不會放大
   虧損倍數。
4. **不會自動下單**：OrderSheetBlock 只產生建議買賣清單，不接券商 API。要接自動下單是完全
   不同等級的風險（金錢直接曝險、程式bug可能直接虧真錢），需要另外明確確認才會實作。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import factors as F
from . import macro as M
from . import regime as R
from .config import BacktestConfig, FactorWeights

EXTREME_MACRO_THRESHOLD = -2.0  # 總經分數低於此值視為「極端崩盤」；尚未用真實總經資料校準
# 這個門檻是唯一還沒能用真實資料驗證的數字——本環境拿不到真實總經歷史序列（見 README「網路
# 限制」一節），只能先沿用一個看起來合理的量級，等真的接上真實資料後，應該改成用歷史
# macro_score 分布的後段百分位（例如最差10%）校準，而不是繼續憑感覺猜一個值。


@dataclass
class StockDecision:
    ticker: str
    score: float
    regime: str               # 決策當下的市場週期："BULL" | "SIDEWAYS" | "BEAR" | "UNKNOWN"
    position_weight: float    # 0.0 ~ 1.0，取代原系統的槓桿倍數，見 regime.POSITION_WEIGHT_BY_REGIME
    entry: float
    stop: float
    target: float | None      # 僅供參考的技術面壓力位（52週高點），不是任何形式的報酬保證
    risk_reward: float | None  # 僅供參考，不是否決依據（見 DecisionBlock 開頭的說明）
    veto_reason: str | None = None


@dataclass
class MarketContext:
    """對應原系統的 ctx（病歷表）：每個 Block 把自己的結果寫進來，傳給下一個 Block。"""
    as_of_date: pd.Timestamp
    macro_score: float = float("nan")
    macro_regime: str = "UNKNOWN"          # "TAILWIND" | "HEADWIND" | "EXTREME_DEFENSIVE"
    market_regime: str = "UNKNOWN"         # "BULL" | "BEAR" | "SIDEWAYS"（理論層：regime.py）
    bear_warning: bool = False              # 波動度+動能是否已出現轉空頭前兆（見 regime.py）
    factor_weights: FactorWeights = field(default_factory=FactorWeights)  # 理論層傳給訊號層
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)
    decisions: list[StockDecision] = field(default_factory=list)
    report_text: str = ""
    order_sheet: pd.DataFrame = field(default_factory=pd.DataFrame)
    halted: bool = False
    halt_reason: str | None = None


class MacroBlock:
    """對應 SentimentBlock：不用 LLM 判斷情緒，直接用 macro.py 算出的總經燈號分數當市場背景。"""

    def run(self, ctx: MarketContext, macro_df: pd.DataFrame) -> MarketContext:
        macro_score_series = M.compute_macro_score(macro_df)
        score = macro_score_series.get(ctx.as_of_date, 0.0)
        if pd.isna(score):
            score = 0.0
        ctx.macro_score = float(score)
        if ctx.macro_score <= EXTREME_MACRO_THRESHOLD:
            ctx.macro_regime = "EXTREME_DEFENSIVE"
        elif ctx.macro_score < 0:
            ctx.macro_regime = "HEADWIND"
        else:
            ctx.macro_regime = "TAILWIND"
        return ctx


class RegimeBlock:
    """理論層：只回答「現在是什麼市場週期」，完全不認識任何個股或因子，
    也不知道 FactorBlock/DecisionBlock 會怎麼使用這個結論——這正是「decouple 理論/訊號/
    策略執行」的意思：這裡只負責判斷週期、並把「這個週期該傾向哪些因子」寫進 ctx，
    至於因子分數怎麼算、算完之後買不買，都不是這個 Block 該管的事。

    週期分類與因子傾斜的實測依據見 regime.py 模組開頭的說明。
    """

    def run(self, ctx: MarketContext, config: BacktestConfig, prices: pd.DataFrame) -> MarketContext:
        index = R.market_proxy_index(prices)
        regime_series = R.classify_regime(index)
        ctx.market_regime = regime_series.get(ctx.as_of_date, "UNKNOWN")
        if pd.isna(ctx.market_regime):
            ctx.market_regime = "UNKNOWN"
        ctx.bear_warning = R.bear_transition_warning(index, ctx.as_of_date)

        tilted = copy.deepcopy(config.factor_weights)
        for field_name, multiplier in R.FACTOR_TILTS_BY_REGIME.get(ctx.market_regime, {}).items():
            if hasattr(tilted, field_name):
                setattr(tilted, field_name, getattr(tilted, field_name) * multiplier)
        ctx.factor_weights = tilted
        return ctx


class FactorBlock:
    """訊號層：只負責「給定一組因子權重，算出每檔股票的複合分數」，不知道現在是什麼市場
    週期、也不知道分數算出來後會被拿去做什麼決策——權重由理論層（RegimeBlock）透過
    `ctx.factor_weights` 傳進來，這裡完全不 import regime.py。
    """

    def run(self, ctx: MarketContext, config: BacktestConfig,
            prices: pd.DataFrame, fundamentals: pd.DataFrame) -> MarketContext:
        price_factors = F.build_price_factors(prices, config.factor_windows)
        fund_factors = F.build_fundamental_factors(fundamentals)
        tickers = list(prices["ticker"].unique())
        snapshot = F.as_of_snapshot(price_factors, fund_factors, ctx.as_of_date, tickers)
        if snapshot.empty:
            ctx.halted = True
            ctx.halt_reason = "候選股清單為空（NO_SETUP）：沒有任何股票在這天有價格資料。"
            return ctx
        snapshot["score"] = F.composite_score(snapshot, ctx.factor_weights)
        latest_close = prices[prices["date"] <= ctx.as_of_date].sort_values("date").groupby("ticker").tail(1)
        snapshot = snapshot.merge(latest_close[["ticker", "close"]], on="ticker", how="left")
        ctx.candidates = snapshot.sort_values("score", ascending=False)
        return ctx


class DecisionBlock:
    """對應 DecisionBlock：硬性否決 -> MathEngine(進場/止損) -> 部位權重。

    **這裡曾經有一版「風報比 RR>=1.5 否決 + 用停損反推目標價」的邏輯，已經拿掉**：
    `config.validated_momentum_revenue_config()` 真正驗證過的策略就是「因子分數選前N檔、
    進場、-20%停損」，沒有風報比門檻、也沒有目標價這件事。原本那組 RR 門檻是照抄加密貨幣
    系統的結構、從沒拿台股資料驗證過會不會反而濾掉本來就有效的訊號（先射箭再畫靶：目標價
    是用停損距離反推出來湊出 RR>=1.5，不是先預期股票會漲到哪裡），等於是拿一個沒驗證過的
    過濾器蓋在已驗證的策略上面——這正是需要修正的「不合理之處」。現在的做法：52週高點
    只當「僅供參考」的技術位階顯示在報告裡，不會否決任何訊號；裁決層唯一的否決依據是
    流動性（已經在 top_n 篩選時處理）與總經硬性否決，不會另外發明新的門檻。

    部位權重也不再是憑感覺定的 100%/75%/50% 三檔，改用 `regime.POSITION_WEIGHT_BY_REGIME`——
    RESEARCH.md 第七節實測出的、依市場週期而異的真實超額勝率換算出來的權重，並在總經逆風
    或已現轉空頭前兆時額外打對折（這是獨立於「哪個週期」之外的第二層風險訊號，兩者不應該
    被合併成同一個判斷）。
    """

    DEFENSIVE_HAIRCUT = 0.6  # 總經逆風或轉空頭前兆時，部位權重額外乘上的折扣係數

    def run(self, ctx: MarketContext, config: BacktestConfig, prices: pd.DataFrame) -> MarketContext:
        # Step 1：硬性否決（比照原系統 FG<=5 / NO_SETUP / NEUTRAL 三種直接 WAIT 的情況）
        if ctx.halted:
            return ctx
        if ctx.macro_regime == "EXTREME_DEFENSIVE":
            ctx.halted = True
            ctx.halt_reason = (
                f"總經燈號極端轉差（macro_score={ctx.macro_score:.2f} <= {EXTREME_MACRO_THRESHOLD}），"
                "比照原系統「FG<=5 極端崩盤直接 WAIT」的邏輯，今天不建議進場。"
            )
            return ctx

        candidates = ctx.candidates.dropna(subset=["score", "close"])
        if candidates.empty:
            ctx.halted = True
            ctx.halt_reason = "所有候選股都缺少必要資料（NO_SETUP）。"
            return ctx

        # 總經逆風，或者價格面已經出現「轉空頭前兆」（波動度暴衝+動能轉負，見 regime.py），
        # 兩者任一成立就先轉防禦模式——後者是價格面的早期警報，往往比總經數據更新更快。
        defensive = ctx.macro_regime == "HEADWIND" or ctx.bear_warning
        top_n = config.defensive_top_n if defensive else config.top_n
        candidates = candidates[candidates["avg_turnover_20d"].fillna(0) >= config.min_avg_daily_turnover]
        candidates = candidates.head(top_n)

        resistance_by_ticker = (
            prices[prices["date"] <= ctx.as_of_date]
            .sort_values("date").groupby("ticker")["close"]
            .apply(lambda s: s.tail(250).max())
        )

        base_weight = R.POSITION_WEIGHT_BY_REGIME.get(ctx.market_regime, R.DEFAULT_POSITION_WEIGHT)
        weight = base_weight * self.DEFENSIVE_HAIRCUT if defensive else base_weight

        for _, row in candidates.iterrows():
            entry = float(row["close"])
            stop = entry * (1 - config.stop_loss_pct)

            # Step 2：MathEngine —— 52週高點僅供參考顯示，不影響任何進出場判斷（見上方說明）。
            resistance = resistance_by_ticker.get(row["ticker"], np.nan)
            target = float(resistance) if pd.notna(resistance) else None
            risk = entry - stop
            rr = (target - entry) / risk if (target is not None and risk > 0) else None

            ctx.decisions.append(StockDecision(
                ticker=row["ticker"], score=float(row["score"]),
                regime=ctx.market_regime, position_weight=round(weight, 4),
                entry=entry, stop=stop, target=target, risk_reward=rr,
            ))

        if not ctx.decisions:
            ctx.halted = True
            ctx.halt_reason = "所有候選股都缺少必要資料或未通過流動性篩選，今天沒有建議標的。"
        return ctx


class ReportBlock:
    """對應 VerdictBlock：純樣板產生中文報告，不需要 LLM。"""

    def run(self, ctx: MarketContext) -> MarketContext:
        lines = [f"===== 台股每日選股報告 {ctx.as_of_date.date()} =====",
                 f"總經背景：{ctx.macro_regime}（macro_score={ctx.macro_score:.2f}）",
                 f"市場週期：{ctx.market_regime}" + ("　⚠ 轉空頭前兆已出現（波動度暴衝+動能轉負）"
                                                    if ctx.bear_warning else "")]
        if ctx.halted:
            lines.append(f"今天不建議任何進場：{ctx.halt_reason}")
            ctx.report_text = "\n".join(lines)
            return ctx

        lines.append(f"\n入選 {len(ctx.decisions)} 檔：\n")
        for d in sorted(ctx.decisions, key=lambda x: -x.score):
            target_str = f"{d.target:.2f}（風報比僅供參考={d.risk_reward:.2f}）" if d.target is not None else "無52週高點資料"
            lines.append(
                f"[{d.ticker}] 分數={d.score:+.2f} 週期={d.regime} 部位權重={d.position_weight:.0%}\n"
                f"    進場={d.entry:.2f}  停損={d.stop:.2f}（-{(1 - d.stop / d.entry):.1%}）  "
                f"參考壓力位={target_str}"
            )
        lines.append(
            "\n提醒：這是根據已驗證因子組合產生的建議清單，不是自動下單，"
            "也不是任何形式的投資建議；真實勝率天花板約55~65%，請自行決定是否採用、如何控管風險。"
        )
        ctx.report_text = "\n".join(lines)
        return ctx


class OrderSheetBlock:
    """對應 ExecutionBlock：只產生「建議買賣清單」的結構化資料，不接券商 API、不自動下單。"""

    def run(self, ctx: MarketContext) -> MarketContext:
        if ctx.halted or not ctx.decisions:
            ctx.order_sheet = pd.DataFrame(columns=[
                "ticker", "action", "regime", "position_weight",
                "entry", "stop", "target", "risk_reward",
            ])
            return ctx
        ctx.order_sheet = pd.DataFrame([{
            "ticker": d.ticker, "action": "BUY", "regime": d.regime,
            "position_weight": d.position_weight, "entry": round(d.entry, 2),
            "stop": round(d.stop, 2),
            "target": round(d.target, 2) if d.target is not None else None,
            "risk_reward": round(d.risk_reward, 2) if d.risk_reward is not None else None,
        } for d in ctx.decisions])
        return ctx


def run_pipeline(config: BacktestConfig, prices: pd.DataFrame, fundamentals: pd.DataFrame,
                  macro_df: pd.DataFrame, as_of_date: pd.Timestamp) -> MarketContext:
    """串起六個 Block，等同原系統的主循環（這裡是單次快照，不是每小時輪詢）。

    執行順序即理論/訊號/執行的資料流向：MacroBlock + RegimeBlock（理論層，判斷背景與
    決定因子傾斜）-> FactorBlock（訊號層，純粹依權重算分數）-> DecisionBlock/ReportBlock/
    OrderSheetBlock（執行層，依分數決定買不買、買多少、風控怎麼設）。
    """
    ctx = MarketContext(as_of_date=pd.Timestamp(as_of_date))
    ctx = MacroBlock().run(ctx, macro_df)
    ctx = RegimeBlock().run(ctx, config, prices)
    ctx = FactorBlock().run(ctx, config, prices, fundamentals)
    ctx = DecisionBlock().run(ctx, config, prices)
    ctx = ReportBlock().run(ctx)
    ctx = OrderSheetBlock().run(ctx)
    return ctx
