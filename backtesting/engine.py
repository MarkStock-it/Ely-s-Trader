"""Sequential, long-only simulator.

Signals are evaluated at candle close and execute at a later candle open
(next candle plus configured latency). Intrabar exits use stop-first when a
single candle touches both stop and target.
"""
import subprocess
from dataclasses import asdict
from typing import Callable, Optional

import pandas as pd

from .data_loader import validate_ohlcv
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, Trade
from strategies.base import Action, Signal


class BacktestEngine:
    def __init__(self, data: pd.DataFrame, config: BacktestConfig):
        self.data = validate_ohlcv(data)
        self.config = config

    def run(self, strategy: Callable[[pd.DataFrame], Optional[str]]) -> BacktestResult:
        c, df = self.config, self.data
        cash, position, trades, series, pending = c.starting_balance, None, [], [], None
        peak = cash
        for i, row in df.iterrows():
            # Pending close signal executes at this open. Strategy never sees row i yet.
            if pending and pending[0] <= i:
                signal, reason, signal_stop, signal_target = pending[1], pending[2], pending[3], pending[4]
                if signal == "buy" and position is None:
                    market = float(row.open); fill = self._fill(market, "buy")
                    budget = cash * c.risk_fraction
                    qty = budget / (fill * (1 + c.fee_rate))
                    if qty >= c.minimum_position_size:
                        fee = fill * qty * c.fee_rate; cash -= fill * qty + fee
                        position = {"timestamp": row.timestamp, "index": i, "market": market, "fill": fill,
                                    "qty": qty, "fee": fee, "reason": reason, "highest": market,
                                    "signal_stop": signal_stop, "signal_target": signal_target}
                elif signal == "sell" and position is not None:
                    cash, position = self._close(cash, position, row.timestamp, float(row.open), reason, trades)
                pending = None

            if position is not None:
                position["highest"] = max(position["highest"], float(row.high))
                stop = position.get("signal_stop")
                if stop is None and c.stop_loss_pct is not None: stop = position["market"] * (1 - c.stop_loss_pct)
                if c.trailing_stop_pct is not None:
                    trailing = position["highest"] * (1 - c.trailing_stop_pct)
                    stop = max(stop or trailing, trailing)
                target = position.get("signal_target")
                if target is None and c.take_profit_pct is not None: target = position["market"] * (1 + c.take_profit_pct)
                stop_hit, target_hit = stop is not None and row.low <= stop, target is not None and row.high >= target
                if stop_hit:  # deliberately first, including ambiguous candles
                    cash, position = self._close(cash, position, row.timestamp, stop, "stop_loss", trades)
                elif target_hit:
                    cash, position = self._close(cash, position, row.timestamp, target, "take_profit", trades)

            value = position["qty"] * float(row.close) if position else 0.0
            unrealized = ((float(row.close) - position["fill"]) * position["qty"] - position["fee"]) if position else 0.0
            equity = cash + value; peak = max(peak, equity); drawdown = peak - equity
            series.append({"timestamp": row.timestamp, "equity": equity, "cash": cash,
                           "position_value": value, "unrealized_pnl": unrealized,
                           "average_entry_price": position["fill"] if position else 0.0, "drawdown": drawdown,
                           "drawdown_percentage": drawdown / peak * 100 if peak else 0.0})
            # Copy is the anti-lookahead boundary: only rows <= i are supplied.
            raw_signal = strategy(df.iloc[:i + 1].copy())
            signal = _normalize_signal(raw_signal)
            if signal.action in (Action.BUY, Action.SELL):
                pending = (i + 1 + c.latency_candles, signal.action.value, signal.reason,
                           signal.stop_loss, signal.take_profit)

        if position is not None:
            last = df.iloc[-1]
            cash, position = self._close(cash, position, last.timestamp, float(last.close), "end_of_data", trades)
            final_drawdown = peak - cash
            series[-1].update(equity=cash, cash=cash, position_value=0.0, unrealized_pnl=0.0,
                              average_entry_price=0.0, drawdown=final_drawdown,
                              drawdown_percentage=final_drawdown / peak * 100 if peak else 0.0)
        metrics = calculate_metrics(c.starting_balance, cash, trades, series, float(df.close.iloc[0]), float(df.close.iloc[-1]))
        metadata = {"execution_timestamp": BacktestResult.executed_at(), "data_start": str(df.timestamp.iloc[0]),
                    "data_end": str(df.timestamp.iloc[-1]), "candles": len(df),
                    "missing_candles": df.attrs.get("missing_candles", []), "git_commit": _git_commit(),
                    "execution_convention": "close signal executes at next candle open plus latency_candles",
                    "intrabar_policy": "stop executes first when stop and target are both touched",
                    "random_seed": c.random_seed}
        return BacktestResult(c, metrics, trades, series, metadata)

    def _fill(self, market: float, side: str) -> float:
        c = self.config
        # Identical formula to ExecutionEngine._paper_fill.
        return market * (1 + c.spread_rate / 2) * (1 + c.slippage_rate) if side == "buy" else market * (1 - c.spread_rate / 2) * (1 - c.slippage_rate)

    def _close(self, cash, position, timestamp, market, reason, trades):
        fill = self._fill(float(market), "sell"); gross_value = fill * position["qty"]
        exit_fee = gross_value * self.config.fee_rate; cash += gross_value - exit_fee
        gross_profit = (fill - position["fill"]) * position["qty"]
        net_profit = gross_profit - position["fee"] - exit_fee
        trades.append(Trade(self.config.strategy, self.config.symbol, self.config.timeframe,
                            position["timestamp"], timestamp, position["market"], position["fill"],
                            float(market), fill, position["qty"], position["fee"], exit_fee,
                            gross_profit, net_profit, net_profit / (position["fill"] * position["qty"] + position["fee"]) * 100,
                            _duration(timestamp, position["timestamp"]), position["reason"], reason))
        return cash, None


def _duration(a, b):
    try: return float((pd.Timestamp(a) - pd.Timestamp(b)).total_seconds())
    except Exception:
        try: return float(a) - float(b)
        except Exception: return 0.0


def _git_commit():
    try: return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2).stdout.strip() or None
    except Exception: return None


def _normalize_signal(value):
    if isinstance(value, Signal): return value
    if value in ("buy", "sell"): return Signal(Action(value), 1.0, "strategy_signal")
    return Signal(Action.HOLD, 0.0, "no signal")
