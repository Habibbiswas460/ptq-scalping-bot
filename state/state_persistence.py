import json
import os
from datetime import datetime
from typing import Any, Dict

STATE_FILE = "logs/bot_state.json"

def save_daily_state(state: Dict[str, Any]):
    """Save daily trading state to file for persistence across restarts"""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save state: {e}")

def load_daily_state() -> Dict[str, Any]:
    """Load daily trading state from file if it's from today"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        if not os.path.exists(STATE_FILE):
            print("📝 No saved state found, starting fresh")
            return {}
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
        if state.get('date') != today:
            print(f"📅 Saved state is from {state.get('date')}, starting fresh for {today}")
            return {}
        print(f"✅ Restored today's state: PnL ₹{state.get('daily_pnl_inr', 0):+.2f} | Trades: {state.get('total_trades_today', 0)} | W/L: {state.get('winning_trades', 0)}/{state.get('losing_trades', 0)}")
        return state
    except Exception as e:
        print(f"⚠️ Failed to load state: {e}")
        return {}