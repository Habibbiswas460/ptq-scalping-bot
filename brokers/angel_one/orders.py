"""Orders and portfolio: place/modify/cancel, order/trade book, positions, holdings.

Mixed into AngelOneClient — methods here use self.smart_api, self._rate_limit(),
self._ensure_logged_in(), self.get_symbol_token() (market_data_rest.py), self.logger.
"""

from typing import Dict, List, Optional

from .exceptions import AngelOneApiError, AngelOneOrderError

ORDER_TYPE_MARKET = "MARKET"
VARIETY_NORMAL = "NORMAL"
PRODUCT_INTRADAY = "INTRADAY"
DURATION_DAY = "DAY"


class OrdersMixin:

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
        trailing_stoploss: float = 0,
        symbol_token: Optional[str] = None
    ) -> Dict:
        """
        Place an order

        Args:
            symbol: Trading symbol (e.g., NIFTY03FEB2625400CE)
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
            symbol_token: Optional pre-resolved token to avoid another lookup

        Returns:
            Order response with orderid

        Raises:
            AngelOneOrderError on failure
        """
        self._rate_limit('placeOrder')
        self._ensure_logged_in()

        # Get symbol token
        symbol_token = symbol_token or self.get_symbol_token(symbol, exchange)
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
