const $ = (id) => document.getElementById(id);
const money = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value || 0));
const number = (value, digits = 2) => Number(value || 0).toFixed(digits);

function toast(message, error = false) {
    let node = $('app-toast');
    if (!node) {
        node = document.createElement('div');
        node.id = 'app-toast';
        document.body.appendChild(node);
    }
    node.textContent = message;
    node.className = error ? 'show error' : 'show';
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.className = '', 3500);
}

async function api(path, options = {}) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
}

document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', event => {
    event.preventDefault();
    document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
    document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
    item.classList.add('active');
    $(item.dataset.page)?.classList.add('active');
    history.replaceState(null, '', `#${item.dataset.page}`);
}));

function setValue(id, value) {
    const node = $(id);
    if (node && value !== undefined && value !== null) node.value = value;
}

function setChecked(id, value) {
    const node = $(id);
    if (node) node.checked = Boolean(value);
}

async function loadConfig() {
    const cfg = await api('/api/config');
    setChecked('mode-paper', cfg.PAPER_MODE);
    setChecked('mode-live', cfg.LIVE_MODE);
    setValue('initial-paper-balance', cfg.PAPER_START_BALANCE);
    setValue('fee-percent', Number(cfg.PAPER_FEE_RATE || 0) * 100);
    setValue('spread-percent', Number(cfg.PAPER_SPREAD_RATE || 0) * 100);
    setValue('slippage-percent', Number(cfg.PAPER_SLIPPAGE_RATE || 0) * 100);
    setValue('latency-ms', cfg.PAPER_ORDER_LATENCY_MS);
    setValue('risk-per-trade', Number(cfg.RISK_PER_TRADE || 0) * 100);
    setValue('max-position-size', cfg.MAX_POSITION_SIZE);
    setValue('max-open-positions', cfg.MAX_OPEN_POSITIONS);
    setValue('daily-loss-limit', cfg.DAILY_LOSS_LIMIT);
    setValue('max-drawdown', cfg.MAX_DRAWDOWN);
    setValue('stop-loss-percent', cfg.STOP_LOSS_PERCENT);
    setValue('take-profit-percent', cfg.TAKE_PROFIT_PERCENT);
    setValue('xgboost-threshold', cfg.XGB_THRESHOLD);
    setChecked('xgboost-enabled', Boolean(cfg.XGB_MODEL_PATH));
    setChecked('lstm-enabled', Boolean(cfg.LSTM_MODEL_PATH));
    setValue('exchange-select', cfg.EXCHANGE);
    setValue('symbols', cfg.SYMBOLS?.join?.(', ') || cfg.SYMBOL || 'BTCUSDT');
    setValue('timeframe', cfg.INTERVAL);
    setValue('refresh-interval', cfg.SLEEP_INTERVAL);
    setChecked('telegram-enabled', cfg.TELEGRAM_ENABLED);
    $('telegram-status').textContent = cfg.TELEGRAM_ENABLED ? 'Enabled' : 'Disabled';
    setValue('backtest-symbol', cfg.SYMBOL || 'BTC/USDT');
}

function configPayload() {
    const symbols = ($('symbols').value || '').split(',').map(x => x.trim()).filter(Boolean);
    return {
        PAPER_MODE: $('mode-paper').checked,
        LIVE_MODE: $('mode-live').checked,
        EXCHANGE: $('exchange-select').value,
        SYMBOL: symbols[0] || 'BTCUSDT', SYMBOLS: symbols,
        INTERVAL: $('timeframe').value, SLEEP_INTERVAL: Number($('refresh-interval').value),
        PAPER_START_BALANCE: Number($('initial-paper-balance').value),
        PAPER_FEE_RATE: Number($('fee-percent').value) / 100,
        PAPER_SPREAD_RATE: Number($('spread-percent').value) / 100,
        PAPER_SLIPPAGE_RATE: Number($('slippage-percent').value) / 100,
        PAPER_ORDER_LATENCY_MS: Number($('latency-ms').value),
        RISK_PER_TRADE: Number($('risk-per-trade').value) / 100,
        MAX_POSITION_SIZE: Number($('max-position-size').value),
        MAX_OPEN_POSITIONS: Number($('max-open-positions').value),
        DAILY_LOSS_LIMIT: Number($('daily-loss-limit').value), MAX_DRAWDOWN: Number($('max-drawdown').value),
        STOP_LOSS_PERCENT: Number($('stop-loss-percent').value), TAKE_PROFIT_PERCENT: Number($('take-profit-percent').value),
        XGB_THRESHOLD: Number($('xgboost-threshold').value),
        TELEGRAM_ENABLED: $('telegram-enabled').checked,
    };
}

let saveTimer;
document.querySelectorAll('#control-center input, #control-center select').forEach(node => node.addEventListener('change', () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveSettings, 250);
}));

async function saveSettings() {
    const payload = configPayload();
    if (payload.LIVE_MODE) {
        const confirmation = prompt('Live trading can place real orders. Type ENABLE LIVE TRADING to continue.');
        if (confirmation !== 'ENABLE LIVE TRADING') {
            $('mode-paper').checked = true; $('mode-live').checked = false;
            toast('Live mode was not enabled', true); return;
        }
        payload.live_confirmation = confirmation;
        payload.API_KEY = $('api-key').value;
        payload.API_SECRET = $('api-secret').value;
    }
    if ($('telegram-token').value) payload.TELEGRAM_BOT_TOKEN = $('telegram-token').value;
    if ($('telegram-chat-id').value) payload.TELEGRAM_CHAT_ID = $('telegram-chat-id').value;
    try { await api('/api/config', { method: 'PUT', body: JSON.stringify(payload) }); toast('Settings saved'); }
    catch (error) { toast(error.message, true); await loadConfig(); }
}

function renderRows(target, rows, empty, renderer, columns = 7) {
    target.innerHTML = rows.length ? rows.map(renderer).join('') : `<tr class="empty-state"><td colspan="${columns}">${empty}</td></tr>`;
}

async function refreshStatus() {
    try {
        const data = await api('/api/status');
        const a = data.account;
        $('bot-status').textContent = data.running ? 'Running' : 'Idle';
        $('execution-mode').textContent = data.mode[0].toUpperCase() + data.mode.slice(1);
        $('balance').textContent = money(a.cash); $('equity').textContent = money(a.equity);
        $('daily-pl').textContent = money(a.realized_pnl);
        $('daily-pl').className = `card-value ${a.realized_pnl < 0 ? 'negative' : 'positive'}`;
        $('daily-pl-pct').textContent = `(${number(a.initial ? a.realized_pnl / a.initial * 100 : 0)}%)`;
        $('win-rate').textContent = a.win_rate == null ? '--' : `${number(a.win_rate * 100, 1)}%`;
        $('profit-factor').textContent = a.profit_factor == null ? '--' : number(a.profit_factor);
        $('drawdown').textContent = `${number(a.drawdown * 100)}%`;
        $('open-positions').textContent = a.holdings.length;
        $('system-health').textContent = data.healthy ? '✓ Good' : '⚠ Error';
        renderRows($('recent-trades'), a.trades, 'No trades yet', t => `<tr><td>${new Date(t.time * 1000).toLocaleString()}</td><td>${t.symbol}</td><td>${t.side}</td><td>${money(t.entry)}</td><td>${money(t.exit)}</td><td class="${t.pnl < 0 ? 'negative' : 'positive'}">${money(t.pnl)}</td><td>${t.status}</td></tr>`);
        renderRows($('holdings-table'), a.holdings, 'No positions', h => `<tr><td>${h.symbol}</td><td>${number(h.quantity, 8)}</td><td>${money(h.entry_price)}</td><td>${money(h.current_price)}</td><td>${money(h.value)}</td><td class="${h.pnl < 0 ? 'negative' : 'positive'}">${money(h.pnl)}</td><td>${number(a.equity ? h.value / a.equity * 100 : 0)}%</td></tr>`);
        $('warnings-list').innerHTML = data.warnings.length ? data.warnings.map(w => `<div class="warning-item ${w.level}">${w.message}</div>`).join('') : '<div class="empty-state">No warnings</div>';
    } catch (error) { $('system-health').textContent = '⚠ Offline'; }
}

async function refreshLogs() {
    try {
        const { logs } = await api('/api/logs');
        const filter = $('log-filter').value;
        const visible = filter === 'all' ? logs : logs.filter(x => x.level === filter);
        $('logs-list').innerHTML = visible.length ? visible.map(x => `<div class="log-entry ${x.level}"><span class="log-level">${x.level.toUpperCase()}</span> ${x.message}</div>`).join('') : '<div class="empty-state">No logs</div>';
    } catch (error) { toast(error.message, true); }
}

async function botAction(action) {
    try { const result = await api(`/api/bot/${action}`, { method: 'POST' }); toast(result.message); await refreshStatus(); }
    catch (error) { toast(error.message, true); }
}

$('start-bot-btn').onclick = () => botAction('start'); $('stop-bot-btn').onclick = () => botAction('stop');
$('restart-bot-btn').onclick = () => botAction('restart');
$('emergency-stop-btn').onclick = () => confirm('Engage the emergency kill switch?') && botAction('emergency-stop');
$('reset-paper-btn').onclick = async () => { if (!confirm('Delete all paper orders and fills?')) return; try { toast((await api('/api/reset-paper', { method: 'POST' })).message); refreshStatus(); } catch (e) { toast(e.message, true); } };
$('clear-logs-btn').onclick = async () => { try { toast((await api('/api/logs', { method: 'DELETE' })).message); refreshLogs(); } catch (e) { toast(e.message, true); } };
$('log-filter').onchange = refreshLogs;

async function testConnection() {
    try { toast((await api('/api/test-connection', { method: 'POST', body: JSON.stringify({ exchange: $('exchange-select').value }) })).message); }
    catch (e) { toast(e.message, true); }
}
$('test-connection-btn').onclick = testConnection; $('test-connection-btn2').onclick = testConnection;
$('test-telegram-btn').onclick = async () => { try { toast((await api('/api/test-telegram', { method: 'POST', body: JSON.stringify({ token: $('telegram-token').value, chat_id: $('telegram-chat-id').value }) })).message); } catch (e) { toast(e.message, true); } };
$('run-backtest-btn').onclick = async () => {
    const button = $('run-backtest-btn'); button.disabled = true; button.textContent = 'Running…';
    try {
        const r = await api('/api/backtest', { method: 'POST', body: JSON.stringify({ symbol: $('backtest-symbol').value, start: $('backtest-start-date').value, end: $('backtest-end-date').value, timeframe: $('backtest-timeframe').value, initial_balance: Number($('backtest-initial-balance').value) }) });
        $('backtest-results').innerHTML = `<div class="results-grid"><div><b>Final balance</b><br>${money(r.final_balance)}</div><div><b>Total return</b><br>${money(r.total_return)} (${number(r.return_pct)}%)</div><div><b>Trades</b><br>${r.trades}</div><div><b>Win rate</b><br>${number(r.win_rate)}%</div><div><b>Max drawdown</b><br>${number(r.max_drawdown)}%</div><div><b>Candles</b><br>${r.candles}</div></div>`;
    } catch (e) { $('backtest-results').innerHTML = `<div class="empty-state">${e.message}</div>`; }
    finally { button.disabled = false; button.textContent = 'Run Backtest'; }
};
$('run-tournament-btn').onclick = async () => {
    const button=$('run-tournament-btn'); button.disabled=true;
    try { const r=await api('/api/strategy-tournament',{method:'POST',body:JSON.stringify({symbol:$('backtest-symbol').value,timeframe:$('backtest-timeframe').value,initial_balance:Number($('backtest-initial-balance').value)})});
      $('tournament-results').innerHTML=`<table><thead><tr><th>Rank</th><th>Strategy</th><th>Return</th><th>Drawdown</th><th>Win rate</th><th>PF</th><th>Sharpe</th><th>Trades</th><th>Score</th></tr></thead><tbody>${r.ranking.map(x=>`<tr><td>${x.rank}</td><td>${x.strategy}</td><td>${number(x.net_return)}%</td><td>${number(x.max_drawdown)}%</td><td>${number(x.win_rate)}%</td><td>${number(x.profit_factor)}</td><td>${number(x.sharpe)}</td><td>${x.trades}</td><td>${number(x.composite_score)}</td></tr>`).join('')}</tbody></table>`;
    } catch(e){$('tournament-results').innerHTML=`<div class="empty-state">${e.message}</div>`;} finally{button.disabled=false;}
};
$('reset-all-btn').onclick = async () => { if (!confirm('Reload saved settings and discard unsaved values?')) return; await loadConfig(); toast('Settings reloaded'); };

async function refreshResearch() {
    try {
        const r = await api('/api/research/status'); const m = r.oos_metrics || {};
        $('research-gate-status').innerHTML = `<div class="results-grid">
          <div><b>State</b><br>${r.state || 'MISSING'}</div><div><b>Enabled / enforced</b><br>${!!r.enabled} / ${!!r.enforcement}</div>
          <div><b>Strategy</b><br>${r.strategy_id || '--'}</div><div><b>Market</b><br>${r.symbol || '--'} ${r.timeframe || ''}</div>
          <div><b>Confidence</b><br>${r.confidence == null ? '--' : number(r.confidence)}</div><div><b>Risk multiplier</b><br>${r.risk_multiplier == null ? '--' : number(r.risk_multiplier)}</div>
          <div><b>OOS trades</b><br>${m.trade_count == null ? '--' : m.trade_count}</div><div><b>Expectancy</b><br>${m.expectancy == null ? '--' : number(m.expectancy)}</div>
          <div><b>OOS drawdown</b><br>${m.maximum_drawdown_percentage == null ? '--' : number(m.maximum_drawdown_percentage)+'%'}</div><div><b>Profit factor</b><br>${m.profit_factor == null ? '--' : number(m.profit_factor)}</div>
          <div><b>Generated</b><br>${r.generated_at || '--'}</div><div><b>Expires</b><br>${r.expires_at || '--'}</div>
          <div><b>Last refresh</b><br>${r.last_refresh_result || r.job?.state || '--'}</div><div><b>Warnings</b><br>${(r.warnings || []).join(', ') || '--'}</div></div>`;
    } catch (e) { $('research-gate-status').textContent = e.message; }
}
$('run-research-btn').onclick = async () => { try { await api('/api/research/run', {method:'POST', body:'{}'}); toast('Research job started'); refreshResearch(); } catch(e) { toast(e.message,true); } };
$('validate-research-btn').onclick = async () => { try { await api('/api/research/validate', {method:'POST', body:JSON.stringify({filename:$('research-artifact').value})}); toast('Artifact is valid'); refreshResearch(); } catch(e) { toast(e.message,true); } };
$('disable-research-btn').onclick = async () => { try { await api('/api/research/disable', {method:'POST'}); toast('Research gate disabled'); refreshResearch(); } catch(e) { toast(e.message,true); } };

function updateTimestamp() { $('timestamp').textContent = new Date().toLocaleString(); }
updateTimestamp(); setInterval(updateTimestamp, 1000);
loadConfig().catch(e => toast(e.message, true)); refreshStatus(); refreshLogs();
refreshResearch(); setInterval(refreshResearch, 5000);
setInterval(refreshStatus, 5000); setInterval(refreshLogs, 10000);
