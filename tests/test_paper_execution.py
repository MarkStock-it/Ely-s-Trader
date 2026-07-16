import sqlite3
from unittest.mock import Mock

import pytest

import db
from execution import ExecutionEngine
from mega_trading_bot import DEFAULT_CONFIG
import safety


class ExchangeStub:
    def __init__(self):
        self.exchange = Mock()

    def round_amount(self, symbol, amount):
        return amount

    def round_price(self, symbol, price):
        return price

    def preflight_validate(self, symbol, amount, price):
        return True, "OK"

    create_market_order = Mock(side_effect=AssertionError("live order called"))


@pytest.fixture
def engine(tmp_path):
    path = str(tmp_path / "paper.db")
    db.init_db(path)
    cfg = dict(DEFAULT_CONFIG, PAPER_START_BALANCE=1000, PAPER_FEE_RATE=0.001,
               PAPER_SLIPPAGE_RATE=0.001, PAPER_SPREAD_RATE=0.002)
    return ExecutionEngine(ExchangeStub(), path, cfg)


def test_default_modes_and_invalid_combinations():
    assert DEFAULT_CONFIG["PAPER_MODE"] is True
    assert DEFAULT_CONFIG["LIVE_MODE"] is False
    for paper, live in ((True, True), (False, False)):
        with pytest.raises(ValueError, match="Exactly one"):
            safety.validate_config(dict(DEFAULT_CONFIG, PAPER_MODE=paper, LIVE_MODE=live))


def test_live_without_credentials_rejected():
    with pytest.raises(ValueError, match="requires both"):
        safety.validate_config(dict(DEFAULT_CONFIG, PAPER_MODE=False, LIVE_MODE=True, API_KEY="", API_SECRET=""))


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_paper_never_calls_live_methods(engine, side):
    if side == "sell":
        engine.create_order("BTCUSDT", "buy", 1, price=100)
    engine.create_order("BTCUSDT", side, 1, price=100)
    engine.ex_mgr.create_market_order.assert_not_called()
    engine.ex_mgr.exchange.create_order.assert_not_called()


@pytest.mark.parametrize("field,value", [("price", 0), ("price", -1), ("amount", 0), ("amount", -1)])
def test_non_positive_inputs_rejected(engine, field, value):
    kwargs = {"amount": 1, "price": 100}
    kwargs[field] = value
    with pytest.raises(ValueError, match="greater than zero"):
        engine.create_order("BTCUSDT", "buy", **kwargs)


def test_balance_holdings_prices_fees_and_net_round_trip(engine):
    buy = engine.create_order("BTCUSDT", "buy", 1, price=100)
    assert buy["fill_price"] > buy["market_price"]
    assert engine.paper_account()["cash"] < 900
    with pytest.raises(ValueError, match="Insufficient paper cash"):
        engine.create_order("BTCUSDT", "buy", 100, price=100)
    with pytest.raises(ValueError, match="Insufficient paper holdings"):
        engine.create_order("BTCUSDT", "sell", 2, price=100)
    sell = engine.create_order("BTCUSDT", "sell", 1, price=110)
    assert sell["fill_price"] < sell["market_price"]
    account = engine.paper_account()
    gross_profit = 10
    assert 0 < account["realized_pnl"] < gross_profit
    assert account["fees_paid"] == pytest.approx(buy["fee"] + sell["fee"])
    assert account["net_equity"] == pytest.approx(1000 + account["realized_pnl"])
    with sqlite3.connect(engine.db_path) as conn:
        meta = conn.execute("SELECT meta FROM fills ORDER BY id LIMIT 1").fetchone()[0]
    assert '"market_price"' in meta and '"fill_price"' in meta
