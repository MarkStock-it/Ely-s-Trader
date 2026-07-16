"""Simple Flask UI to view bot status and logs, with health and metrics endpoints."""
from flask import Flask, render_template_string, send_file, Response, jsonify
import json
import os
import db
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

APP = Flask(__name__)
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "mega_trading_bot.log")
CFG_PATH = os.path.join(ROOT, "config.json")

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mega Trading Bot - Status</title>

<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Fira+Code&display=swap" rel="stylesheet">

<style>
:root {
    --bg: #0f172a;
    --card: rgba(255,255,255,0.05);
    --accent: #00ffcc;
    --danger: #ff4d4d;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --border: rgba(255,255,255,0.1);
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: 'Orbitron', sans-serif;
    background: linear-gradient(135deg, #0f172a, #020617);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

/* Header */
header {
    padding: 20px 40px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(10px);
}

.title {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 2px;
}

.live-indicator {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 14px;
}

.dot {
    width: 12px;
    height: 12px;
    background: var(--accent);
    border-radius: 50%;
    animation: pulse 1.5s infinite;
}

@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(0,255,204, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(0,255,204, 0); }
    100% { box-shadow: 0 0 0 0 rgba(0,255,204, 0); }
}

/* Layout */
.container {
    padding: 30px 40px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 30px;
    flex: 1;
}

.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    backdrop-filter: blur(15px);
    box-shadow: 0 0 30px rgba(0,0,0,0.3);
    display: flex;
    flex-direction: column;
}

.card h2 {
    margin-top: 0;
    font-size: 18px;
    margin-bottom: 15px;
    color: var(--accent);
}

/* Code blocks */
pre {
    font-family: 'Fira Code', monospace;
    font-size: 13px;
    white-space: pre-wrap;
    word-break: break-word;
    background: #0b1220;
    padding: 15px;
    border-radius: 10px;
    border: 1px solid var(--border);
    overflow-y: auto;
}

/* Scrollable log */
.log-box {
    flex: 1;
    overflow-y: auto;
}

/* Buttons */
.controls {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
}

button {
    background: var(--accent);
    color: black;
    border: none;
    padding: 8px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: bold;
    transition: 0.2s;
}

button:hover {
    opacity: 0.8;
    transform: translateY(-2px);
}

/* Responsive */
@media(max-width: 1000px){
    .container {
        grid-template-columns: 1fr;
    }
}

/* Footer */
footer {
    text-align: center;
    padding: 15px;
    font-size: 12px;
    color: var(--muted);
    border-top: 1px solid var(--border);
}
</style>
</head>

<body>

<header>
    <div class="title">MEGA TRADING BOT</div>
    <div class="live-indicator">
        <div class="dot"></div>
        LIVE SYSTEM
    </div>
</header>

<div class="container">

    <!-- CONFIG CARD -->
    <div class="card">
        <h2>⚙ Configuration</h2>
        <div class="controls">
            <button onclick="copyConfig()">Copy</button>
            <button onclick="location.reload()">Refresh</button>
        </div>
        <pre id="configBox">{{ config }}</pre>
    </div>

    <!-- LOG CARD -->
    <div class="card">
        <h2>📈 Latest Log (Tail)</h2>
        <div class="log-box">
            <pre id="logBox">{{ log }}</pre>
        </div>
    </div>

</div>

<footer>
    Mega Trading Bot Dashboard • Built for Market Domination
</footer>

<script>
function copyConfig(){
    const text = document.getElementById("configBox").innerText;
    navigator.clipboard.writeText(text);
    alert("Config copied to clipboard!");
}

// Auto-scroll log to bottom
const logBox = document.getElementById("logBox");
logBox.scrollTop = logBox.scrollHeight;
</script>

</body>
</html>
"""



@APP.route("/")
def index():
    cfg = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {"error": "failed to load config"}
    logtail = "(no logs yet)"
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-300:]
                logtail = "".join(lines)
        except Exception:
            logtail = "failed to read log"
    return render_template_string(TEMPLATE, config=json.dumps(cfg, indent=2), log=logtail)


@APP.route("/health")
def health():
    # basic checks: config exists, DB file exists
    cfg = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {"error": "failed to load config"}
    data_path = cfg.get("DATA_PATH", os.path.join(os.path.dirname(__file__), "data"))
    db_file = os.path.join(data_path, "mega_trades.db")
    status = {"config_loaded": bool(cfg), "db_exists": os.path.exists(db_file)}
    return jsonify(status)


@APP.route("/status")
def status():
    # return simple status: open orders count and tail of audit log
    cfg = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    data_path = cfg.get("DATA_PATH", os.path.join(os.path.dirname(__file__), "data"))
    db_file = os.path.join(data_path, "mega_trades.db")
    open_orders = []
    try:
        if os.path.exists(db_file):
            open_orders = db.get_open_orders(db_file)
    except Exception:
        open_orders = []
    return jsonify({"open_orders_count": len(open_orders), "open_orders": open_orders[:20]})


@APP.route('/metrics')
def metrics():
    try:
        data = generate_latest()
        return Response(data, mimetype=CONTENT_TYPE_LATEST)
    except Exception:
        return Response(b"", status=500)


if __name__ == "__main__":
    APP.run(host="127.0.0.1", port=8080, debug=False)
