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
class FactorWindows:
    """動能/波動度因子的回看窗口（交易日）。長期策略適合用長窗口濾掉雜訊，短期策略要縮短
    窗口才能捕捉到半年內的訊號，因此拆成獨立設定，不寫死在 factors.py 裡。"""

    momentum_lookback_days: int = 252  # 動能因子的回看天數（長期預設：12個月）
    momentum_skip_days: int = 21       # 動能因子排除最近幾天，避開短期反轉（長期預設：1個月）
    volatility_window_days: int = 60   # 波動度因子的滾動窗口天數


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

    rebalance_freq: str = "M"       # "W" 週頻 / "M" 月頻 / "Q" 季頻
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
    factor_windows: FactorWindows = field(default_factory=FactorWindows)

    min_avg_daily_turnover: float = 5_000_000  # 最低近20日平均成交金額（元），流動性篩選


def long_term_config() -> BacktestConfig:
    """長期投資策略預設（持有期以年計）：重價值+品質+股息，弱化動能，季頻再平衡降低周轉率
    與稅費侵蝕，核心邏輯對應 RESEARCH.md 的溫國信/陳重銘存股法 + 價值/品質量化因子。
    """
    cfg = BacktestConfig()
    cfg.rebalance_freq = "Q"
    cfg.top_n = 15                    # 分散持股，降低單一個股風險
    cfg.defensive_top_n = 8
    cfg.min_holding_days_before_stop = 10  # 長期策略不理會短期雜訊型下殺，避免頻繁被停損洗出場
    cfg.factor_windows = FactorWindows(
        momentum_lookback_days=252, momentum_skip_days=21, volatility_window_days=60,
    )
    cfg.factor_weights = FactorWeights(
        earnings_yield=1.0, book_to_price=1.0, dividend_yield=1.5,
        roe=1.5, gross_margin=0.5, debt_to_equity=-0.5,
        revenue_growth_yoy=0.5, eps_growth_yoy=0.5,
        momentum_12_1=0.3, low_volatility=0.5, institutional_net_buy=0.0,
    )
    return cfg


def short_term_config() -> BacktestConfig:
    """短期投資策略預設（持有期以月計，鎖定半年內）：重動能+營收動能+籌碼，弱化長期價值面，
    週頻再平衡、縮短動能/波動度回看窗口，才能捕捉半年內的訊號並即時反應停損。
    """
    cfg = BacktestConfig()
    cfg.rebalance_freq = "W"
    cfg.top_n = 6                     # 集中持股，追求短期超額報酬，波動也會較大
    cfg.defensive_top_n = 3
    cfg.min_holding_days_before_stop = 1  # 短線策略要能快速停損，不設緩衝期
    cfg.factor_windows = FactorWindows(
        momentum_lookback_days=60, momentum_skip_days=5, volatility_window_days=20,
    )
    cfg.factor_weights = FactorWeights(
        earnings_yield=0.3, book_to_price=0.2, dividend_yield=0.2,
        roe=0.5, gross_margin=0.2, debt_to_equity=-0.2,
        revenue_growth_yoy=1.5, eps_growth_yoy=0.5,
        momentum_12_1=1.5, low_volatility=0.2, institutional_net_buy=1.0,
    )
    return cfg
