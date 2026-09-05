"""集中管理回測參數的設定檔。所有可調整的策略參數都放這裡，不要散落在程式各處。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactorWeights:
    """各因子在複合分數中的權重，總和不需要為 1（會在計算時自動處理），設 0 代表停用該因子。"""

    earnings_yield: float = 1.0       # 價值：1/PE，越高越好
    book_to_price: float = 1.0        # 價值：1/PB，越高越好
    dividend_yield: float = 1.0       # 價值：股息殖利率，越高越好
    roe: float = 1.0                  # 品質：股東權益報酬率，越高越好
    gross_margin: float = 0.5         # 品質：毛利率，越高越好
    debt_to_equity: float = -0.5      # 品質：負債權益比，越低越好（權重為負代表反向）
    revenue_growth_yoy: float = 1.0   # 成長：月營收年增率，越高越好
    eps_growth_yoy: float = 0.5       # 成長：EPS 年增率，越高越好
    momentum_12_1: float = 1.0        # 動能：12-1 月報酬，越高越好
    low_volatility: float = 0.5       # 低波動：60 日年化波動度反向，越低波動分數越高
    institutional_net_buy: float = 0.0  # 籌碼：三大法人近20日買賣超占成交量比例（預設停用）


@dataclass
class BacktestConfig:
    start_date: str = "2015-01-01"
    end_date: str = "2024-12-31"

    universe: list[str] = field(default_factory=lambda: [
        # 預設母體：台灣 0050 成分股常客，示範用，實務上建議改用完整上市櫃清單並做流動性篩選
        "2330", "2317", "2454", "2308", "2382", "2412", "2881", "2882",
        "1301", "1303", "2002", "2891", "3711", "2886", "2884", "5880",
        "1216", "2892", "3034", "2379",
    ])
    benchmark: str = "0050"  # 對照基準（元大台灣50 ETF）

    rebalance_freq: str = "M"       # "M" 月頻 / "Q" 季頻
    top_n: int = 10                 # 每期選幾檔
    defensive_top_n: int = 5        # 總經濾網觸發防禦模式時，選股檔數下修為多少
    macro_defensive_threshold: float = -1.0  # macro_score 低於此值視為防禦模式

    stop_loss_pct: float = 0.20     # 停損百分比（相對買進成本價）
    min_holding_days_before_stop: int = 1  # 買進後至少持有幾天才啟用停損判斷，避免當沖式雜訊

    buy_commission_rate: float = 0.0855e-2   # 台股買進手續費（0.1425% * 0.6 折，可自行調整）
    sell_commission_rate: float = 0.0855e-2  # 台股賣出手續費
    sell_tax_rate: float = 0.30e-2           # 台股證券交易稅（賣出時課徵）

    risk_free_rate_annual: float = 0.012     # 年化無風險利率假設（可用台灣一年期定存利率替代）

    factor_weights: FactorWeights = field(default_factory=FactorWeights)

    min_avg_daily_turnover: float = 5_000_000  # 最低近20日平均成交金額（元），流動性篩選
