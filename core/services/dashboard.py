"""
PTQ Scalping Bot - Enhanced Dashboard
Complete real-time web dashboard with ALL trading details
Version 3.0 - Full Featured
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Bot state reference (set by main bot)
_bot_state = None
_broker = None
_recent_ticks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    yield


app = FastAPI(
    title="PTQ Scalping Bot Dashboard",
    description="Complete real-time trading dashboard with all details",
    version="3.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


def set_state_reference(state, broker=None, ticks_ref=None):
    """Set references to bot state and broker"""
    global _bot_state, _broker, _recent_ticks
    _bot_state = state
    _broker = broker
    if ticks_ref is not None:
        _recent_ticks = ticks_ref


# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the main dashboard HTML"""
    return DASHBOARD_HTML


@app.get("/api/status")
async def get_status():
    """Get current bot status with all details"""
    if not _bot_state:
        return {"error": "Bot not connected"}
    
    return {
        "state": getattr(_bot_state, 'state', 'UNKNOWN'),
        "daily_pnl": getattr(_bot_state, 'daily_pnl_inr', 0),
        "daily_pnl_pct": getattr(_bot_state, 'daily_pnl_pct', 0),
        "total_trades": getattr(_bot_state, 'total_trades_today', 0),
        "winning_trades": getattr(_bot_state, 'winning_trades', 0),
        "losing_trades": getattr(_bot_state, 'losing_trades', 0),
        "consecutive_losses": getattr(_bot_state, 'consecutive_losses', 0),
        "day_type": getattr(_bot_state, 'day_type', 'NORMAL'),
        "estimated_vix": getattr(_bot_state, 'estimated_vix', 15.0),
        "loop_count": getattr(_bot_state, 'loop_count', 0),
        "trades_this_hour": getattr(_bot_state, 'trades_this_hour', 0),
        "current_trade": _get_current_trade_detailed(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/config")
async def get_config():
    """Get current bot configuration"""
    try:
        from config.constants import (
            TOTAL_CAPITAL, PAPER_TRADING, USE_LIVE_DATA, CE_QUANTITY, PE_QUANTITY,
            SL_POINTS_FIXED, TP_POINTS_FIXED, MIN_SCORE_TO_TRADE, MIN_CONFIDENCE,
            MAX_TRADES_PER_DAY, MAX_TRADES_PER_HOUR, KILL_SWITCH_LOSS,
            MAX_DAILY_LOSS_AMOUNT, TRAILING_ENABLED, MARKET_OPEN_TIME, MARKET_CLOSE_TIME
        )
        return {
            "capital": TOTAL_CAPITAL,
            "paper_trading": PAPER_TRADING,
            "use_live_data": USE_LIVE_DATA,
            "ce_quantity": CE_QUANTITY,
            "pe_quantity": PE_QUANTITY,
            "sl_points": SL_POINTS_FIXED,
            "tp_points": TP_POINTS_FIXED,
            "min_score": MIN_SCORE_TO_TRADE,
            "min_confidence": MIN_CONFIDENCE,
            "max_trades_day": MAX_TRADES_PER_DAY,
            "max_trades_hour": MAX_TRADES_PER_HOUR,
            "kill_switch": KILL_SWITCH_LOSS,
            "max_daily_loss": MAX_DAILY_LOSS_AMOUNT,
            "tsl_enabled": TRAILING_ENABLED,
            "market_open": MARKET_OPEN_TIME,
            "market_close": MARKET_CLOSE_TIME
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/trades")
async def get_trades():
    """Get today's trades with full details"""
    try:
        from core.services.database import get_todays_trades
        trades = get_todays_trades()
        return {"trades": trades, "count": len(trades)}
    except Exception as e:
        return {"error": str(e), "trades": [], "count": 0}


@app.get("/api/trades/history")
async def get_trade_history(days: int = 7):
    """Get trade history for multiple days"""
    try:
        from core.services.database import db
        history = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            trades = db.get_trades_by_date(date)
            if trades:
                pnl = sum(t['pnl'] or 0 for t in trades)
                wins = len([t for t in trades if (t['pnl'] or 0) > 0])
                losses = len([t for t in trades if (t['pnl'] or 0) < 0])
                history.append({
                    "date": date,
                    "trades": len(trades),
                    "pnl": pnl,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": (wins / len(trades) * 100) if trades else 0
                })
        return {"history": history}
    except Exception as e:
        return {"error": str(e), "history": []}


@app.get("/api/summary")
async def get_summary():
    """Get daily summary"""
    try:
        from core.services.database import get_todays_summary
        summary = get_todays_summary()
        return summary or {}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/analytics/hourly")
async def get_hourly_analytics():
    """Get performance by hour"""
    try:
        from core.services.database import db
        return {"data": db.get_performance_by_hour()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/analytics/direction")
async def get_direction_analytics():
    """Get CE vs PE performance"""
    try:
        from core.services.database import db
        return {"data": db.get_performance_by_direction()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/analytics/streaks")
async def get_streak_analytics():
    """Get win/loss streaks"""
    try:
        from core.services.database import db
        return db.get_win_streak()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/signals")
async def get_recent_signals():
    """Get recent signals for analysis"""
    try:
        from core.services.database import db
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM signals 
                ORDER BY timestamp DESC 
                LIMIT 50
            ''')
            signals = [dict(row) for row in cursor.fetchall()]
            return {"signals": signals}
    except Exception as e:
        return {"error": str(e), "signals": []}


@app.get("/api/tick")
async def get_current_tick():
    """Get current tick data with bid/ask spread"""
    if _recent_ticks and len(_recent_ticks) > 0:
        tick = _recent_ticks[-1]
        return {
            "ltp": tick.get('ltp'),
            "bid": tick.get('bid'),
            "ask": tick.get('ask'),
            "spot_price": tick.get('spot_price'),
            "volume": tick.get('volume'),
            "timestamp": tick.get('timestamp')
        }
    return {"error": "No tick data"}


@app.post("/api/command/{command}")
async def execute_command(command: str):
    """Execute bot command"""
    if not _bot_state:
        raise HTTPException(status_code=503, detail="Bot not connected")
    
    if command == "stop":
        _bot_state.state = "KILL_SWITCH"
        return {"success": True, "message": "Trading stopped - Kill switch activated"}
    
    elif command == "start":
        _bot_state.state = "IDLE"
        return {"success": True, "message": "Trading resumed - Bot is active"}
    
    elif command == "status":
        return await get_status()
    
    raise HTTPException(status_code=400, detail=f"Unknown command: {command}")


def _get_current_trade_detailed() -> Optional[Dict]:
    """Get current open trade with ALL details for dashboard"""
    if _bot_state and hasattr(_bot_state, 'current_trade') and _bot_state.current_trade:
        trade = _bot_state.current_trade
        entry_time = trade.get('entry_time')
        hold_time = 0
        if entry_time:
            hold_time = int((datetime.now() - entry_time).total_seconds())
        
        return {
            "direction": trade.get('direction'),
            "entry_price": trade.get('entry_price'),
            "current_price": trade.get('current_price'),
            "current_pnl": trade.get('current_pnl', 0),
            "price_diff": trade.get('price_diff', 0),
            "current_tsl": trade.get('current_tsl', -8),
            "max_profit_points": trade.get('max_profit_points', 0),
            "qty": trade.get('qty'),
            "entry_time": str(entry_time) if entry_time else None,
            "hold_time_sec": hold_time,
            "score": trade.get('score'),
            "confidence": trade.get('confidence'),
            "symbol": trade.get('symbol')
        }
    return None


# ==========================================
# WEBSOCKET FOR REAL-TIME UPDATES
# ==========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates - 0.5 second interval"""
    await manager.connect(websocket)
    try:
        while True:
            # Send status update every 0.5 seconds for faster updates
            status = await get_status()
            await websocket.send_json({
                "type": "status",
                "data": status
            })
            
            # Also send tick data if available
            if _recent_ticks and len(_recent_ticks) > 0:
                tick = _recent_ticks[-1]
                await websocket.send_json({
                    "type": "tick",
                    "data": {
                        "ltp": tick.get('ltp'),
                        "spot": tick.get('spot_price'),
                        "bid": tick.get('bid'),
                        "ask": tick.get('ask'),
                        "volume": tick.get('volume'),
                        "timestamp": tick.get('timestamp')
                    }
                })
            
            await asyncio.sleep(0.5)  # Faster updates
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_update(update_type: str, data: dict):
    """Broadcast update to all connected clients"""
    await manager.broadcast({
        "type": update_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })


# ==========================================
# PREMIUM TRADING DASHBOARD - PRO UI
# ==========================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTQ Trading Terminal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: #151c2c;
            --bg-card-hover: #1a2235;
            --border: #1e2a3a;
            --text-primary: #e2e8f0;
            --text-secondary: #8892a4;
            --accent-green: #00d26a;
            --accent-red: #ff4757;
            --accent-blue: #3b82f6;
            --accent-yellow: #fbbf24;
            --accent-purple: #8b5cf6;
        }
        
        * { box-sizing: border-box; }
        body { 
            font-family: 'Inter', sans-serif; 
            background: var(--bg-primary);
            color: var(--text-primary);
        }
        .mono { font-family: 'JetBrains Mono', monospace; }
        
        /* Glassmorphism Cards */
        .glass-card {
            background: linear-gradient(135deg, rgba(21, 28, 44, 0.9) 0%, rgba(17, 24, 39, 0.95) 100%);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            transition: all 0.3s ease;
        }
        .glass-card:hover {
            border-color: rgba(255, 255, 255, 0.1);
            transform: translateY(-2px);
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
        }
        
        /* Stat Cards */
        .stat-card {
            background: linear-gradient(145deg, #151c2c 0%, #0f1520 100%);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            position: relative;
            overflow: hidden;
        }
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple));
            opacity: 0;
            transition: opacity 0.3s;
        }
        .stat-card:hover::before { opacity: 1; }
        
        /* P&L Colors */
        .profit { color: var(--accent-green); }
        .loss { color: var(--accent-red); }
        .neutral { color: var(--text-secondary); }
        
        /* Pulse Animation */
        .live-pulse {
            animation: livePulse 2s ease-in-out infinite;
        }
        @keyframes livePulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 210, 106, 0.4); }
            50% { opacity: 0.8; box-shadow: 0 0 0 8px rgba(0, 210, 106, 0); }
        }
        
        /* Glow Effects */
        .glow-profit { box-shadow: 0 0 30px rgba(0, 210, 106, 0.2), inset 0 0 30px rgba(0, 210, 106, 0.05); }
        .glow-loss { box-shadow: 0 0 30px rgba(255, 71, 87, 0.2), inset 0 0 30px rgba(255, 71, 87, 0.05); }
        
        /* Progress Bar */
        .progress-bar {
            height: 4px;
            background: var(--border);
            border-radius: 2px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple));
            border-radius: 2px;
            transition: width 0.5s ease;
        }
        
        /* Table Styles */
        .trade-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
        }
        .trade-table th {
            background: rgba(30, 42, 58, 0.5);
            font-weight: 500;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            padding: 12px 16px;
            text-align: left;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        .trade-table td {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-size: 13px;
        }
        .trade-table tr:hover td {
            background: rgba(59, 130, 246, 0.05);
        }
        
        /* Buttons */
        .btn {
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 500;
            font-size: 13px;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .btn-danger {
            background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
            border: 1px solid #dc2626;
        }
        .btn-danger:hover {
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
            transform: scale(1.02);
        }
        .btn-success {
            background: linear-gradient(135deg, #059669 0%, #047857 100%);
            border: 1px solid #059669;
        }
        .btn-success:hover {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            transform: scale(1.02);
        }
        
        /* Scrollbar */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg-secondary); }
        ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #4b5563; }
        
        /* Badge */
        .badge {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .badge-paper { background: linear-gradient(135deg, #f59e0b, #d97706); }
        .badge-live { background: linear-gradient(135deg, #dc2626, #991b1b); }
        
        /* Direction Indicator */
        .direction-ce {
            background: linear-gradient(135deg, rgba(0, 210, 106, 0.2), rgba(0, 210, 106, 0.05));
            border: 1px solid rgba(0, 210, 106, 0.3);
            color: var(--accent-green);
        }
        .direction-pe {
            background: linear-gradient(135deg, rgba(255, 71, 87, 0.2), rgba(255, 71, 87, 0.05));
            border: 1px solid rgba(255, 71, 87, 0.3);
            color: var(--accent-red);
        }
        
        /* Market Status Indicator */
        .market-open { color: var(--accent-green); }
        .market-closed { color: var(--accent-red); }
        
        /* Metric with trend */
        .metric-trend {
            display: flex;
            align-items: baseline;
            gap: 8px;
        }
        .trend-up::after { content: '↑'; color: var(--accent-green); margin-left: 4px; }
        .trend-down::after { content: '↓'; color: var(--accent-red); margin-left: 4px; }
    </style>
</head>
<body class="min-h-screen">
    <!-- Header -->
    <header class="border-b border-[#1e2a3a] sticky top-0 z-50 bg-[#0a0e17]/95 backdrop-blur-xl">
        <div class="max-w-[1800px] mx-auto px-6 py-4">
            <div class="flex justify-between items-center">
                <div class="flex items-center gap-6">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-xl">
                            ⚡
                        </div>
                        <div>
                            <h1 class="text-lg font-semibold tracking-tight">PTQ Terminal</h1>
                            <p class="text-xs text-[#8892a4]">SMART SCALP v3.0</p>
                        </div>
                    </div>
                    <span id="mode-badge" class="badge badge-paper">PAPER MODE</span>
                    <div class="flex items-center gap-2 text-sm">
                        <span class="w-2 h-2 rounded-full bg-green-500 live-pulse"></span>
                        <span id="market-status" class="text-[#8892a4]">Market Open</span>
                    </div>
                </div>
                <div class="flex items-center gap-4">
                    <div class="text-right mr-4">
                        <p id="clock" class="mono text-xl font-medium">--:--:--</p>
                        <p id="date" class="text-xs text-[#8892a4]">Loading...</p>
                    </div>
                    <button onclick="sendCommand('stop')" class="btn btn-danger">
                        <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><rect width="10" height="10" x="3" y="3" rx="1"/></svg>
                        STOP
                    </button>
                    <button onclick="sendCommand('start')" class="btn btn-success">
                        <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M4 3.5l9 4.5-9 4.5V3.5z"/></svg>
                        START
                    </button>
                </div>
            </div>
        </div>
    </header>

    <main class="max-w-[1800px] mx-auto px-6 py-6">
        <!-- Hero Stats Row -->
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-6">
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Status</p>
                <p id="state" class="mono text-lg font-semibold text-blue-400">IDLE</p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Daily P&L</p>
                <p id="pnl" class="mono text-lg font-semibold">₹0.00</p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Return</p>
                <p id="pnl-pct" class="mono text-lg font-semibold">0.00%</p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Trades</p>
                <p id="trades-count" class="mono text-lg font-semibold">0</p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Win Rate</p>
                <p id="winrate" class="mono text-lg font-semibold">0%</p>
                <div class="progress-bar mt-2"><div id="winrate-bar" class="progress-fill" style="width:0%"></div></div>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">W / L</p>
                <p id="wl" class="mono text-lg font-semibold"><span class="profit">0</span> / <span class="loss">0</span></p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">India VIX</p>
                <p id="vix" class="mono text-lg font-semibold text-yellow-400">--</p>
            </div>
            <div class="stat-card">
                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Day Type</p>
                <p id="daytype" class="mono text-lg font-semibold text-purple-400">--</p>
            </div>
        </div>

        <!-- Main Content Grid -->
        <div class="grid grid-cols-12 gap-6 mb-6">
            <!-- Left Column: Market Data -->
            <div class="col-span-12 lg:col-span-3">
                <div class="glass-card p-5 h-full">
                    <div class="flex items-center justify-between mb-5">
                        <h3 class="font-semibold flex items-center gap-2">
                            <span class="w-2 h-2 rounded-full bg-red-500 live-pulse"></span>
                            Live Market
                        </h3>
                        <span class="text-xs text-[#8892a4]">Real-time</span>
                    </div>
                    
                    <div class="space-y-5">
                        <div class="bg-[#0f1520] rounded-xl p-4">
                            <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-2">NIFTY 50 SPOT</p>
                            <p id="spot" class="mono text-3xl font-bold text-yellow-400">--,---.--</p>
                        </div>
                        
                        <div class="bg-[#0f1520] rounded-xl p-4">
                            <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-2">Option LTP</p>
                            <p id="ltp" class="mono text-2xl font-bold">₹--.--</p>
                        </div>
                        
                        <div class="grid grid-cols-2 gap-3">
                            <div class="bg-[#0f1520] rounded-lg p-3">
                                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Bid</p>
                                <p id="bid" class="mono text-lg font-semibold profit">--</p>
                            </div>
                            <div class="bg-[#0f1520] rounded-lg p-3">
                                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Ask</p>
                                <p id="ask" class="mono text-lg font-semibold loss">--</p>
                            </div>
                            <div class="bg-[#0f1520] rounded-lg p-3">
                                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Spread</p>
                                <p id="spread" class="mono text-lg font-semibold">--%</p>
                            </div>
                            <div class="bg-[#0f1520] rounded-lg p-3">
                                <p class="text-[10px] uppercase tracking-wider text-[#8892a4] mb-1">Volume</p>
                                <p id="volume" class="mono text-lg font-semibold">--</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Center Column: Active Trade -->
            <div class="col-span-12 lg:col-span-5">
                <div class="glass-card p-5 h-full">
                    <div class="flex items-center justify-between mb-5">
                        <h3 class="font-semibold">🎯 Active Position</h3>
                        <span id="trade-status-badge" class="text-xs px-2 py-1 rounded bg-[#1e2a3a] text-[#8892a4]">No Position</span>
                    </div>
                    <div id="current-trade" class="min-h-[200px] flex items-center justify-center">
                        <div class="text-center text-[#8892a4]">
                            <div class="text-5xl mb-3 opacity-50">📊</div>
                            <p class="text-sm">Waiting for trade signal...</p>
                            <p class="text-xs mt-1">Bot is scanning for opportunities</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right Column: Config -->
            <div class="col-span-12 lg:col-span-4">
                <div class="glass-card p-5 h-full">
                    <div class="flex items-center justify-between mb-5">
                        <h3 class="font-semibold">⚙️ Configuration</h3>
                        <span class="text-xs text-[#8892a4]">From .env</span>
                    </div>
                    <div id="config-display" class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                        <p class="text-[#8892a4]">Loading...</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Charts Row -->
        <div class="grid grid-cols-12 gap-6 mb-6">
            <!-- P&L Chart -->
            <div class="col-span-12 lg:col-span-7">
                <div class="glass-card p-5">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="font-semibold">📈 P&L Timeline</h3>
                        <div class="flex items-center gap-2 text-xs text-[#8892a4]">
                            <span class="w-2 h-2 rounded-full bg-blue-500"></span> Live Updates
                        </div>
                    </div>
                    <div class="h-[250px]">
                        <canvas id="pnlChart"></canvas>
                    </div>
                </div>
            </div>

            <!-- CE vs PE -->
            <div class="col-span-12 lg:col-span-5">
                <div class="glass-card p-5">
                    <h3 class="font-semibold mb-4">📊 Direction Analysis</h3>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="direction-ce rounded-xl p-4 text-center">
                            <p class="text-2xl mb-2">📈</p>
                            <p class="font-bold text-lg">CALL (CE)</p>
                            <p id="ce-pnl" class="mono text-2xl font-bold mt-2">₹0</p>
                            <p id="ce-trades" class="text-xs mt-1 opacity-70">0 trades</p>
                            <p id="ce-winrate" class="text-xs opacity-70">0% win</p>
                        </div>
                        <div class="direction-pe rounded-xl p-4 text-center">
                            <p class="text-2xl mb-2">📉</p>
                            <p class="font-bold text-lg">PUT (PE)</p>
                            <p id="pe-pnl" class="mono text-2xl font-bold mt-2">₹0</p>
                            <p id="pe-trades" class="text-xs mt-1 opacity-70">0 trades</p>
                            <p id="pe-winrate" class="text-xs opacity-70">0% win</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- History & Hourly Row -->
        <div class="grid grid-cols-12 gap-6 mb-6">
            <!-- Weekly History -->
            <div class="col-span-12 lg:col-span-5">
                <div class="glass-card p-5">
                    <h3 class="font-semibold mb-4">📅 7-Day Performance</h3>
                    <div id="weekly-history" class="space-y-2 max-h-[220px] overflow-y-auto pr-2">
                        <p class="text-[#8892a4] text-sm">Loading history...</p>
                    </div>
                </div>
            </div>

            <!-- Hourly Chart -->
            <div class="col-span-12 lg:col-span-7">
                <div class="glass-card p-5">
                    <h3 class="font-semibold mb-4">⏰ Hourly Breakdown</h3>
                    <div class="h-[220px]">
                        <canvas id="hourlyChart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <!-- Trades Table -->
        <div class="glass-card p-5 mb-6">
            <div class="flex items-center justify-between mb-4">
                <h3 class="font-semibold">📝 Today's Trades</h3>
                <span id="trades-summary" class="text-sm text-[#8892a4]">0 trades • ₹0 P&L</span>
            </div>
            <div class="overflow-x-auto max-h-[350px] overflow-y-auto rounded-lg border border-[#1e2a3a]">
                <table class="trade-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Time</th>
                            <th>Direction</th>
                            <th>Symbol</th>
                            <th>Entry</th>
                            <th>Exit</th>
                            <th>Qty</th>
                            <th>Points</th>
                            <th>P&L</th>
                            <th>Duration</th>
                            <th>Score</th>
                            <th>Exit Reason</th>
                        </tr>
                    </thead>
                    <tbody id="trades-table">
                        <tr><td colspan="12" class="text-center py-8 text-[#8892a4]">No trades executed today</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Signals Table -->
        <div class="glass-card p-5">
            <div class="flex items-center justify-between mb-4">
                <h3 class="font-semibold">📡 Signal History</h3>
                <span id="signals-summary" class="text-sm text-[#8892a4]">Recent trading signals</span>
            </div>
            <div class="overflow-x-auto max-h-[280px] overflow-y-auto rounded-lg border border-[#1e2a3a]">
                <table class="trade-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Direction</th>
                            <th>Score</th>
                            <th>Confidence</th>
                            <th>RSI</th>
                            <th>MACD</th>
                            <th>Regime</th>
                            <th>Spot</th>
                            <th>Executed</th>
                        </tr>
                    </thead>
                    <tbody id="signals-table">
                        <tr><td colspan="9" class="text-center py-8 text-[#8892a4]">No signals recorded yet</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <!-- Footer -->
    <footer class="border-t border-[#1e2a3a] mt-8 py-4">
        <div class="max-w-[1800px] mx-auto px-6">
            <div class="flex justify-between items-center text-sm text-[#8892a4]">
                <div class="flex items-center gap-6">
                    <span>PTQ Terminal v3.0</span>
                    <span class="text-[#3b4a5f]">•</span>
                    <span>SMART SCALP Strategy</span>
                </div>
                <div class="flex items-center gap-6 mono text-xs">
                    <span>Loop: <span id="loop-count" class="text-white">0</span></span>
                    <span>Hourly: <span id="trades-hour" class="text-white">0</span></span>
                    <span>Consec Loss: <span id="consec-loss" class="text-yellow-400">0</span></span>
                </div>
            </div>
        </div>
    </footer>

    <!-- Toast Container -->
    <div id="toast-container" class="fixed top-20 right-6 z-50 space-y-2"></div>

    <script>
        let ws;
        let pnlChart, hourlyChart;
        let pnlData = [];
        let pnlLabels = [];

        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
            connectWebSocket();
            loadInitialData();
            updateClock();
            setInterval(updateClock, 1000);
            setInterval(loadTrades, 10000);
            setInterval(loadSignals, 15000);
            setInterval(loadDirectionStats, 30000);
        });

        function updateClock() {
            const now = new Date();
            document.getElementById('clock').textContent = now.toLocaleTimeString('en-IN', {hour12: false});
            document.getElementById('date').textContent = now.toLocaleDateString('en-IN', {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'});
            
            // Market status
            const hour = now.getHours();
            const min = now.getMinutes();
            const timeNum = hour * 100 + min;
            const isOpen = timeNum >= 915 && timeNum <= 1530;
            document.getElementById('market-status').textContent = isOpen ? 'Market Open' : 'Market Closed';
            document.getElementById('market-status').className = isOpen ? 'market-open' : 'market-closed';
        }

        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            const colors = {
                success: 'bg-green-600 border-green-500',
                error: 'bg-red-600 border-red-500',
                info: 'bg-blue-600 border-blue-500'
            };
            toast.className = `px-4 py-3 rounded-lg border ${colors[type]} text-white text-sm shadow-xl transform transition-all duration-300 translate-x-full`;
            toast.textContent = message;
            container.appendChild(toast);
            
            setTimeout(() => toast.classList.remove('translate-x-full'), 10);
            setTimeout(() => {
                toast.classList.add('translate-x-full', 'opacity-0');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        function initCharts() {
            Chart.defaults.color = '#8892a4';
            Chart.defaults.borderColor = '#1e2a3a';
            
            // P&L Chart
            const pnlCtx = document.getElementById('pnlChart').getContext('2d');
            pnlChart = new Chart(pnlCtx, {
                type: 'line',
                data: {
                    labels: pnlLabels,
                    datasets: [{
                        label: 'P&L',
                        data: pnlData,
                        borderColor: '#3b82f6',
                        backgroundColor: (ctx) => {
                            const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 250);
                            gradient.addColorStop(0, 'rgba(59, 130, 246, 0.3)');
                            gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');
                            return gradient;
                        },
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    interaction: { intersect: false, mode: 'index' },
                    scales: {
                        y: { 
                            grid: { color: 'rgba(30,42,58,0.5)' },
                            ticks: { callback: v => '₹' + v.toLocaleString() }
                        },
                        x: { 
                            grid: { display: false },
                            ticks: { maxTicksLimit: 8 }
                        }
                    }
                }
            });

            // Hourly Chart
            const hourlyCtx = document.getElementById('hourlyChart').getContext('2d');
            hourlyChart = new Chart(hourlyCtx, {
                type: 'bar',
                data: {
                    labels: ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
                    datasets: [{
                        label: 'P&L',
                        data: [0, 0, 0, 0, 0, 0, 0],
                        backgroundColor: '#3b82f6',
                        borderRadius: 6,
                        borderSkipped: false
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { 
                            grid: { color: 'rgba(30,42,58,0.5)' },
                            ticks: { callback: v => '₹' + v }
                        },
                        x: { grid: { display: false } }
                    }
                }
            });
        }

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => showToast('Connected to trading server', 'success');
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === 'status') updateStatus(msg.data);
                else if (msg.type === 'tick') updateTick(msg.data);
            };
            ws.onclose = () => {
                showToast('Connection lost. Reconnecting...', 'error');
                setTimeout(connectWebSocket, 3000);
            };
        }

        function updateStatus(data) {
            // State
            const stateEl = document.getElementById('state');
            stateEl.textContent = data.state;
            const stateColors = {
                'IDLE': 'text-blue-400',
                'ENTRY_READY': 'text-yellow-400', 
                'IN_TRADE': 'text-orange-400',
                'COOLDOWN': 'text-purple-400',
                'KILL_SWITCH': 'text-red-400'
            };
            stateEl.className = `mono text-lg font-semibold ${stateColors[data.state] || ''}`;
            
            // P&L
            const pnl = data.daily_pnl || 0;
            const pnlEl = document.getElementById('pnl');
            pnlEl.textContent = `₹${pnl.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            pnlEl.className = `mono text-lg font-semibold ${pnl >= 0 ? 'profit' : 'loss'}`;
            
            const pnlPct = data.daily_pnl_pct || 0;
            const pnlPctEl = document.getElementById('pnl-pct');
            pnlPctEl.textContent = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
            pnlPctEl.className = `mono text-lg font-semibold ${pnlPct >= 0 ? 'profit' : 'loss'}`;
            
            // Trades
            document.getElementById('trades-count').textContent = data.total_trades || 0;
            document.getElementById('wl').innerHTML = `<span class="profit">${data.winning_trades || 0}</span> / <span class="loss">${data.losing_trades || 0}</span>`;
            
            const winRate = data.total_trades > 0 ? ((data.winning_trades / data.total_trades) * 100) : 0;
            const winrateEl = document.getElementById('winrate');
            winrateEl.textContent = `${winRate.toFixed(0)}%`;
            winrateEl.className = `mono text-lg font-semibold ${winRate >= 50 ? 'profit' : winRate > 0 ? 'loss' : ''}`;
            document.getElementById('winrate-bar').style.width = `${winRate}%`;
            
            // VIX & Day Type
            document.getElementById('vix').textContent = `${(data.estimated_vix || 15).toFixed(1)}`;
            document.getElementById('daytype').textContent = data.day_type || '--';
            
            // Footer
            document.getElementById('loop-count').textContent = data.loop_count || 0;
            document.getElementById('trades-hour').textContent = data.trades_this_hour || 0;
            document.getElementById('consec-loss').textContent = data.consecutive_losses || 0;
            
            updateCurrentTrade(data.current_trade);
            updateChart(pnl);
        }

        function updateTick(data) {
            if (data.spot) document.getElementById('spot').textContent = parseFloat(data.spot).toLocaleString('en-IN', {minimumFractionDigits: 2});
            if (data.ltp) document.getElementById('ltp').textContent = `₹${parseFloat(data.ltp).toFixed(2)}`;
            if (data.bid) document.getElementById('bid').textContent = `₹${parseFloat(data.bid).toFixed(2)}`;
            if (data.ask) document.getElementById('ask').textContent = `₹${parseFloat(data.ask).toFixed(2)}`;
            if (data.bid && data.ask && data.ltp) {
                const spread = ((data.ask - data.bid) / data.ltp * 100).toFixed(3);
                document.getElementById('spread').textContent = `${spread}%`;
            }
            if (data.volume) document.getElementById('volume').textContent = parseInt(data.volume).toLocaleString();
        }

        function updateCurrentTrade(trade) {
            const el = document.getElementById('current-trade');
            const badge = document.getElementById('trade-status-badge');
            
            if (!trade) {
                badge.textContent = 'No Position';
                badge.className = 'text-xs px-2 py-1 rounded bg-[#1e2a3a] text-[#8892a4]';
                el.innerHTML = `
                    <div class="text-center text-[#8892a4] py-8">
                        <div class="text-5xl mb-3 opacity-50">📊</div>
                        <p class="text-sm">Waiting for trade signal...</p>
                        <p class="text-xs mt-1">Bot is scanning for opportunities</p>
                    </div>
                `;
                el.parentElement.classList.remove('glow-profit', 'glow-loss');
                return;
            }
            
            const pnl = trade.current_pnl || 0;
            const isProfit = pnl >= 0;
            const dirClass = trade.direction === 'CE' ? 'direction-ce' : 'direction-pe';
            const parentCard = el.parentElement;
            
            parentCard.classList.remove('glow-profit', 'glow-loss');
            parentCard.classList.add(isProfit ? 'glow-profit' : 'glow-loss');
            
            badge.textContent = '● LIVE TRADE';
            badge.className = `text-xs px-2 py-1 rounded ${isProfit ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`;
            
            el.innerHTML = `
                <div class="space-y-4">
                    <div class="flex items-center justify-between">
                        <div class="${dirClass} px-4 py-2 rounded-lg">
                            <span class="text-2xl mr-2">${trade.direction === 'CE' ? '📈' : '📉'}</span>
                            <span class="font-bold text-xl">${trade.direction || '--'}</span>
                        </div>
                        <div class="text-right">
                            <p class="text-xs text-[#8892a4]">Current P&L</p>
                            <p class="mono text-3xl font-bold ${isProfit ? 'profit' : 'loss'}">₹${pnl.toFixed(2)}</p>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-4 gap-3">
                        <div class="bg-[#0f1520] rounded-lg p-3 text-center">
                            <p class="text-[10px] uppercase text-[#8892a4]">Entry</p>
                            <p class="mono font-semibold">₹${(trade.entry_price || 0).toFixed(2)}</p>
                        </div>
                        <div class="bg-[#0f1520] rounded-lg p-3 text-center">
                            <p class="text-[10px] uppercase text-[#8892a4]">Points</p>
                            <p class="mono font-semibold ${isProfit ? 'profit' : 'loss'}">${(trade.price_diff || 0).toFixed(2)}</p>
                        </div>
                        <div class="bg-[#0f1520] rounded-lg p-3 text-center">
                            <p class="text-[10px] uppercase text-[#8892a4]">TSL</p>
                            <p class="mono font-semibold text-orange-400">${(trade.current_tsl || -8).toFixed(1)}</p>
                        </div>
                        <div class="bg-[#0f1520] rounded-lg p-3 text-center">
                            <p class="text-[10px] uppercase text-[#8892a4]">Max Profit</p>
                            <p class="mono font-semibold profit">${(trade.max_profit_points || 0).toFixed(1)}</p>
                        </div>
                    </div>
                    
                    <div class="flex justify-between text-sm text-[#8892a4]">
                        <span>Qty: <span class="text-white">${trade.qty || '--'}</span></span>
                        <span>Hold: <span class="text-white">${trade.hold_time_sec || 0}s</span></span>
                        <span>Score: <span class="text-white">${trade.score || '--'}</span></span>
                        <span>Conf: <span class="text-white">${trade.confidence || '--'}%</span></span>
                    </div>
                </div>
            `;
        }

        function updateChart(pnl) {
            const now = new Date().toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit'});
            if (pnlLabels.length > 120) { pnlLabels.shift(); pnlData.shift(); }
            pnlLabels.push(now);
            pnlData.push(pnl);
            pnlChart.update('none');
        }

        async function loadInitialData() {
            try {
                const configResp = await fetch('/api/config');
                const config = await configResp.json();
                
                const badge = document.getElementById('mode-badge');
                badge.textContent = config.paper_trading ? 'PAPER MODE' : 'LIVE MODE';
                badge.className = `badge ${config.paper_trading ? 'badge-paper' : 'badge-live'}`;
                
                document.getElementById('config-display').innerHTML = `
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Capital</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium">₹${(config.capital || 0).toLocaleString()}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Data Source</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium">${config.use_live_data ? '🔴 LIVE' : '🟡 SIMULATED'}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">CE / PE Qty</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium mono">${config.ce_quantity || '-'} / ${config.pe_quantity || '-'}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">SL / TP</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium"><span class="loss">${config.sl_points || '-'}</span> / <span class="profit">${config.tp_points || '-'}</span> pts</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Trailing SL</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium">${config.tsl_enabled ? '<span class="profit">✓ Enabled</span>' : '<span class="loss">✗ Disabled</span>'}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Min Score</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium mono">${config.min_score || '-'}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Max Daily Trades</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium mono">${config.max_trades_day || '-'}</div>
                    
                    <div class="py-2 border-b border-[#1e2a3a]"><span class="text-[#8892a4]">Kill Switch</span></div>
                    <div class="py-2 border-b border-[#1e2a3a] text-right font-medium loss">-₹${Math.abs(config.kill_switch || 0).toLocaleString()}</div>
                    
                    <div class="py-2"><span class="text-[#8892a4]">Market Hours</span></div>
                    <div class="py-2 text-right font-medium mono text-xs">${config.market_open || '09:15'} - ${config.market_close || '15:15'}</div>
                `;
            } catch(e) { console.error('Config load failed:', e); }

            loadDirectionStats();
            loadWeeklyHistory();
            loadHourlyStats();
            loadTrades();
            loadSignals();
        }

        async function loadDirectionStats() {
            try {
                const resp = await fetch('/api/analytics/direction');
                const data = await resp.json();
                if (data.data) {
                    const ce = data.data.CE || {total_pnl: 0, total_trades: 0, wins: 0};
                    const pe = data.data.PE || {total_pnl: 0, total_trades: 0, wins: 0};
                    
                    const cePnl = document.getElementById('ce-pnl');
                    cePnl.textContent = `₹${(ce.total_pnl || 0).toFixed(0)}`;
                    cePnl.className = `mono text-2xl font-bold mt-2 ${(ce.total_pnl || 0) >= 0 ? 'profit' : 'loss'}`;
                    document.getElementById('ce-trades').textContent = `${ce.total_trades || 0} trades`;
                    document.getElementById('ce-winrate').textContent = `${ce.total_trades > 0 ? ((ce.wins || 0) / ce.total_trades * 100).toFixed(0) : 0}% win rate`;
                    
                    const pePnl = document.getElementById('pe-pnl');
                    pePnl.textContent = `₹${(pe.total_pnl || 0).toFixed(0)}`;
                    pePnl.className = `mono text-2xl font-bold mt-2 ${(pe.total_pnl || 0) >= 0 ? 'profit' : 'loss'}`;
                    document.getElementById('pe-trades').textContent = `${pe.total_trades || 0} trades`;
                    document.getElementById('pe-winrate').textContent = `${pe.total_trades > 0 ? ((pe.wins || 0) / pe.total_trades * 100).toFixed(0) : 0}% win rate`;
                }
            } catch(e) { console.error('Direction stats failed:', e); }
        }

        async function loadWeeklyHistory() {
            try {
                const resp = await fetch('/api/trades/history?days=7');
                const data = await resp.json();
                const container = document.getElementById('weekly-history');
                
                if (data.history && data.history.length > 0) {
                    container.innerHTML = data.history.map(day => `
                        <div class="flex items-center justify-between bg-[#0f1520] rounded-lg p-3 hover:bg-[#151d2d] transition cursor-pointer">
                            <div>
                                <p class="font-medium">${day.date}</p>
                                <p class="text-xs text-[#8892a4]">${day.trades} trades • ${day.win_rate.toFixed(0)}% win</p>
                            </div>
                            <div class="text-right">
                                <p class="mono font-bold ${day.pnl >= 0 ? 'profit' : 'loss'}">₹${day.pnl.toFixed(0)}</p>
                                <p class="text-xs text-[#8892a4]">${day.wins}W / ${day.losses}L</p>
                            </div>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<p class="text-center py-8 text-[#8892a4]">No history available</p>';
                }
            } catch(e) { console.error('Weekly history failed:', e); }
        }

        async function loadHourlyStats() {
            try {
                const resp = await fetch('/api/analytics/hourly');
                const data = await resp.json();
                if (data.data && data.data.length > 0) {
                    const labels = data.data.map(h => h.hour + ':00');
                    const values = data.data.map(h => h.total_pnl || 0);
                    const colors = values.map(v => v >= 0 ? '#00d26a' : '#ff4757');
                    hourlyChart.data.labels = labels;
                    hourlyChart.data.datasets[0].data = values;
                    hourlyChart.data.datasets[0].backgroundColor = colors;
                    hourlyChart.update();
                }
            } catch(e) { console.error('Hourly stats failed:', e); }
        }

        async function loadTrades() {
            try {
                const resp = await fetch('/api/trades');
                const data = await resp.json();
                const tbody = document.getElementById('trades-table');
                
                if (!data.trades || data.trades.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="12" class="text-center py-8 text-[#8892a4]">No trades executed today</td></tr>';
                    document.getElementById('trades-summary').textContent = '0 trades • ₹0 P&L';
                    return;
                }
                
                const totalPnl = data.trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
                document.getElementById('trades-summary').textContent = `${data.trades.length} trades • ₹${totalPnl.toFixed(0)} P&L`;
                
                tbody.innerHTML = data.trades.map((trade, i) => {
                    const points = trade.exit_price && trade.entry_price ? (trade.exit_price - trade.entry_price) : 0;
                    const pnl = trade.pnl || 0;
                    return `
                    <tr>
                        <td class="text-[#8892a4]">${i + 1}</td>
                        <td class="mono text-xs">${trade.entry_time ? new Date(trade.entry_time).toLocaleTimeString('en-IN') : '-'}</td>
                        <td><span class="px-2 py-1 rounded text-xs font-medium ${trade.direction === 'CE' ? 'direction-ce' : 'direction-pe'}">${trade.direction === 'CE' ? '📈 CE' : '📉 PE'}</span></td>
                        <td class="text-xs text-[#8892a4] max-w-[120px] truncate">${trade.symbol || '-'}</td>
                        <td class="mono">₹${(trade.entry_price || 0).toFixed(2)}</td>
                        <td class="mono">₹${(trade.exit_price || 0).toFixed(2)}</td>
                        <td class="mono">${trade.qty || '-'}</td>
                        <td class="mono ${points >= 0 ? 'profit' : 'loss'}">${points >= 0 ? '+' : ''}${points.toFixed(2)}</td>
                        <td class="mono font-bold ${pnl >= 0 ? 'profit' : 'loss'}">₹${pnl.toFixed(0)}</td>
                        <td class="mono text-xs">${trade.hold_time_sec || 0}s</td>
                        <td class="mono">${trade.score || '-'}</td>
                        <td class="text-xs text-[#8892a4] max-w-[100px] truncate" title="${trade.exit_reason || ''}">${trade.exit_reason || '-'}</td>
                    </tr>
                `}).join('');
            } catch(e) { console.error('Failed to load trades:', e); }
        }

        async function loadSignals() {
            try {
                const resp = await fetch('/api/signals');
                const data = await resp.json();
                const tbody = document.getElementById('signals-table');
                
                if (!data.signals || data.signals.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="9" class="text-center py-8 text-[#8892a4]">No signals recorded yet</td></tr>';
                    return;
                }
                
                const taken = data.signals.filter(s => s.was_taken).length;
                document.getElementById('signals-summary').textContent = `${data.signals.length} signals • ${taken} executed (${(taken/data.signals.length*100).toFixed(0)}%)`;
                
                tbody.innerHTML = data.signals.slice(0, 30).map(sig => `
                    <tr class="${sig.was_taken ? 'bg-blue-900/10' : ''}">
                        <td class="mono text-xs">${sig.timestamp ? new Date(sig.timestamp).toLocaleTimeString('en-IN') : '-'}</td>
                        <td><span class="px-2 py-1 rounded text-xs font-medium ${sig.direction === 'CE' ? 'direction-ce' : sig.direction === 'PE' ? 'direction-pe' : 'bg-[#1e2a3a]'}">${sig.direction === 'CE' ? '📈 CE' : sig.direction === 'PE' ? '📉 PE' : '--'}</span></td>
                        <td class="mono font-bold">${sig.score || '-'}</td>
                        <td class="mono">${sig.confidence || '-'}%</td>
                        <td class="mono text-xs">${sig.rsi ? sig.rsi.toFixed(1) : '-'}</td>
                        <td class="mono text-xs">${sig.macd_hist ? sig.macd_hist.toFixed(3) : '-'}</td>
                        <td class="text-xs">${sig.regime || '-'}</td>
                        <td class="mono">₹${sig.spot_price ? parseFloat(sig.spot_price).toFixed(0) : '-'}</td>
                        <td>${sig.was_taken ? '<span class="profit">✓ Yes</span>' : '<span class="text-[#8892a4]">✗ No</span>'}</td>
                    </tr>
                `).join('');
            } catch(e) { console.error('Failed to load signals:', e); }
        }

        async function sendCommand(cmd) {
            try {
                const resp = await fetch(`/api/command/${cmd}`, { method: 'POST' });
                const data = await resp.json();
                showToast(data.message || 'Command executed', data.success ? 'success' : 'error');
            } catch(e) {
                showToast('Failed to send command: ' + e.message, 'error');
            }
        }
    </script>
</body>
</html>
"""


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Run the dashboard server"""
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_dashboard_background(host: str = "0.0.0.0", port: int = 8080):
    """Start dashboard in background thread"""
    import threading
    thread = threading.Thread(
        target=run_dashboard,
        args=(host, port),
        daemon=True
    )
    thread.start()
    return thread
