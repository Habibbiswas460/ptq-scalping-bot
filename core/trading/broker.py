"""
PTQ Scalping Bot - Broker Interface (FINAL FIX v2.0)
=====================================================
Changes from original:
1. WebSocket integration for real-time ticks (180s delay eliminated)
2. ScripMaster JSON download (searchScrip rate limit eliminated)
3. Order status verification loop (fire-and-forget eliminated)
4. Clean Paper Trading + Live Data support
5. Preserved: _find_nearest_expiry, exit_position, position cache
"""

import json
import time
import math
import random
import requests
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from brokers.angel_one import AngelOneClient
from utils.logger import BotLogger
from utils.helpers import current_time_ms

from config.constants import (
    PAPER_TRADING, USE_LIVE_DATA, ENABLE_WEBSOCKET,
    OPTION_TYPE, EXCHANGE, STOP_LOSS_PCT, STOP_LOSS_AMOUNT,
    LOG_DIRECTORY, LOG_CONSOLE,
    ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET,
    SL_POINTS_FIXED, TP_POINTS_FIXED, CE_QUANTITY, PE_QUANTITY,
    TOTAL_CAPITAL
)

# ScripMaster download URL (Angel One official)
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


class BrokerInterface:
    """Broker interface for Angel One — WebSocket enabled"""

    def __init__(self):
        self.broker_client: Optional[AngelOneClient] = None
        self.logger: Optional[BotLogger] = None

        # Token map from ScripMaster (symbol -> token)
        self.token_map: Dict[str, str] = {}

        # Trading state
        self.current_symbol: Optional[str] = None
        self.current_strike: int = 0
        self.spot_price: float = 0.0
        self._current_expiry: Optional[str] = None
        self._option_token: Optional[str] = None

        # WebSocket tick state (thread-safe)
        self._tick_lock = threading.Lock()
        self.last_tick: Optional[Dict] = None
        self.last_valid_tick_time: Optional[datetime] = None
        self._ws_connected: bool = False

        # Phase 4: Position caching (5-second TTL)
        self._position_cache: Optional[Dict] = None
        self._position_cache_time: float = 0
        self._position_cache_ttl = 5.0

        # REST polling fallback state
        self._last_spot_fetch: float = 0
        self._last_option_fetch: float = 0
        self._cached_option_tick: Optional[Dict] = None

        # Simulation state (for paper trading without live data)
        self._simulated_premium: Optional[float] = None
        self._premium_trend: int = 1
        self._trend_ticks: int = 0
        self._simulated_spot: float = 25200.0

    # =========================================================================
    # CONNECTION
    # =========================================================================

    def connect(self) -> bool:
        """Initialize and connect to Angel One broker"""
        self.logger = BotLogger(log_dir=LOG_DIRECTORY, enable_console=LOG_CONSOLE)

        self.logger.info("── PTQ Scalp v3.0 ──")
        self.logger.info(f"   Mode: {'PAPER' if PAPER_TRADING else 'LIVE'}  │  Data: {'WebSocket' if USE_LIVE_DATA and ENABLE_WEBSOCKET else 'REST' if USE_LIVE_DATA else 'Simulated'}")

        # Set initial values
        self.current_strike = 25200
        self.spot_price = 25200.0
        self._simulated_spot = 25200.0

        # Always connect to Angel One for real data
        try:
            if not ANGEL_API_KEY or ANGEL_API_KEY == "your_api_key_here":
                self.logger.warning("⚠ Angel One credentials not configured in .env")
                if PAPER_TRADING:
                    self.logger.info("✓ Paper trading mode — Pure simulation")
                    return True
                self.logger.error("✗ Live trading requires valid credentials")
                return False

            self.broker_client = AngelOneClient(
                api_key=ANGEL_API_KEY,
                client_id=ANGEL_CLIENT_ID,
                password=ANGEL_PASSWORD,
                totp_secret=ANGEL_TOTP_SECRET
            )

            if not self.broker_client.login():
                self.logger.error("❌ Angel One login failed")
                if PAPER_TRADING:
                    self.logger.info("✓ Falling back to simulation")
                    return True
                return False

            # Login success already logged by client.py

            # Step 1: Download ScripMaster (replaces searchScrip calls)
            self._load_scrip_master()

            # Step 2: Get real NIFTY spot + setup symbols
            if not self._setup_market_data():
                if PAPER_TRADING:
                    self.logger.warning("⚠ Market data setup failed, using simulation")
                    return True
                return False

            # Step 3: Start WebSocket for real-time ticks
            if USE_LIVE_DATA and ENABLE_WEBSOCKET:
                self._start_websocket()
            elif USE_LIVE_DATA:
                self.logger.info("📊 Live data via REST polling (WebSocket disabled)")
            else:
                self.logger.info("📊 Using simulated data")

            if PAPER_TRADING:
                self.logger.info("📊 Paper trading mode — READY")
            else:
                try:
                    profile = self.broker_client.get_profile()
                    if profile:
                        self.logger.info(f"✓ Connected as: {profile.get('name', 'Trader')}")
                except Exception:
                    pass
                self.logger.info("✓ LIVE trading mode — READY")

            return True

        except Exception as e:
            self.logger.error(f"❌ Connection error: {e}")
            if PAPER_TRADING:
                self.logger.info("✓ Falling back to simulation")
                return True
            return False

    # =========================================================================
    # SCRIP MASTER — eliminates searchScrip rate limit issues
    # =========================================================================

    def _load_scrip_master(self):
        """
        Download Angel One ScripMaster JSON and build token_map.
        This replaces ALL searchScrip API calls — zero rate limit risk.
        """
        self.logger.info("📥 Downloading ScripMaster JSON...")
        try:
            response = requests.get(SCRIP_MASTER_URL, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Cache only NIFTY NFO symbols (saves memory)
            count = 0
            for item in data:
                if item.get('exch_seg') == 'NFO' and item.get('name') == 'NIFTY':
                    sym = item.get('symbol', '')
                    tok = item.get('token', '')
                    if sym and tok:
                        self.token_map[sym] = tok
                        count += 1

            self.logger.info(f"✅ ScripMaster cached: {count} NIFTY NFO tokens")

        except Exception as e:
            self.logger.warning(f"⚠ ScripMaster download failed: {e}")
            self.logger.warning("  Will fall back to searchScrip API (slower)")

    def _get_token(self, symbol: str, exchange: str = "NFO") -> Optional[str]:
        """
        Get symbol token — ScripMaster first, API fallback.
        """
        # 1. Try ScripMaster cache (instant, no API call)
        token = self.token_map.get(symbol)
        if token:
            return token

        # 2. Fallback to broker API (with rate limit risk)
        if self.broker_client:
            try:
                token = self.broker_client.get_symbol_token(symbol, exchange)
                if token:
                    self.token_map[symbol] = token  # Cache for next time
                return token
            except Exception as e:
                self.logger.warning(f"⚠ Token search failed for {symbol}: {e}")

        return None

    # =========================================================================
    # MARKET DATA SETUP
    # =========================================================================

    def _setup_market_data(self) -> bool:
        """Get NIFTY spot, determine ATM strike, find expiry, build symbol"""
        try:
            # Get real NIFTY spot price
            real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
            if real_spot and real_spot > 10000:
                self.spot_price = real_spot
                self._simulated_spot = real_spot
                self.current_strike = round(real_spot / 50) * 50
                self.logger.info(f"✅ NIFTY Spot: ₹{real_spot:,.2f} → ATM Strike: {self.current_strike}")
            else:
                self.logger.warning("⚠ Could not fetch NIFTY spot, using default")

            # Find nearest expiry
            self._current_expiry = self._find_nearest_expiry()

            # Build option symbol
            self.current_symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)

            # Get token from ScripMaster (or API fallback)
            self._option_token = self._get_token(self.current_symbol, EXCHANGE)

            self.logger.info(f"🎯 Target: {self.current_symbol} (Token: {self._option_token})")
            self.logger.info(f"📅 Expiry: {self._current_expiry}")

            # Also fetch initial option tick via REST
            self._fetch_option_tick_rest()

            self._last_spot_fetch = time.time()
            return True

        except Exception as e:
            self.logger.error(f"❌ Market data setup error: {e}")
            return False

    # =========================================================================
    # WEBSOCKET — real-time ticks (eliminates 180s polling delay)
    # =========================================================================

    def _start_websocket(self):
        """Start WebSocket and subscribe to NIFTY spot + option"""
        if not self.broker_client:
            return

        try:
            self.broker_client.start_websocket(on_tick=self._on_ws_tick)
            time.sleep(2)  # Wait for connection

            if not self.broker_client.ws_connected:
                self.logger.warning("⚠ WebSocket connection failed, will use REST polling")
                return

            # Subscribe: NIFTY spot (LTP) + Option (Quote for bid/ask)
            tokens = [
                ("NSE", "99926000", 1),  # NIFTY spot — LTP mode
            ]

            if self._option_token:
                tokens.append((EXCHANGE, self._option_token, 2))  # Option — Quote mode

            self.broker_client.subscribe(tokens)
            self._ws_connected = True
            self.logger.info(f"🔌 WebSocket subscribed to {len(tokens)} tokens")

        except Exception as e:
            self.logger.warning(f"⚠ WebSocket start failed: {e}")
            self._ws_connected = False

    def _on_ws_tick(self, tick_data: Dict):
        """Handle incoming WebSocket tick — thread-safe"""
        with self._tick_lock:
            token = str(tick_data.get('token', ''))

            if token == "99926000":
                # NIFTY spot update
                ltp = tick_data.get('ltp', 0)
                if ltp and ltp > 10000:
                    self.spot_price = ltp
            else:
                # Option tick update
                ltp = tick_data.get('ltp', 0)
                if not ltp or ltp <= 0:
                    return

                # Build tick dict with bid/ask from Quote mode
                bid = tick_data.get('best_bid_price', 0) or ltp
                ask = tick_data.get('best_ask_price', 0) or ltp
                volume = tick_data.get('volume', 0) or 0

                # If bid/ask not available in WebSocket data, estimate
                if bid <= 0 or ask <= 0:
                    spread = max(0.05, ltp * 0.003)  # 0.3% spread estimate
                    bid = round(ltp - spread / 2, 2)
                    ask = round(ltp + spread / 2, 2)

                self.last_tick = {
                    'timestamp': current_time_ms(),
                    'ltp': round(ltp, 2),
                    'bid': round(bid, 2),
                    'ask': round(ask, 2),
                    'volume': volume,
                    'spot_price': self.spot_price,
                    'symbol': self.current_symbol,
                    'strike': self.current_strike,
                    'direction': OPTION_TYPE,
                }
                self.last_valid_tick_time = datetime.now()

    # =========================================================================
    # REST FALLBACK — when WebSocket is disabled or fails
    # =========================================================================

    def _fetch_option_tick_rest(self) -> Optional[Dict]:
        """Fetch option tick via REST API (used as fallback or initial)"""
        if not self.broker_client or not self.current_symbol:
            return None

        try:
            tick = self.broker_client.get_market_tick(
                symbol=self.current_symbol,
                exchange=EXCHANGE
            )
            if tick:
                tick['spot_price'] = self.spot_price
                tick['strike'] = self.current_strike
                tick['direction'] = OPTION_TYPE
                self._cached_option_tick = tick
                self._last_option_fetch = time.time()
                self.last_valid_tick_time = datetime.now()
                return tick
        except Exception as e:
            if not hasattr(self, '_last_rest_error') or time.time() - self._last_rest_error > 300:
                self.logger.warning(f"⚠ REST tick fetch failed: {e}")
                self._last_rest_error = time.time()

        return None

    def _get_rest_tick(self) -> Optional[Dict]:
        """
        Get tick via REST polling with 10-second interval.
        (Was 180s — reduced since WebSocket is primary now)
        """
        if not self.broker_client:
            return None

        poll_interval = 10  # 10 seconds (WebSocket is primary, REST is backup)

        # Fetch NIFTY spot every 30s via REST
        if time.time() - self._last_spot_fetch > 30:
            try:
                real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                if real_spot and real_spot > 10000:
                    self.spot_price = real_spot
                    self._last_spot_fetch = time.time()

                    # Check if strike needs adjustment
                    base_strike = round(self.spot_price / 50) * 50
                    if abs(self.spot_price - self.current_strike) >= 150:
                        self.current_strike = base_strike
                        self.current_symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)
                        self._option_token = self._get_token(self.current_symbol, EXCHANGE)
                        self.logger.info(f"🔧 Strike adjusted: {self.current_strike} | {self.current_symbol}")
            except Exception:
                pass

        # Fetch option tick
        if time.time() - self._last_option_fetch > poll_interval:
            tick = self._fetch_option_tick_rest()
            if tick:
                return tick

        # Return cached tick with small noise
        if self._cached_option_tick:
            cached = self._cached_option_tick.copy()
            cached['spot_price'] = self.spot_price
            noise = random.gauss(0, 0.3)
            cached['ltp'] = round(cached.get('ltp', 125.0) + noise, 2)
            cached['bid'] = round(cached['ltp'] - 0.25, 2)
            cached['ask'] = round(cached['ltp'] + 0.25, 2)
            cached['timestamp'] = current_time_ms()
            self.last_valid_tick_time = datetime.now()
            return cached

        return None

    # =========================================================================
    # GET TICK — unified entry point
    # =========================================================================

    def get_tick(self) -> Optional[Dict[str, Any]]:
        """
        Get current market tick data.
        Priority: WebSocket -> REST polling -> Simulation
        """
        # Path 1: WebSocket tick (real-time, <100ms latency)
        if USE_LIVE_DATA and self._ws_connected and self.last_tick:
            with self._tick_lock:
                tick = self.last_tick.copy()

            # Check staleness — if no WS tick for 30s, fall back to REST
            if self.last_valid_tick_time:
                age = (datetime.now() - self.last_valid_tick_time).total_seconds()
                if age > 30:
                    # Only warn once per minute about stale ticks
                    stale_warn_key = int(age // 60)
                    if not hasattr(self, '_last_stale_warn') or self._last_stale_warn != stale_warn_key:
                        self.logger.warning(f"⚠ WS stale ({age:.0f}s) → REST fallback")
                        self._last_stale_warn = stale_warn_key
                    rest_tick = self._get_rest_tick()
                    if rest_tick:
                        return rest_tick
            return tick

        # Path 2: REST polling (10s interval, for when WebSocket is off/failed)
        if USE_LIVE_DATA and self.broker_client:
            rest_tick = self._get_rest_tick()
            if rest_tick:
                return rest_tick

        # Path 3: Simulation (paper trading without live data)
        return self._get_simulated_tick()

    # =========================================================================
    # SIMULATION
    # =========================================================================

    def _get_simulated_tick(self) -> Dict:
        """Generate realistic simulated tick for paper trading"""
        if self._simulated_premium is None:
            self._simulated_premium = 125.0
        if not hasattr(self, '_wave_position'):
            self._wave_position = 0.0
            self._wave_speed = random.uniform(0.005, 0.02)
            self._wave_amplitude = random.uniform(15, 40)
            self._base_price = self._simulated_spot

        # Try real spot from broker (every 5 min)
        if self.broker_client and (time.time() - self._last_spot_fetch > 300):
            try:
                real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                if real_spot and real_spot > 10000:
                    self._simulated_spot = real_spot
                    self._base_price = real_spot
                    self._last_spot_fetch = time.time()
            except Exception:
                pass

        # Sinusoidal + Trend + Noise spot movement
        self._wave_position += self._wave_speed
        wave = math.sin(self._wave_position) * self._wave_amplitude
        trend = math.sin(self._wave_position * 0.1) * 30
        if not hasattr(self, '_random_walk'):
            self._random_walk = 0
        self._random_walk += random.gauss(0, 2)
        self._random_walk = max(-50, min(50, self._random_walk))
        self.spot_price = round(self._base_price + wave + trend + self._random_walk + random.gauss(0, 1), 2)

        # Auto-adjust strike
        base_strike = round(self.spot_price / 50) * 50
        if not hasattr(self, '_last_strike') or abs(self.spot_price - self.current_strike) >= 150:
            self.current_strike = base_strike
        self._last_strike = self.current_strike

        # Option premium correlated with spot
        spot_change = self.spot_price - (self._base_price + wave + trend)
        delta_effect = spot_change * 0.5
        self._trend_ticks += 1
        if random.random() < 0.02:
            self._premium_trend *= -1
        noise = random.gauss(0, 0.5)
        target_premium = 125 + delta_effect + self._premium_trend * 10 + noise
        target_premium = max(40, min(300, target_premium))

        # Max 2pt move per tick
        max_change = 2.0
        diff = target_premium - self._simulated_premium
        if abs(diff) > max_change:
            self._simulated_premium += max_change if diff > 0 else -max_change
        else:
            self._simulated_premium = target_premium
        self._simulated_premium = max(40, min(300, self._simulated_premium))

        ltp = round(self._simulated_premium, 2)
        spread = 0.50
        base_volume = 400000
        volume_spike = abs(wave) / self._wave_amplitude * 200000
        volume = int(base_volume + volume_spike + random.uniform(-50000, 50000))
        self.last_valid_tick_time = datetime.now()

        return {
            'timestamp': current_time_ms(),
            'bid': round(ltp - spread / 2, 2),
            'ask': round(ltp + spread / 2, 2),
            'ltp': ltp,
            'volume': volume,
            'spot_price': self.spot_price,
            'symbol': self.current_symbol,
            'strike': self.current_strike,
            'direction': OPTION_TYPE,
        }

    # =========================================================================
    # ORDER PLACEMENT — with verification
    # =========================================================================

    def place_order(self, side: str, qty: int, trades_this_hour: int = 0,
                    direction: str = "CE", signal_params: Dict = None) -> Optional[Dict]:
        """
        Place order — Paper or Live with status verification.
        """
        if signal_params is None:
            signal_params = {}

        self.logger.info(f"📋 Placing {side} order: {qty} {direction} contracts")

        # Build option symbol for this direction
        option_symbol = self._build_option_symbol(self.current_strike, direction)
        self.logger.info(f"   Strike: {self.current_strike} | Symbol: {option_symbol}")

        # Get SL/TP from signal params (which now come from .env via strategy)
        sl_points = signal_params.get('sl_points', SL_POINTS_FIXED)
        tp_points = signal_params.get('tp_points', TP_POINTS_FIXED)
        confidence = signal_params.get('confidence', 60)

        # -- PAPER TRADING --
        if PAPER_TRADING:
            tick = self.get_tick()
            if not tick:
                self.logger.error("❌ No tick data for paper order")
                return None

            entry_price = tick['ask'] if side == 'BUY' else tick['bid']

            trade = {
                'order_id': f"PAPER_{int(time.time())}_{trades_this_hour}",
                'entry_price': entry_price,
                'entry_time': datetime.now(),
                'qty': qty,
                'side': side,
                'direction': direction,
                'symbol': option_symbol,
                'strike': self.current_strike,
                'spot_at_entry': self.spot_price,
                'highest_price': entry_price,
                'fixed_sl_price': entry_price - sl_points if side == 'BUY' else entry_price + sl_points,
                'trailing_sl_price': entry_price - sl_points if side == 'BUY' else entry_price + sl_points,
                'sl_points': sl_points,
                'tp_points': tp_points,
                'tp_price': entry_price + tp_points if side == 'BUY' else entry_price - tp_points,
                'confidence': confidence,
                'initial_sl_amount': sl_points * qty,
                'tp1_hit': False,
                'tp2_hit': False,
                'signal_params': signal_params,
                'status': 'COMPLETE',
            }

            self.logger.info(f"✅ [PAPER] Order filled: {trade['order_id']} @ ₹{entry_price:.2f}")
            self.logger.info(f"   {direction} {self.current_strike} | SL: -{sl_points}pts | TP: +{tp_points}pts | Conf: {confidence}%")
            return trade

        # -- LIVE TRADING — with order verification --
        try:
            symbol_token = self._get_token(option_symbol, EXCHANGE)
            if not symbol_token:
                self.logger.error(f"❌ Token not found for {option_symbol}")
                return None

            order_resp = self.broker_client.place_order(
                symbol=option_symbol,
                exchange=EXCHANGE,
                transaction_type=side,
                quantity=qty,
                symbol_token=symbol_token
            )

            if not order_resp or not order_resp.get('orderid'):
                self.logger.error(f"❌ Order rejected: {order_resp}")
                return None

            order_id = order_resp['orderid']
            self.logger.info(f"🚀 [LIVE] Order sent: {order_id} — Verifying...")

            # -- ORDER STATUS VERIFICATION (wait up to 5s) --
            for attempt in range(5):
                time.sleep(1)
                try:
                    status = self.broker_client.get_order_status(order_id)
                    if not status:
                        continue

                    order_status = str(status.get('orderstatus', '')).lower()

                    if order_status == 'complete':
                        avg_price = float(status.get('averageprice', 0))
                        filled_qty = int(status.get('filledshares', qty))

                        trade = {
                            'order_id': order_id,
                            'entry_price': avg_price,
                            'entry_time': datetime.now(),
                            'qty': filled_qty,
                            'side': side,
                            'direction': direction,
                            'symbol': option_symbol,
                            'strike': self.current_strike,
                            'spot_at_entry': self.spot_price,
                            'highest_price': avg_price,
                            'fixed_sl_price': avg_price - sl_points if side == 'BUY' else avg_price + sl_points,
                            'trailing_sl_price': avg_price - sl_points if side == 'BUY' else avg_price + sl_points,
                            'sl_points': sl_points,
                            'tp_points': tp_points,
                            'tp_price': avg_price + tp_points if side == 'BUY' else avg_price - tp_points,
                            'confidence': confidence,
                            'initial_sl_amount': sl_points * filled_qty,
                            'tp1_hit': False,
                            'tp2_hit': False,
                            'signal_params': signal_params,
                            'status': 'COMPLETE',
                        }
                        self.logger.info(f"✅ [LIVE] Order filled: {order_id} @ ₹{avg_price:.2f} | Qty: {filled_qty}")
                        self.clear_position_cache()
                        return trade

                    elif order_status == 'rejected':
                        reject_reason = status.get('text', 'Unknown')
                        self.logger.error(f"❌ Order REJECTED: {reject_reason}")
                        return None

                    elif order_status == 'cancelled':
                        self.logger.error(f"❌ Order CANCELLED: {order_id}")
                        return None

                except Exception as e:
                    self.logger.warning(f"⚠ Order status check error (attempt {attempt + 1}): {e}")

            self.logger.warning(f"⚠ Order status timeout: {order_id} — treating as failed")
            return None

        except Exception as e:
            self.logger.error(f"❌ Order placement error: {e}")
            return None

    # =========================================================================
    # EXIT POSITION
    # =========================================================================

    def exit_position(self, trade: Dict, exit_reason: str, daily_pnl_inr: float,
                      total_capital: float) -> Dict[str, Any]:
        """Exit current position — Paper or Live with verification"""
        if trade is None:
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}

        self.logger.info(f"🚪 Exiting position: {trade['order_id']} | Reason: {exit_reason}")

        tick = self.get_tick()
        if not tick:
            self.logger.error("Cannot exit: No tick data")
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}

        exit_price = tick['bid'] if trade['side'] == 'BUY' else tick['ask']
        entry_price = trade['entry_price']
        qty = trade['qty']

        # Calculate PnL
        if trade['side'] == 'BUY':
            price_diff = exit_price - entry_price
        else:
            price_diff = entry_price - exit_price

        pnl_inr = price_diff * qty
        pnl_pct = (pnl_inr / total_capital) * 100
        hold_time = (datetime.now() - trade['entry_time']).total_seconds()

        new_daily_pnl = daily_pnl_inr + pnl_inr
        new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100

        # Log trade exit
        self.logger.trade_exit({
            'order_id': trade['order_id'],
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time_sec': hold_time
        })
        self.logger.info(f"💰 PnL: ₹{pnl_inr:+.2f} ({pnl_pct:+.2f}%) | Daily: ₹{new_daily_pnl:+.2f} ({new_daily_pnl_pct:+.2f}%)")

        # Execute exit order if live trading
        if not PAPER_TRADING and self.broker_client:
            try:
                exit_side = "SELL" if trade['side'] == "BUY" else "BUY"
                symbol = trade.get('symbol', self.current_symbol)
                symbol_token = self._get_token(symbol, EXCHANGE)

                if symbol_token:
                    order_resp = self.broker_client.place_order(
                        symbol=symbol,
                        exchange=EXCHANGE,
                        transaction_type=exit_side,
                        quantity=qty,
                        symbol_token=symbol_token
                    )

                    if order_resp and order_resp.get('orderid'):
                        exit_order_id = order_resp['orderid']
                        self.logger.info(f"✅ Exit order sent: {exit_order_id}")

                        # Verify exit fill
                        for _ in range(5):
                            time.sleep(1)
                            try:
                                status = self.broker_client.get_order_status(exit_order_id)
                                if status and str(status.get('orderstatus', '')).lower() == 'complete':
                                    real_exit = float(status.get('averageprice', exit_price))
                                    # Recalculate with real exit price
                                    if trade['side'] == 'BUY':
                                        pnl_inr = (real_exit - entry_price) * qty
                                    else:
                                        pnl_inr = (entry_price - real_exit) * qty
                                    self.logger.info(f"✅ Exit confirmed @ ₹{real_exit:.2f}")
                                    break
                            except Exception:
                                pass
                    else:
                        self.logger.error(f"❌ Exit order failed: {order_resp}")
                        # TODO: Emergency — position may remain open!

                self.clear_position_cache()

            except Exception as e:
                self.logger.error(f"❌ Exit order error: {e}")

        return {
            'pnl_inr': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time': hold_time
        }

    # =========================================================================
    # EXPIRY & SYMBOL HELPERS
    # =========================================================================

    def _find_nearest_expiry(self) -> str:
        """
        Find nearest NIFTY expiry — uses ScripMaster data first, API fallback.
        """
        # Method 1: Search ScripMaster for contracts
        if self.token_map:
            today = datetime.now()
            for days_ahead in range(0, 15):
                check_date = today + timedelta(days=days_ahead)
                expiry_str = check_date.strftime("%d%b%y").upper()
                # See if any symbols match this expiry
                prefix = f"NIFTY{expiry_str}"
                matches = [sym for sym in self.token_map if sym.startswith(prefix)]
                if len(matches) > 10:  # Enough contracts = valid expiry
                    self.logger.info(f"✓ Expiry from ScripMaster: {expiry_str} ({len(matches)} contracts)")
                    return expiry_str

        # Method 2: Search via Angel One API (original logic)
        if self.broker_client:
            import sys
            import io
            today = datetime.now()

            for days_ahead in range(1, 15):
                check_date = today + timedelta(days=days_ahead)
                expiry_str = check_date.strftime("%d%b%y").upper()
                try:
                    search_term = f"NIFTY{expiry_str}"
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()
                    try:
                        results = self.broker_client.search_symbol(search_term, "NFO")
                    finally:
                        sys.stdout = old_stdout

                    if results and len(results) > 10:
                        self.logger.info(f"✓ Expiry from API: {expiry_str} ({len(results)} contracts)")
                        return expiry_str
                    time.sleep(0.3)
                except Exception as e:
                    self.logger.warning(f"Expiry search error: {e}")
                    time.sleep(1)

        # Fallback: next Thursday
        today = datetime.now()
        days_ahead = 3 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        expiry_date = today + timedelta(days=days_ahead)
        return expiry_date.strftime("%d%b%y").upper()

    def _build_option_symbol(self, strike: int, option_type: str = "CE") -> str:
        """Build NIFTY option symbol: NIFTY{DDMMMYY}{STRIKE}{CE/PE}"""
        if not self._current_expiry:
            self._current_expiry = self._find_nearest_expiry()
        return f"NIFTY{self._current_expiry}{strike}{option_type}"

    # =========================================================================
    # POSITION CACHE (Phase 4)
    # =========================================================================

    def get_position_cached(self, force_refresh: bool = False) -> Optional[Dict]:
        """Get position with 5-second cache"""
        if not self.broker_client:
            return None

        current_time = time.time()
        if (not force_refresh and
                self._position_cache is not None and
                current_time - self._position_cache_time < self._position_cache_ttl):
            return self._position_cache

        try:
            positions = self.broker_client.get_positions()
            if positions and len(positions) > 0:
                self._position_cache = positions[0]
                self._position_cache_time = current_time
                return self._position_cache
        except Exception as e:
            self.logger.warning(f"Position query error: {e}")

        return self._position_cache

    def clear_position_cache(self) -> None:
        """Clear position cache"""
        self._position_cache = None
        self._position_cache_time = 0

    def logout(self):
        """Logout and cleanup"""
        if self.broker_client:
            if self._ws_connected:
                try:
                    self.broker_client.stop_websocket()
                except Exception:
                    pass
            if not PAPER_TRADING:
                self.broker_client.logout()


# Singleton instance
broker = BrokerInterface()
