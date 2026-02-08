"""
PTQ Scalping Bot — Professional Telegram Dashboard
Inline keyboard controls, live log streaming, full bot management
"""

import asyncio
import aiohttp
import threading
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, List
from queue import Queue, Empty


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

        # Live log streaming
        self._live_logs_enabled = False
        self._live_log_last_pos = {}
        self._live_log_rate_count = 0
        self._live_log_rate_reset = time.time()
        self._live_log_max_per_min = 15

        # Dashboard message tracking (edit instead of send new)
        self._dashboard_msg_id = None

        # Callback handlers
        self._callbacks = {
            'dash': self._cb_dashboard,
            'status': self._cb_status,
            'pnl': self._cb_pnl,
            'trades': self._cb_trades,
            'logs_on': self._cb_logs_on,
            'logs_off': self._cb_logs_off,
            'stop': self._cb_stop_trading,
            'resume': self._cb_resume_trading,
            'signals': self._cb_signals,
            'refresh': self._cb_refresh,
            'help': self._cb_help,
        }

        # Command handlers (text commands)
        self._commands = {
            '/start': self._cmd_start,
            '/dash': self._cmd_dashboard,
            '/status': self._cmd_status,
            '/pnl': self._cmd_pnl,
            '/trades': self._cmd_trades,
            '/logs': self._cmd_toggle_logs,
            '/stop': self._cmd_stop,
            '/resume': self._cmd_resume,
            '/help': self._cmd_help,
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
        """Build the main dashboard inline keyboard"""
        logs_btn = ("🔴 Logs OFF", "logs_on") if not self._live_logs_enabled else ("🟢 Logs ON", "logs_off")

        is_stopped = self.bot_state and getattr(self.bot_state, 'state', '') == 'KILL_SWITCH'
        trade_btn = ("▶️ Resume", "resume") if is_stopped else ("⏹ Stop", "stop")

        keyboard = {
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
                    {'text': logs_btn[0], 'callback_data': logs_btn[1]},
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
        return keyboard

    def _back_keyboard(self) -> Dict:
        """Simple back-to-dashboard keyboard"""
        return {
            'inline_keyboard': [
                [{'text': '« Back to Dashboard', 'callback_data': 'dash'}]
            ]
        }

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

        logs_status = "🟢 ON" if self._live_logs_enabled else "🔴 OFF"

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
            f"  Live Logs: {logs_status}\n\n"
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

    async def _cb_logs_on(self, callback_id: str, msg_id: int):
        self._live_logs_enabled = True
        self._init_log_positions()
        await self._answer_callback(callback_id, "🟢 Live logs enabled")
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

    async def _cb_logs_off(self, callback_id: str, msg_id: int):
        self._live_logs_enabled = False
        await self._answer_callback(callback_id, "🔴 Live logs disabled")
        text = self._build_dashboard_text()
        await self._edit_msg(msg_id, text, reply_markup=self._main_keyboard())

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
            "<b>Buttons:</b>\n"
            "  📊 Dashboard — main overview\n"
            "  💰 P&L — profit/loss details\n"
            "  📈 Status — engine details\n"
            "  📝 Trades — today's trades\n"
            "  🎯 Signals — recent signals\n"
            "  🟢/🔴 Logs — toggle live log stream\n"
            "  ⏹/▶️ Stop/Resume — trading control\n"
            "  🔄 Refresh — update data\n\n"
            "<b>Commands:</b>\n"
            "  /dash — open dashboard\n"
            "  /status — quick status\n"
            "  /pnl — P&L\n"
            "  /trades — trades list\n"
            "  /logs — toggle live logs\n"
            "  /stop — stop trading\n"
            "  /resume — resume trading\n"
            "  /help — this help\n"
        )
        await self._answer_callback(callback_id)
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

    async def _cmd_toggle_logs(self, chat_id: str):
        self._live_logs_enabled = not self._live_logs_enabled
        if self._live_logs_enabled:
            self._init_log_positions()
            await self._send_msg("🟢 <b>Live logs enabled</b>\nImportant events will be streamed here.")
        else:
            await self._send_msg("🔴 <b>Live logs disabled</b>")

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
            "/status /pnl /trades /logs /stop /resume"
        )
        await self._send_msg(text)

    # ═══════════════════════════════════════════
    # NOTIFICATION METHODS (auto-sent by bot)
    # ═══════════════════════════════════════════

    def notify_entry(self, trade: Dict):
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
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} <b>EXIT</b> — <b>₹{pnl:+,.2f}</b>\n"
            f"  ₹{trade.get('entry_price',0):.2f} → ₹{trade.get('exit_price',0):.2f} "
            f"({trade.get('hold_time_sec',0)}s)\n"
            f"  <i>{exit_reason[:80]}</i>"
        )
        self.send_message(msg)

    def notify_kill_switch(self, reason: str, details: Dict):
        msg = (
            f"🚨 <b>KILL SWITCH</b>\n"
            f"  Reason: {reason}\n"
            f"  <i>Trading halted</i>"
        )
        self.send_message(msg)

    def notify_daily_summary(self, summary: Dict):
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

    def notify_error(self, error: str):
        self.send_message(f"⚠️ <b>ERROR</b>\n<code>{error[:300]}</code>")

    # ═══════════════════════════════════════════
    # LIVE LOG STREAMING
    # ═══════════════════════════════════════════

    def _init_log_positions(self):
        """Set log file positions to current end (don't send old logs)"""
        if not self.logger:
            return
        for name, path in [('main', self.logger.main_log),
                           ('trade', getattr(self.logger, 'trade_log', None)),
                           ('error', getattr(self.logger, 'error_log', None))]:
            if path and os.path.exists(path):
                self._live_log_last_pos[name] = os.path.getsize(path)

    def _check_live_logs(self) -> List[str]:
        """Check for new important log lines"""
        if not self._live_logs_enabled or not self.logger:
            return []

        important_keywords = [
            'SIGNAL', 'ENTRY', 'EXIT', 'KILL', 'ERROR',
            'MARKET OPEN', 'Strike adjusted', 'Spread'
        ]

        new_messages = []
        for name, path in [('main', self.logger.main_log),
                           ('trade', getattr(self.logger, 'trade_log', None)),
                           ('error', getattr(self.logger, 'error_log', None))]:
            if not path or not os.path.exists(path):
                continue

            last = self._live_log_last_pos.get(name, 0)
            try:
                with open(path, 'r') as f:
                    f.seek(last)
                    lines = f.readlines()
                    self._live_log_last_pos[name] = f.tell()
            except Exception:
                continue

            for line in lines:
                clean = line.strip()
                if not clean:
                    continue

                # Trade/error logs always important
                is_important = name in ('trade', 'error')
                if not is_important:
                    is_important = any(kw in clean.upper() for kw in important_keywords)

                if is_important:
                    # Strip timestamp brackets
                    display = clean
                    if display.startswith('[') and ']' in display:
                        parts = display.split(']', 2)
                        if len(parts) >= 3:
                            display = parts[2].strip()
                        elif len(parts) == 2:
                            display = parts[1].strip()

                    if len(display) > 150:
                        display = display[:147] + "..."
                    new_messages.append(display)

        return new_messages[-10:]  # Max 10 per cycle

    def _can_send_log(self) -> bool:
        """Rate limit live logs"""
        now = time.time()
        if now - self._live_log_rate_reset > 60:
            self._live_log_rate_count = 0
            self._live_log_rate_reset = now
        if self._live_log_rate_count >= self._live_log_max_per_min:
            return False
        self._live_log_rate_count += 1
        return True

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
            log_check_counter = 0

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

                # 3. Stream live logs (every ~3 seconds)
                log_check_counter += 1
                if log_check_counter >= 3 and self._live_logs_enabled:
                    log_check_counter = 0
                    try:
                        new_logs = self._check_live_logs()
                        if new_logs and self._can_send_log():
                            batch = "\n".join(f"<code>▸ {l}</code>" for l in new_logs)
                            await self._send_msg(f"📋 <b>Live</b>\n{batch}")
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

            handler = self._callbacks.get(data)
            if handler:
                try:
                    await handler(callback_id, msg_id)
                except Exception as e:
                    await self._answer_callback(callback_id, f"Error: {e}")
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
                    await self._send_msg(f"❌ Error: {e}")


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
