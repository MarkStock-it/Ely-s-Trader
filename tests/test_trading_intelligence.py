import json
import time
import pytest

from analytics.database import TradingIntelligenceDatabase
from analytics.decision_log import get_decision_history, log_decision
from analytics.market_history import get_market_history, store_market
from analytics.portfolio_history import get_daily_returns, get_equity_curve, store_snapshot
from analytics.reports import generate_reports
from analytics.strategy_stats import get_strategy_statistics
from analytics.trade_history import get_best_trade, get_last_trade, get_trade, get_trades, get_worst_trade, store_trade


def trade(number, pnl=10, strategy="macd"):
    return {"trade_id": f"trade-{number}", "strategy_id": strategy, "strategy_version": "1",
            "symbol": "BTCUSDT", "timeframe": "1m", "direction": "buy",
            "entry_time": 1000 + number, "exit_time": 1100 + number,
            "entry_price": 100, "exit_price": 100 + pnl, "quantity": 1,
            "stop_loss": 95, "take_profit": 115, "fees": 1, "spread": .0002,
            "slippage": .0005, "gross_pnl": pnl + 1, "net_pnl": pnl,
            "return_pct": pnl, "r_multiple": pnl / 5, "hold_duration": 100,
            "exit_reason": "target", "confidence": .8, "risk_multiplier": .75,
            "research_approval_id": "approval-1", "market_regime": "bull_trend",
            "config_fingerprint": "fingerprint"}


def test_trade_and_restart_persistence(tmp_path):
    path = tmp_path / "trades.db"
    first = TradingIntelligenceDatabase(path, asynchronous=False)
    store_trade(first, trade(1), async_write=False)
    store_trade(first, trade(1), async_write=False)  # duplicate is ignored
    second = TradingIntelligenceDatabase(path, asynchronous=False)
    assert get_trade(second, "trade-1")["net_pnl"] == 10
    assert len(get_trades(second)) == 1


def test_decisions_snapshots_market_and_queries(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False)
    log_decision(tid, symbol="BTCUSDT", strategy="macd", signal="buy", confidence=.7,
                 indicator_values={"atr": 2}, research_result={"allowed": True},
                 risk_result={"allowed": False}, final_decision="rejected", async_write=False)
    store_snapshot(tid, {"timestamp": 1000, "cash": 100, "equity": 100,
        "unrealized_pnl": 0, "realized_pnl": 0, "drawdown": 0,
        "open_positions": 0, "exposure": 0, "portfolio_value": 100}, async_write=False)
    store_snapshot(tid, {"timestamp": 1100, "cash": 105, "equity": 105,
        "unrealized_pnl": 0, "realized_pnl": 5, "drawdown": 0,
        "open_positions": 0, "exposure": 0, "portfolio_value": 105}, async_write=False)
    store_market(tid, timestamp=1000, symbol="BTCUSDT", timeframe="1m", regime="bull",
                 atr=2, volume=10, volatility=.01, trend_strength=.02, async_write=False)
    assert get_decision_history(tid)[0]["final_decision"] == "rejected"
    assert len(get_equity_curve(tid)) == 2 and get_daily_returns(tid)[0]["return"] == pytest.approx(.05)
    assert get_market_history(tid)[0]["atr"] == 2


def test_statistics_best_worst_and_reports(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "tid.db", asynchronous=False)
    for item in (trade(1, 10), trade(2, -5), trade(3, 20)):
        store_trade(tid, item, async_write=False)
    stats = get_strategy_statistics(tid, "macd")
    assert stats["trades"] == 3 and stats["wins"] == 2 and stats["losses"] == 1
    assert stats["profit_factor"] == 6 and get_best_trade(tid)["net_pnl"] == 20
    assert get_worst_trade(tid)["net_pnl"] == -5 and get_last_trade(tid)["trade_id"] == "trade-3"
    paths = generate_reports(tid, tmp_path / "reports")
    assert all((tmp_path / "reports" / name).exists() for name in paths)
    assert len(json.loads((tmp_path / "reports" / "strategy_statistics.json").read_text())) == 1


def test_large_history_is_indexed_and_paginated(tmp_path):
    tid = TradingIntelligenceDatabase(tmp_path / "large.db", asynchronous=False)
    base = trade(0)
    fields = tuple(base)
    sql = f"INSERT INTO analytics_trades ({','.join(fields)},created_at) VALUES ({','.join('?' for _ in fields)},?)"
    rows = []
    for number in range(5000):
        item = trade(number)
        rows.append(tuple(item[x] for x in fields) + (time.time(),))
    started = time.perf_counter()
    with tid.connection() as con:
        con.executemany(sql, rows)
    result = get_trades(tid, strategy="macd", symbol="BTCUSDT", limit=25, offset=100)
    elapsed = time.perf_counter() - started
    with tid.connection(readonly=True) as con:
        indexes = {row[1] for row in con.execute("PRAGMA index_list(analytics_trades)")}
    assert len(result) == 25 and "idx_at_strategy_exit" in indexes
    assert elapsed < 10
