import json

import pandas as pd
import pytest

from backtesting.data_loader import load_market_dataset
from backtesting.models import BacktestConfig
from market_data import MarketDataStore, TIMEFRAME_MS, dataset_hash, download_ohlcv, validate_market_data
from walkforward.market_pipeline import run_market_walkforward
from walkforward.models import QualificationRules, WalkForwardConfig


def candles(count=36, timeframe="1h", start="2024-01-01T00:00:00Z"):
    timestamp = pd.date_range(start, periods=count, freq={"15m":"15min", "1h":"1h", "4h":"4h"}[timeframe], tz="UTC")
    close = [100 + i % 8 for i in range(count)]
    return pd.DataFrame({"timestamp": timestamp, "open": close,
        "high": [x + 1 for x in close], "low": [x - 1 for x in close],
        "close": close, "volume": [10 + i for i in range(count)]})


@pytest.mark.parametrize("mutation,match", [
    (lambda x: x.assign(high=50), "relationships"),
    (lambda x: x.assign(volume=-1), "negative"),
    (lambda x: pd.concat([x, x.iloc[[0]]], ignore_index=True), "Duplicate"),
    (lambda x: x.iloc[[0,2,1,3,4]].reset_index(drop=True), "ordered"),
    (lambda x: x.drop(index=2).reset_index(drop=True), "Missing candles"),
])
def test_malformed_candles_are_rejected(mutation, match):
    with pytest.raises(ValueError, match=match):
        validate_market_data(mutation(candles(5)), "1h")


def test_hash_stability_and_immutable_save(tmp_path):
    store = MarketDataStore(tmp_path / "market")
    first = store.save(candles(), exchange="binance", symbol="BTC/USDT", timeframe="1h",
                       downloaded_at="2024-01-02T00:00:00Z")
    loaded, metadata = store.load(first["dataset_hash"])
    second = store.save(candles(), exchange="binance", symbol="BTC/USDT", timeframe="1h",
                        downloaded_at="2025-01-02T00:00:00Z")
    assert metadata["dataset_hash"] == dataset_hash(loaded) == first["dataset_hash"]
    assert second["download_time"] == "2024-01-02T00:00:00Z"
    assert json.loads(open(first["metadata_path"], encoding="utf-8").read())["schema_version"] == "1"


def test_offline_reload_never_uses_network(tmp_path):
    store = MarketDataStore(tmp_path / "market")
    saved = store.save(candles(), exchange="binance", symbol="ETH/USDT", timeframe="1h")
    loaded, metadata = load_market_dataset(saved["dataset_hash"], root=str(store.root))
    assert len(loaded) == 36 and metadata["symbol"] == "ETH/USDT"


def test_paginated_ccxt_download(tmp_path):
    source = candles(10, "15m")
    raw = [[int(pd.Timestamp(row.timestamp).timestamp()*1000), row.open, row.high, row.low, row.close, row.volume]
           for row in source.itertuples()]
    class Exchange:
        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            return [row for row in raw if row[0] >= since][:limit]
    store = MarketDataStore(tmp_path / "market")
    saved = download_ohlcv(Exchange(), store, exchange="binance", symbol="SOL/USDT", timeframe="15m",
                           start=source.timestamp.iloc[0], end=source.timestamp.iloc[-1], limit=3)
    loaded, _ = store.load(saved["metadata_path"])
    assert len(loaded) == 10 and saved["candle_count"] == 10


def test_walkforward_runs_all_datasets_and_enabled_strategies_reproducibly(tmp_path):
    store = MarketDataStore(tmp_path / "market")
    symbols, timeframes = ["BTC/USDT", "ETH/USDT"], ["1h", "4h"]
    for symbol in symbols:
        for timeframe in timeframes:
            store.save(candles(36, timeframe), exchange="binance", symbol=symbol, timeframe=timeframe,
                       downloaded_at="2024-01-02T00:00:00Z")
    kwargs = dict(symbols=symbols, timeframes=timeframes,
        backtest_config=BacktestConfig(starting_balance=1000),
        walkforward_config=WalkForwardConfig(8, 4, 4, 4),
        rules=QualificationRules(minimum_oos_trades=0))
    first = run_market_walkforward(store, **kwargs)
    second = run_market_walkforward(store, **kwargs)
    assert first["run_hash"] == second["run_hash"]
    assert len(first["datasets"]) == 4
    assert len(first["aggregated_strategies"]) == 3
    assert all(x["dataset_count"] == 4 for x in first["aggregated_strategies"])
