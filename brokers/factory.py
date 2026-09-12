"""Constructs the configured broker client, so core/trading/broker.py doesn't hardcode
brokers.angel_one.client.AngelOneClient — the seam a second broker plugs into later.

Only Angel One exists today (BROKER defaults to "angel_one" and is the only value handled) —
this file's job is that seam, not a multi-broker registry that has nothing to register yet.
"""

from typing import Optional

from brokers.base import BrokerClient
from brokers.angel_one.client import AngelOneClient
from utils.logger import BotLogger


def create_broker_client(
    broker: str,
    api_key: str,
    client_id: str,
    password: str,
    totp_secret: str,
    logger: Optional[BotLogger] = None,
) -> BrokerClient:
    """Build the BrokerClient for `broker`. Raises ValueError for anything unrecognized —
    there is no silent fallback to Angel One, a typo'd config value should fail loudly."""
    if broker == "angel_one":
        return AngelOneClient(
            api_key=api_key,
            client_id=client_id,
            password=password,
            totp_secret=totp_secret,
            logger=logger,
        )
    raise ValueError(f"Unknown broker: {broker!r} (only 'angel_one' is implemented today)")
