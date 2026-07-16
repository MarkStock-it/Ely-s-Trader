from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Candle:
    timestamp: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class BacktestConfig:
    strategy: str = "macd"
    strategy_version: str = "1"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    starting_balance: float = 10000.0
    fee_rate: float = 0.001
    spread_rate: float = 0.0002
    slippage_rate: float = 0.0005
    latency_candles: int = 0
    risk_fraction: float = 1.0
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    minimum_position_size: float = 0.0
    random_seed: Optional[int] = None
    intrabar_policy: str = "stop_first"

    def __post_init__(self):
        if self.starting_balance <= 0 or not 0 < self.risk_fraction <= 1:
            raise ValueError("starting_balance must be positive and risk_fraction in (0, 1]")
        if any(x < 0 for x in (self.fee_rate, self.spread_rate, self.slippage_rate, self.minimum_position_size)):
            raise ValueError("cost rates and minimum position size must be non-negative")
        if self.latency_candles < 0:
            raise ValueError("latency_candles must be non-negative")
        if self.intrabar_policy != "stop_first":
            raise ValueError("Only the conservative stop_first intrabar policy is supported")


@dataclass
class Trade:
    strategy: str
    symbol: str
    timeframe: str
    entry_timestamp: Any
    exit_timestamp: Any
    entry_market_price: float
    entry_fill_price: float
    exit_market_price: float
    exit_fill_price: float
    quantity: float
    entry_fee: float
    exit_fee: float
    gross_profit: float
    net_profit: float
    return_percentage: float
    holding_duration: float
    entry_reason: str
    exit_reason: str
    market_regime: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class BacktestResult:
    config: BacktestConfig
    metrics: Dict[str, Any]
    trades: List[Trade]
    equity: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {"configuration": asdict(self.config), "metrics": self.metrics,
                "trades": [t.to_dict() for t in self.trades], "equity": self.equity,
                "metadata": self.metadata}

    @staticmethod
    def executed_at():
        return datetime.now(timezone.utc).isoformat()
