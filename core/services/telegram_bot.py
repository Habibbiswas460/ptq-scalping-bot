"""
PTQ Scalping Bot - Telegram Notifications
Real-time alerts, daily summaries, and remote commands
"""

import asyncio
import aiohttp
import threading
from datetime import datetime
from typing import Dict, Optional, Callable, List
from queue import Queue
import json


class TelegramBot:
    """Telegram bot for notifications and remote commands"""
    
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        # Message queue for async sending
        self._message_queue: Queue = Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Command handlers
        self._commands: Dict[str, Callable] = {}
        self._register_default_commands()
        
        # Bot state reference (set by main bot)
        self.bot_state = None
        self.broker = None
    
    def _register_default_commands(self):
        """Register default bot commands"""
        self._commands = {
            '/status': self._cmd_status,
            '/pnl': self._cmd_pnl,
            '/trades': self._cmd_trades,
            '/stop': self._cmd_stop,
            '/start_bot': self._cmd_start_bot,
            '/help': self._cmd_help,
        }
    
    def set_state_reference(self, state, broker=None):
        """Set reference to bot state for status commands"""
        self.bot_state = state
        self.broker = broker
    
    def register_command(self, command: str, handler: Callable):
        """Register custom command handler"""
        self._commands[command] = handler
    
    # ==========================================
    # NOTIFICATION METHODS
    # ==========================================
    
    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Queue message for sending"""
        if not self.enabled:
            return
        self._message_queue.put({
            'text': text,
            'parse_mode': parse_mode
        })
    
    async def _send_message_async(self, text: str, parse_mode: str = "HTML"):
        """Actually send message to Telegram"""
        if not self.enabled or not self.token or not self.chat_id:
            return False
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': parse_mode
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    return resp.status == 200
        except Exception as e:
            print(f"⚠️ Telegram send error: {e}")
            return False
    
    def notify_entry(self, trade: Dict):
        """Send trade entry notification"""
        direction = trade.get('direction', 'CE')
        emoji = "🟢" if direction == "CE" else "🔴"
        
        message = f"""
{emoji} <b>TRADE ENTRY</b> {emoji}

📊 <b>Direction:</b> {direction}
💰 <b>Entry Price:</b> ₹{trade.get('entry_price', 0):.2f}
📦 <b>Quantity:</b> {trade.get('qty', 0)}
🎯 <b>Score:</b> {trade.get('score', 0)} | Conf: {trade.get('confidence', 0)}%

📝 <b>Reason:</b> {trade.get('entry_reason', 'N/A')[:100]}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_message(message.strip())
    
    def notify_exit(self, trade: Dict, pnl: float, exit_reason: str):
        """Send trade exit notification"""
        emoji = "✅" if pnl > 0 else "❌"
        pnl_emoji = "📈" if pnl > 0 else "📉"
        
        message = f"""
{emoji} <b>TRADE EXIT</b> {emoji}

{pnl_emoji} <b>P&L:</b> ₹{pnl:+,.2f}
💰 <b>Entry:</b> ₹{trade.get('entry_price', 0):.2f}
💰 <b>Exit:</b> ₹{trade.get('exit_price', 0):.2f}
⏱ <b>Hold Time:</b> {trade.get('hold_time_sec', 0)}s

📝 <b>Exit Reason:</b> {exit_reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_message(message.strip())
    
    def notify_kill_switch(self, reason: str, details: Dict):
        """Send kill switch alert"""
        message = f"""
🚨🚨🚨 <b>KILL SWITCH ACTIVATED</b> 🚨🚨🚨

⚠️ <b>Reason:</b> {reason}

📊 <b>Details:</b>
{json.dumps(details, indent=2)}

⏰ {datetime.now().strftime('%H:%M:%S')}

<i>Trading halted. Manual intervention required.</i>
"""
        self.send_message(message.strip())
    
    def notify_daily_summary(self, summary: Dict):
        """Send daily trading summary"""
        win_rate = summary.get('win_rate', 0)
        total_pnl = summary.get('total_pnl', 0)
        pnl_emoji = "🎉" if total_pnl > 0 else "😔"
        
        message = f"""
📊 <b>DAILY TRADING SUMMARY</b> 📊

{pnl_emoji} <b>Total P&L:</b> ₹{total_pnl:+,.2f}

📈 <b>Statistics:</b>
• Trades: {summary.get('total_trades', 0)}
• Wins: {summary.get('winning_trades', 0)} | Losses: {summary.get('losing_trades', 0)}
• Win Rate: {win_rate:.1f}%
• Profit Factor: {summary.get('profit_factor', 0):.2f}x

💰 <b>Averages:</b>
• Avg Win: ₹{summary.get('avg_win', 0):+,.2f}
• Avg Loss: ₹{summary.get('avg_loss', 0):+,.2f}

🎯 <b>Direction Breakdown:</b>
• CE: {summary.get('ce_trades', 0)} trades | ₹{summary.get('ce_pnl', 0):+,.2f}
• PE: {summary.get('pe_trades', 0)} trades | ₹{summary.get('pe_pnl', 0):+,.2f}

📅 {datetime.now().strftime('%Y-%m-%d')}
"""
        self.send_message(message.strip())
    
    def notify_startup(self, config: Dict):
        """Send bot startup notification"""
        message = f"""
🚀 <b>PTQ SCALPING BOT STARTED</b> 🚀

💰 <b>Capital:</b> ₹{config.get('capital', 30000):,}
📊 <b>Mode:</b> {'PAPER' if config.get('paper_trading', True) else 'LIVE'}
🎯 <b>Strategy:</b> SMART SCALP v3.0

⚙️ <b>Settings:</b>
• CE Qty: {config.get('ce_qty', 260)}
• PE Qty: {config.get('pe_qty', 156)}
• SL: {config.get('sl_points', 8)} pts
• TP: {config.get('tp_points', 16)} pts

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_message(message.strip())
    
    def notify_shutdown(self, summary: Dict):
        """Send bot shutdown notification"""
        message = f"""
🛑 <b>PTQ SCALPING BOT STOPPED</b> 🛑

📊 <b>Final Summary:</b>
• P&L: ₹{summary.get('daily_pnl', 0):+,.2f}
• Trades: {summary.get('total_trades', 0)}
• Win Rate: {summary.get('win_rate', 0):.1f}%

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_message(message.strip())
    
    def notify_error(self, error: str):
        """Send error notification"""
        message = f"""
⚠️ <b>ERROR ALERT</b> ⚠️

{error[:500]}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_message(message.strip())
    
    # ==========================================
    # COMMAND HANDLERS
    # ==========================================
    
    def _cmd_status(self) -> str:
        """Get current bot status"""
        if not self.bot_state:
            return "❌ Bot state not available"
        
        state = self.bot_state
        return f"""
🤖 <b>BOT STATUS</b>

📊 <b>State:</b> {getattr(state, 'state', 'UNKNOWN')}
💰 <b>Daily P&L:</b> ₹{getattr(state, 'daily_pnl_inr', 0):+,.2f}
📈 <b>Trades Today:</b> {getattr(state, 'total_trades_today', 0)}
🎯 <b>W/L:</b> {getattr(state, 'winning_trades', 0)}W/{getattr(state, 'losing_trades', 0)}L
⏱ <b>Consecutive Losses:</b> {getattr(state, 'consecutive_losses', 0)}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    
    def _cmd_pnl(self) -> str:
        """Get current P&L"""
        if not self.bot_state:
            return "❌ Bot state not available"
        
        pnl = getattr(self.bot_state, 'daily_pnl_inr', 0)
        pnl_pct = getattr(self.bot_state, 'daily_pnl_pct', 0)
        emoji = "📈" if pnl >= 0 else "📉"
        
        return f"""
{emoji} <b>Current P&L</b>

💰 ₹{pnl:+,.2f} ({pnl_pct:+.2f}%)

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    
    def _cmd_trades(self) -> str:
        """Get today's trades"""
        try:
            from core.services.database import get_todays_trades
            trades = get_todays_trades()
            
            if not trades:
                return "📝 No trades today"
            
            lines = ["📝 <b>Today's Trades</b>\n"]
            for i, t in enumerate(trades[:10], 1):
                emoji = "✅" if t['pnl'] > 0 else "❌" if t['pnl'] < 0 else "⏳"
                lines.append(f"{i}. {emoji} {t['direction']} | ₹{t['pnl']:+,.0f}")
            
            if len(trades) > 10:
                lines.append(f"\n<i>...and {len(trades)-10} more</i>")
            
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"
    
    def _cmd_stop(self) -> str:
        """Stop trading (keep monitoring)"""
        if self.bot_state:
            self.bot_state.state = "KILL_SWITCH"
            return "🛑 Trading stopped. Bot will continue monitoring."
        return "❌ Cannot stop - bot state not available"
    
    def _cmd_start_bot(self) -> str:
        """Resume trading"""
        if self.bot_state:
            self.bot_state.state = "IDLE"
            return "✅ Trading resumed."
        return "❌ Cannot start - bot state not available"
    
    def _cmd_help(self) -> str:
        """Show available commands"""
        return """
🤖 <b>Available Commands</b>

/status - Current bot status
/pnl - Today's P&L
/trades - Today's trades
/stop - Stop trading (monitoring continues)
/start_bot - Resume trading
/help - Show this message
"""
    
    # ==========================================
    # POLLING & BACKGROUND PROCESSING
    # ==========================================
    
    def start(self):
        """Start background message sender"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._background_worker, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop background worker"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _background_worker(self):
        """Background worker for sending messages and polling"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def worker():
            last_update_id = 0
            
            while self._running:
                # Send queued messages
                while not self._message_queue.empty():
                    try:
                        msg = self._message_queue.get_nowait()
                        await self._send_message_async(msg['text'], msg.get('parse_mode', 'HTML'))
                    except Exception:
                        pass
                
                # Poll for commands
                try:
                    updates = await self._get_updates(last_update_id + 1)
                    for update in updates:
                        last_update_id = update.get('update_id', last_update_id)
                        await self._handle_update(update)
                except Exception:
                    pass
                
                await asyncio.sleep(1)
        
        loop.run_until_complete(worker())
    
    async def _get_updates(self, offset: int = 0) -> List[Dict]:
        """Get updates from Telegram"""
        if not self.enabled or not self.token:
            return []
        
        url = f"{self.base_url}/getUpdates"
        params = {'offset': offset, 'timeout': 1}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('result', [])
        except Exception:
            pass
        return []
    
    async def _handle_update(self, update: Dict):
        """Handle incoming update"""
        message = update.get('message', {})
        text = message.get('text', '')
        chat_id = str(message.get('chat', {}).get('id', ''))
        
        # Only respond to authorized chat
        if chat_id != self.chat_id:
            return
        
        # Check if it's a command
        if text.startswith('/'):
            command = text.split()[0].lower()
            if command in self._commands:
                try:
                    response = self._commands[command]()
                    await self._send_message_async(response)
                except Exception as e:
                    await self._send_message_async(f"❌ Error: {e}")


# Singleton instance
_telegram_bot: Optional[TelegramBot] = None


def init_telegram(token: str, chat_id: str, enabled: bool = True) -> TelegramBot:
    """Initialize Telegram bot singleton"""
    global _telegram_bot
    _telegram_bot = TelegramBot(token, chat_id, enabled)
    _telegram_bot.start()
    return _telegram_bot


def get_telegram() -> Optional[TelegramBot]:
    """Get Telegram bot instance"""
    return _telegram_bot


# Convenience functions
def send_telegram(message: str):
    """Quick send message"""
    if _telegram_bot:
        _telegram_bot.send_message(message)

def notify_entry(trade: Dict):
    if _telegram_bot:
        _telegram_bot.notify_entry(trade)

def notify_exit(trade: Dict, pnl: float, reason: str):
    if _telegram_bot:
        _telegram_bot.notify_exit(trade, pnl, reason)

def notify_kill_switch(reason: str, details: Dict):
    if _telegram_bot:
        _telegram_bot.notify_kill_switch(reason, details)

def notify_daily_summary(summary: Dict):
    if _telegram_bot:
        _telegram_bot.notify_daily_summary(summary)
