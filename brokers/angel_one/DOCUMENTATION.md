# Angel One SmartAPI Integration

## Complete Reference for PTQ Scalping Bot

---

## Overview

The PTQ Scalping Bot uses Angel One SmartAPI as its exclusive data and order execution provider. All market data, option chains, Greeks, and order execution flow through this integration.

---

## Authentication

### Required Credentials

| Field | Description | Source |
|-------|-------------|--------|
| `api_key` | SmartAPI application key | SmartAPI Dashboard |
| `client_id` | Your Angel One client code | Account details |
| `password` | 4-digit MPIN | Your trading PIN |
| `totp_secret` | Base32 TOTP secret | Authenticator setup |

### TOTP Generation

The client automatically generates TOTP codes:

```python
import pyotp

totp = pyotp.TOTP(totp_secret)
current_otp = totp.now()  # 6-digit code
```

### Session Management

- Session valid for 24 hours
- Auto-refresh using `refresh_token`
- Logout clears all tokens

---

## Market Data

### Instrument Tokens

| Instrument | Token | Exchange | Description |
|------------|-------|----------|-------------|
| NIFTY 50 | 99926000 | NSE | NIFTY spot index |
| India VIX | 26017 | NSE | Volatility index |
| Bank NIFTY | 99926009 | NSE | Bank NIFTY spot |
| NIFTY Options | Dynamic | NFO | Use `search_symbol` |

### Getting LTP

```python
# NIFTY Spot
nifty_spot = client.get_ltp("NSE", "NIFTY", "99926000")
# Returns: 25342.75

# NIFTY Option
option_ltp = client.get_ltp("NFO", "NIFTY03FEB2625400CE", token)
# Returns: 125.50

# India VIX
vix = client.get_ltp("NSE", "INDIAVIX", "26017")
# Returns: 14.32
```

### Symbol Search

```python
# Search for NIFTY options
results = client.search_symbol("NIFTY03FEB26", "NFO")
# Returns list of matching contracts

# Get specific option
results = client.search_symbol("NIFTY03FEB2625400CE", "NFO")
# Returns token and details
```

---

## NIFTY Option Symbol Format

### Format
```
NIFTY{DDMMMYY}{STRIKE}{CE/PE}
```

### Components

| Part | Format | Example |
|------|--------|---------|
| Underlying | NIFTY | NIFTY |
| Expiry | DDMMMYY | 03FEB26 |
| Strike | 5-digit | 25400 |
| Type | CE/PE | CE |

### Examples

```
NIFTY03FEB2625400CE  →  Call at 25400, expiry 03 Feb 2026
NIFTY03FEB2625350PE  →  Put at 25350, expiry 03 Feb 2026
NIFTY10FEB2625500CE  →  Call at 25500, expiry 10 Feb 2026
```

---

## Weekly Expiry Detection

### Algorithm

NIFTY weekly options typically expire on Thursday, but holidays can shift this:

```python
def find_nearest_expiry():
    """Search for valid expiry day-by-day"""
    for days in range(1, 15):
        check_date = today + timedelta(days=days)
        expiry = check_date.strftime("%d%b%y").upper()
        
        # Test if contracts exist
        symbol = f"NIFTY{expiry}25000CE"
        results = search_symbol(symbol, "NFO")
        
        if len(results) > 10:  # Valid expiry found
            return expiry
    
    return fallback_thursday()
```

### Holiday Handling

| Scenario | Normal | Actual |
|----------|--------|--------|
| Republic Day week | Thu 30 Jan | Tue 03 Feb |
| Independence Day | Thu 15 Aug | Wed 14 Aug |
| Diwali week | Thu | Previous day |

---

## Order Execution

### Order Types

| Type | Constant | Use Case |
|------|----------|----------|
| MARKET | `ORDER_TYPE_MARKET` | Immediate execution |
| LIMIT | `ORDER_TYPE_LIMIT` | Specific price |
| SL-LIMIT | `ORDER_TYPE_SL_LIMIT` | Stop loss with limit |
| SL-MARKET | `ORDER_TYPE_SL_MARKET` | Stop loss market |

### Place Order

```python
order_id = client.place_order(
    variety="NORMAL",
    symbol="NIFTY03FEB2625400CE",
    token="12345",
    transaction_type="BUY",
    exchange="NFO",
    order_type="MARKET",
    product_type="INTRADAY",
    quantity=65,
    price=0,
    trigger_price=0
)
```

### Modify Order

```python
client.modify_order(
    order_id="123456789",
    variety="NORMAL",
    order_type="LIMIT",
    price=128.50,
    quantity=65,
    trigger_price=0
)
```

### Cancel Order

```python
client.cancel_order(
    order_id="123456789",
    variety="NORMAL"
)
```

---

## Option Greeks

### Get Greeks

```python
greeks = client.get_option_greeks(
    exchange="NFO",
    symbol="NIFTY",
    expiry="03FEB26"
)

# Returns per strike:
# {
#   "25400CE": {"delta": 0.52, "gamma": 0.0012, "theta": -15.2, "vega": 18.5},
#   "25400PE": {"delta": -0.48, "gamma": 0.0012, "theta": -14.8, "vega": 18.5},
#   ...
# }
```

### Greeks Used by Bot

| Greek | Purpose | Threshold |
|-------|---------|-----------|
| Delta | Directional bias | 0.3-0.7 preferred |
| Gamma | Risk near expiry | Avoid high gamma on expiry |
| Theta | Time decay | Factor into holding time |
| Vega | Volatility sensitivity | Higher Vega in low VIX |

---

## WebSocket Streaming

### Modes

| Mode | Data | Use |
|------|------|-----|
| LTP | Price only | Fast updates |
| QUOTE | Price + volume + OI | Standard |
| SNAP_QUOTE | Full depth | Detailed |

### Subscribe

```python
def on_tick(tick):
    print(f"LTP: {tick['ltp']}")

client.subscribe_ws(
    tokens=[("NFO", "12345")],
    mode="LTP",
    callback=on_tick
)
```

### Tick Format

```python
{
    "token": "12345",
    "ltp": 125.50,
    "volume": 145000,
    "open": 122.00,
    "high": 128.00,
    "low": 120.50,
    "close": 124.00,  # Previous close
    "oi": 2500000,
    "timestamp": 1706435400
}
```

---

## Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| LTP/Quote | 1 req/sec | Per token |
| Order APIs | 10 req/sec | Account |
| Search | 5 req/sec | Account |
| WebSocket | 100 tokens | Per connection |

### Handling Rate Limits

```python
import time

def safe_api_call(func, *args, retries=3):
    for attempt in range(retries):
        try:
            return func(*args)
        except RateLimitError:
            time.sleep(1)
    return None
```

---

## Error Handling

### Common Errors

| Code | Message | Action |
|------|---------|--------|
| AB1000 | Invalid request | Check parameters |
| AB1001 | Invalid credentials | Re-authenticate |
| AB1002 | Session expired | Refresh token |
| AB1003 | Insufficient margin | Reduce quantity |
| AB1004 | Order rejected | Check limits |
| AB1010 | Market closed | Wait for market |

### Exception Classes

```python
from brokers.angel_one.exceptions import (
    AngelOneError,        # Base exception
    AngelOneLoginError,   # Auth failures
    AngelOneApiError,     # API errors
    AngelOneOrderError,   # Order failures
    AngelOneRateLimitError # Rate limit hit
)

try:
    client.place_order(...)
except AngelOneOrderError as e:
    logger.error(f"Order failed: {e}")
except AngelOneApiError as e:
    logger.error(f"API error: {e}")
```

---

## Best Practices

### 1. Connection Management
```python
# Always check connection before trading
if not client.is_logged_in():
    client.login()
```

### 2. Token Caching
```python
# Cache tokens to avoid repeated searches
token_cache = {}

def get_token(symbol):
    if symbol not in token_cache:
        results = client.search_symbol(symbol, "NFO")
        if results:
            token_cache[symbol] = results[0]['token']
    return token_cache.get(symbol)
```

### 3. Graceful Shutdown
```python
import atexit

atexit.register(client.logout)
```

### 4. Logging
```python
# Log all API calls for debugging
logger.debug(f"API Call: {endpoint} | Params: {params}")
logger.debug(f"Response: {response}")
```

---

## Testing

### Test Connection
```bash
python -c "
from brokers.angel_one import AngelOneClient
import json

with open('config/credentials.json') as f:
    creds = json.load(f)['angel_one']

client = AngelOneClient(
    api_key=creds['api_key'],
    client_id=creds['client_id'],
    password=creds['password'],
    totp_secret=creds['totp_token']
)

print('Login:', client.login())
print('NIFTY Spot:', client.get_ltp('NSE', 'NIFTY', '99926000'))
print('Profile:', client.get_profile())
"
```

### Test Symbol Search
```bash
python -c "
from brokers.angel_one import AngelOneClient
# ... login code ...

results = client.search_symbol('NIFTY03FEB2625400CE', 'NFO')
print('Found:', len(results), 'contracts')
for r in results[:5]:
    print(f\"  {r['tradingsymbol']} - Token: {r['symboltoken']}\")
"
```

---

## Resources

- [Angel One SmartAPI Docs](https://smartapi.angelone.in/docs/)
- [SmartAPI Python SDK](https://github.com/angelbroking-github/smartapi-python)
- [API Status Page](https://smartapi.angelone.in/status)
