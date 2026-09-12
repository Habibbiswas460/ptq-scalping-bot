"""
PTQ Scalping Bot - Broker Interface

BrokerInterface composes its behavior from sibling mixin files — each one file, one
concern, mirroring the same pattern brokers/angel_one/client.py uses:

- strike_selector.py       strike rotation, premium search, expiry, option-symbol building
- reconnect_manager.py     subscribe/unsubscribe, WebSocket session start, the 4-layer
                           reconnect protection (heartbeat monitor, backoff, circuit
                           breaker, pre-market reconnect)
- tick_feed.py             the WebSocket tick callback, REST fallback/polling, the
                           paper-trading simulator, persistence/observability helpers
- historical_candles.py    historical OHLC fetch with retry, in-memory + on-disk cache
- order_execution.py       place_order / exit_position, position cache

__init__/connect/logout stay here as the orchestration entry points, along with
_load_scrip_master/_get_token (the instrument master), resolve_strike_for_direction, and
get_tick/_get_tick_uncached — these five specifically stay on this class rather than
moving into a mixin file because existing tests patch module globals this file owns
(SCRIP_MASTER_CACHE_FILE, CROSS_DIRECTION_STRIKE_ENABLED/TTL_SEC, USE_LIVE_DATA) that a
function only honors when it's defined in the module the patch targets — moving the
function elsewhere would silently stop honoring the patch, not just relocate the code.
"""

import json
import time
import requests
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from brokers.base import BrokerClient
from brokers.factory import create_broker_client
from core.market_data.tick_cache import TickCache
from core.market_data.tick_validator import SequenceTracker
from core.market_data.ohlcv_aggregator import OHLCVAggregator
from core.market_data.tick_writer import BatchedTickWriter
from utils.logger import BotLogger
from utils.helpers import current_time_ms

from core.trading.strike_selector import StrikeSelectorMixin
from core.trading.reconnect_manager import ReconnectManagerMixin
from core.trading.tick_feed import TickFeedMixin
from core.trading.historical_candles import HistoricalCandlesMixin
from core.trading.order_execution import OrderExecutionMixin

from config.constants import (
    BROKER_NAME,
    PAPER_TRADING, USE_LIVE_DATA, ENABLE_WEBSOCKET,
    OPTION_TYPE, EXCHANGE,
    LOG_DIRECTORY, LOG_CONSOLE,
    ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET,
    CROSS_DIRECTION_STRIKE_ENABLED, CROSS_DIRECTION_STRIKE_TTL_SEC,
    MARKET_OPEN_TIME,
    NIFTY_SPOT_TOKEN,
    SCRIP_MASTER_URL,
    SCRIP_MASTER_CACHE_TTL_SEC,
    SCRIP_MASTER_CACHE_FILE as _SCRIP_MASTER_CACHE_FILE,
)

# ScripMaster location comes from config.constants, because utils/instruments.py reads the
# same cache to answer "when is expiry" - the file is the broker's own contract list and
# the only authority on that, so where it lives is stated once.
SCRIP_MASTER_CACHE_FILE = Path(_SCRIP_MASTER_CACHE_FILE)


class BrokerInterface(StrikeSelectorMixin, ReconnectManagerMixin, TickFeedMixin,
                       HistoricalCandlesMixin, OrderExecutionMixin):
    """Broker interface for Angel One — WebSocket enabled"""

    def __init__(self):
        self.broker_client: Optional[BrokerClient] = None
        self.logger: Optional[BotLogger] = None

        # Token map from ScripMaster (symbol -> token)
        self.token_map: Dict[str, str] = {}

        # Quote-source observability (measurement only — never read by any
        # trading decision). Counts how often bid/ask came from the real book
        # versus the estimated-spread fallback, so the inertness of the
        # spread-based filters can be quantified before anything is changed.
        self._quote_source_counts: Dict[str, int] = {}
        self._quote_source_last_log: float = 0.0
        self._quote_source_log_interval_sec: float = 300.0

        # Trading state
        self.current_symbol: Optional[str] = None
        self.current_strike: int = 0
        self.spot_price: float = 0.0
        self._current_expiry: Optional[str] = None
        # symbol -> the exchange's own contract record (expiry, strike, lot, tick, freeze)
        self.contracts: Dict[str, Dict[str, Any]] = {}
        self._option_token: Optional[str] = None

        # Last known-good historical candles, keyed by "exchange:token:interval"
        # (fallback source when the broker API rate-limits a fetch)
        self._historical_candles_cache: Dict[str, Dict[str, Any]] = {}
        # direction -> {strike, atm, at}: the opposite direction's own premium-band
        # strike, cached because the search costs up to five REST calls.
        self._cross_strike_cache: Dict[str, Dict[str, Any]] = {}

        # WebSocket tick state (thread-safe)
        self._tick_lock = threading.Lock()
        self.last_tick: Optional[Dict] = None
        self._last_logged_tick: Optional[tuple] = None  # (symbol, ltp, bid, ask) dedup key for tick persistence
        self.last_valid_tick_time: Optional[datetime] = None  # When we last SERVED a tick
        self._ws_original_tick_time: Optional[float] = None   # When original tick data arrived
        self._ws_connected: bool = False

        # ═══════════════════════════════════════════════════════════════════
        # UNBREAKABLE WEBSOCKET TUNNEL - 4 Layers of Protection (Algo Trading)
        # ═══════════════════════════════════════════════════════════════════
        # Layer 1: Heartbeat Monitor (15s for algo trading - fast detection)
        # Note: Angel One only sends on price CHANGES. REST polling fills gaps.
        self._ws_last_tick_time: float = 0
        self._ws_last_option_tick_time: float = 0
        self._ws_heartbeat_timeout: int = 30  # 30 seconds for algo trading (more conservative)
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
        self._ws_connection_limit_cooldown_sec: int = 900  # 15 minutes on broker 429 limit

        # Layer 4: Pre-Market Reconnect Timer (reconnect 2 min before market open)
        self._ws_premarket_reconnect_done: bool = False
        self._market_open_time = MARKET_OPEN_TIME  # IST, from MARKET_OPEN
        self._premarket_reconnect_margin_sec: int = 120  # 2 min before market

        # Algo Trading: Tick Buffer for smoother data flow
        self._tick_buffer: List[Dict] = []
        self._tick_buffer_max_size: int = 10  # Keep last 10 ticks
        self._use_tick_buffer: bool = True  # Enable tick smoothing
        # ═══════════════════════════════════════════════════════════════════

        # core/market_data/ pipeline — additive: a token-keyed mirror of every
        # accepted tick, plus null/sequence/book-sanity observability. self.last_tick
        # (above) stays the sole source of truth for entry/exit decisions; nothing here
        # gates or alters it.
        self.market_tick_cache = TickCache()
        self._tick_sequence_tracker = SequenceTracker()
        # In-memory only (no disk I/O), so it's cheap enough to feed on every tick.
        # Runs alongside get_historical_candles()'s REST fetch, doesn't replace it —
        # strategies keep reading candles from there until told otherwise.
        self.market_ohlcv = OHLCVAggregator(on_candle_close=self._on_market_candle_closed)
        # Lazily created in _start_websocket() — constructing TickStore eagerly here
        # would create data/tick_store/ on disk just from instantiating BrokerInterface
        # (e.g. every test that imports this module), not from actually connecting.
        self.tick_writer: Optional[BatchedTickWriter] = None

        # Phase 4: Position caching (5-second TTL)
        self._position_cache: Optional[Dict] = None
        self._position_cache_time: float = 0
        self._position_cache_ttl = 5.0

        # Reconnect guard to avoid duplicate reconnection attempts
        self._ws_reconnect_lock = threading.Lock()
        self._ws_reconnect_running: bool = False
        self._ws_shutdown_requested: bool = False
        self._ws_heartbeat_stop_event = threading.Event()

        # REST polling fallback state
        self._last_spot_fetch: float = 0
        self._last_option_fetch: float = 0
        self._cached_option_tick: Optional[Dict] = None

        # Strike rotation guardrails: prevent re-subscription churn during WS stress
        self._last_strike_rotation_time: float = 0.0
        self._strike_rotation_cooldown_sec: int = 180
        self._last_ws_reconnect_time: float = 0.0
        self._ws_reconnect_stress_cooldown_sec: int = 180
        self._last_ws_ack_timeout_time: float = 0.0
        self._ws_ack_timeout_cooldown_sec: int = 180

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
        self._ws_shutdown_requested = False
        self._ws_heartbeat_stop_event.clear()
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

            self.broker_client = create_broker_client(
                broker=BROKER_NAME,
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
        # Try local cache first to avoid blocking startup on slow network.
        try:
            if SCRIP_MASTER_CACHE_FILE.exists():
                age_sec = time.time() - SCRIP_MASTER_CACHE_FILE.stat().st_mtime
                with SCRIP_MASTER_CACHE_FILE.open("r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, dict):
                    cached_map = cached.get("token_map", {})
                    cached_contracts = cached.get("contracts", {})
                    if isinstance(cached_contracts, dict):
                        self.contracts.update(cached_contracts)
                else:
                    cached_map = {}
                if isinstance(cached_map, dict) and cached_map:
                    self.token_map.update({str(k): str(v) for k, v in cached_map.items() if k and v})
                    if age_sec <= SCRIP_MASTER_CACHE_TTL_SEC and self.contracts:
                        self.logger.info(
                            f"✅ ScripMaster cache loaded: {len(self.token_map)} tokens "
                            f"(age {int(age_sec)}s)"
                        )
                        return
                    else:
                        self.logger.info(
                            f"♻ Using stale ScripMaster cache while refreshing in foreground "
                            f"(age {int(age_sec)}s)"
                        )
        except Exception as e:
            self.logger.warning(f"⚠ Local ScripMaster cache read failed: {e}")

        self.logger.info("📥 Downloading ScripMaster JSON...")
        try:
            # Keep timeout tight so readiness flow cannot block for long.
            response = requests.get(SCRIP_MASTER_URL, timeout=(5, 12))
            response.raise_for_status()
            data = response.json()

            # Cache only NIFTY NFO symbols (saves memory), keeping the contract fields
            # the exchange states rather than only symbol -> token. expiry, lotsize,
            # tick_size, strike and freeze_qty had each been replaced by a constant
            # somewhere in the codebase; utils/instruments.py reads them from here.
            count = 0
            for item in data:
                if item.get('exch_seg') == 'NFO' and item.get('name') == 'NIFTY':
                    sym = item.get('symbol', '')
                    tok = item.get('token', '')
                    if sym and tok:
                        self.token_map[sym] = tok
                        self.contracts[sym] = {
                            'token': tok,
                            'expiry': item.get('expiry', ''),
                            'strike': item.get('strike', ''),
                            'lotsize': item.get('lotsize', ''),
                            'tick_size': item.get('tick_size', ''),
                            'freeze_qty': item.get('freeze_qty', ''),
                            'instrumenttype': item.get('instrumenttype', ''),
                        }
                        count += 1

            self.logger.info(f"✅ ScripMaster cached: {count} NIFTY NFO contracts")

            # Persist to local cache for next startup.
            try:
                SCRIP_MASTER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with SCRIP_MASTER_CACHE_FILE.open("w", encoding="utf-8") as f:
                    json.dump({"saved_at": datetime.now().isoformat(),
                               "token_map": self.token_map,
                               "contracts": self.contracts}, f)
            except Exception as cache_err:
                self.logger.warning(f"⚠ Could not save ScripMaster cache: {cache_err}")

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
            real_spot = self.broker_client.get_ltp("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
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

    # =========================================================================
    # GET TICK — unified entry point
    # =========================================================================

    def resolve_strike_for_direction(self, direction: str) -> int:
        """The strike to use for `direction` — the one place that answers this question.

        `current_strike` was chosen by _find_strike_by_premium() for whichever option type
        is currently subscribed, so it is only the right strike for that type. Reusing it
        for the opposite direction picks the opposite moneyness: with an ITM CE (strike
        below spot) the same-strike PE is OTM and cheap, which is why every cross-direction
        PE on 2026-09-07 priced at ₹31-32 against the ₹70 floor and was rejected after it
        had already cleared confidence.

        Both get_tick_for_direction() and place_order() go through here, so the contract
        that is validated is always the contract that gets traded. Any divergence between
        those two would be worse than the bug this fixes.

        The search costs up to five REST LTP calls, and the strategy evaluates many times a
        second, so the answer is cached per direction until the TTL expires or the ATM
        strike moves. On failure the current strike is returned — the old behaviour — so a
        lookup problem degrades to what the bot did before rather than to no trade at all.
        """
        if not CROSS_DIRECTION_STRIKE_ENABLED:
            return self.current_strike
        # Already the subscribed type: current_strike was chosen for exactly this.
        if self.current_symbol and self.current_symbol.endswith(direction):
            return self.current_strike
        if not self.spot_price or self.spot_price < 10000:
            return self.current_strike

        atm = round(self.spot_price / 50) * 50
        entry = self._cross_strike_cache.get(direction)
        if (entry and entry.get("atm") == atm
                and (time.time() - entry.get("at", 0)) < CROSS_DIRECTION_STRIKE_TTL_SEC):
            return entry["strike"]

        try:
            strike, premium = self._find_strike_by_premium(direction)
        except Exception as e:
            self.logger.debug(f"Cross-direction strike search failed for {direction}: {e}")
            return self.current_strike
        if not strike:
            return self.current_strike

        if not entry or entry.get("strike") != strike:
            self.logger.info(
                f"🎯 Cross-direction strike for {direction}: {strike} "
                f"(premium ₹{premium:.0f}) — subscribed {self.current_symbol} is "
                f"{self.current_strike}"
            )
        self._cross_strike_cache[direction] = {"strike": strike, "atm": atm, "at": time.time()}
        return strike

    def get_tick(self) -> Optional[Dict[str, Any]]:
        """
        Get current market tick data (Algo Trading Optimized).
        Priority: WebSocket -> REST polling -> Simulation
        Each tick is tagged with 'data_source' for tracking.

        Note: Layer 1 heartbeat monitor handles staleness detection and
        triggers reconnect automatically. This method focuses on data delivery.

        Every real (non-simulated) tick returned here is also persisted to
        the ticks table for future strategy-layer analysis — see
        fixed.md's tick-persistence entry. This is the single funnel point
        all three tick sources converge through, so it's the one place
        that needs to log rather than each source individually.
        """
        tick = self._get_tick_uncached()
        if tick and tick.get('data_source') != 'SIMULATION':
            self._persist_tick(tick)
        return tick

    def _get_tick_uncached(self) -> Optional[Dict[str, Any]]:
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
                    self._clear_rest_cache()
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
                        self._on_ws_disconnect("WS stale and REST refresh failed")
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

    def logout(self):
        """Logout and cleanup"""
        self._ws_shutdown_requested = True
        self._ws_heartbeat_stop_event.set()
        self._ws_connected = False
        # Force-close any in-progress 5-min candle and flush whatever the writer is
        # still holding, so a clean shutdown doesn't lose the last few seconds of data.
        self.market_ohlcv.flush()
        if self.tick_writer:
            self.tick_writer.stop()
        if self.broker_client:
            try:
                self.broker_client.stop_websocket()
            except Exception:
                pass
            if not PAPER_TRADING:
                self.broker_client.logout()

        if self._ws_heartbeat_thread and self._ws_heartbeat_thread.is_alive():
            self._ws_heartbeat_thread.join(timeout=1.0)


# Singleton instance
broker = BrokerInterface()
