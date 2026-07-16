from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    action: Action
    confidence: float
    reason: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if not self.reason:
            raise ValueError("signal reason is required")
        for name, value in (("stop_loss", self.stop_loss), ("take_profit", self.take_profit)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")


class Strategy(ABC):
    strategy_id: str
    version: str = "1"

    @abstractmethod
    def generate(self, candles: pd.DataFrame) -> Signal:
        """Generate a signal using only the supplied historical window."""

    def __call__(self, candles: pd.DataFrame) -> Signal:
        return self.generate(candles)
