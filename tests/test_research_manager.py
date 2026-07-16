import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from research.artifacts import ArtifactStore
from research.factory import request_from_config
from research.hashing import configuration_fingerprint
from research.manager import ResearchManager
from research.runner import RunOutput, VibeRunner, parse_runner_json
from research.schemas import ResearchResult
from research.validation import risk_multiplier, validate_result
from vibetrader import VibeResearchGate

NOW = datetime.now(timezone.utc)
CFG = {"STRATEGY":"macd", "STRATEGY_VERSION":"1", "SYMBOL":"BTCUSDT", "INTERVAL":"1m",
       "PAPER_FEE_RATE":.001, "PAPER_SPREAD_RATE":.0002, "PAPER_SLIPPAGE_RATE":.0005,
       "RISK_PER_TRADE":.01, "MAX_AGGREGATE_RISK":.03, "MAX_POSITION_FRACTION":1,
       "VIBETRADER_MIN_OOS_TRADES":20, "VIBETRADER_MIN_EXPECTANCY":0,
       "VIBETRADER_MAX_OOS_DRAWDOWN_PCT":15, "VIBETRADER_MIN_CONFIDENCE":.65,
       "RESEARCH_MAX_AGE_SECONDS":86400, "RESEARCH_APPROVAL_TTL_SECONDS":3600,
       "RESEARCH_REFRESH_LEAD_SECONDS":600}

def request(**cfg): return request_from_config(dict(CFG, **cfg), request_id="req-1")
def strategy_a(x): return x
def strategy_b(x): return not x
def result(r, fp, **changes):
    value={"schema_version":1,"request_id":r.request_id,"strategy_id":r.strategy_id,"symbol":r.symbol,
      "timeframe":r.timeframe,"direction":"long","generated_at":NOW.isoformat(),
      "data_start":(NOW-timedelta(days=30)).isoformat(),"data_end":NOW.isoformat(),"in_sample_metrics":{},
      "out_of_sample_metrics":{"trade_count":30,"expectancy":2.0,"maximum_drawdown_percentage":8.0,
       "net_return_percentage":5.0,"profit_factor":1.4},"confidence":.8,"warnings":[],"limitations":[],
      "source_run_id":"vibe-1","configuration_fingerprint":fp}
    value.update(changes); return value

def test_fingerprint_stable_and_sensitive():
    r=request(); assert configuration_fingerprint(r,strategy_a)==configuration_fingerprint(r,strategy_a)
    assert configuration_fingerprint(r,strategy_a)!=configuration_fingerprint(request(ATR_PERIOD=99),strategy_a)
    assert configuration_fingerprint(r,strategy_a)!=configuration_fingerprint(request(PAPER_FEE_RATE=.02),strategy_a)
    assert configuration_fingerprint(r,strategy_a)!=configuration_fingerprint(r,strategy_b)

def test_strict_result_parsing_and_validation():
    r=request(); fp=configuration_fingerprint(r,strategy_a); parsed=ResearchResult.parse(result(r,fp))
    assert validate_result(r,parsed,fp,CFG)["risk_multiplier"]<=1
    with pytest.raises(ValueError): ResearchResult.parse("free form prose")
    bad=result(r,fp); bad.pop("confidence");
    with pytest.raises(ValueError): ResearchResult.parse(bad)
    for value in (float("nan"),float("inf")):
        with pytest.raises(ValueError): ResearchResult.parse(result(r,fp,confidence=value))

@pytest.mark.parametrize("change,match", [({"symbol":"ETHUSDT"},"symbol"),({"timeframe":"4h"},"timeframe"),
 ({"direction":"short"},"direction"),({"generated_at":(NOW+timedelta(hours=1)).isoformat()},"future"),
 ({"generated_at":(NOW-timedelta(days=3)).isoformat()},"stale")])
def test_identity_and_time_rejections(change,match):
    r=request(); fp=configuration_fingerprint(r,strategy_a)
    with pytest.raises(ValueError,match=match):
        parsed=ResearchResult.parse(result(r,fp,**change))
        validate_result(r,parsed,fp,CFG,now=NOW)

@pytest.mark.parametrize("metric,value,match", [("trade_count",2,"trades"),("expectancy",0,"expectancy"),
 ("maximum_drawdown_percentage",30,"drawdown")])
def test_metric_threshold_rejections(metric,value,match):
    r=request(); fp=configuration_fingerprint(r,strategy_a); p=result(r,fp); p["out_of_sample_metrics"][metric]=value
    with pytest.raises(ValueError,match=match): validate_result(r,ResearchResult.parse(p),fp,CFG,now=NOW)

def test_confidence_and_multiplier():
    r=request(); fp=configuration_fingerprint(r,strategy_a)
    with pytest.raises(ValueError,match="confidence"): validate_result(r,ResearchResult.parse(result(r,fp,confidence=.2)),fp,CFG,now=NOW)
    values=[risk_multiplier(x,.65,.25) for x in (.5,.65,.8,1)]
    assert values[0]==0 and values==sorted(values) and max(values)<=1

def test_runner_security_malformed_timeout_missing():
    calls=[]
    def fake(args,**kwargs): calls.append((args,kwargs)); return SimpleNamespace(returncode=0,stdout="not json",stderr="")
    out=VibeRunner(run=fake).execute(request()); assert calls[0][1]["shell"] is False
    with pytest.raises(ValueError,match="malformed"): parse_runner_json(out)
    def timeout(*a,**k): raise subprocess.TimeoutExpired(a[0],1)
    assert VibeRunner(run=timeout).execute(request()).error=="research timed out"
    def missing(*a,**k): raise FileNotFoundError
    assert "not found" in VibeRunner(run=missing).execute(request()).error

def test_failed_refresh_preserves_current_and_gate_expiry(tmp_path):
    store=ArtifactStore(tmp_path/"research"); r=request(); fp=configuration_fingerprint(r,strategy_a)
    approval=validate_result(r,ResearchResult.parse(result(r,fp)),fp,CFG,now=NOW); store.current(approval)
    manager=ResearchManager(dict(CFG,RESEARCH_DATA_PATH=str(store.root)),store=store,runner=SimpleNamespace(execute=lambda r:RunOutput(1,"","bad")))
    with pytest.raises(ValueError): manager.run(r,strategy_a)
    assert store.read_current()["approval_id"]==approval["approval_id"]
    cfg=dict(CFG,VIBETRADER_ENABLED=True,VIBETRADER_ENFORCE=True,VIBETRADER_APPROVAL_FILE=str(store.root/"current_approval.json"))
    assert VibeResearchGate(cfg,strategy_a).evaluate("BTCUSDT","1m","sell").allowed
    saved=store.read_current(); saved["expires_at"]=(NOW-timedelta(seconds=1)).isoformat(); store.current(saved)
    assert not VibeResearchGate(cfg,strategy_a).evaluate("BTCUSDT","1m","buy").allowed

def test_config_mismatch_veto_and_no_execution_capability(tmp_path):
    assert not hasattr(VibeResearchGate,"create_order")
    store=ArtifactStore(tmp_path/"research"); r=request(); fp=configuration_fingerprint(r,strategy_a)
    store.current(validate_result(r,ResearchResult.parse(result(r,fp)),fp,CFG,now=NOW))
    cfg=dict(CFG,VIBETRADER_ENABLED=True,VIBETRADER_ENFORCE=True,VIBETRADER_APPROVAL_FILE=str(store.root/"current_approval.json"),PAPER_FEE_RATE=.02)
    assert VibeResearchGate(cfg,strategy_a).evaluate("BTCUSDT","1m","buy").state=="CONFIG_MISMATCH"
    assert cfg.get("LIVE_MODE") is not True
