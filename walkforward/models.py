from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardConfig:
    train_size: int = 500
    validation_size: int = 200
    test_size: int = 200
    step_size: int = 200

    def __post_init__(self):
        if min(self.train_size, self.validation_size, self.test_size, self.step_size) <= 0:
            raise ValueError("walk-forward window sizes must be positive")


@dataclass(frozen=True)
class QualificationRules:
    minimum_oos_trades: int = 5
    minimum_profit_factor: float = 1.0
    maximum_drawdown_pct: float = 20.0
    maximum_losing_window_pct: float = 50.0
    maximum_degradation_pct: float = 50.0

    def __post_init__(self):
        if self.minimum_oos_trades < 0 or self.minimum_profit_factor < 0:
            raise ValueError("trade and profit-factor thresholds must be non-negative")
        if not 0 <= self.maximum_losing_window_pct <= 100:
            raise ValueError("maximum_losing_window_pct must be in [0, 100]")
