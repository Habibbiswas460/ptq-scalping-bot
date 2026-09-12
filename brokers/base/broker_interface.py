"""The contract every broker adapter implements.

This exists so a second broker can be added later (brokers/<name>/) without touching
core/trading/broker.py or core/market_data/ — both should be written against this shape,
not against brokers.angel_one.client.AngelOneClient directly. AngelOneClient implements it
today; nothing else does yet, and nothing here should be extended speculatively ahead of
that second broker actually existing.
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional


class BrokerClient(ABC):
    """Auth, orders, REST market data and WebSocket streaming — the surface PTQ's trading
    and market-data layers actually call today, lifted from brokers/angel_one/client.py."""

    # -- Authentication ---------------------------------------------------
    @abstractmethod
    def login(self) -> bool: ...

    @abstractmethod
    def logout(self) -> bool: ...

    @abstractmethod
    def get_profile(self) -> Dict: ...

    # -- Orders -------------------------------------------------------------
    @abstractmethod
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                     quantity: int, **kwargs) -> Dict: ...

    @abstractmethod
    def modify_order(self, order_id: str, **kwargs) -> Dict: ...

    @abstractmethod
    def cancel_order(self, order_id: str, variety: str) -> Dict: ...

    @abstractmethod
    def get_positions(self) -> List[Dict]: ...

    # -- REST market data -----------------------------------------------------
    @abstractmethod
    def get_ltp(self, exchange: str, symbol: str, symbol_token: str,
                max_retries: int = 3) -> Optional[float]: ...

    @abstractmethod
    def get_candle_data(self, symbol_token: str, exchange: str, interval: str,
                         from_date: str, to_date: str) -> List[Dict]: ...

    @abstractmethod
    def get_symbol_token(self, symbol: str, exchange: str = "NFO") -> Optional[str]: ...

    # -- WebSocket streaming -----------------------------------------------------
    @abstractmethod
    def start_websocket(self, on_tick: Optional[Callable[[Dict], None]] = None,
                         on_order_update: Optional[Callable[[Dict], None]] = None,
                         num_connections: int = 1) -> None: ...

    @abstractmethod
    def stop_websocket(self) -> None: ...

    @abstractmethod
    def subscribe(self, tokens: List[tuple]) -> bool: ...

    @abstractmethod
    def unsubscribe(self, tokens: List[tuple]) -> bool: ...
