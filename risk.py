"""Portfolio-level entry guards shared by the running bot."""
from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = "OK"


def position_risk(entry: float, stop: float, quantity: float) -> float:
    return abs(float(entry) - float(stop)) * float(quantity)


def cap_quantity(quantity: float, cash: float, price: float, fee_rate: float,
                 max_position_fraction: float = 1.0, exchange_max: float | None = None) -> float:
    affordable = cash * max_position_fraction / (price * (1 + fee_rate))
    result = min(float(quantity), affordable)
    if exchange_max is not None and float(exchange_max) > 0:
        result = min(result, float(exchange_max))
    return max(0.0, result)


def entry_guard(*, equity: float, initial_equity: float, day_start_equity: float,
                proposed_risk: float, existing_risks: Iterable[float], cfg) -> RiskDecision:
    daily_limit = float(cfg.get("DAILY_LOSS_LIMIT", 0.03))
    drawdown_limit = float(cfg.get("MAX_DRAWDOWN", 0.15))
    aggregate_limit = float(cfg.get("MAX_AGGREGATE_RISK", 0.03))
    if day_start_equity > 0 and equity <= day_start_equity * (1 - daily_limit):
        return RiskDecision(False, "daily loss limit reached")
    if initial_equity > 0 and equity <= initial_equity * (1 - drawdown_limit):
        return RiskDecision(False, "maximum drawdown reached")
    if equity <= 0 or sum(existing_risks) + proposed_risk > equity * aggregate_limit:
        return RiskDecision(False, "aggregate portfolio risk limit exceeded")
    return RiskDecision(True)
