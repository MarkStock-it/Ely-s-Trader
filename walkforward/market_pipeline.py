"""Reproducible walk-forward validation across immutable market datasets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

from backtesting.models import BacktestConfig
from market_data import MarketDataStore
from strategies.registry import default_registry
from walkforward.engine import WalkForwardEngine
from walkforward.metrics import aggregate
from walkforward.models import QualificationRules, WalkForwardConfig


def run_market_walkforward(store: MarketDataStore, *, symbols, timeframes,
                           enabled_strategy_ids=None, backtest_config=None,
                           walkforward_config=None, rules=None, dataset_hashes=None):
    strategies = default_registry(enabled_strategy_ids).enabled()
    bt = backtest_config or BacktestConfig()
    wf = walkforward_config or WalkForwardConfig()
    qualification = rules or QualificationRules()
    catalog = store.list(symbols=set(symbols), timeframes=set(timeframes))
    if dataset_hashes:
        wanted = set(dataset_hashes); catalog = [x for x in catalog if x["dataset_hash"] in wanted]
        missing_hashes = wanted - {x["dataset_hash"] for x in catalog}
        if missing_hashes: raise FileNotFoundError("Dataset hashes not found: " + ", ".join(sorted(missing_hashes)))
    selected = []
    for symbol in symbols:
        for timeframe in timeframes:
            matches = [x for x in catalog if x["symbol"] == symbol and x["timeframe"] == timeframe]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one immutable dataset for {symbol} {timeframe}; found {len(matches)}")
            selected.append(matches[0])
    dataset_results = []
    for metadata in selected:
        data, verified = store.load(metadata["metadata_path"])
        config = replace(bt, symbol=verified["symbol"], timeframe=verified["timeframe"])
        result = WalkForwardEngine(data, config, wf, qualification).run(strategies)
        dataset_results.append({"dataset_hash": verified["dataset_hash"], "exchange": verified["exchange"],
            "symbol": verified["symbol"], "timeframe": verified["timeframe"],
            "qualification": [{k: v for k, v in row.items() if k != "windows"} for row in result["strategies"]],
            "result": result})
    aggregated = []
    for strategy_id in strategies:
        summaries = [next(x for x in item["result"]["strategies"] if x["strategy"] == strategy_id)
                     for item in dataset_results]
        oos = [window["oos_metrics"] for summary in summaries for window in summary["windows"]]
        aggregated.append({"strategy": strategy_id, "qualified": all(x["qualified"] for x in summaries),
            "qualification_result": "Approved" if all(x["qualified"] for x in summaries) else "Failed",
            "datasets_qualified": sum(x["qualified"] for x in summaries),
            "dataset_count": len(summaries), "oos_trade_count": sum(x["oos_trade_count"] for x in summaries),
            "aggregated_oos_metrics": aggregate(oos)})
    identity = {"schema_version": "1", "dataset_hashes": sorted(x["dataset_hash"] for x in selected),
                "strategies": sorted(strategies), "backtest": asdict(bt),
                "walkforward": asdict(wf), "qualification": asdict(qualification)}
    run_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    return {"run_hash": run_hash, "inputs": identity, "aggregated_strategies": aggregated,
            "datasets": dataset_results}
