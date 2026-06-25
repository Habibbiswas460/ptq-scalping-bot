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
    TOTAL_CAPITAL, MIN_ENTRY_PREMIUM, MAX_ENTRY_PREMIUM,
    # v3.1 Order execution config
    USE_LIMIT_ORDERS, LIMIT_ORDER_OFFSET, MAX_SLIPPAGE_PCT,
    ORDER_RETRY_ENABLED, ORDER_MAX_RETRIES, ORDER_RETRY_DELAY_MS, ORDER_PRICE_CHASE_STEP
)

# ScripMaster download URL (Angel One official)
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Premium range for strike selection (use tighter range than entry filter)
STRIKE_PREMIUM_MIN = 90.0   # Minimum premium for strike selection
STRIKE_PREMIUM_MAX = 150.0  # Maximum premium for strike selection


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
        self.last_valid_tick_time: Optional[datetime] = None  # When we last SERVED a tick
        self._ws_original_tick_time: Optional[float] = None   # When original tick data arrived
        self._ws_connected: bool = False
        
        # ═══════════════════════════════════════════════════════════════════
        # UNBREAKABLE WEBSOCKET TUNNEL - 4 Layers of Protection (Algo Trading)
        # ═══════════════════════════════════════════════════════════════════
        # Layer 1: Heartbeat Monitor (15s for algo trading - fast detection)
        # Note: Angel One only sends on price CHANGES. REST polling fills gaps.
        self._ws_last_tick_time: float = 0
        self._ws_heartbeat_timeout: int = 15  # 15 seconds for algo trading
        self._ws_heartbeat_thread: Optional[threading.Thread] = None
        
        # Layer 2: Auto-Reconnect Loop with Exponential Backoff
        self._ws_reconnect_attempts: int = 0
        self._ws_max_reconnect_attempts: int = 15  # More attempts before circuit breaker
        self._ws_reconnect_delay: float = 1.0  # Start at 1 second
        self._ws_max_reconnect_delay: float = 30.0  # Max 30 seconds between attempts
        
        # Layer 3: Circuit Breaker
        self._ws_circuit_open: bool = False
        self._ws_circuit_cooldown_until: Optional[datetime] = None
        self._ws_circuit_cooldown_sec: int = 180  # 3 minutes (faster retry)
        
        # Layer 4: Pre-Market Reconnect Timer (reconnect 2 min before market open)
        self._ws_premarket_reconnect_done: bool = False
        self._market_open_time = "09:15"  # IST
        self._premarket_reconnect_margin_sec: int = 120  # 2 min before market
        
        # Algo Trading: Tick Buffer for smoother data flow
        self._tick_buffer: List[Dict] = []
        self._tick_buffer_max_size: int = 10  # Keep last 10 ticks
        self._use_tick_buffer: bool = True  # Enable tick smoothing
        # ═══════════════════════════════════════════════════════════════════

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

        self.logger.info("── PTQ Scalp v3.4 ──")
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
        """Get NIFTY spot, find best strike by premium, find expiry, build symbol"""
        try:
            # Get real NIFTY spot price
            real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
            if real_spot and real_spot > 10000:
                self.spot_price = real_spot
                self._simulated_spot = real_spot
                atm_strike = round(real_spot / 50) * 50
                self.logger.info(f"✅ NIFTY Spot: ₹{real_spot:,.2f} → ATM Strike: {atm_strike}")
            else:
                self.logger.warning("⚠ Could not fetch NIFTY spot, using default")
                atm_strike = 25200

            # Find nearest expiry
            self._current_expiry = self._find_nearest_expiry()

            # Find best strike by premium (₹90-150 range)
            best_strike, best_premium = self._find_strike_by_premium(OPTION_TYPE)
            self.current_strike = best_strike if best_strike else atm_strike
            
            strike_type = "ATM" if self.current_strike == atm_strike else ("OTM" if (OPTION_TYPE == 'CE' and self.current_strike > atm_strike) or (OPTION_TYPE == 'PE' and self.current_strike < atm_strike) else "ITM")
            self.logger.info(f"💰 Selected {strike_type} Strike: {self.current_strike} (Premium: ₹{best_premium:.0f})")

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

    def check_and_rotate_strike(self, direction: str = None) -> bool:
        """
        Check if strike needs rotation based on PREMIUM (not just spot movement).
        Select ATM/OTM/ITM based on which has premium in ₹90-150 range.
        
        Args:
            direction: 'CE' or 'PE' - if provided, rotates to this direction
        
        Returns:
            True if strike was rotated, False otherwise
        """
        if not self.spot_price or self.spot_price < 10000:
            return False
        
        opt_type = direction if direction else OPTION_TYPE
        
        # Get current option premium
        current_premium = 0
        if self.last_tick:
            current_premium = self.last_tick.get('ltp', 0)
        
        # Check if premium is out of range
        need_rotation = False
        if current_premium > 0:
            if current_premium < STRIKE_PREMIUM_MIN or current_premium > STRIKE_PREMIUM_MAX:
                need_rotation = True
                self.logger.info(f"💰 Premium ₹{current_premium:.0f} out of range (₹{STRIKE_PREMIUM_MIN:.0f}-₹{STRIKE_PREMIUM_MAX:.0f}) - searching better strike...")
        
        # Also check spot movement (original logic)
        atm_strike = round(self.spot_price / 50) * 50
        strike_gap = abs(self.spot_price - self.current_strike)
        if strike_gap >= 50:
            need_rotation = True
        
        if not need_rotation:
            return False
        
        # Find best strike by premium
        best_strike, best_premium = self._find_strike_by_premium(opt_type)
        
        if best_strike and best_strike != self.current_strike:
            old_strike = self.current_strike
            old_symbol = self.current_symbol
            old_token = self._option_token
            
            # Update strike
            self.current_strike = best_strike
            self.current_symbol = self._build_option_symbol(self.current_strike, opt_type)
            self._option_token = self._get_token(self.current_symbol, EXCHANGE)
            
            strike_type = "ATM" if best_strike == atm_strike else ("OTM" if (opt_type == 'CE' and best_strike > atm_strike) or (opt_type == 'PE' and best_strike < atm_strike) else "ITM")
            self.logger.info(f"🔄 STRIKE ROTATION: {old_strike} → {self.current_strike} ({strike_type}) | Premium: ₹{best_premium:.0f}")
            self.logger.info(f"   Symbol: {old_symbol} → {self.current_symbol}")
            
            # Re-subscribe WebSocket to new token
            if self._ws_connected and self.broker_client and self._option_token:
                try:
                    if old_token:
                        self.broker_client.unsubscribe([(EXCHANGE, old_token, 2)])
                    self.broker_client.subscribe([(EXCHANGE, self._option_token, 2)])
                    self.logger.info(f"🔌 WebSocket re-subscribed to {self.current_symbol}")
                except Exception as e:
                    self.logger.warning(f"⚠ WebSocket re-subscribe failed: {e}")
            
            # Clear cached tick
            self._cached_option_tick = None
            self.last_tick = None
            
            return True
        
        return False
    
    def _find_strike_by_premium(self, option_type: str = "CE") -> tuple:
        """
        Find the best strike where premium is in ₹90-150 range.
        Searches ATM first, then OTM/ITM based on premium.
        
        Args:
            option_type: 'CE' or 'PE'
            
        Returns:
            (best_strike, premium) or (None, 0) if not found
        """
        if not self.spot_price or self.spot_price < 10000:
            return None, 0
        
        atm_strike = round(self.spot_price / 50) * 50
        
        # Build list of strikes to check: ATM, then 2 OTM, then 2 ITM
        strikes_to_check = [atm_strike]
        
        # For CE: OTM = higher strikes, ITM = lower strikes
        # For PE: OTM = lower strikes, ITM = higher strikes
        if option_type == 'CE':
            otm_strikes = [atm_strike + 50, atm_strike + 100]  # Higher = OTM for CE
            itm_strikes = [atm_strike - 50, atm_strike - 100]  # Lower = ITM for CE
        else:  # PE
            otm_strikes = [atm_strike - 50, atm_strike - 100]  # Lower = OTM for PE
            itm_strikes = [atm_strike + 50, atm_strike + 100]  # Higher = ITM for PE
        
        strikes_to_check.extend(otm_strikes)
        strikes_to_check.extend(itm_strikes)
        
        # Get LTP for each strike
        best_strike = None
        best_premium = 0
        best_distance_from_mid = float('inf')  # Prefer premium closer to middle of range
        
        mid_premium = (STRIKE_PREMIUM_MIN + STRIKE_PREMIUM_MAX) / 2  # ₹120
        
        for strike in strikes_to_check:
            if strike <= 0:
                continue
                
            symbol = self._build_option_symbol(strike, option_type)
            token = self._get_token(symbol, EXCHANGE)
            
            if not token:
                continue
            
            try:
                ltp = self.broker_client.get_ltp(EXCHANGE, symbol, token)
                if ltp and ltp > 0:
                    # Check if premium is in range
                    if STRIKE_PREMIUM_MIN <= ltp <= STRIKE_PREMIUM_MAX:
                        distance = abs(ltp - mid_premium)
                        if distance < best_distance_from_mid:
                            best_strike = strike
                            best_premium = ltp
                            best_distance_from_mid = distance
                            self.logger.debug(f"   Found: {symbol} @ ₹{ltp:.0f} (in range)")
                    else:
                        self.logger.debug(f"   Skip: {symbol} @ ₹{ltp:.0f} (out of range)")
            except Exception as e:
                self.logger.debug(f"   Error fetching {symbol}: {e}")
        
        # If no strike found in range, use ATM as fallback
        if not best_strike:
            self.logger.warning(f"⚠ No strike found with premium ₹{STRIKE_PREMIUM_MIN:.0f}-₹{STRIKE_PREMIUM_MAX:.0f}, using ATM {atm_strike}")
            best_strike = atm_strike
            # Get ATM premium for logging
            try:
                symbol = self._build_option_symbol(atm_strike, option_type)
                token = self._get_token(symbol, EXCHANGE)
                if token:
                    best_premium = self.broker_client.get_ltp(EXCHANGE, symbol, token) or 0
            except:
                pass
        
        return best_strike, best_premium

    # =========================================================================
    # WEBSOCKET — real-time ticks (eliminates 180s polling delay)
    # =========================================================================

    def _start_websocket(self):
        """Start WebSocket and subscribe to NIFTY spot + option"""
        if not self.broker_client:
            return

        try:
            self.broker_client.start_websocket(
                on_tick=self._on_ws_tick,
            )
            # Register disconnect callback so BrokerInterface knows when WS dies
            self.broker_client._broker_ws_disconnect_cb = self._on_ws_disconnect
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
            self._ws_last_tick_time = time.time()  # Initialize heartbeat
            self._ws_reconnect_attempts = 0  # Reset on successful connect
            self.logger.info(f"🔌 WebSocket subscribed to {len(tokens)} tokens")
            
            # Layer 1: Start heartbeat monitor (if not already running)
            if not self._ws_heartbeat_thread or not self._ws_heartbeat_thread.is_alive():
                self._start_ws_heartbeat_monitor()

        except Exception as e:
            self.logger.warning(f"⚠ WebSocket start failed: {e}")
            self._ws_connected = False
            # Trigger reconnect on failure
            if self._ws_reconnect_attempts < self._ws_max_reconnect_attempts:
                threading.Thread(target=self._trigger_ws_reconnect, daemon=True).start()

    def _on_ws_disconnect(self, reason: str = "unknown"):
        """Called when WebSocket disconnects — triggers Layer 2 auto-reconnect"""
        was_connected = self._ws_connected
        self._ws_connected = False
        
        if was_connected and self.logger:
            self.logger.warning(f"⚠ WebSocket DISCONNECTED: {reason}")
            
            # Layer 2: Trigger auto-reconnect (don't fall back to REST)
            self._trigger_ws_reconnect()
    
    def _trigger_ws_reconnect(self):
        """Layer 2: Auto-reconnect loop with exponential backoff - keeps trying WebSocket"""
        # Check Layer 3: Circuit Breaker
        if self._ws_circuit_open:
            if self._ws_circuit_cooldown_until and datetime.now() < self._ws_circuit_cooldown_until:
                # Still in cooldown - silently skip
                return
            else:
                # Cooldown expired - reset circuit breaker
                self._ws_circuit_open = False
                self._ws_reconnect_attempts = 0
                self._ws_reconnect_delay = 1.0  # Reset delay
                self.logger.info("🔄 Circuit breaker reset - attempting reconnection...")
        
        # Increment attempt counter
        self._ws_reconnect_attempts += 1
        
        # Layer 3: Check if we've exceeded max attempts
        if self._ws_reconnect_attempts > self._ws_max_reconnect_attempts:
            self._ws_circuit_open = True
            self._ws_circuit_cooldown_until = datetime.now() + timedelta(seconds=self._ws_circuit_cooldown_sec)
            self.logger.warning(
                f"🔌 CIRCUIT BREAKER OPEN | {self._ws_reconnect_attempts} failed attempts | "
                f"Sleeping for {self._ws_circuit_cooldown_sec//60} minutes (until {self._ws_circuit_cooldown_until.strftime('%H:%M:%S')})"
            )
            return
        
        # Calculate exponential backoff delay
        current_delay = min(self._ws_reconnect_delay * (2 ** (self._ws_reconnect_attempts - 1)), 
                           self._ws_max_reconnect_delay)
        
        # Attempt reconnection
        self.logger.info(f"🔄 WebSocket reconnect attempt {self._ws_reconnect_attempts}/{self._ws_max_reconnect_attempts} (delay: {current_delay:.1f}s)...")
        
        try:
            # Exponential backoff delay
            time.sleep(current_delay)
            
            # Stop old WebSocket
            if self.broker_client:
                try:
                    self.broker_client.stop_websocket()
                except:
                    pass
            
            # Start fresh WebSocket
            self._start_websocket()
            
            # If successful, reset counter
            if self._ws_connected:
                self._ws_reconnect_attempts = 0
                self.logger.info("✅ WebSocket reconnected successfully!")
        except Exception as e:
            self.logger.warning(f"⚠ Reconnect failed: {e}")
            # Schedule another attempt
            threading.Thread(target=self._trigger_ws_reconnect, daemon=True).start()
    
    def _start_ws_heartbeat_monitor(self):
        """Layer 1: Heartbeat monitor - checks if ticks are flowing (algo-trading optimized)
        
        Note: Angel One WebSocket only sends ticks on PRICE CHANGES.
        If market is quiet, no ticks come even on a healthy connection.
        We use a longer timeout and check if we have usable cached data.
        """
        def heartbeat_monitor():
            while True:
                try:
                    # If circuit breaker is open, just sleep
                    if self._ws_circuit_open:
                        time.sleep(60)  # Check circuit breaker every minute
                        continue
                    
                    # Layer 4: Check for pre-market reconnect (2 min before market open)
                    self._check_premarket_reconnect()
                    
                    # Check if we're getting ticks
                    time_since_last_tick = time.time() - self._ws_last_tick_time
                    
                    # Only reconnect if:
                    # 1. Connected but no tick received for 2+ minutes, AND
                    # 2. We have no usable cached data (or it's very stale)
                    has_usable_cache = self.last_tick is not None and self._ws_original_tick_time is not None
                    original_tick_age = time.time() - self._ws_original_tick_time if self._ws_original_tick_time else 999
                    
                    if self._ws_connected and time_since_last_tick > self._ws_heartbeat_timeout:
                        # If original tick data < 5 min old (being refreshed by REST), don't reconnect
                        if has_usable_cache and original_tick_age < 300:
                            # Log once per minute that we're using REST refresh
                            if int(time_since_last_tick) % 60 == 0:
                                self.logger.info(f"ℹ WebSocket quiet ({time_since_last_tick:.0f}s), REST keeping data fresh ({original_tick_age:.0f}s old)")
                        else:
                            self.logger.warning(f"💔 Heartbeat FAILED: No tick for {time_since_last_tick:.0f}s - reconnecting...")
                            self._on_ws_disconnect("Heartbeat timeout")
                    
                    time.sleep(30)  # Check every 30 seconds
                    
                except Exception as e:
                    self.logger.debug(f"Heartbeat monitor error: {e}")
                    time.sleep(5)
        
        self._ws_heartbeat_thread = threading.Thread(target=heartbeat_monitor, daemon=True, name="WS-Heartbeat")
        self._ws_heartbeat_thread.start()

    def _check_premarket_reconnect(self):
        """Layer 4: Reconnect WebSocket 2 minutes before market open to ensure fresh connection"""
        if self._ws_premarket_reconnect_done:
            return  # Already done for today
        
        now = datetime.now()
        market_open_hour, market_open_min = map(int, self._market_open_time.split(":"))
        market_open = now.replace(hour=market_open_hour, minute=market_open_min, second=0, microsecond=0)
        
        # Check if we're in the pre-market reconnect window
        premarket_reconnect_time = market_open - timedelta(seconds=self._premarket_reconnect_margin_sec)
        
        if premarket_reconnect_time <= now < market_open:
            self._ws_premarket_reconnect_done = True
            self.logger.info("🔄 PRE-MARKET RECONNECT: Refreshing WebSocket before market open...")
            
            # Force reconnect for fresh connection
            if self.broker_client:
                try:
                    self.broker_client.stop_websocket()
                    time.sleep(1)
                    self._start_websocket()
                    self.logger.info("✅ Pre-market WebSocket refresh complete!")
                except Exception as e:
                    self.logger.warning(f"⚠ Pre-market reconnect failed: {e}")
    
    def reset_premarket_reconnect(self):
        """Reset pre-market reconnect flag for new trading day (call at midnight)"""
        self._ws_premarket_reconnect_done = False

    def _on_ws_tick(self, tick_data: Dict):
        """Handle incoming WebSocket tick — thread-safe"""
        with self._tick_lock:
            token = str(tick_data.get('token', ''))
            
            # Layer 1: Update heartbeat timestamp (tick received = connection alive)
            self._ws_last_tick_time = time.time()
            
            # Reset reconnect counter and delay on successful tick
            if self._ws_reconnect_attempts > 0:
                self._ws_reconnect_attempts = 0
                self._ws_reconnect_delay = 1.0  # Reset exponential backoff

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

                # FIX: If bid/ask equal OR not available, estimate spread
                # This prevents inverted market (bid >= ask) rejection
                if bid <= 0 or ask <= 0 or bid >= ask:
                    spread = max(0.05, ltp * 0.003)  # 0.3% spread estimate
                    bid = round(ltp - spread / 2, 2)
                    ask = round(ltp + spread / 2, 2)

                # ═══════════════════════════════════════════════════════════════
                # CRITICAL FIX: Only accept ticks from CURRENT subscribed token
                # After symbol switch, old token's ticks may still arrive briefly
                # ═══════════════════════════════════════════════════════════════
                if self._option_token and token != self._option_token:
                    # This tick is from old symbol, discard it
                    return
                
                tick_ts = current_time_ms()
                new_tick = {
                    'timestamp': tick_ts,
                    'original_timestamp': tick_ts,
                    'ltp': round(ltp, 2),
                    'bid': round(bid, 2),
                    'ask': round(ask, 2),
                    'volume': volume,
                    'spot_price': self.spot_price,
                    'symbol': self.current_symbol,
                    'strike': self.current_strike,
                    'direction': OPTION_TYPE,
                    'token': token,  # Include token for debugging
                }
                
                # Add to tick buffer for smoother data flow
                if self._use_tick_buffer:
                    self._tick_buffer.append(new_tick)
                    if len(self._tick_buffer) > self._tick_buffer_max_size:
                        self._tick_buffer.pop(0)
                
                self.last_tick = new_tick
                self.last_valid_tick_time = datetime.now()
                self._ws_original_tick_time = time.time()  # Track when real data arrived

    # =========================================================================
    # REST FALLBACK — when WebSocket is disabled or fails
    # =========================================================================

    def _fetch_option_tick_rest(self) -> Optional[Dict]:
        """Fetch option tick via REST API (used as fallback or initial)
        
        Circuit Breaker Pattern:
        - If 10+ consecutive errors, enter cooldown mode
        - Cooldown: 300 seconds (5 min) before retrying
        - Prevents log spam during network outages
        """
        if not self.broker_client or not self.current_symbol:
            return None
        
        # Initialize circuit breaker state
        if not hasattr(self, '_network_error_count'):
            self._network_error_count = 0
            self._network_cooldown_until = None
        
        # Check if in cooldown mode (circuit breaker open)
        if self._network_cooldown_until:
            if datetime.now() < self._network_cooldown_until:
                # Still in cooldown - return cached tick silently
                if self._cached_option_tick:
                    cached = self._cached_option_tick.copy()
                    cached['timestamp'] = current_time_ms()
                    return cached
                return None
            else:
                # Cooldown expired - reset and try again
                self._network_cooldown_until = None
                self._network_error_count = 0
                self.logger.info("🔄 Network cooldown ended - retrying connection...")

        try:
            tick = self.broker_client.get_market_tick(
                symbol=self.current_symbol,
                exchange=EXCHANGE
            )
            if tick:
                tick_ts = current_time_ms()
                tick['spot_price'] = self.spot_price
                tick['strike'] = self.current_strike
                tick['direction'] = OPTION_TYPE
                tick['symbol'] = self.current_symbol  # CRITICAL: Set symbol for verification
                tick['timestamp'] = tick_ts
                tick['original_timestamp'] = tick_ts
                self._cached_option_tick = tick
                self._last_option_fetch = time.time()
                self.last_valid_tick_time = datetime.now()
                # Reset error count on success
                self._network_error_count = 0
                return tick
        except (ConnectionError, OSError, requests.exceptions.RequestException) as e:
            self._network_error_count += 1
            error_str = str(e).lower()
            
            # Check if this is a network-related error
            is_network_error = any(x in error_str for x in [
                'name resolution', 'connection', 'network', 'timeout', 
                'unreachable', 'reset', 'refused', 'dns'
            ])
            
            if is_network_error and self._network_error_count >= 10:
                # Circuit breaker OPEN - enter cooldown
                self._network_cooldown_until = datetime.now() + timedelta(seconds=300)
                self.logger.warning(
                    f"🔌 Network Down - Circuit breaker activated | "
                    f"Errors: {self._network_error_count} | "
                    f"Cooldown: 5 minutes (until {self._network_cooldown_until.strftime('%H:%M:%S')})"
                )
            elif self._network_error_count == 1 or self._network_error_count % 50 == 0:
                # Log only first error and every 50th to prevent spam
                self.logger.warning(f"⚠ REST tick fetch failed ({self._network_error_count}x): {e}")
        except Exception as e:
            # Non-network errors - log normally but less frequently
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
                    if abs(self.spot_price - self.current_strike) >= 50:  # Reduced from 150 to 50
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

        # Return cached tick (no noise for accurate paper trading)
        # BUG FIX #14: Removed random noise that was distorting prices
        if self._cached_option_tick:
            cached = self._cached_option_tick.copy()
            cached['spot_price'] = self.spot_price
            # Keep exact LTP from last REST fetch - no artificial noise
            cached['timestamp'] = current_time_ms()
            if 'original_timestamp' not in cached:
                cached['original_timestamp'] = self._last_option_fetch and int(self._last_option_fetch * 1000) or current_time_ms()
            self.last_valid_tick_time = datetime.now()
            return cached

        return None

    # =========================================================================
    # GET TICK — unified entry point
    # =========================================================================

    def get_tick(self) -> Optional[Dict[str, Any]]:
        """
        Get current market tick data (Algo Trading Optimized).
        Priority: WebSocket -> REST polling -> Simulation
        Each tick is tagged with 'data_source' for tracking.
        
        Note: Layer 1 heartbeat monitor handles staleness detection and
        triggers reconnect automatically. This method focuses on data delivery.
        """
        # Path 1: WebSocket tick (real-time, <100ms latency)
        if USE_LIVE_DATA and self._ws_connected and self.last_tick:
            # Check if original tick is stale - use REST to refresh
            original_age = time.time() - self._ws_original_tick_time if self._ws_original_tick_time else 999
            
            # If WebSocket tick is > 60s old, force REST refresh to get latest price
            # This handles the case where WebSocket only sends on price change
            if original_age > 60:
                # Periodic REST refresh (every 60 seconds when WS is quiet)
                last_rest = getattr(self, '_last_rest_refresh', 0)
                if time.time() - last_rest > 60:
                    self.logger.info(f"🔄 REST refresh triggered (WS tick {original_age:.0f}s old)")
                    # Force fresh REST call - bypass _get_rest_tick() interval check
                    rest_tick = self._fetch_option_tick_rest()
                    if rest_tick:
                        self._last_rest_refresh = time.time()
                        self._last_option_fetch = time.time()  # Reset interval
                        # Update WebSocket cached tick with fresh REST data
                        with self._tick_lock:
                            self.last_tick = rest_tick.copy()
                            self._ws_original_tick_time = time.time()
                        rest_tick['data_source'] = 'REST_REFRESH'
                        self.last_valid_tick_time = datetime.now()
                        self.logger.info(f"✅ REST refresh: LTP ₹{rest_tick.get('ltp', 0):.2f}")
                        return rest_tick
                    else:
                        self.logger.warning("⚠ REST refresh failed")
                        return None
            
            with self._tick_lock:
                tick = self.last_tick.copy()
                # CRITICAL FIX: Refresh timestamp to NOW to prevent stale tick rejection
                tick['timestamp'] = current_time_ms()

            # Ensure tick symbol matches currently subscribed symbol
            if tick.get('symbol') and self.current_symbol and tick.get('symbol') != self.current_symbol:
                self.logger.warning(f"⚠ Tick symbol mismatch: cache {tick.get('symbol')} vs expected {self.current_symbol} — attempting REST refresh")
                # Try one REST fetch to get correct symbol's price
                rest_tick = self._fetch_option_tick_rest()
                if rest_tick:
                    with self._tick_lock:
                        self.last_tick = rest_tick.copy()
                        self._ws_original_tick_time = time.time()
                    rest_tick['data_source'] = 'REST_REFRESH'
                    self.last_valid_tick_time = datetime.now()
                    self.logger.info(f"✅ REST refresh after symbol mismatch: LTP ₹{rest_tick.get('ltp', 0):.2f}")
                    return rest_tick
                else:
                    # If refresh failed, skip returning a tick to avoid wrong-symbol actions
                    return None

            # Track when we last successfully served a tick
            self.last_valid_tick_time = datetime.now()
            
            tick['data_source'] = 'WEBSOCKET'
            return tick

        # Path 2: REST polling (for when WebSocket is off/failed)
        if USE_LIVE_DATA and self.broker_client:
            rest_tick = self._get_rest_tick()
            if rest_tick:
                rest_tick['data_source'] = 'REST'
                return rest_tick

        # Path 3: Simulation (paper trading without live data)
        return self._get_simulated_tick()

    def get_ws_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status for monitoring"""
        return {
            'connected': self._ws_connected,
            'last_tick_time': self._ws_last_tick_time,
            'time_since_last_tick': time.time() - self._ws_last_tick_time if self._ws_last_tick_time else None,
            'reconnect_attempts': self._ws_reconnect_attempts,
            'circuit_breaker_open': self._ws_circuit_open,
            'circuit_cooldown_until': self._ws_circuit_cooldown_until.strftime('%H:%M:%S') if self._ws_circuit_cooldown_until else None,
            'premarket_reconnect_done': self._ws_premarket_reconnect_done,
            'tick_buffer_size': len(self._tick_buffer),
        }

    def get_smoothed_tick(self) -> Optional[Dict[str, Any]]:
        """Get averaged tick from buffer for smoother algo trading (reduces noise)"""
        if not self._tick_buffer or len(self._tick_buffer) < 2:
            return self.get_tick()
        
        with self._tick_lock:
            # Calculate average of buffered ticks
            avg_ltp = sum(t['ltp'] for t in self._tick_buffer) / len(self._tick_buffer)
            avg_bid = sum(t['bid'] for t in self._tick_buffer) / len(self._tick_buffer)
            avg_ask = sum(t['ask'] for t in self._tick_buffer) / len(self._tick_buffer)
            total_volume = self._tick_buffer[-1].get('volume', 0)
            
            # Use latest tick as base, but with smoothed prices
            smoothed = self._tick_buffer[-1].copy()
            smoothed['ltp'] = round(avg_ltp, 2)
            smoothed['bid'] = round(avg_bid, 2)
            smoothed['ask'] = round(avg_ask, 2)
            smoothed['volume'] = total_volume
            smoothed['data_source'] = 'WEBSOCKET_SMOOTHED'
            smoothed['buffer_size'] = len(self._tick_buffer)
            
            return smoothed

    def clear_tick_buffer(self):
        """Clear tick buffer (call on position change to reset smoothing)"""
        with self._tick_lock:
            self._tick_buffer.clear()

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
            'data_source': 'SIMULATION',
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

        # ═══════════════════════════════════════════════════════════════════
        # CRITICAL FIX: Update current_symbol BEFORE getting tick
        # This ensures tick data matches the actual symbol being traded
        # ═══════════════════════════════════════════════════════════════════
        old_symbol = self.current_symbol
        if option_symbol != self.current_symbol:
            self.current_symbol = option_symbol
            self._option_token = self._get_token(option_symbol, EXCHANGE)
            self.logger.info(f"📍 Symbol switched: {old_symbol} → {option_symbol}")
            
            # Re-subscribe WebSocket to new symbol
            if USE_LIVE_DATA and ENABLE_WEBSOCKET and self._ws_connected:
                if self.broker_client and self._option_token:
                    try:
                        # Clear old tick data to avoid stale price
                        with self._tick_lock:
                            self.last_tick = None
                            self._tick_buffer.clear()
                        
                        self.broker_client.subscribe_symbols([
                            {"exchangeType": "2", "tokens": [self._option_token]}
                        ])
                        self.logger.info(f"🔌 WebSocket re-subscribed to {option_symbol}")
                        
                        # Wait briefly for first tick from new symbol
                        time.sleep(0.3)
                    except Exception as e:
                        self.logger.warning(f"⚠ WebSocket re-subscribe failed: {e}")

        # Get SL/TP from signal params (which now come from .env via strategy)
        sl_points = signal_params.get('sl_points', SL_POINTS_FIXED)
        tp_points = signal_params.get('tp_points', TP_POINTS_FIXED)
        confidence = signal_params.get('confidence', 60)

        # -- PAPER TRADING --
        if PAPER_TRADING:
            tick = self.get_tick()
            
            # CRITICAL: If tick is from wrong symbol or stale, fetch fresh via REST
            if tick and tick.get('symbol') != option_symbol:
                self.logger.warning(f"⚠ Tick symbol mismatch: {tick.get('symbol')} vs {option_symbol}")
                # Force REST fetch for correct symbol's price
                rest_tick = self._fetch_option_tick_rest()
                if rest_tick:
                    tick = rest_tick
                    self.logger.info(f"✅ REST tick for {option_symbol}: LTP ₹{tick.get('ltp', 0):.2f}")
            
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

        # -- LIVE TRADING — with smart order execution --
        try:
            symbol_token = self._get_token(option_symbol, EXCHANGE)
            if not symbol_token:
                self.logger.error(f"❌ Token not found for {option_symbol}")
                return None

            # Get current tick for price calculation
            tick = self.get_tick()
            if not tick:
                self.logger.error("❌ No tick data for order pricing")
                return None
            
            # ═══════════════════════════════════════════════════════════════════
            # v3.1: SMART LIMIT ORDER EXECUTION WITH RETRY
            # ═══════════════════════════════════════════════════════════════════
            if USE_LIMIT_ORDERS:
                # Calculate initial limit price
                bid = tick.get('bid', tick['ltp'] - 0.5)
                ask = tick.get('ask', tick['ltp'] + 0.5)
                
                if side == 'BUY':
                    # For BUY: start at ask - offset, chase up on retries
                    limit_price = ask - LIMIT_ORDER_OFFSET
                else:
                    # For SELL: start at bid + offset, chase down on retries
                    limit_price = bid + LIMIT_ORDER_OFFSET
                
                limit_price = round(limit_price, 2)
                
                # Retry loop with price chasing
                order_resp = None
                for attempt in range(ORDER_MAX_RETRIES if ORDER_RETRY_ENABLED else 1):
                    self.logger.info(f"📦 LIMIT order attempt {attempt + 1}: {side} @ ₹{limit_price:.2f}")
                    
                    try:
                        order_resp = self.broker_client.place_order(
                            symbol=option_symbol,
                            exchange=EXCHANGE,
                            transaction_type=side,
                            quantity=qty,
                            order_type="LIMIT",
                            price=limit_price,
                            symbol_token=symbol_token
                        )
                        
                        if order_resp and order_resp.get('orderid'):
                            order_id = order_resp['orderid']
                            
                            # Wait for fill (2 seconds)
                            time.sleep(2)
                            status = self.broker_client.get_order_status(order_id)
                            
                            if status:
                                order_status = str(status.get('orderstatus', '')).lower()
                                
                                if order_status == 'complete':
                                    # Order filled! Success!
                                    break
                                elif order_status == 'open' or order_status == 'pending':
                                    # Not filled yet - cancel and retry with better price
                                    self.logger.info(f"⏳ LIMIT order pending, cancelling for retry...")
                                    try:
                                        self.broker_client.cancel_order(order_id)
                                    except:
                                        pass
                                    
                                    # Chase price
                                    if side == 'BUY':
                                        limit_price += ORDER_PRICE_CHASE_STEP
                                    else:
                                        limit_price -= ORDER_PRICE_CHASE_STEP
                                    limit_price = round(limit_price, 2)
                                    
                                    time.sleep(ORDER_RETRY_DELAY_MS / 1000)
                                    continue
                                elif order_status == 'rejected':
                                    self.logger.warning(f"⚠ LIMIT order rejected: {status.get('text')}")
                                    break
                    
                    except Exception as e:
                        self.logger.warning(f"⚠ LIMIT order attempt {attempt + 1} failed: {e}")
                
                # If LIMIT orders failed, fall back to MARKET
                if not order_resp or not order_resp.get('orderid'):
                    self.logger.warning("⚠ LIMIT orders failed, falling back to MARKET order")
                else:
                    # Check final status
                    order_id = order_resp['orderid']
                    status = self.broker_client.get_order_status(order_id)
                    if status and str(status.get('orderstatus', '')).lower() != 'complete':
                        self.logger.warning("⚠ LIMIT order not filled, falling back to MARKET")
                        try:
                            self.broker_client.cancel_order(order_id)
                        except:
                            pass
                        order_resp = None
            
            # MARKET order (original path or fallback)
            if not USE_LIMIT_ORDERS or not order_resp or not order_resp.get('orderid'):
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

                        # v3.4: Slippage validation — alert if fill deviates too much
                        expected_price = tick.get('ltp', avg_price) if tick else avg_price
                        if expected_price > 0:
                            slippage_pct = abs(avg_price - expected_price) / expected_price * 100
                            if slippage_pct > MAX_SLIPPAGE_PCT:
                                self.logger.warning(
                                    f"⚠️ HIGH SLIPPAGE: {slippage_pct:.2f}% | Expected ₹{expected_price:.2f} → Got ₹{avg_price:.2f}"
                                )
                                try:
                                    from core.services.telegram_bot import send_alert
                                    send_alert(
                                        f"⚠️ SLIPPAGE ALERT\n"
                                        f"Expected: ₹{expected_price:.2f}\n"
                                        f"Filled: ₹{avg_price:.2f}\n"
                                        f"Slip: {slippage_pct:.2f}% (limit {MAX_SLIPPAGE_PCT}%)"
                                    )
                                except Exception:
                                    pass

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
                      total_capital: float, current_tick: Dict = None) -> Dict[str, Any]:
        """Exit current position — Paper or Live with verification.
        
        Args:
            current_tick: If provided, use this tick for PnL calculation instead
                          of calling get_tick() again (prevents data source mismatch).
        """
        if trade is None:
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}

        self.logger.info(f"🚪 Exiting position: {trade['order_id']} | Reason: {exit_reason}")

        # FIX: Use the same tick that triggered the exit, not a new one
        tick = current_tick if current_tick else self.get_tick()
        if not tick:
            self.logger.error("Cannot exit: No tick data")
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0, 'exit_confirmed': False}

        exit_price = tick['bid'] if trade['side'] == 'BUY' else tick['ask']
        entry_price = trade['entry_price']
        qty = trade['qty']

        # Calculate PnL
        if trade['side'] == 'BUY':
            price_diff = exit_price - entry_price
        else:
            price_diff = entry_price - exit_price

        pnl_inr = price_diff * qty

        # FIX: If exit engine already calculated capped PnL, use it
        # This prevents mismatch when tick sources differ
        if 'current_pnl' in trade and trade['current_pnl'] != 0:
            engine_pnl = trade['current_pnl']
            # Use engine PnL if it's a loss (exit engine caps losses properly)
            if engine_pnl < 0:
                pnl_inr = engine_pnl
                self.logger.info(f"   Using exit engine PnL: ₹{pnl_inr:+.2f} (capped)")
            # For profits, also trust exit engine when tick-based PnL is suspicious (e.g. zero)
            elif abs(pnl_inr) < 0.01 and abs(engine_pnl) > 0.01:
                pnl_inr = engine_pnl
                self.logger.info(f"   Using exit engine PnL: ₹{pnl_inr:+.2f} (tick PnL was zero)")

        pnl_pct = (pnl_inr / total_capital) * 100
        hold_time = (datetime.now() - trade['entry_time']).total_seconds()

        new_daily_pnl = daily_pnl_inr + pnl_inr
        new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100

        exit_confirmed = True

        # Execute exit order if live trading
        if not PAPER_TRADING and self.broker_client:
            exit_confirmed = False
            try:
                exit_side = "SELL" if trade['side'] == "BUY" else "BUY"
                symbol = trade.get('symbol', self.current_symbol)
                symbol_token = self._get_token(symbol, EXCHANGE)

                if symbol_token:
                    # ═══════════════════════════════════════════════════════════
                    # EXIT ORDER WITH RETRY (v3.3 - Critical Safety Fix)
                    # Retry up to 3 times with MARKET order fallback
                    # ═══════════════════════════════════════════════════════════
                    exit_order_id = None
                    max_exit_retries = 3
                    
                    for attempt in range(1, max_exit_retries + 1):
                        try:
                            # First attempt: normal order, retries: force MARKET
                            order_type = "MARKET" if attempt > 1 else None
                            
                            order_kwargs = dict(
                                symbol=symbol,
                                exchange=EXCHANGE,
                                transaction_type=exit_side,
                                quantity=qty,
                                symbol_token=symbol_token
                            )
                            if order_type:
                                order_kwargs['order_type'] = order_type
                            
                            order_resp = self.broker_client.place_order(**order_kwargs)
                            
                            if order_resp and order_resp.get('orderid'):
                                exit_order_id = order_resp['orderid']
                                self.logger.info(f"✅ Exit order sent (attempt {attempt}): {exit_order_id}")
                                break
                            else:
                                self.logger.warning(f"⚠️ Exit order attempt {attempt}/{max_exit_retries} failed: {order_resp}")
                                if attempt < max_exit_retries:
                                    time.sleep(1)
                        except Exception as retry_err:
                            self.logger.error(f"❌ Exit order attempt {attempt}/{max_exit_retries} error: {retry_err}")
                            if attempt < max_exit_retries:
                                time.sleep(1)
                    
                    if exit_order_id:
                        # Verify exit fill
                        for _ in range(5):
                            time.sleep(1)
                            try:
                                status = self.broker_client.get_order_status(exit_order_id)
                                if status and str(status.get('orderstatus', '')).lower() == 'complete':
                                    real_exit = float(status.get('averageprice', exit_price))
                                    # v3.4: Exit slippage check
                                    if exit_price > 0:
                                        exit_slip_pct = abs(real_exit - exit_price) / exit_price * 100
                                        if exit_slip_pct > MAX_SLIPPAGE_PCT:
                                            self.logger.warning(f"⚠️ EXIT SLIPPAGE: {exit_slip_pct:.2f}% | Target ₹{exit_price:.2f} → Got ₹{real_exit:.2f}")
                                    # Recalculate with real exit price
                                    if trade['side'] == 'BUY':
                                        pnl_inr = (real_exit - entry_price) * qty
                                    else:
                                        pnl_inr = (entry_price - real_exit) * qty
                                    exit_price = real_exit
                                    pnl_pct = (pnl_inr / total_capital) * 100
                                    new_daily_pnl = daily_pnl_inr + pnl_inr
                                    new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100
                                    exit_confirmed = True
                                    self.logger.info(f"✅ Exit confirmed @ ₹{real_exit:.2f}")
                                    break
                            except Exception:
                                pass
                    else:
                        self.logger.error(f"🚨 CRITICAL: All {max_exit_retries} exit attempts FAILED! Position may remain OPEN!")
                        self.logger.error(f"🚨 Manual intervention needed: {exit_side} {qty} {symbol}")
                        # Send Telegram alert if available
                        try:
                            from core.services.telegram_bot import get_telegram
                            tg = get_telegram()
                            if tg:
                                tg.send_message(
                                    f"🚨 EMERGENCY: Exit order FAILED after {max_exit_retries} retries!\n"
                                    f"Action: {exit_side} {qty} {symbol}\n"
                                    f"Please close position MANUALLY!"
                                )
                        except Exception:
                            pass

                self.clear_position_cache()

            except Exception as e:
                self.logger.error(f"❌ Exit order error: {e}")

        if not exit_confirmed:
            self.logger.error("🚨 Exit not confirmed. Keeping trade open in bot state.")
            return {
                'pnl_inr': pnl_inr,
                'pnl_pct': pnl_pct,
                'hold_time': hold_time,
                'exit_confirmed': False
            }

        # Log trade exit only after paper exit or confirmed live exit.
        self.logger.trade_exit({
            'order_id': trade['order_id'],
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time_sec': hold_time
        })
        self.logger.info(f"💰 PnL: ₹{pnl_inr:+.2f} ({pnl_pct:+.2f}%) | Daily: ₹{new_daily_pnl:+.2f} ({new_daily_pnl_pct:+.2f}%)")

        return {
            'pnl_inr': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time': hold_time,
            'exit_confirmed': True
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
