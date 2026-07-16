from .base import Strategy
from .donchian_volume import DonchianVolumeBreakout
from .ema_adx import EmaAdxTrend
from .rsi_bollinger import RsiBollingerMeanReversion


class StrategyRegistry:
    def __init__(self): self._strategies = {}
    def register(self, strategy):
        if not isinstance(strategy, Strategy): raise TypeError("strategy must implement Strategy")
        if strategy.strategy_id in self._strategies: raise ValueError(f"duplicate strategy ID: {strategy.strategy_id}")
        self._strategies[strategy.strategy_id]=strategy; return strategy
    def get(self,strategy_id):
        if strategy_id not in self._strategies: raise KeyError(f"unknown or disabled strategy: {strategy_id}")
        return self._strategies[strategy_id]
    def enabled(self): return dict(self._strategies)
    def ids(self): return tuple(self._strategies)


def default_registry(enabled_ids=None):
    all_strategies=[EmaAdxTrend(),RsiBollingerMeanReversion(),DonchianVolumeBreakout()]
    enabled=set(enabled_ids) if enabled_ids is not None else {x.strategy_id for x in all_strategies}
    registry=StrategyRegistry()
    for strategy in all_strategies:
        if strategy.strategy_id in enabled: registry.register(strategy)
    unknown=enabled-set(x.strategy_id for x in all_strategies)
    if unknown: raise ValueError("unknown enabled strategies: "+", ".join(sorted(unknown)))
    return registry
