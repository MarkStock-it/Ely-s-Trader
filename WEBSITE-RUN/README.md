# Ely's Trader - Frontend UI

A polished dark trading terminal UI inspired by TradingView and Binance.

## Files

- **index.html** - Main entry point with all page sections
- **styles.css** - Dark theme, responsive layout, component styles
- **app.js** - API-backed controls, live dashboard updates, logs, settings, and backtesting

## Component Structure

### Pages (6 sections)
1. **Dashboard** - Status cards, recent trades, warnings
2. **Strategies** - Strategy toggles with configurable parameters
3. **Portfolio** - Holdings table, allocation chart placeholder
4. **Backtesting** - Backtest configuration, results display
5. **Logs** - Log filtering and display
6. **Control Center** - All bot controls and settings

### Control Center Controls

**Bot Controls:**
- Start, Stop, Restart, Emergency Stop buttons

**Execution Mode:**
- Paper/Live trading radio buttons

**Account Settings:**
- Initial paper balance input
- Reset paper account button

**Trading Parameters:**
- Fee, Spread, Slippage, Latency inputs

**Risk Management:**
- Risk per trade, Max position size, Max open positions
- Daily loss limit, Max drawdown

**Entry/Exit Settings:**
- Stop loss, Take profit percentages

**AI Models:**
- XGBoost toggle with confidence threshold
- LSTM toggle

**Exchange Configuration:**
- Exchange selector (Binance, Coinbase, Kraken, Bybit)
- API key and secret fields
- Test connection button

**Trading Configuration:**
- Symbols (comma-separated)
- Timeframe selector
- Refresh interval

**Notifications:**
- Telegram enable toggle
- Telegram token and chat ID inputs
- Test notification button

### Dashboard Cards (10 metrics)
- Bot Status
- Execution Mode
- Balance
- Equity
- Daily P/L
- Win Rate
- Profit Factor
- Drawdown
- Open Positions
- System Health

## HTML Structure

All controls have clear `id` and `name` attributes for Codex integration:

```html
<!-- Example control -->
<input type="number" id="initial-paper-balance" name="initial-paper-balance">
<button id="start-bot-btn" class="btn btn-success">Start Bot</button>
<input type="checkbox" id="xgboost-enabled" name="xgboost-enabled">
```

## CSS Features

- **Dark theme** with accent colors (teal/cyan)
- **Reusable classes**: `.card`, `.btn`, `.form-group`, `.toggle-switch`
- **Responsive grid layout**: Works on desktop, tablet, mobile
- **Semantic structure**: Easy to wire with backend APIs
- **No animations** beyond smooth transitions
- **Compact spacing**: Professional trading terminal feel

## Running

Start the Flask control plane from the project directory:

```powershell
python web_ui.py
```

Then open `http://127.0.0.1:8080`. The page must be served by Flask; opening
`index.html` directly cannot access the API.

The UI refreshes bot/account status and logs automatically. Control changes
are saved to `config.json`. Live mode requires API credentials and the exact
confirmation phrase shown by the UI; paper mode remains the default.

## Chart Placeholders

Chart areas are simple divs with text labels:
- Portfolio allocation (pie chart)
- Equity curve (line chart)
- Drawdown chart (area chart)

Replace `.chart-placeholder` divs with actual charting library when needed.

## Customization

### Colors
Edit CSS variables in `:root`:
```css
--accent-primary: #00d4aa;  /* Teal */
--danger: #ef4444;            /* Red */
--success: #10b981;           /* Green */
```

### Layout
All grids use `grid-template-columns: repeat(auto-fit, minmax(...))`
for responsive behavior. Adjust breakpoints in media queries.

### Controls
Add more inputs to Control Center sections following the same pattern:
```html
<div class="form-row">
    <div class="form-group">
        <label for="new-control">New Control</label>
        <input type="text" id="new-control" name="new-control">
    </div>
</div>
```

## Integration Notes

- All form inputs have unique `id` and `name` attributes
- Button IDs follow pattern: `{action}-{element}-btn`
- Toggle switches work with standard checkbox inputs
- Radio buttons for mode selection
- Ready for Fetch API / WebSocket integration
- No external dependencies (no jQuery, no chart libs)
