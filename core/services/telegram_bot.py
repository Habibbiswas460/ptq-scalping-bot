"""
PTQ Scalping Bot — Telegram Dashboard

Inline keyboard controls, heartbeat, session error log and preferences.

Note on logs: this used to tail the bot's log files and forward any line containing one of a
few keywords. 'SIGNAL' matched every '[DEBUG] No signal: ...' line, of which a quiet session
produces thousands, so turning logs on flooded the chat with debug noise. Raw log forwarding
is gone. What replaced it: a periodic heartbeat for "is it alive", and a session error buffer
for "did something break" — both on the menu.
"""

import asyncio
import aiohttp
import threading
import time
import json
import os
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Callable, List
from queue import Queue, Empty

from core.services.telegram_prefs import (
    TelegramPrefs, SCHEMA as PREF_SCHEMA, INTERVAL_KEY, INTERVAL_CHOICES,
)

MAX_SESSION_ERRORS = 50


class TelegramBot:
    """Professional Telegram Dashboard with inline keyboard controls"""

    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled
        self.base_url = f"https://api.telegram.org/bot{token}"

        # Message queue
        self._message_queue: Queue = Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # State references
        self.bot_state = None
        self.broker = None
        self.logger = None

        # Preferences (persisted; .env supplies the defaults)
        self.prefs = TelegramPrefs()

        # Heartbeat
        self._last_heartbeat = 0.0

        # Session errors — a bounded buffer so a failure loop cannot exhaust memory
        self._errors: deque = deque(maxlen=MAX_SESSION_ERRORS)
        self._error_seq = 0
        self._errors_lock = threading.Lock()
        self._error_log_pos = None

        # Dashboard message tracking (edit instead of send new)
        self._dashboard_msg_id = None

        # Callback handlers
        self._callbacks = {
            'dash': self._cb_dashboard,
            'status': self._cb_status,
            'pnl': self._cb_pnl,
            'trades': self._cb_trades,
            'hb_on': self._cb_heartbeat_on,
            'hb_off': self._cb_heartbeat_off,
            'errors': self._cb_errors,
            'errors_clear': self._cb_errors_clear,
            'prefs': self._cb_prefs,
            'pref_int': self._cb_pref_interval,
            'stop': self._cb_stop_trading,
            'resume': self._cb_resume_trading,
            'signals': self._cb_signals,
            'refresh': self._cb_refresh,
            'help': self._cb_help,
            'analytics': self._cb_analytics,
            'ws_status': self._cb_ws_status,
        }

        # Command handlers (text commands)
        self._commands = {
            '/start': self._cmd_start,
            '/dash': self._cmd_dashboard,
            '/status': self._cmd_status,
            '/pnl': self._cmd_pnl,
            '/trades': self._cmd_trades,
            '/heartbeat': self._cmd_toggle_heartbeat,
            '/errors': self._cmd_errors,
            '/prefs': self._cmd_prefs,
            '/stop': self._cmd_stop,
            '/resume': self._cmd_resume,
            '/help': self._cmd_help,
            '/analytics': self._cmd_analytics,
            '/ws': self._cmd_ws_status,
        }

    def set_state_reference(self, state, broker=None):
        """Set reference to bot state"""
        self.bot_state = state
        self.broker = broker

    def set_logger(self, logger):
        """Set logger reference for live log streaming"""
        self.logger = logger

    # ═══════════════════════════════════════════
    # SEND METHODS (with inline keyboard support)
    # ═══════════════════════════════════════════

    def send_message(self, text: str, parse_mode: str = "HTML",
                     reply_markup: Optional[Dict] = None):
        """Queue a message for sending"""
        if not self.enabled:
            return
        self._message_queue.put({
            'action': 'send',
            'text': text,
            'parse_mode': parse_mode,
            'reply_markup': reply_markup
        })

    async def _send_msg(self, text: str, parse_mode: str = "HTML",
                        reply_markup: Optional[Dict] = None) -> Optional[int]:
        """Send message and return message_id"""
        if not self.enabled or not self.token:
            return None

        url = f"{self.base_url}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text[:4096],
            'parse_mode': parse_mode
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('result', {}).get('message_id')
        except Exception as e:
            print(f"⚠ Telegram send: {e}")
        return None

    async def _edit_msg(self, message_id: int, text: str,
                        parse_mode: str = "HTML",
                        reply_markup: Optional[Dict] = None):
        """Edit an existing message"""
        url = f"{self.base_url}/editMessageText"
        payload = {
            'chat_id': self.chat_id,
            'message_id': message_id,
            'text': text[:4096],
            'parse_mode': parse_mode
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def _answer_callback(self, callback_id: str, text: str = ""):
        """Answer callback query (removes loading spinner)"""
        url = f"{self.base_url}/answerCallbackQuery"
        payload = {'callback_query_id': callback_id}
        if text:
            payload['text'] = text
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=payload, timeout=5)
        except Exception:
            pass

    # ═══════════════════════════════════════════
    # KEYBOARD BUILDERS
    # ═══════════════════════════════════════════

    def _main_keyboard(self) -> Dict:
        """Main dashboard keyboard.

        Analytics and WS status used to be reachable only by typing /analytics and /ws — the
        handlers existed but nothing on the menu pointed at them. They have buttons now.
        """
        hb_on = bool(self.prefs.get('heartbeat'))
        hb_btn = ("💓 Heartbeat ON", "hb_off") if hb_on else ("🩶 Heartbeat OFF", "hb_on")

        is_stopped = self.bot_state and getattr(self.bot_state, 'state', '') == 'KILL_SWITCH'
        trade_btn = ("▶️ Resume", "resume") if is_stopped else ("⏹ Stop", "stop")

        n_err = self.error_count()
        err_btn = f"🐞 Errors ({n_err})" if n_err else "🐞 Errors"

        return {
            'inline_keyboard': [
                [
                    {'text': '📊 Dashboard', 'callback_data': 'dash'},
                    {'text': '💰 P&L', 'callback_data': 'pnl'},
                ],
                [
                    {'text': '📈 Status', 'callback_data': 'status'},
                    {'text': '📝 Trades', 'callback_data': 'trades'},
                ],
                [
                    {'text': '🎯 Signals', 'callback_data': 'signals'},
                    {'text': '📉 Analytics', 'callback_data': 'analytics'},
                ],
                [
                    {'text': err_btn, 'callback_data': 'errors'},
                    {'text': '📡 Feed', 'callback_data': 'ws_status'},
                ],
                [
                    {'text': hb_btn[0], 'callback_data': hb_btn[1]},
                    {'text': '⚙️ Settings', 'callback_data': 'prefs'},
                ],
                [
                    {'text': trade_btn[0], 'callback_data': trade_btn[1]},
                    {'text': '🔄 Refresh', 'callback_data': 'refresh'},
                ],
                [
                    {'text': '❓ Help', 'callback_data': 'help'},
                ],
            ]
        }

    def _back_keyboard(self) -> Dict:
        """Simple back-to-dashboard keyboard"""
        return {
            'inline_keyboard': [
                [{'text': '« Back to Dashboard', 'callback_data': 'dash'}]
            ]
        }

    def _errors_keyboard(self) -> Dict:
        rows = []
        if self.error_count():
            rows.append([{'text': '🧹 Clear', 'callback_data': 'errors_clear'}])
        rows.append([{'text': '« Back to Dashboard', 'callback_data': 'dash'}])
        return {'inline_keyboard': rows}

    def _prefs_keyboard(self) -> Dict:
        rows = []
        keys = list(PREF_SCHEMA.keys())
        for i in range(0, len(keys), 2):
            row = []
            for key in keys[i:i + 2]:
                label = PREF_SCHEMA[key][0]
                mark = '✅' if self.prefs.get(key) else '⬜'
                row.append({'text': f'{mark} {label}', 'callback_data': f'pf:{key}'})
            rows.append(row)
        mins = self.prefs.get(INTERVAL_KEY, 15)
        rows.append([{'text': f'⏱ Heartbeat every {mins} min', 'callback_data': 'pref_int'}])
        rows.append([{'text': '« Back to Dashboard', 'callback_data': 'dash'}])
        return {'inline_keyboard': rows}

    def _build_prefs_text(self) -> str:
        lines = ["⚙️ <b>Settings</b>", ""]
        for key, (label, _) in PREF_SCHEMA.items():
            lines.append(f"{'✅' if self.prefs.get(key) else '⬜'} {label}")
        lines.append("")
        lines.append(f"⏱ Heartbeat interval: <b>{self.prefs.get(INTERVAL_KEY, 15)} min</b> "
                     f"<i>(tap to cycle {', '.join(str(c) for c in INTERVAL_CHOICES)})</i>")
        lines.append("")
        lines.append("<i>Saved to disk, so these survive a restart. .env supplies the "
                     "starting values only.</i>")
        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # DASHBOARD VIEWS
    # ═══════════════════════════════════════════

    def _build_dashboard_text(self) -> str:
        """Build the main dashboard view"""
        s = self.bot_state
        if not s:
            return "⚠️ Bot not connected"

        pnl = getattr(s, 'daily_pnl_inr', 0)
        pnl_pct = getattr(s, 'daily_pnl_pct', 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        state = getattr(s, 'state', '?')
        wins = getattr(s, 'winning_trades', 0)
        losses = getattr(s, 'losing_trades', 0)
        total = getattr(s, 'total_trades_today', 0)
        wr = f"{(wins/total*100):.0f}%" if total > 0 else "–"
        vix = getattr(s, 'estimated_vix', 0)
        consec = getattr(s, 'consecutive_losses', 0)
        loops = getattr(s, 'loop_count', 0)

        spot = "--"
        ltp = "--"
        if self.broker:
            if hasattr(self.broker, 'spot_price') and self.broker.spot_price > 1000:
                spot = f"₹{self.broker.spot_price:,.0f}"
            if hasattr(self.broker, 'last_tick') and self.broker.last_tick:
                ltp = f"₹{self.broker.last_tick.get('ltp', 0):.2f}"

        hb = self.prefs.get("heartbeat")
        hb_status = (f"🟢 every {self.prefs.get(INTERVAL_KEY, 15)}m" if hb else "🔴 OFF")
        n_err = self.error_count()

        try:
            from core.services.mode_switch import get_current_mode
            mode = get_current_mode()
        except Exception:
            mode = "?"

        text = (
            f"<b>📊 PTQ SCALP DASHBOARD</b>\n"
            f"{'━'*30}\n\n"
            f"<b>Market</b>\n"
            f"  NIFTY: <code>{spot}</code>\n"
            f"  LTP:   <code>{ltp}</code>\n\n"
            f"<b>Performance</b>\n"
            f"  {pnl_emoji} P&L: <code>₹{pnl:+,.2f}</code> ({pnl_pct:+.2f}%)\n"
            f"  Trades: <code>{total}</code> ({wins}W / {losses}L)\n"
            f"  Win Rate: <code>{wr}</code>\n\n"
            f"<b>Engine</b>\n"
            f"  State: <code>{state}</code>\n"
            f"  Mode: <code>{mode}</code>\n"
            f"  VIX: <code>{vix:.1f}%</code>\n"
            f"  Consec Loss: <code>{consec}</code>\n"
            f"  Loops: <code>{loops:,}</code>\n\n"
            f"<b>Controls</b>\n"
            f"  Heartbeat: {hb_status}\n"
            f"  Errors: {'🐞 ' + str(n_err) if n_err else '✅ none'}\n\n"
            f"<i>Updated {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        return text

    def _build_status_text(self) -> str:
        """Detailed status view"""
        s = self.bot_state
        if not s:
            return "⚠️ Bot not connected"

        day_type = getattr(s, 'day_type', '?')
        trades_h = getattr(s, 'trades_this_hour', 0)
        ticks = getattr(s, 'ticks_processed', 0)

        try:
            from config.constants import (
                MAX_TRADES_PER_HOUR, MAX_TRADES_PER_DAY,
                TOTAL_CAPITAL, KILL_SWITCH_LOSS, MAX_DAILY_LOSS_AMOUNT
            )
        except Exception:
            MAX_TRADES_PER_HOUR = MAX_TRADES_PER_DAY = 0
            TOTAL_CAPITAL = KILL_SWITCH_LOSS = MAX_DAILY_LOSS_AMOUNT = 0

        try:
            from core.services.mode_switch import get_current_mode, get_mode_emoji
            mode = f"{get_mode_emoji()} {get_current_mode()}"
        except Exception:
            mode = "?"

        text = (
            f"<b>📈 DETAILED STATUS</b>\n"
            f"{'━'*30}\n\n"
            f"  State: <code>{getattr(s, 'state', '?')}</code>\n"
            f"  Mode: {mode}\n"
            f"  Day Type: <code>{day_type}</code>\n\n"
            f"<b>Limits</b>\n"
            f"  Trades/Hour: <code>{trades_h}/{MAX_TRADES_PER_HOUR}</code>\n"
            f"  Trades/Day: <code>{getattr(s, 'total_trades_today', 0)}/{MAX_TRADES_PER_DAY}</code>\n"
            f"  Kill Switch: <code>₹{KILL_SWITCH_LOSS}</code>\n"
            f"  Max Loss: <code>₹{MAX_DAILY_LOSS_AMOUNT}</code>\n\n"
            f"<b>Session</b>\n"
            f"  Capital: <code>₹{TOTAL_CAPITAL:,}</code>\n"
            f"  Ticks: <code>{ticks:,}</code>\n"
            f"  VIX: <code>{getattr(s, 'estimated_vix', 0):.1f}%</code>\n\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
        )
        return text

    def _build_pnl_text(self) -> str:
        """P&L detail view"""
        s = self.bot_state
        if not s:
            return "⚠️ Bot not connected"

        pnl = getattr(s, 'daily_pnl_inr', 0)
        pnl_pct = getattr(s, 'daily_pnl_pct', 0)
        wins = getattr(s, 'winning_trades', 0)
        losses = getattr(s, 'losing_trades', 0)
        total = wins + losses
        wr = f"{(wins/total*100):.1f}%" if total > 0 else "–"

        bar_len = 20
        if total > 0:
            win_bars = int((wins / total) * bar_len)
            bar = "🟩" * win_bars + "🟥" * (bar_len - win_bars)
        else:
            bar = "⬜" * bar_len

        pnl_emoji = "🎉" if pnl > 0 else "😐" if pnl == 0 else "😔"

        text = (
            f"<b>💰 P&L REPORT</b>\n"
            f"{'━'*30}\n\n"
            f"  {pnl_emoji} <b>₹{pnl:+,.2f}</b> ({pnl_pct:+.2f}%)\n\n"
            f"  Wins: <code>{wins}</code>  |  Losses: <code>{losses}</code>\n"
            f"  Win Rate: <code>{wr}</code>\n\n"
            f"  {bar}\n\n"
            f"  Consec Losses: <code>{getattr(s, 'consecutive_losses', 0)}</code>\n\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
        )
        return text

    def _build_trades_text(self) -> str:
        """Today's trades view"""
        try:
            from core.services.database import get_todays_trades
            trades = get_todays_trades()
            if not trades:
                return "📝 <b>No trades today</b>"

            lines = [f"<b>📝 TODAY'S TRADES ({len(trades)})</b>\n{'━'*30}\n"]
            for i, t in enumerate(trades[:15], 1):
                pnl_val = t.get('pnl', 0)
                emoji = "✅" if pnl_val > 0 else "❌"
                direction = t.get('direction', '?')
                entry = t.get('entry_price', 0)
                exit_p = t.get('exit_price', 0)
                hold = t.get('hold_time_sec', 0)
                lines.append(
                    f"{i}. {emoji} {direction} ₹{entry:.0f}→₹{exit_p:.0f} "
                    f"<b>₹{pnl_val:+,.0f}</b> ({hold}s)"
                )

            if len(trades) > 15:
                lines.append(f"\n<i>+{len(trades)-15} more</i>")

            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error loading trades: {e}"

    def _build_signals_text(self) -> str:
        """Recent signals view"""
        try:
            if self.logger:
                hist = self.logger.get_signal_history(15)
                if hist:
                    return hist
        except Exception:
            pass
        return "📡 No signal data available"

    # ═══════════════════════════════════════════
    # CALLBACK HANDLERS (button presses)
    # ═══════════════════════════════════════════

    async def _cb_dashboard(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id)
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

    async def _cb_status(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id, "📈 Status")
        text = self._build_status_text()
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_pnl(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id, "💰 P&L")
        text = self._build_pnl_text()
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_trades(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id, "📝 Trades")
        text = self._build_trades_text()
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_signals(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id, "🎯 Signals")
        text = self._build_signals_text()
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_heartbeat_on(self, callback_id: str, msg_id: int):
        self.prefs.toggle('heartbeat') if not self.prefs.get('heartbeat') else None
        self._last_heartbeat = 0.0          # send one immediately so the user sees it work
        await self._answer_callback(callback_id, "💓 Heartbeat on")
        await self._edit_msg(msg_id, self._build_dashboard_text(),
                             reply_markup=self._main_keyboard())

    async def _cb_heartbeat_off(self, callback_id: str, msg_id: int):
        self.prefs.toggle('heartbeat') if self.prefs.get('heartbeat') else None
        await self._answer_callback(callback_id, "🩶 Heartbeat off")
        await self._edit_msg(msg_id, self._build_dashboard_text(),
                             reply_markup=self._main_keyboard())

    async def _cb_errors(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id)
        await self._edit_msg(msg_id, self._build_errors_text(),
                             reply_markup=self._errors_keyboard())

    async def _cb_errors_clear(self, callback_id: str, msg_id: int):
        self.clear_errors()
        await self._answer_callback(callback_id, "Cleared")
        await self._edit_msg(msg_id, self._build_errors_text(),
                             reply_markup=self._errors_keyboard())

    async def _cb_prefs(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id)
        await self._edit_msg(msg_id, self._build_prefs_text(),
                             reply_markup=self._prefs_keyboard())

    async def _cb_pref_toggle(self, callback_id: str, msg_id: int, key: str):
        new_val = self.prefs.toggle(key)
        label = PREF_SCHEMA.get(key, (key, None))[0]
        await self._answer_callback(callback_id, f"{label}: {'on' if new_val else 'off'}")
        await self._edit_msg(msg_id, self._build_prefs_text(),
                             reply_markup=self._prefs_keyboard())

    async def _cb_pref_interval(self, callback_id: str, msg_id: int):
        mins = self.prefs.cycle_interval()
        await self._answer_callback(callback_id, f"Heartbeat every {mins} min")
        await self._edit_msg(msg_id, self._build_prefs_text(),
                             reply_markup=self._prefs_keyboard())

    async def _cb_stop_trading(self, callback_id: str, msg_id: int):
        if self.bot_state:
            self.bot_state.state = "KILL_SWITCH"
            await self._answer_callback(callback_id, "⏹ Trading stopped")
        else:
            await self._answer_callback(callback_id, "❌ No state")
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

    async def _cb_resume_trading(self, callback_id: str, msg_id: int):
        if self.bot_state:
            self.bot_state.state = "IDLE"
            await self._answer_callback(callback_id, "▶️ Trading resumed")
        else:
            await self._answer_callback(callback_id, "❌ No state")
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

    async def _cb_refresh(self, callback_id: str, msg_id: int):
        await self._answer_callback(callback_id, "🔄 Refreshed")
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

    async def _cb_help(self, callback_id: str, msg_id: int):
        text = (
            "<b>❓ HELP</b>\n"
            f"{'━'*30}\n\n"
            "<b>Monitoring</b>\n"
            "  📊 Dashboard — main overview\n"
            "  💰 P&amp;L — profit/loss detail\n"
            "  📈 Status — engine detail\n"
            "  📝 Trades — today's trades\n"
            "  🎯 Signals — recent signals\n"
            "  📉 Analytics — 7-day summary\n"
            "  📡 Feed — websocket health\n\n"
            "<b>Alerts</b>\n"
            "  💓 Heartbeat — periodic 'still alive' message.\n"
            "     Debug logs are never forwarded here.\n"
            "  🐞 Errors — anything that broke this session\n"
            "  ⚙️ Settings — choose which alerts you get\n\n"
            "<b>Control</b>\n"
            "  ⏹/▶️ Stop/Resume — trading control\n"
            "  🔄 Refresh — update data\n\n"
            "<b>Commands:</b>\n"
            "  /dash /status /pnl /trades\n"
            "  /heartbeat — toggle the heartbeat\n"
            "  /errors — session errors\n"
            "  /prefs — settings\n"
            "  /stop /resume /analytics /ws /help\n"
        )
        await self._answer_callback(callback_id)
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_analytics(self, callback_id: str, msg_id: int):
        """Show analytics in callback"""
        await self._answer_callback(callback_id, "📊 Loading analytics...")
        try:
            from utils.analytics import TradeAnalytics
            from datetime import datetime, timedelta
            
            analytics = TradeAnalytics()
            total_pnl = 0
            total_trades = 0
            total_wins = 0
            days_with_data = 0
            
            for i in range(7):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                trades = analytics.load_trades(date)
                if trades:
                    paired = analytics.get_paired_trades(trades)
                    if paired:
                        days_with_data += 1
                        total_trades += len(paired)
                        total_pnl += sum(t['pnl'] for t in paired)
                        total_wins += len([t for t in paired if t['pnl'] > 0])
            
            win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = total_pnl / days_with_data if days_with_data > 0 else 0
            
            emoji = "📈" if total_pnl > 0 else "📉"
            
            text = (
                f"{emoji} <b>7-DAY ANALYTICS</b>\n"
                f"{'━'*25}\n"
                f"  Total P&L: <code>₹{total_pnl:+,.2f}</code>\n"
                f"  Avg/Day: <code>₹{avg_pnl:+,.2f}</code>\n"
                f"  Trades: <code>{total_trades}</code>\n"
                f"  Win Rate: <code>{win_rate:.1f}%</code>\n"
                f"  Trading Days: <code>{days_with_data}/7</code>\n"
            )
        except Exception as e:
            text = f"❌ Analytics error: {str(e)[:100]}"
        
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    async def _cb_ws_status(self, callback_id: str, msg_id: int):
        """Show WebSocket status in callback"""
        await self._answer_callback(callback_id, "🔌 Checking...")
        
        if not self.broker:
            text = "❌ Broker not connected"
        else:
            try:
                if hasattr(self.broker, 'get_ws_status'):
                    status = self.broker.get_ws_status()
                    connected = status.get('connected', False)
                    time_since = status.get('time_since_last_tick')
                    reconnects = status.get('reconnect_attempts', 0)
                    circuit_open = status.get('circuit_breaker_open', False)
                    buffer_size = status.get('tick_buffer_size', 0)
                    
                    ws_emoji = "🟢" if connected else "🔴"
                    circuit_emoji = "⚠️" if circuit_open else "✓"
                    
                    time_text = f"<code>{time_since:.1f}s ago</code>" if time_since else "<code>N/A</code>"
                    
                    text = (
                        f"🔌 <b>WEBSOCKET STATUS</b>\n"
                        f"{'━'*25}\n"
                        f"  Status: {ws_emoji} {'Connected' if connected else 'Disconnected'}\n"
                        f"  Last tick: {time_text}\n"
                        f"  Reconnects: <code>{reconnects}</code>\n"
                        f"  Circuit: {circuit_emoji} {'OPEN' if circuit_open else 'Closed'}\n"
                        f"  Buffer: <code>{buffer_size}</code> ticks\n"
                    )
                else:
                    ws_connected = getattr(self.broker, '_ws_connected', False)
                    ws_emoji = "🟢" if ws_connected else "🔴"
                    text = f"🔌 WebSocket: {ws_emoji} {'Connected' if ws_connected else 'Disconnected'}"
            except Exception as e:
                text = f"❌ Error: {str(e)[:100]}"
        
        await self._edit_msg(msg_id, text, reply_markup=self._back_keyboard())

    # ═══════════════════════════════════════════
    # COMMAND HANDLERS (text messages)
    # ═══════════════════════════════════════════

    async def _cmd_start(self, chat_id: str):
        text = self._build_dashboard_text()
        msg_id = await self._send_msg(text, reply_markup=self._main_keyboard())
        if msg_id:
            self._dashboard_msg_id = msg_id

    async def _cmd_dashboard(self, chat_id: str):
        text = self._build_dashboard_text()
        msg_id = await self._send_msg(text, reply_markup=self._main_keyboard())
        if msg_id:
            self._dashboard_msg_id = msg_id

    async def _cmd_status(self, chat_id: str):
        text = self._build_status_text()
        await self._send_msg(text, reply_markup=self._back_keyboard())

    async def _cmd_pnl(self, chat_id: str):
        text = self._build_pnl_text()
        await self._send_msg(text, reply_markup=self._back_keyboard())

    async def _cmd_trades(self, chat_id: str):
        text = self._build_trades_text()
        await self._send_msg(text, reply_markup=self._back_keyboard())

    async def _cmd_toggle_heartbeat(self, chat_id: str):
        now_on = self.prefs.toggle('heartbeat')
        if now_on:
            self._last_heartbeat = 0.0
            mins = self.prefs.get(INTERVAL_KEY, 15)
            await self._send_msg(f"💓 <b>Heartbeat on</b> — every {mins} min.\n"
                                 f"<i>Debug logs are never forwarded; use 🐞 Errors for "
                                 f"anything that actually broke.</i>")
        else:
            await self._send_msg("🩶 <b>Heartbeat off</b>")

    async def _cmd_errors(self, chat_id: str):
        await self._send_msg(self._build_errors_text(), reply_markup=self._errors_keyboard())

    async def _cmd_prefs(self, chat_id: str):
        await self._send_msg(self._build_prefs_text(), reply_markup=self._prefs_keyboard())

    async def _cmd_stop(self, chat_id: str):
        if self.bot_state:
            self.bot_state.state = "KILL_SWITCH"
            await self._send_msg("⏹ <b>Trading stopped</b>\nBot continues monitoring. Use /resume to restart.")
        else:
            await self._send_msg("❌ Bot state not available")

    async def _cmd_resume(self, chat_id: str):
        if self.bot_state:
            self.bot_state.state = "IDLE"
            await self._send_msg("▶️ <b>Trading resumed</b>")
        else:
            await self._send_msg("❌ Bot state not available")

    async def _cmd_help(self, chat_id: str):
        text = (
            "<b>🤖 PTQ SCALP BOT</b>\n\n"
            "Type /dash to open the interactive dashboard.\n\n"
            "<b>Quick commands:</b>\n"
            "/status /pnl /trades /heartbeat /errors /prefs\n"
            "/stop /resume /analytics /ws /help\n"
            "/analytics /ws"
        )
        await self._send_msg(text)

    async def _cmd_analytics(self, chat_id: str):
        """Show weekly analytics summary"""
        try:
            from utils.analytics import TradeAnalytics
            from datetime import datetime, timedelta
            
            analytics = TradeAnalytics()
            total_pnl = 0
            total_trades = 0
            total_wins = 0
            days_with_data = 0
            
            for i in range(7):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                trades = analytics.load_trades(date)
                if trades:
                    paired = analytics.get_paired_trades(trades)
                    if paired:
                        days_with_data += 1
                        total_trades += len(paired)
                        total_pnl += sum(t['pnl'] for t in paired)
                        total_wins += len([t for t in paired if t['pnl'] > 0])
            
            win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = total_pnl / days_with_data if days_with_data > 0 else 0
            
            emoji = "📈" if total_pnl > 0 else "📉"
            
            text = (
                f"{emoji} <b>7-DAY ANALYTICS</b>\n"
                f"{'━'*25}\n"
                f"  Total P&L: <code>₹{total_pnl:+,.2f}</code>\n"
                f"  Avg/Day: <code>₹{avg_pnl:+,.2f}</code>\n"
                f"  Trades: <code>{total_trades}</code>\n"
                f"  Win Rate: <code>{win_rate:.1f}%</code>\n"
                f"  Trading Days: <code>{days_with_data}/7</code>\n"
            )
            await self._send_msg(text)
        except Exception as e:
            await self._send_msg(f"❌ Analytics error: {str(e)[:100]}")

    async def _cmd_ws_status(self, chat_id: str):
        """Show WebSocket connection status"""
        if not self.broker:
            await self._send_msg("❌ Broker not connected")
            return
        
        try:
            if hasattr(self.broker, 'get_ws_status'):
                status = self.broker.get_ws_status()
                connected = status.get('connected', False)
                time_since = status.get('time_since_last_tick')
                reconnects = status.get('reconnect_attempts', 0)
                circuit_open = status.get('circuit_breaker_open', False)
                
                ws_emoji = "🟢" if connected else "🔴"
                circuit_emoji = "⚠️" if circuit_open else "✓"
                
                text = (
                    f"🔌 <b>WEBSOCKET STATUS</b>\n"
                    f"{'━'*25}\n"
                    f"  Status: {ws_emoji} {'Connected' if connected else 'Disconnected'}\n"
                    f"  Last tick: <code>{time_since:.1f}s ago</code>\n" if time_since else
                    f"  Last tick: <code>N/A</code>\n"
                    f"  Reconnects: <code>{reconnects}</code>\n"
                    f"  Circuit: {circuit_emoji} {'OPEN' if circuit_open else 'Closed'}\n"
                )
            else:
                ws_connected = getattr(self.broker, '_ws_connected', False)
                ws_emoji = "🟢" if ws_connected else "🔴"
                text = f"🔌 WebSocket: {ws_emoji} {'Connected' if ws_connected else 'Disconnected'}"
            
            await self._send_msg(text)
        except Exception as e:
            await self._send_msg(f"❌ Error: {str(e)[:100]}")

    # ═══════════════════════════════════════════
    # NOTIFICATION METHODS (auto-sent by bot)
    # ═══════════════════════════════════════════

    def notify_entry(self, trade: Dict):
        # TELEGRAM_NOTIFY_ENTRIES existed in config and .env but nothing read it,
        # so switching it off did nothing. It is honoured here now, via prefs.
        if not self.prefs.get('notify_entries', True):
            return
        emoji = "🟢" if trade.get('direction', 'CE') == "CE" else "🔴"
        msg = (
            f"{emoji} <b>ENTRY</b>\n"
            f"  {trade.get('direction','?')} @ ₹{trade.get('entry_price',0):.2f} "
            f"× {trade.get('qty',0)}\n"
            f"  Score: {trade.get('score',0)} | Conf: {trade.get('confidence',0)}%\n"
            f"  <i>{trade.get('entry_reason','')[:80]}</i>"
        )
        self.send_message(msg)

    def notify_exit(self, trade: Dict, pnl: float, exit_reason: str):
        if not self.prefs.get('notify_exits', True):
            return
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} <b>EXIT</b> — <b>₹{pnl:+,.2f}</b>\n"
            f"  ₹{trade.get('entry_price',0):.2f} → ₹{trade.get('exit_price',0):.2f} "
            f"({trade.get('hold_time_sec',0)}s)\n"
            f"  <i>{exit_reason[:80]}</i>"
        )
        self.send_message(msg)

    def notify_kill_switch(self, reason: str, details: Dict):
        if not self.prefs.get('notify_kill', True):
            return
        msg = (
            f"🚨 <b>KILL SWITCH</b>\n"
            f"  Reason: {reason}\n"
            f"  <i>Trading halted</i>"
        )
        self.send_message(msg)

    def notify_daily_summary(self, summary: Dict):
        if not self.prefs.get('daily_summary', True):
            return
        total = summary.get('total_trades', 0)
        wins = summary.get('winning_trades', 0)
        pnl = summary.get('total_pnl', 0)
        wr = (wins / total * 100) if total > 0 else 0
        emoji = "🎉" if pnl > 0 else "😐" if pnl == 0 else "😔"

        msg = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"{'━'*25}\n"
            f"  P&L: <code>₹{pnl:+,.2f}</code>\n"
            f"  Trades: {total} ({wins}W / {summary.get('losing_trades',0)}L)\n"
            f"  Win Rate: {wr:.1f}%\n"
            f"  <i>{datetime.now().strftime('%Y-%m-%d')}</i>"
        )
        self.send_message(msg)

    def notify_startup(self, config: Dict):
        mode = 'PAPER' if config.get('paper_trading', True) else 'LIVE'
        msg = (
            f"🚀 <b>BOT STARTED</b>\n"
            f"{'━'*25}\n"
            f"  Mode: <code>{mode}</code>\n"
            f"  Capital: <code>₹{config.get('capital',30000):,}</code>\n"
            f"  CE: {config.get('ce_qty',0)} | PE: {config.get('pe_qty',0)}\n"
            f"  SL: {config.get('sl_points',0)} | TP: {config.get('tp_points',0)}\n\n"
            f"Type /dash for the interactive dashboard."
        )
        self.send_message(msg, reply_markup=self._main_keyboard())

    def notify_shutdown(self, summary: Dict):
        msg = (
            f"🛑 <b>BOT STOPPED</b>\n"
            f"  P&L: ₹{summary.get('daily_pnl',0):+,.2f}\n"
            f"  Trades: {summary.get('total_trades',0)}"
        )
        self.send_message(msg)

    def notify_error(self, error: str, source: str = "bot"):
        """Record every error; send one only if the user wants error alerts.

        Recording is unconditional so the 🐞 Errors menu is always complete even when alerts
        are muted. The text is HTML-escaped because an unescaped '<' in an exception message
        makes the Telegram API reject the message outright — losing exactly the report that
        mattered.
        """
        self.record_error(error, source=source)
        if not self.prefs.get('notify_errors', True):
            return
        self.send_message(f"⚠️ <b>ERROR</b>\n<code>{self._escape(str(error)[:300])}</code>")

    # ═══════════════════════════════════════════
    # SESSION ERRORS
    # ═══════════════════════════════════════════

    def record_error(self, message: str, source: str = "bot") -> None:
        """Record an error raised by the running session so it can be read from the menu.

        Called from notify_error and from the error-log tail. Bounded and lock-guarded because
        the trading loop, the Telegram worker and the broker callbacks all reach it.
        """
        text = (message or "").strip()
        if not text:
            return
        with self._errors_lock:
            self._error_seq += 1
            self._errors.append({
                'n': self._error_seq,
                'at': datetime.now().strftime('%H:%M:%S'),
                'source': source,
                'text': text[:400],
            })

    def error_count(self) -> int:
        with self._errors_lock:
            return len(self._errors)

    def clear_errors(self) -> None:
        with self._errors_lock:
            self._errors.clear()

    def _tail_error_log(self) -> None:
        """Pull anything new from the error log into the session buffer.

        Only the error log is read. The main log is deliberately never tailed — that is what
        used to push '[DEBUG] No signal: ...' into the chat by the thousand.
        """
        path = getattr(self.logger, 'error_log', None) if self.logger else None
        if not path or not os.path.exists(path):
            return
        try:
            size = os.path.getsize(path)
            if self._error_log_pos is None:      # first look: start at the end, skip history
                self._error_log_pos = size
                return
            if size < self._error_log_pos:       # rotated
                self._error_log_pos = 0
            if size == self._error_log_pos:
                return
            with open(path, 'r') as f:
                f.seek(self._error_log_pos)
                lines = f.readlines()
                self._error_log_pos = f.tell()
        except Exception:
            return
        for line in lines:
            clean = line.strip()
            if not clean or clean.startswith('#') or '[DEBUG]' in clean:
                continue
            self.record_error(clean, source='log')

    def _build_errors_text(self) -> str:
        with self._errors_lock:
            items = list(self._errors)
        if not items:
            return ("🐞 <b>Session Errors</b>\n\n"
                    "✅ Nothing recorded since the bot started.\n\n"
                    "<i>Errors raised while running appear here — the chat is not used for "
                    "debug logs.</i>")
        shown = items[-12:]
        lines = [f"🐞 <b>Session Errors</b> — {len(items)} recorded"]
        if len(items) > len(shown):
            lines.append(f"<i>showing the last {len(shown)}</i>")
        lines.append("")
        for e in shown:
            lines.append(f"<b>#{e['n']}</b> <code>{e['at']}</code> · {e['source']}")
            lines.append(f"<code>{self._escape(e['text'][:220])}</code>")
        return "\n".join(lines)

    @staticmethod
    def _escape(text: str) -> str:
        """Escape the three characters Telegram's HTML parse mode cares about.

        Unescaped '<' in an exception message makes the API reject the whole message, so an
        error report could silently fail to arrive — exactly when it is needed most.
        """
        return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    # ═══════════════════════════════════════════
    # HEARTBEAT
    # ═══════════════════════════════════════════

    def _build_heartbeat_text(self) -> str:
        """One compact line-set proving the bot is alive, sent on the chosen interval."""
        s = self.bot_state
        now = datetime.now().strftime('%H:%M:%S')
        n_err = self.error_count()
        err_line = (f"\n🐞 <b>{n_err}</b> error(s) this session — see the menu" if n_err else "")
        if not s:
            return (f"💓 <b>Heartbeat</b> · <code>{now}</code>\n"
                    f"<i>Bot state not connected</i>{err_line}")
        pnl = getattr(s, 'daily_pnl_inr', 0) or 0
        trades = getattr(s, 'trades_today', 0) or 0
        wins = getattr(s, 'wins_today', 0) or 0
        state = getattr(s, 'state', '?')
        ltp = 0
        spot = 0
        if self.broker:
            spot = getattr(self.broker, 'spot_price', 0) or 0
            tick = getattr(self.broker, 'last_tick', None) or {}
            ltp = tick.get('ltp', 0) or 0
        return (
            f"💓 <b>Heartbeat</b> · <code>{now}</code>\n"
            f"State <b>{state}</b> · NIFTY <b>{spot:,.0f}</b> · LTP <b>₹{ltp:,.2f}</b>\n"
            f"Trades <b>{trades}</b> ({wins}W) · P&amp;L <b>₹{pnl:+,.0f}</b>{err_line}"
        )

    def _heartbeat_due(self) -> bool:
        if not self.prefs.get('heartbeat'):
            return False
        interval = max(1, int(self.prefs.get(INTERVAL_KEY, 15))) * 60
        return (time.time() - self._last_heartbeat) >= interval

    # ═══════════════════════════════════════════
    # BACKGROUND WORKER
    # ═══════════════════════════════════════════

    def start(self):
        """Start background worker"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._bg_worker, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background worker"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _bg_worker(self):
        """Background: send queued messages, poll updates, stream logs"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def worker():
            last_update_id = 0
            tick_counter = 0

            while self._running:
                # 1. Send queued messages
                while not self._message_queue.empty():
                    try:
                        item = self._message_queue.get_nowait()
                        if item.get('action') == 'send':
                            msg_id = await self._send_msg(
                                item['text'],
                                item.get('parse_mode', 'HTML'),
                                item.get('reply_markup')
                            )
                            if msg_id and item.get('reply_markup'):
                                self._dashboard_msg_id = msg_id
                    except Empty:
                        break
                    except Exception as e:
                        print(f"⚠ TG queue: {e}")

                # 2. Poll for updates (commands + button presses)
                try:
                    updates = await self._get_updates(last_update_id + 1)
                    for update in updates:
                        last_update_id = update.get('update_id', last_update_id)
                        await self._handle_update(update)
                except Exception:
                    pass

                # 3. Pull any new errors into the session buffer (~every 3s).
                #    Only the error log is read — never the main log, which is what used to
                #    push DEBUG lines into the chat.
                tick_counter += 1
                if tick_counter % 3 == 0:
                    try:
                        self._tail_error_log()
                    except Exception:
                        pass

                # 4. Heartbeat on the configured interval
                try:
                    if self._heartbeat_due():
                        self._last_heartbeat = time.time()
                        await self._send_msg(self._build_heartbeat_text())
                except Exception:
                    pass

                await asyncio.sleep(1)

        loop.run_until_complete(worker())

    async def _get_updates(self, offset: int = 0) -> List[Dict]:
        """Poll Telegram for updates"""
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
        """Route update to command or callback handler"""

        # Handle callback queries (button presses)
        callback = update.get('callback_query')
        if callback:
            data = callback.get('data', '')
            callback_id = callback.get('id', '')
            msg_id = callback.get('message', {}).get('message_id', 0)
            chat_id = str(callback.get('message', {}).get('chat', {}).get('id', ''))

            if chat_id != self.chat_id:
                return

            # preference toggles carry their key in the callback data
            if data.startswith('pf:'):
                try:
                    await self._cb_pref_toggle(callback_id, msg_id, data[3:])
                except Exception as e:
                    self.record_error(f"pref toggle {data}: {e}", source="telegram")
                    await self._answer_callback(callback_id, "Could not save that setting")
                return

            handler = self._callbacks.get(data)
            if handler:
                try:
                    await handler(callback_id, msg_id)
                except Exception as e:
                    # a failing button used to vanish into the callback answer only
                    self.record_error(f"callback {data}: {e}", source="telegram")
                    await self._answer_callback(callback_id, f"Error: {e}")
            else:
                await self._answer_callback(callback_id, "Unknown action")
            return

        # Handle text messages (commands)
        message = update.get('message', {})
        text = message.get('text', '')
        chat_id = str(message.get('chat', {}).get('id', ''))

        if chat_id != self.chat_id:
            return

        if text.startswith('/'):
            cmd = text.split()[0].lower().split('@')[0]  # handle /cmd@botname
            handler = self._commands.get(cmd)
            if handler:
                try:
                    await handler(chat_id)
                except Exception as e:
                    self.record_error(f"command {cmd}: {e}", source="telegram")
                    await self._send_msg(f"❌ Error: {self._escape(str(e))}")


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════

_telegram_bot: Optional[TelegramBot] = None


def init_telegram(token: str, chat_id: str, enabled: bool = True) -> TelegramBot:
    """Initialize Telegram bot singleton"""
    global _telegram_bot
    _telegram_bot = TelegramBot(token, chat_id, enabled)
    _telegram_bot.start()
    return _telegram_bot


def get_telegram() -> Optional[TelegramBot]:
    return _telegram_bot


# Convenience functions
def send_telegram(message: str):
    if _telegram_bot:
        _telegram_bot.send_message(message)

def send_alert(message: str):
    """Send urgent alert via Telegram (used by kill_switch, broker, state_machine)"""
    if _telegram_bot:
        _telegram_bot.send_message(f"🚨 {message}")

def record_error(message: str, source: str = "bot"):
    """Record a session error for the 🐞 Errors menu.

    Safe to call from anywhere, including before Telegram is initialised — errors raised
    during startup simply have nowhere to go yet, and must never break the caller.
    """
    if _telegram_bot:
        try:
            _telegram_bot.record_error(message, source=source)
        except Exception:
            pass


def notify_error(message: str, source: str = "bot"):
    if _telegram_bot:
        _telegram_bot.notify_error(message, source=source)


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
