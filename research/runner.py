from dataclasses import dataclass
import json
import subprocess

@dataclass(frozen=True)
class RunOutput:
    exit_code: int | None; stdout: str; stderr: str; error: str | None = None

class VibeRunner:
    def __init__(self, executable="vibe-trading", timeout=180, output_limit=1_000_000, run=subprocess.run):
        self.executable, self.timeout, self.output_limit, self._run = executable, timeout, output_limit, run
    def execute(self, r):
        safe = {k: getattr(r, k) for k in ("request_id", "strategy_id", "strategy_version", "symbol", "timeframe", "direction", "strategy_parameters", "risk_parameters", "execution_assumptions", "data_period")}
        safe["required_output"] = "Return only schema_version 1 Ely ResearchResult JSON; no markdown"
        args = [self.executable, "run", "-p", "Perform reproducible OOS/walk-forward research: " + json.dumps(safe, sort_keys=True, allow_nan=False), "--json"]
        try:
            x = self._run(args, shell=False, capture_output=True, text=True, timeout=self.timeout, encoding="utf-8", errors="replace")
            too_big = len(x.stdout) > self.output_limit or len(x.stderr) > self.output_limit
            return RunOutput(x.returncode, x.stdout[:self.output_limit], x.stderr[:self.output_limit], "output exceeded limit" if too_big else None)
        except FileNotFoundError: return RunOutput(None, "", "", "vibe-trading executable not found")
        except subprocess.TimeoutExpired as exc: return RunOutput(None, _text(exc.stdout)[:self.output_limit], _text(exc.stderr)[:self.output_limit], "research timed out")

def parse_runner_json(output):
    if output.error: raise ValueError(output.error)
    if output.exit_code != 0: raise ValueError(f"Vibe-Trading exited with code {output.exit_code}")
    try: return json.loads(output.stdout)
    except json.JSONDecodeError as exc: raise ValueError("malformed structured Vibe output") from exc

def _text(value):
    if value is None: return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
