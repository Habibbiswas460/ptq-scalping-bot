"""
Angel One SmartAPI Client
Documentation: https://smartapi.angelbroking.com/docs/
"""

from SmartApi import SmartConnect
import pyotp
import time
import threading
from typing import Dict, Optional, Callable
from datetime import datetime


class AngelOneClient:
    """
    Angel One broker client for trading operations
    
    Features:
    - Login & authentication
    - Order placement (Market, Limit, SL)
    - Market data fetching
    - WebSocket for real-time updates
    """
    
    def __init__(self, api_key: str, client_id: str, password: str, totp_token: str):
        """
        Initialize Angel One client
        
        Args:
            api_key: SmartAPI key from Angel One
            client_id: Your client ID
            password: Account password
            totp_token: TOTP token for 2FA
        """
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_token = totp_token
        self.smart_api = None
        self.auth_token = None
        self.feed_token = None
        
        # Tick data
        self.latest_tick = None
        self.tick_callback = None
        self.last_tick_time = None
        
        # Symbol cache
        self.symbol_cache = {}
        
    def login(self) -> bool:
        """
        Login to Angel One SmartAPI
        
        Returns:
            bool: True if login successful
        """
        try:
            self.smart_api = SmartConnect(api_key=self.api_key)
            
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_token).now()
            
            # Login
            data = self.smart_api.generateSession(
                self.client_id,
                self.password,
                totp
            )
            
            if data['status']:
                self.auth_token = data['data']['jwtToken']
                self.feed_token = self.smart_api.getfeedToken()
                print("✓ Angel One login successful")
                return True
            else:
                print(f"✗ Login failed: {data['message']}")
                return False
                
        except Exception as e:
            print(f"✗ Login error: {str(e)}")
            return False
    
    def get_profile(self) -> Optional[Dict]:
        """Get user profile"""
        try:
            return self.smart_api.getProfile(self.auth_token)
        except Exception as e:
            print(f"Error getting profile: {str(e)}")
            return None
    
    def place_order(
        self,
        symbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        variety: str = "NORMAL"
    ) -> Optional[Dict]:
        """
        Place an order
        
        Args:
            symbol: Trading symbol (e.g., 'SBIN-EQ')
            exchange: Exchange (NSE, BSE, NFO, etc.)
            transaction_type: BUY or SELL
            quantity: Order quantity
            order_type: MARKET, LIMIT, SL, SL-M
            price: Price (for LIMIT orders)
            variety: NORMAL, STOPLOSS, AMO
            
        Returns:
            Order response dict
        """
        try:
            order_params = {
                "variety": variety,
                "tradingsymbol": symbol,
                "symboltoken": "",  # Get from symbol search
                "transactiontype": transaction_type,
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": price,
                "squareoff": "0",
                "stoploss": "0",
                "quantity": quantity
            }
            
            return self.smart_api.placeOrder(order_params)
            
        except Exception as e:
            print(f"Order placement error: {str(e)}")
            return None
    
    def get_ltp(self, exchange: str, symbol_token: str) -> Optional[float]:
        """
        Get Last Traded Price
        
        Args:
            exchange: Exchange name
            symbol_token: Symbol token
            
        Returns:
            LTP as float
        """
        try:
            data = self.smart_api.ltpData(exchange, symbol_token, symbol_token)
            if data and 'data' in data:
                return float(data['data']['ltp'])
            return None
        except Exception as e:
            print(f"LTP fetch error: {str(e)}")
            return None
    
    def search_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Search for symbol information
        
        Args:
            symbol: Symbol to search
            
        Returns:
            Symbol information
        """
        try:
            return self.smart_api.searchScrip(exchange="NFO", searchscrip=symbol)
        except Exception as e:
            print(f"Symbol search error: {str(e)}")
            return None
    
    def get_symbol_token(self, symbol: str, exchange: str = "NFO") -> Optional[str]:
        """
        Get symbol token (required for Angel One API)
        Caches results for performance
        
        Args:
            symbol: Trading symbol (e.g., 'NIFTY23JAN50CE')
            exchange: Exchange code
        
        Returns:
            Symbol token as string
        """
        cache_key = f"{exchange}:{symbol}"
        
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]
        
        try:
            result = self.search_symbol(symbol)
            if result and result.get('status') and result.get('data'):
                # Find matching symbol
                for item in result['data']:
                    if item.get('symbol') == symbol and item.get('exch_seg') == exchange:
                        token = item.get('token')
                        self.symbol_cache[cache_key] = token
                        return token
            return None
        except Exception as e:
            print(f"Symbol token fetch error: {str(e)}")
            return None
    
    def get_market_tick(self, symbol: str, exchange: str = "NFO") -> Optional[Dict]:
        """
        Get real-time market tick for a symbol
        Uses LTP data API (faster than WebSocket for single symbol)
        
        Args:
            symbol: Trading symbol
            exchange: Exchange
        
        Returns:
            Tick dict with timestamp, bid, ask, ltp, volume
        """
        try:
            symbol_token = self.get_symbol_token(symbol, exchange)
            if not symbol_token:
                return None
            
            # Get LTP data
            data = self.smart_api.ltpData(exchange, symbol, symbol_token)
            
            if data and data.get('status') and data.get('data'):
                tick_data = data['data']
                ltp = float(tick_data.get('ltp', 0))
                
                # Estimate bid/ask from LTP (spread ~0.05-0.1%)
                # In production, use order book depth
                spread_estimate = ltp * 0.001  # 0.1% spread
                bid = ltp - spread_estimate / 2
                ask = ltp + spread_estimate / 2
                
                tick = {
                    'timestamp': int(time.time() * 1000),  # Current time in ms
                    'bid': bid,
                    'ask': ask,
                    'ltp': ltp,
                    'volume': int(tick_data.get('volume', 0)),
                    'symbol': symbol,
                    'exchange': exchange
                }
                
                self.latest_tick = tick
                self.last_tick_time = datetime.now()
                
                return tick
            
            return None
            
        except Exception as e:
            print(f"Tick fetch error: {str(e)}")
            return None
    
    def get_order_book(self) -> Optional[Dict]:
        """Get current order book"""
        try:
            return self.smart_api.orderBook()
        except Exception as e:
            print(f"Order book fetch error: {str(e)}")
            return None
    
    def get_positions(self) -> Optional[Dict]:
        """Get current positions"""
        try:
            return self.smart_api.position()
        except Exception as e:
            print(f"Positions fetch error: {str(e)}")
            return None
    
    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> Optional[Dict]:
        """Cancel an order"""
        try:
            return self.smart_api.cancelOrder(order_id, variety)
        except Exception as e:
            print(f"Cancel order error: {str(e)}")
            return None
    
    def modify_order(self, order_id: str, order_params: Dict) -> Optional[Dict]:
        """Modify an existing order"""
        try:
            return self.smart_api.modifyOrder(order_params)
        except Exception as e:
            print(f"Modify order error: {str(e)}")
            return None
    
    def logout(self):
        """Logout from Angel One"""
        try:
            if self.smart_api:
                self.smart_api.terminateSession(self.client_id)
                print("✓ Logged out successfully")
        except Exception as e:
            print(f"Logout error: {str(e)}")
