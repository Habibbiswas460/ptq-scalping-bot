"""Broker-agnostic contract and canonical tick shape.

Every concrete broker adapter (brokers/angel_one/ today, any future broker later) implements
BrokerClient and normalizes its wire ticks into the CANONICAL_TICK_FIELDS shape, so
core/trading/broker.py and core/market_data/ can depend on this package instead of on any
one broker's client directly.
"""

from .broker_interface import BrokerClient
from .tick_schema import CANONICAL_TICK_FIELDS

__all__ = ["BrokerClient", "CANONICAL_TICK_FIELDS"]
