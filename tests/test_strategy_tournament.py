import json

import pandas as pd
import pytest

from backtesting.comparison import compare_strategies
from backtesting.models import BacktestConfig
from backtesting.reports import export_csv, export_json
from strategies import Action, Signal, StrategyRegistry, default_registry
from strategies.ema_adx import EmaAdxTrend


def candles(count=100):
    prices=[100+i*.2+(3 if i%15==0 else 0) for i in range(count)]
    return pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=count,freq="h"),"open":prices,
        "high":[x+1 for x in prices],"low":[x-1 for x in prices],"close":prices,
        "volume":[200 if i%15==0 else 100 for i in range(count)]})


def test_registry_discovers_only_enabled_ids():
    registry=default_registry(["ema_adx_trend","donchian_volume_breakout"])
    assert registry.ids()==("ema_adx_trend","donchian_volume_breakout")
    with pytest.raises(KeyError):registry.get("rsi_bollinger_mean_reversion")
    with pytest.raises(ValueError):default_registry(["unknown"])


def test_all_three_return_consistent_signal_model():
    registry=default_registry(); assert len(registry.ids())==3
    for strategy in registry.enabled().values():
        signal=strategy.generate(candles())
        assert isinstance(signal,Signal) and isinstance(signal.action,Action)
        assert 0<=signal.confidence<=1 and signal.reason


def test_future_candles_do_not_change_prefix_signal():
    prefix=candles(70); altered=pd.concat([prefix,candles(30).assign(close=9999,high=10000,low=9998)],ignore_index=True)
    for strategy in default_registry().enabled().values():
        assert strategy.generate(prefix)==strategy.generate(altered.iloc[:70].copy())


def test_tournament_uses_identical_data_and_assumptions():
    seen=[]
    class Spy:
        def __init__(self,name):self.name=name
        def __call__(self,window):
            seen.append((self.name,len(window),float(window.close.iloc[-1]))); return Signal(Action.HOLD,0,"spy")
    cfg=BacktestConfig(fee_rate=.012,spread_rate=.023,slippage_rate=.034,risk_fraction=.4)
    rows=compare_strategies(candles(40),cfg,{"a":Spy("a"),"b":Spy("b")})
    assert {(r["result"].config.fee_rate,r["result"].config.spread_rate,r["result"].config.slippage_rate,r["result"].config.risk_fraction) for r in rows}=={(.012,.023,.034,.4)}
    assert [x[1:] for x in seen if x[0]=="a"]==[x[1:] for x in seen if x[0]=="b"]


def test_ranking_penalizes_tiny_samples_and_exports(tmp_path):
    def one(window):return Signal(Action.BUY,1,"one") if len(window)==1 else Signal(Action.HOLD,0,"wait")
    def none(window):return Signal(Action.HOLD,0,"none")
    ranking=compare_strategies(candles(40),BacktestConfig(),{"one":one,"none":none},minimum_trades=10)
    assert all("expectancy" in r and "fees" in r for r in ranking)
    assert max(r["composite_score"] for r in ranking)<100
    payload={"ranking":[{k:v for k,v in row.items() if k!="result"} for row in ranking]}
    jp,cp=tmp_path/"ranking.json",tmp_path/"ranking.csv";export_json(payload,str(jp));export_csv(payload,str(cp))
    assert len(json.loads(jp.read_text())["ranking"])==2 and "composite_score" in cp.read_text()


def test_signal_stop_target_are_used_by_shared_engine():
    from backtesting.engine import BacktestEngine
    data=candles(5); data.loc[2,"low"]=90; data.loc[2,"high"]=120
    def strategy(window):
        return Signal(Action.BUY,1,"bounded",95,115) if len(window)==1 else Signal(Action.HOLD,0,"wait")
    result=BacktestEngine(data,BacktestConfig(fee_rate=0,spread_rate=0,slippage_rate=0)).run(strategy)
    assert result.trades[0].exit_reason=="stop_loss"
