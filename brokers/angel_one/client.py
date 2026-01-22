"""
Angel One SmartAPI Client - Complete Implementation
Documentation: https://smartapi.angelbroking.com/docs/

Features:
- Authentication (Login, Token Refresh, Logout)
- Orders (Place, Modify, Cancel, Order Book, Trade Book)
- Market Data (LTP, OHLC, Full Quote)
- Portfolio (Holdings, Positions)
- Option Greeks
- WebSocket Streaming 2.0
- Rate Limiting & Error Handling
"""

import time
import json
import struct
import threading
import requests
import pyotp
from typing import Dict, Optional, Callable, List, Any
from datetime import datetime

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None

try:
    import websocket
except ImportError:
    websocket = None

from utils.logger import BotLogger


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class AngelOneError(Exception):
    """Base exception for Angel One errors"""
    pass

class AngelOneLoginError(AngelOneError):
    """Login/authentication error"""
    pass

class AngelOneApiError(AngelOneError):
    """General API error"""
    pass

class AngelOneOrderError(AngelOneError):
    """Order placement/modification error"""
    pass

class AngelOneRateLimitError(AngelOneError):
    """Rate limit exceeded"""
    pass


# =============================================================================
# CONSTANTS
# =============================================================================

# API Endpoints
BASE_URL = "https://apiconnect.angelone.in"
WEBSOCKET_URL = "wss://smartapisocket.angelone.in/smart-stream"

# Exchange Types
EXCHANGE_NSE = "NSE"
EXCHANGE_BSE = "BSE"
EXCHANGE_NFO = "NFO"
EXCHANGE_MCX = "MCX"
EXCHANGE_CDS = "CDS"

# WebSocket Exchange Types
WS_EXCHANGE_NSE_CM = 1
WS_EXCHANGE_NSE_FO = 2
WS_EXCHANGE_BSE_CM = 3
WS_EXCHANGE_BSE_FO = 4
WS_EXCHANGE_MCX_FO = 5
WS_EXCHANGE_NCX_FO = 7
WS_EXCHANGE_CDE_FO = 13

# WebSocket Modes
WS_MODE_LTP = 1
WS_MODE_QUOTE = 2
WS_MODE_SNAP_QUOTE = 3

# Order Types
ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_SL_LIMIT = "STOPLOSS_LIMIT"
ORDER_TYPE_SL_MARKET = "STOPLOSS_MARKET"

# Order Varieties
VARIETY_NORMAL = "NORMAL"
VARIETY_STOPLOSS = "STOPLOSS"
VARIETY_ROBO = "ROBO"  # Bracket Order

# Product Types
PRODUCT_INTRADAY = "INTRADAY"
PRODUCT_DELIVERY = "DELIVERY"
PRODUCT_MARGIN = "MARGIN"
PRODUCT_CARRYFORWARD = "CARRYFORWARD"

# Transaction Types
TRANSACTION_BUY = "BUY"
TRANSACTION_SELL = "SELL"

# Duration Types
DURATION_DAY = "DAY"
DURATION_IOC = "IOC"

# Rate Limits (per second)
RATE_LIMITS = {
    'login': 1,
    'generateTokens': 1,
    'getProfile': 3,
    'getRMS': 2,
    'placeOrder': 9,
    'modifyOrder': 9,
    'cancelOrder': 9,
    'getOrderBook': 1,
    'getLtpData': 10,
    'getPosition': 1,
    'getTradeBook': 1,
    'quote': 10,
    'optionGreek': 1,
    'getCandleData': 3
}


# =============================================================================
# ANGEL ONE CLIENT
# =============================================================================

class AngelOneClient:
    """
    Complete Angel One SmartAPI Client
    
    Usage:
        client = AngelOneClient(api_key, client_id, password, totp_secret)
        client.login()
        
        # Place order
        order = client.place_order(
            symbol="NIFTY2612725200CE",
            exchange="NFO",
            transaction_type="BUY",
            quantity=25,
            order_type="MARKET"
        )
        
        # Get LTP
        ltp = client.get_ltp("NFO", "NIFTY2612725200CE", "12345")
        
        # WebSocket streaming
        client.start_websocket(on_tick=my_callback)
        client.subscribe([("NFO", "12345", WS_MODE_LTP)])
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
        
        # API connections
        self.smart_api = None  # type: Optional[SmartConnect]
        self.auth_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        
        # Session info
        self.is_logged_in = False
        self.login_time: Optional[datetime] = None
        
        # Symbol cache
        self.symbol_cache: Dict[str, str] = {}
        
        # WebSocket
        self.ws = None  # WebSocketApp instance
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_connected = False
        self.subscriptions: Dict[str, int] = {}  # token -> mode
        self.on_tick_callback: Optional[Callable] = None
        self.on_order_update_callback: Optional[Callable] = None
        
        # Rate limiting
        self.last_call_time: Dict[str, float] = {}
        
        # Tick data
        self.latest_ticks: Dict[str, Dict] = {}
        
    # =========================================================================
    # AUTHENTICATION
    # =========================================================================
    
    def login(self) -> bool:
        """
        Login to Angel One SmartAPI
        
        Returns:
            True if login successful
            
        Raises:
            AngelOneLoginError on failure
        """
        if SmartConnect is None:
            raise AngelOneLoginError("smartapi-python not installed. Run: pip install smartapi-python")
            
        self._rate_limit('login')
        self.logger.info("🔐 Logging in to Angel One SmartAPI...")
        
        try:
            self.smart_api = SmartConnect(api_key=self.api_key)
            
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_secret).now()
            
            # Login
            data = self.smart_api.generateSession(
                self.client_id,
                self.password,
                totp
            )
            
            if data and data.get('status'):
                self.auth_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = self.smart_api.getfeedToken()
                self.is_logged_in = True
                self.login_time = datetime.now()
                
                self.logger.info("✅ Angel One login successful")
                return True
            else:
                error_msg = data.get('message', 'Unknown error') if data else 'No response'
                raise AngelOneLoginError(f"Login failed: {error_msg}")
                
        except AngelOneLoginError:
            raise
        except Exception as e:
            self.logger.error(f"❌ Login error: {e}")
            raise AngelOneLoginError(f"Login error: {str(e)}")
    
    def refresh_tokens(self) -> bool:
        """
        Refresh JWT tokens when expired
        
        Returns:
            True if refresh successful
        """
        self._rate_limit('generateTokens')
        
        if not self.refresh_token:
            self.logger.warning("No refresh token available, need full login")
            return False
            
        try:
            data = self.smart_api.generateToken(self.refresh_token)
            
            if data and data.get('status'):
                self.auth_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = data['data'].get('feedToken', self.feed_token)
                self.logger.info("🔄 Tokens refreshed successfully")
                return True
            else:
                self.logger.error(f"Token refresh failed: {data.get('message')}")
                return False
                
        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return False
    
    def logout(self) -> bool:
        """
        Logout from Angel One
        
        Returns:
            True if logout successful
        """
        self.logger.info("👋 Logging out from Angel One...")
        
        try:
            # Stop WebSocket
            self.stop_websocket()
            
            # Terminate session
            if self.smart_api and self.is_logged_in:
                self.smart_api.terminateSession(self.client_id)
                
            self.is_logged_in = False
            self.auth_token = None
            self.refresh_token = None
            self.feed_token = None
            
            self.logger.info("✅ Logged out successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Logout error: {e}")
            return False
    
    def get_profile(self) -> Dict:
        """
        Get user profile information
        
        Returns:
            User profile data
        """
        self._rate_limit('getProfile')
        self._ensure_logged_in()
        
        try:
            data = self.smart_api.getProfile(self.auth_token)
            if data and data.get('status'):
                return data['data']
            raise AngelOneApiError(f"Profile fetch failed: {data.get('message')}")
        except AngelOneApiError:
            raise
        except Exception as e:
            raise AngelOneApiError(f"Profile error: {str(e)}")
    
    def get_funds(self) -> Dict:
        """
        Get RMS (Risk Management System) funds and margins
        
        Returns:
            Funds data including available cash, margins, etc.
        """
        self._rate_limit('getRMS')
        self._ensure_logged_in()
        
        try:
            data = self.smart_api.rmsLimit()
            if data and data.get('status'):
                return data['data']
            raise AngelOneApiError(f"Funds fetch failed: {data.get('message')}")
        except AngelOneApiError:
            raise
        except Exception as e:
            raise AngelOneApiError(f"Funds error: {str(e)}")
    
    # =========================================================================
    # ORDERS
    # =========================================================================
    
    def place_order(
        self,
        symbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = ORDER_TYPE_MARKET,
        price: float = 0,
        trigger_price: float = 0,
        variety: str = VARIETY_NORMAL,
        product_type: str = PRODUCT_INTRADAY,
        duration: str = DURATION_DAY,
        disclosed_quantity: int = 0,
        order_tag: str = "",
        squareoff: float = 0,
        stoploss: float = 0,
        trailing_stoploss: float = 0
    ) -> Dict:
        """
        Place an order
        
        Args:
            symbol: Trading symbol (e.g., NIFTY2612725200CE)
            exchange: Exchange (NSE, BSE, NFO, MCX, CDS)
            transaction_type: BUY or SELL
            quantity: Order quantity
            order_type: MARKET, LIMIT, STOPLOSS_LIMIT, STOPLOSS_MARKET
            price: Limit price (for LIMIT orders)
            trigger_price: Trigger price (for SL orders)
            variety: NORMAL, STOPLOSS, ROBO
            product_type: INTRADAY, DELIVERY, MARGIN, CARRYFORWARD
            duration: DAY or IOC
            disclosed_quantity: Disclosed quantity
            order_tag: Custom tag (max 20 chars)
            squareoff: Squareoff value (ROBO orders)
            stoploss: Stoploss value (ROBO orders)
            trailing_stoploss: Trailing SL (ROBO orders)
            
        Returns:
            Order response with orderid
            
        Raises:
            AngelOneOrderError on failure
        """
        self._rate_limit('placeOrder')
        self._ensure_logged_in()
        
        # Get symbol token
        symbol_token = self.get_symbol_token(symbol, exchange)
        if not symbol_token:
            raise AngelOneOrderError(f"Symbol token not found for {symbol}")
        
        order_params = {
            "variety": variety,
            "tradingsymbol": symbol,
            "symboltoken": symbol_token,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": product_type,
            "duration": duration,
            "price": str(price),
            "squareoff": str(squareoff),
            "stoploss": str(stoploss),
            "quantity": str(quantity)
        }
        
        # Optional parameters
        if trigger_price > 0:
            order_params["triggerprice"] = str(trigger_price)
        if disclosed_quantity > 0:
            order_params["disclosedquantity"] = str(disclosed_quantity)
        if order_tag:
            order_params["ordertag"] = order_tag[:20]
        if trailing_stoploss > 0:
            order_params["trailingstoploss"] = str(trailing_stoploss)
            
        try:
            response = self.smart_api.placeOrder(order_params)
            
            if response and response.get('status'):
                order_id = response['data'].get('orderid')
                self.logger.info(f"✅ Order placed: {order_id} | {transaction_type} {quantity} {symbol}")
                return response['data']
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                raise AngelOneOrderError(f"Order failed: {error_msg}")
                
        except AngelOneOrderError:
            raise
        except Exception as e:
            raise AngelOneOrderError(f"Order error: {str(e)}")
    
    def modify_order(
        self,
        order_id: str,
        variety: str = VARIETY_NORMAL,
        order_type: Optional[str] = None,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
        trigger_price: Optional[float] = None,
        duration: Optional[str] = None
    ) -> Dict:
        """
        Modify an existing order
        
        Args:
            order_id: Order ID to modify
            variety: Order variety
            order_type: New order type
            price: New price
            quantity: New quantity
            trigger_price: New trigger price
            duration: New duration
            
        Returns:
            Modification response
        """
        self._rate_limit('modifyOrder')
        self._ensure_logged_in()
        
        modify_params = {
            "variety": variety,
            "orderid": order_id
        }
        
        if order_type:
            modify_params["ordertype"] = order_type
        if price is not None:
            modify_params["price"] = str(price)
        if quantity is not None:
            modify_params["quantity"] = str(quantity)
        if trigger_price is not None:
            modify_params["triggerprice"] = str(trigger_price)
        if duration:
            modify_params["duration"] = duration
            
        try:
            response = self.smart_api.modifyOrder(modify_params)
            
            if response and response.get('status'):
                self.logger.info(f"✅ Order modified: {order_id}")
                return response['data']
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                raise AngelOneOrderError(f"Modify failed: {error_msg}")
                
        except AngelOneOrderError:
            raise
        except Exception as e:
            raise AngelOneOrderError(f"Modify error: {str(e)}")
    
    def cancel_order(self, order_id: str, variety: str = VARIETY_NORMAL) -> Dict:
        """
        Cancel an order
        
        Args:
            order_id: Order ID to cancel
            variety: Order variety
            
        Returns:
            Cancellation response
        """
        self._rate_limit('cancelOrder')
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.cancelOrder(order_id, variety)
            
            if response and response.get('status'):
                self.logger.info(f"✅ Order cancelled: {order_id}")
                return response['data']
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                raise AngelOneOrderError(f"Cancel failed: {error_msg}")
                
        except AngelOneOrderError:
            raise
        except Exception as e:
            raise AngelOneOrderError(f"Cancel error: {str(e)}")
    
    def get_order_book(self) -> List[Dict]:
        """Get all orders for today"""
        self._rate_limit('getOrderBook')
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.orderBook()
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Order book error: {e}")
            return []
    
    def get_trade_book(self) -> List[Dict]:
        """Get all trades for today"""
        self._rate_limit('getTradeBook')
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.tradeBook()
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Trade book error: {e}")
            return []
    
    def get_order_status(self, unique_order_id: str) -> Optional[Dict]:
        """Get individual order status by unique order ID"""
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.individual_order_details(unique_order_id)
            if response and response.get('status'):
                return response.get('data')
            return None
        except Exception as e:
            self.logger.error(f"Order status error: {e}")
            return None
    
    # =========================================================================
    # MARKET DATA
    # =========================================================================
    
    def get_ltp(self, exchange: str, symbol: str, symbol_token: str) -> Optional[float]:
        """
        Get Last Traded Price
        
        Args:
            exchange: Exchange code
            symbol: Trading symbol
            symbol_token: Symbol token
            
        Returns:
            LTP as float or None
        """
        self._rate_limit('getLtpData')
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.ltpData(exchange, symbol, symbol_token)
            if response and response.get('status') and response.get('data'):
                return float(response['data'].get('ltp', 0))
            return None
        except Exception as e:
            self.logger.error(f"LTP error for {symbol}: {e}")
            return None
    
    def get_quote(
        self, 
        exchange_tokens: Dict[str, List[str]], 
        mode: str = "LTP"
    ) -> Dict:
        """
        Get market quote data
        
        Args:
            exchange_tokens: Dict of exchange -> list of tokens
                Example: {"NFO": ["12345", "12346"], "NSE": ["3045"]}
            mode: LTP, OHLC, or FULL
            
        Returns:
            Quote data
        """
        self._rate_limit('quote')
        self._ensure_logged_in()
        
        try:
            params = {
                "mode": mode,
                "exchangeTokens": exchange_tokens
            }
            
            response = self.smart_api.getMarketData(params)
            if response and response.get('status'):
                return response.get('data', {})
            return {}
        except Exception as e:
            self.logger.error(f"Quote error: {e}")
            return {}
    
    def get_market_tick(self, symbol: str, exchange: str = "NFO") -> Optional[Dict]:
        """
        Get real-time tick data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            
        Returns:
            Tick dict with ltp, bid, ask, volume
        """
        symbol_token = self.get_symbol_token(symbol, exchange)
        if not symbol_token:
            return None
            
        ltp = self.get_ltp(exchange, symbol, symbol_token)
        if ltp is None:
            return None
            
        # Estimate spread (0.1% of LTP)
        spread = ltp * 0.001
        
        tick = {
            'timestamp': int(time.time() * 1000),
            'ltp': ltp,
            'bid': round(ltp - spread/2, 2),
            'ask': round(ltp + spread/2, 2),
            'volume': 0,  # Not available from LTP endpoint
            'symbol': symbol,
            'exchange': exchange,
            'symbol_token': symbol_token
        }
        
        self.latest_ticks[symbol] = tick
        return tick
    
    # =========================================================================
    # PORTFOLIO
    # =========================================================================
    
    def get_holdings(self) -> List[Dict]:
        """Get long-term holdings"""
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.holding()
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Holdings error: {e}")
            return []
    
    def get_all_holdings(self) -> Dict:
        """Get all holdings with summary"""
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.allholding()
            if response and response.get('status'):
                return response.get('data', {})
            return {}
        except Exception as e:
            self.logger.error(f"All holdings error: {e}")
            return {}
    
    def get_positions(self) -> List[Dict]:
        """Get current day positions"""
        self._rate_limit('getPosition')
        self._ensure_logged_in()
        
        try:
            response = self.smart_api.position()
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Positions error: {e}")
            return []
    
    def convert_position(
        self,
        symbol: str,
        exchange: str,
        symbol_token: str,
        transaction_type: str,
        quantity: int,
        old_product: str,
        new_product: str
    ) -> bool:
        """
        Convert position from one product type to another
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            symbol_token: Symbol token
            transaction_type: BUY or SELL
            quantity: Position quantity
            old_product: Current product type
            new_product: Target product type
            
        Returns:
            True if conversion successful
        """
        self._ensure_logged_in()
        
        try:
            params = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "oldproducttype": old_product,
                "newproducttype": new_product,
                "tradingsymbol": symbol,
                "transactiontype": transaction_type,
                "quantity": quantity,
                "type": "DAY"
            }
            
            response = self.smart_api.convertPosition(params)
            if response and response.get('status'):
                self.logger.info(f"Position converted: {symbol}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Position convert error: {e}")
            return False
    
    # =========================================================================
    # OPTION GREEKS
    # =========================================================================
    
    def get_option_greeks(
        self, 
        underlying: str, 
        expiry_date: str
    ) -> List[Dict]:
        """
        Get option Greeks for all strikes of an underlying
        
        Args:
            underlying: Underlying name (e.g., "NIFTY", "BANKNIFTY")
            expiry_date: Expiry date in format "25JAN2024"
            
        Returns:
            List of Greeks data for each strike
        """
        self._rate_limit('optionGreek')
        self._ensure_logged_in()
        
        try:
            params = {
                "name": underlying,
                "expirydate": expiry_date
            }
            
            response = self.smart_api.optionGreek(params)
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Option Greeks error: {e}")
            return []
    
    # =========================================================================
    # HISTORICAL DATA
    # =========================================================================
    
    def get_candle_data(
        self,
        symbol_token: str,
        exchange: str,
        interval: str,
        from_date: str,
        to_date: str
    ) -> List[Dict]:
        """
        Get historical candle data
        
        Args:
            symbol_token: Symbol token
            exchange: Exchange code
            interval: ONE_MINUTE, FIVE_MINUTE, TEN_MINUTE, FIFTEEN_MINUTE,
                     THIRTY_MINUTE, ONE_HOUR, ONE_DAY
            from_date: Start date "YYYY-MM-DD HH:MM"
            to_date: End date "YYYY-MM-DD HH:MM"
            
        Returns:
            List of candle data
        """
        self._rate_limit('getCandleData')
        self._ensure_logged_in()
        
        try:
            params = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "interval": interval,
                "fromdate": from_date,
                "todate": to_date
            }
            
            response = self.smart_api.getCandleData(params)
            if response and response.get('status'):
                return response.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Candle data error: {e}")
            return []
    
    # =========================================================================
    # SYMBOL UTILITIES
    # =========================================================================
    
    def get_symbol_token(self, symbol: str, exchange: str = "NFO") -> Optional[str]:
        """
        Get symbol token (required for most API calls)
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            
        Returns:
            Symbol token string or None
        """
        cache_key = f"{exchange}:{symbol}"
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]
        
        try:
            result = self.smart_api.searchScrip(exchange=exchange, searchscrip=symbol)
            if result and result.get('status') and result.get('data'):
                for item in result['data']:
                    if item.get('tradingsymbol') == symbol or item.get('symbol') == symbol:
                        token = item.get('symboltoken') or item.get('token')
                        if token:
                            self.symbol_cache[cache_key] = token
                            return token
            return None
        except Exception as e:
            self.logger.error(f"Symbol token search error for {symbol}: {e}")
            return None
    
    def search_symbol(self, search_term: str, exchange: str = "NFO") -> List[Dict]:
        """
        Search for symbols
        
        Args:
            search_term: Search string
            exchange: Exchange code
            
        Returns:
            List of matching symbols
        """
        try:
            result = self.smart_api.searchScrip(exchange=exchange, searchscrip=search_term)
            if result and result.get('status'):
                return result.get('data', []) or []
            return []
        except Exception as e:
            self.logger.error(f"Symbol search error: {e}")
            return []
    
    # =========================================================================
    # WEBSOCKET STREAMING
    # =========================================================================
    
    def start_websocket(
        self,
        on_tick: Optional[Callable[[Dict], None]] = None,
        on_order_update: Optional[Callable[[Dict], None]] = None
    ):
        """
        Start WebSocket connection for real-time data
        
        Args:
            on_tick: Callback function for tick data
            on_order_update: Callback function for order updates
        """
        if websocket is None:
            self.logger.warning("websocket-client not installed. Run: pip install websocket-client")
            return
            
        if self.ws_connected:
            self.logger.warning("WebSocket already connected")
            return
            
        self.on_tick_callback = on_tick
        self.on_order_update_callback = on_order_update
        
        self.ws_thread = threading.Thread(target=self._ws_connect, daemon=True)
        self.ws_thread.start()
    
    def stop_websocket(self):
        """Stop WebSocket connection"""
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
        self.ws_connected = False
        self.logger.info("WebSocket stopped")
    
    def subscribe(self, tokens: List[tuple]):
        """
        Subscribe to market data
        
        Args:
            tokens: List of (exchange, token, mode) tuples
                Example: [("NFO", "12345", WS_MODE_LTP)]
        """
        if not self.ws_connected:
            self.logger.warning("WebSocket not connected")
            return
            
        # Group by exchange
        exchange_tokens = {}
        for exchange, token, mode in tokens:
            ws_exchange = self._get_ws_exchange_type(exchange)
            if ws_exchange not in exchange_tokens:
                exchange_tokens[ws_exchange] = []
            exchange_tokens[ws_exchange].append(token)
            self.subscriptions[token] = mode
        
        # Build subscribe message
        token_list = []
        for exchange_type, token_ids in exchange_tokens.items():
            token_list.append({
                "exchangeType": exchange_type,
                "tokens": token_ids
            })
        
        subscribe_msg = {
            "correlationID": f"sub_{int(time.time())}",
            "action": 1,  # Subscribe
            "params": {
                "mode": tokens[0][2] if tokens else WS_MODE_LTP,
                "tokenList": token_list
            }
        }
        
        self.ws.send(json.dumps(subscribe_msg))
        self.logger.info(f"Subscribed to {len(tokens)} tokens")
    
    def unsubscribe(self, tokens: List[tuple]):
        """
        Unsubscribe from market data
        
        Args:
            tokens: List of (exchange, token, mode) tuples
        """
        if not self.ws_connected:
            return
            
        # Build unsubscribe message
        exchange_tokens = {}
        for exchange, token, mode in tokens:
            ws_exchange = self._get_ws_exchange_type(exchange)
            if ws_exchange not in exchange_tokens:
                exchange_tokens[ws_exchange] = []
            exchange_tokens[ws_exchange].append(token)
            self.subscriptions.pop(token, None)
        
        token_list = []
        for exchange_type, token_ids in exchange_tokens.items():
            token_list.append({
                "exchangeType": exchange_type,
                "tokens": token_ids
            })
        
        unsubscribe_msg = {
            "correlationID": f"unsub_{int(time.time())}",
            "action": 0,  # Unsubscribe
            "params": {
                "mode": tokens[0][2] if tokens else WS_MODE_LTP,
                "tokenList": token_list
            }
        }
        
        self.ws.send(json.dumps(unsubscribe_msg))
    
    def _ws_connect(self):
        """Internal: Connect to WebSocket"""
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "x-api-key": self.api_key,
            "x-client-code": self.client_id,
            "x-feed-token": self.feed_token
        }
        
        self.ws = websocket.WebSocketApp(
            WEBSOCKET_URL,
            header=headers,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close
        )
        
        self.ws.run_forever()
    
    def _on_ws_open(self, ws):
        """WebSocket opened"""
        self.ws_connected = True
        self.logger.info("🔌 WebSocket connected")
        
        # Start heartbeat thread
        self._start_heartbeat()
    
    def _on_ws_message(self, ws, message):
        """WebSocket message received"""
        try:
            # Check if it's a text message (pong or error)
            if isinstance(message, str):
                if message == "pong":
                    return
                # Try to parse as JSON (error message)
                try:
                    data = json.loads(message)
                    if 'errorCode' in data:
                        self.logger.error(f"WebSocket error: {data.get('errorMessage')}")
                    return
                except:
                    pass
            
            # Binary message - parse tick data
            if isinstance(message, bytes):
                tick = self._parse_ws_binary(message)
                if tick and self.on_tick_callback:
                    self.on_tick_callback(tick)
                
        except Exception as e:
            self.logger.error(f"WebSocket message error: {e}")
    
    def _on_ws_error(self, ws, error):
        """WebSocket error"""
        self.logger.error(f"WebSocket error: {error}")
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """WebSocket closed"""
        self.ws_connected = False
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
    
    def _start_heartbeat(self):
        """Start WebSocket heartbeat"""
        def heartbeat():
            while self.ws_connected and self.ws:
                try:
                    self.ws.send("ping")
                    time.sleep(30)  # Send heartbeat every 30 seconds
                except:
                    break
        
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
    
    def _parse_ws_binary(self, data: bytes) -> Optional[Dict]:
        """
        Parse WebSocket binary tick data
        
        Binary format (Little Endian):
        - Byte 0: Subscription Mode (1=LTP, 2=Quote, 3=SnapQuote)
        - Byte 1: Exchange Type
        - Bytes 2-26: Token (25 bytes, null-terminated string)
        - Bytes 27-34: Sequence Number (int64)
        - Bytes 35-42: Exchange Timestamp (int64, epoch ms)
        - Bytes 43-50: LTP (int64, divide by 100)
        - ... more fields for Quote/SnapQuote modes
        """
        if len(data) < 51:
            return None
            
        try:
            mode = data[0]
            exchange_type = data[1]
            
            # Token is 25 bytes, null-terminated
            token_bytes = data[2:27]
            token = token_bytes.decode('utf-8').rstrip('\x00')
            
            # Parse numeric fields (Little Endian)
            sequence = struct.unpack('<q', data[27:35])[0]
            timestamp = struct.unpack('<q', data[35:43])[0]
            ltp_raw = struct.unpack('<q', data[43:51])[0]
            
            # Convert LTP (divide by 100 for most, 10000000 for currencies)
            ltp = ltp_raw / 100.0
            
            tick = {
                'mode': mode,
                'exchange_type': exchange_type,
                'token': token,
                'sequence': sequence,
                'timestamp': timestamp,
                'ltp': ltp
            }
            
            # Parse additional fields for Quote mode
            if mode >= WS_MODE_QUOTE and len(data) >= 123:
                tick['last_trade_qty'] = struct.unpack('<q', data[51:59])[0]
                tick['avg_price'] = struct.unpack('<q', data[59:67])[0] / 100.0
                tick['volume'] = struct.unpack('<q', data[67:75])[0]
                tick['total_buy_qty'] = struct.unpack('<d', data[75:83])[0]
                tick['total_sell_qty'] = struct.unpack('<d', data[83:91])[0]
                tick['open'] = struct.unpack('<q', data[91:99])[0] / 100.0
                tick['high'] = struct.unpack('<q', data[99:107])[0] / 100.0
                tick['low'] = struct.unpack('<q', data[107:115])[0] / 100.0
                tick['close'] = struct.unpack('<q', data[115:123])[0] / 100.0
            
            # Parse additional fields for SnapQuote mode
            if mode >= WS_MODE_SNAP_QUOTE and len(data) >= 379:
                tick['last_trade_time'] = struct.unpack('<q', data[123:131])[0]
                tick['open_interest'] = struct.unpack('<q', data[131:139])[0]
                tick['upper_circuit'] = struct.unpack('<q', data[347:355])[0] / 100.0
                tick['lower_circuit'] = struct.unpack('<q', data[355:363])[0] / 100.0
                tick['week_52_high'] = struct.unpack('<q', data[363:371])[0] / 100.0
                tick['week_52_low'] = struct.unpack('<q', data[371:379])[0] / 100.0
            
            return tick
            
        except Exception as e:
            self.logger.error(f"Binary parse error: {e}")
            return None
    
    def _get_ws_exchange_type(self, exchange: str) -> int:
        """Convert exchange string to WebSocket exchange type"""
        mapping = {
            'NSE': WS_EXCHANGE_NSE_CM,
            'NFO': WS_EXCHANGE_NSE_FO,
            'BSE': WS_EXCHANGE_BSE_CM,
            'BFO': WS_EXCHANGE_BSE_FO,
            'MCX': WS_EXCHANGE_MCX_FO,
            'CDS': WS_EXCHANGE_CDE_FO
        }
        return mapping.get(exchange, WS_EXCHANGE_NSE_CM)
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _ensure_logged_in(self):
        """Ensure client is logged in"""
        if not self.is_logged_in:
            raise AngelOneApiError("Not logged in. Call login() first.")
    
    def _rate_limit(self, endpoint: str):
        """Apply rate limiting"""
        if endpoint in RATE_LIMITS:
            last_time = self.last_call_time.get(endpoint, 0)
            min_interval = 1.0 / RATE_LIMITS[endpoint]
            elapsed = time.time() - last_time
            
            if elapsed < min_interval:
                sleep_time = min_interval - elapsed
                time.sleep(sleep_time)
        
        self.last_call_time[endpoint] = time.time()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_client_from_config(config_path: str) -> AngelOneClient:
    """
    Create client from config file
    
    Args:
        config_path: Path to credentials.json
        
    Returns:
        Initialized AngelOneClient
    """
    with open(config_path, 'r') as f:
        creds = json.load(f)
    
    return AngelOneClient(
        api_key=creds.get('api_key', ''),
        client_id=creds.get('client_id', ''),
        password=creds.get('password', ''),
        totp_secret=creds.get('totp_secret', '')
    )
