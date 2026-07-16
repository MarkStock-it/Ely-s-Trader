"""Out-of-sample and walk-forward research helpers."""
from dataclasses import replace

from .engine import BacktestEngine


def non_overlapping_evaluation(datasets, config, strategy):
    """Evaluate named symbol/timeframe/period datasets without combining them."""
    results = []
    for case in datasets:
        cfg = replace(config, symbol=case["symbol"], timeframe=case["timeframe"])
        result = BacktestEngine(case["data"], cfg).run(strategy)
        results.append({"symbol": cfg.symbol, "timeframe": cfg.timeframe,
                        "period": case.get("period"), "result": result})
    return results


def walk_forward(data, config, strategy, train_candles: int, test_candles: int):
    """Run strictly non-overlapping OOS windows after each training window.

    The strategy factory may expose ``fit(train)``; otherwise training data is
    recorded but never passed into the test engine, which remains leak-free.
    """
    if train_candles <= 0 or test_candles <= 0: raise ValueError("window sizes must be positive")
    windows = []
    start = 0
    while start + train_candles + test_candles <= len(data):
        train = data.iloc[start:start + train_candles].copy()
        test = data.iloc[start + train_candles:start + train_candles + test_candles].copy()
        fitted = strategy.fit(train) if hasattr(strategy, "fit") else strategy
        result = BacktestEngine(test, config).run(fitted)
        windows.append({"train_start": str(train.timestamp.iloc[0]), "train_end": str(train.timestamp.iloc[-1]),
                        "test_start": str(test.timestamp.iloc[0]), "test_end": str(test.timestamp.iloc[-1]),
                        "result": result})
        start += test_candles
    return windows
