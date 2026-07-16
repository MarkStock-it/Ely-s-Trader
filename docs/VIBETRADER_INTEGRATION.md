# Vibe-Trading research gate

Vibe-Trading is integrated as an entry confirmation and risk-scaling layer,
not as an execution engine. Its own documentation defines it as research,
simulation, and backtesting software that does not execute live trades.

## Workflow

1. Run Vibe-Trading research for the exact symbol and timeframe, including
   walk-forward/out-of-sample validation, costs, trade count, and drawdown.
2. Inspect the report. Do not accept generated strategy claims without the
   underlying test artifacts.
3. Copy `data/vibetrader_approval.example.json` to the ignored
   `data/vibetrader_approval.json` and enter the inspected OOS metrics.
4. Give the approval a short expiry. Research must be refreshed after expiry.
5. Set `VIBETRADER_ENABLED=true`. Keep `VIBETRADER_ENFORCE=true` to fail closed.

Example research command:

```powershell
vibe-trading run -p "Validate the existing long-only BTC-USDT MACD strategy on 1m data with fees, spread and slippage. Use non-overlapping walk-forward tests. Report OOS trade count, expectancy, maximum drawdown, and evidence-backed confidence. Do not propose live execution." --json
```

The bot validates the artifact schema, timestamps, symbol, timeframe,
direction, confidence, OOS trade count, expectancy, and drawdown. An approval
can veto an entry and reduce position risk, but can never increase configured
risk or block an exit. Missing/malformed/stale artifacts veto entries in
enforced mode. Vibe-Trading is never invoked from the real-time candle loop.
