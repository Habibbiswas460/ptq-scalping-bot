"""
Angel One SmartAPI Client - thin facade
Documentation: https://smartapi.angelbroking.com/docs/

AngelOneClient composes the mixins below — each one file, one concern:
- auth.py            login/logout/refresh/profile/funds
- orders.py          place/modify/cancel order, order/trade book, positions, holdings
- market_data_rest.py LTP/quote/batch/Greeks/candles/symbol search, rate limiting, symbol cache
- websocket_client.py connect/reconnect/heartbeat/ping-pong/subscribe/unsubscribe/ACK
- message_parser.py  binary tick + best-5 depth parsing

All mixins operate on this one instance's attributes (set up once, below) — this class
implements brokers.base.BrokerClient so core/trading/broker.py can eventually depend on
that contract instead of on this class directly.
"""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.logger import BotLogger

# Suppress verbose SmartAPI SDK logging BEFORE importing it (auth.py imports SmartConnect
# at module load time, immediately below) — keeping this ordering matters, it silences the
# SDK's own loggers before anything can log through them.
import logging as _logging
_null_handler = _logging.NullHandler()
for _logger_name in ['SmartApi', 'smartConnect', 'smartapi', 'SmartApi.smartConnect']:
    _sdk_logger = _logging.getLogger(_logger_name)
    _sdk_logger.handlers = [_null_handler]
    _sdk_logger.setLevel(_logging.ERROR)  # Only show errors

from brokers.base import BrokerClient
from .auth import AuthMixin
from .orders import OrdersMixin
from .market_data_rest import MarketDataRestMixin
from .websocket_client import WebSocketMixin
from .message_parser import MessageParserMixin


class AngelOneClient(AuthMixin, OrdersMixin, MarketDataRestMixin, WebSocketMixin, MessageParserMixin, BrokerClient):
    # BrokerClient (the ABC) must come LAST: Python's MRO resolves attributes in base-list
    # order, so if it came first its abstract stub methods (empty `...` bodies) would shadow
    # the mixins' real implementations of the same names instead of the other way round.
    """
    Complete Angel One SmartAPI Client

    Usage:
        client = AngelOneClient(api_key, client_id, password, totp_secret)
        client.login()

        # Place order (symbol format: NIFTY{DDMMMYY}{STRIKE}{CE/PE})
        order = client.place_order(
            symbol="NIFTY03FEB2625400CE",
            exchange="NFO",
            transaction_type="BUY",
            quantity=25,
            order_type="MARKET"
        )

        # Get LTP
        ltp = client.get_ltp("NFO", "NIFTY03FEB2625400CE", "49801")

        # WebSocket streaming
        client.start_websocket(on_tick=my_callback)
        client.subscribe([("NFO", "49801", 1)])  # 1 = LTP mode
    """

    def __init__(
        self,
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str,
        logger: Optional[BotLogger] = None
    ):
        """
        Initialize Angel One client

        Args:
            api_key: SmartAPI key from Angel One developer portal
            client_id: Your trading account ID (Client Code)
            password: Account PIN
            totp_secret: TOTP secret for 2FA (from authenticator app)
            logger: Optional custom logger
        """
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret

        self.logger = logger or BotLogger()
        # One warning per process if the best-5 book cannot be made sense of; without the
        # latch a malformed book would log on every tick.
        self._best5_warned = False

        # API connections
        self.smart_api = None  # type: Optional[Any]
        self.auth_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.feed_token: Optional[str] = None

        # Session info
        self.is_logged_in = False
        self.login_time: Optional[datetime] = None

        # Symbol cache (with TTL for Phase 3 optimization)
        self.symbol_cache: Dict[str, str] = {}
        self.symbol_cache_ttl: Dict[str, float] = {}  # token expiry times
        self.symbol_cache_ttl_sec = 86400.0  # 24 hours (Phase 3)

        # WebSocket - RACE CONDITION FIX v3.1: Thread-safe access
        self._ws_lock = threading.RLock()  # Reentrant lock for WebSocket
        self.ws = None  # WebSocketApp instance
        self.ws_thread: Optional[threading.Thread] = None
        self._ws_threads: List[threading.Thread] = []
        self.ws_connected = False
        self._manual_ws_stop = False
        self.subscriptions = {}  # Active subscriptions {token: mode}
        self._pending_ack_events: Dict[str, threading.Event] = {}
        self._pending_ack_results: Dict[str, bool] = {}
        self._pending_ack_lock = threading.Lock()

        # Phase 5: WebSocket Redundancy (3 concurrent connections)
        self.ws_connections = []  # List of WebSocket connections for failover
        self.ws_primary_index = 0  # Index of primary connection
        self.ws_max_connections = 3  # Maximum concurrent connections allowed
        self.ws_subscriptions = {}  # Track subscriptions across all connections
        self.on_tick_callback = None
        self.on_order_update_callback = None

        # Rate limiting
        self.last_call_time: Dict[str, float] = {}

        # Circuit breaker for network errors (reduces log spam during outages)
        self._api_error_count: int = 0
        self._api_cooldown_until: float = 0.0
        self._api_cooldown_duration: float = 60.0  # 60 second cooldown
        self._api_error_threshold: int = 5  # Enter cooldown after 5 consecutive errors

        # Tick data
        self.latest_ticks: Dict[str, Dict] = {}


def create_client_from_config(config_path: str) -> AngelOneClient:
    """
    Create client from config file

    Args:
        config_path: Path to credentials.json

    Returns:
        Initialized AngelOneClient
    """
    import json
    with open(config_path, 'r') as f:
        creds = json.load(f)

    return AngelOneClient(
        api_key=creds.get('api_key', ''),
        client_id=creds.get('client_id', ''),
        password=creds.get('password', ''),
        totp_secret=creds.get('totp_secret', '')
    )
