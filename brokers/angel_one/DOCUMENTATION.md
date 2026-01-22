# Angel One SmartAPI - Complete Documentation

## 📚 Overview

Angel One SmartAPI provides REST API and WebSocket for trading operations with comprehensive market data access.

**Base URL**: `https://apiconnect.angelone.in`  
**WebSocket URL**: `wss://smartapisocket.angelone.in/smart-stream`

## 🔗 Official Resources

- **API Documentation**: https://smartapi.angelbroking.com/docs/
- **Python SDK**: https://github.com/angelbroking-github/smartapi-python
- **Developer Portal**: https://smartapi.angelbroking.com/

---

## 🚀 Getting Started

### 1. Register for API

1. Visit Angel One website
2. Enable API access from your account
3. Get your API credentials:
   - API Key
   - Client ID
   - Password/PIN
   - TOTP Secret (for 2FA)

### 2. Installation

```bash
pip install smartapi-python
pip install pyotp
pip install websocket-client
```

### 3. Authentication

```python
from SmartApi import SmartConnect
import pyotp

api_key = "your_api_key"
client_id = "your_client_id"
password = "your_password"
totp_token = "your_totp_secret"

# Initialize
smart_api = SmartConnect(api_key=api_key)

# Generate TOTP
totp = pyotp.TOTP(totp_token).now()

# Login
data = smart_api.generateSession(client_id, password, totp)
auth_token = data['data']['jwtToken']
refresh_token = data['data']['refreshToken']
feed_token = smart_api.getfeedToken()
```

---

## 📡 API Endpoints

### Authentication

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/rest/auth/angelbroking/user/v1/loginByPassword` | POST | 1/sec | Login |
| `/rest/auth/angelbroking/jwt/v1/generateTokens` | POST | 1/sec | Refresh tokens |
| `/rest/auth/angelbroking/user/v1/logout` | POST | 1/sec | Logout |
| `/rest/secure/angelbroking/user/v1/getProfile` | GET | 3/sec | Get profile |
| `/rest/secure/angelbroking/user/v1/getRMS` | GET | 2/sec | Get RMS/Funds |

### Orders

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/rest/secure/angelbroking/order/v1/placeOrder` | POST | 9/sec | Place order |
| `/rest/secure/angelbroking/order/v1/modifyOrder` | POST | 9/sec | Modify order |
| `/rest/secure/angelbroking/order/v1/cancelOrder` | POST | 9/sec | Cancel order |
| `/rest/secure/angelbroking/order/v1/getOrderBook` | GET | 1/sec | Order book |
| `/rest/secure/angelbroking/order/v1/getTradeBook` | GET | 1/sec | Trade book |

### Market Data

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/rest/secure/angelbroking/order/v1/getLtpData` | POST | 10/sec | Get LTP |
| `/rest/secure/angelbroking/market/v1/quote` | POST | 10/sec | Get quote |
| `/rest/secure/angelbroking/historical/v1/getCandleData` | POST | 3/sec | Historical data |
| `/rest/secure/angelbroking/marketData/v1/optionGreek` | POST | 1/sec | Option Greeks |

### Portfolio

| Endpoint | Method | Rate Limit | Description |
|----------|--------|------------|-------------|
| `/rest/secure/angelbroking/portfolio/v1/getHolding` | GET | - | Get holdings |
| `/rest/secure/angelbroking/portfolio/v1/getAllHolding` | GET | - | All holdings |
| `/rest/secure/angelbroking/order/v1/getPosition` | GET | 1/sec | Get positions |
| `/rest/secure/angelbroking/order/v1/convertPosition` | POST | - | Convert position |

---

## 📊 Market Data Modes

### Quote API Modes

```python
# LTP Only
params = {
    "mode": "LTP",
    "exchangeTokens": {"NFO": ["12345"]}
}

# OHLC Data
params = {
    "mode": "OHLC",
    "exchangeTokens": {"NFO": ["12345"]}
}

# Full Quote
params = {
    "mode": "FULL",
    "exchangeTokens": {"NFO": ["12345"]}
}
```

**Limits**: Max 50 tokens per request, 1 request/second

### Response Fields

| Mode | Fields |
|------|--------|
| **LTP** | ltp, exchange, tradingSymbol, symbolToken |
| **OHLC** | ltp + open, high, low, close |
| **FULL** | OHLC + volume, avgPrice, bidQty, bidPrice, askQty, askPrice, totBuyQuan, totSellQuan |

---

## 🔌 WebSocket 2.0

### Connection

```python
import websocket

WEBSOCKET_URL = "wss://smartapisocket.angelone.in/smart-stream"

headers = {
    "Authorization": f"Bearer {auth_token}",
    "x-api-key": api_key,
    "x-client-code": client_id,
    "x-feed-token": feed_token
}

ws = websocket.WebSocketApp(
    WEBSOCKET_URL,
    header=headers,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)
```

### Subscribe/Unsubscribe

```python
# Subscribe
subscribe_msg = {
    "correlationID": "sub_123",
    "action": 1,  # 1=Subscribe
    "params": {
        "mode": 1,  # 1=LTP, 2=Quote, 3=SnapQuote
        "tokenList": [
            {"exchangeType": 2, "tokens": ["12345", "12346"]}  # 2=NFO
        ]
    }
}
ws.send(json.dumps(subscribe_msg))

# Unsubscribe
unsubscribe_msg = {
    "correlationID": "unsub_123",
    "action": 0,  # 0=Unsubscribe
    "params": {
        "mode": 1,
        "tokenList": [
            {"exchangeType": 2, "tokens": ["12345"]}
        ]
    }
}
ws.send(json.dumps(unsubscribe_msg))
```

### Exchange Type Codes

| Code | Exchange |
|------|----------|
| 1 | NSE_CM (NSE Cash) |
| 2 | NSE_FO (NFO) |
| 3 | BSE_CM (BSE Cash) |
| 4 | BSE_FO (BFO) |
| 5 | MCX_FO (MCX) |
| 7 | NCX_FO (NCX) |
| 13 | CDE_FO (CDS) |

### WebSocket Modes

| Mode | Name | Bytes | Data |
|------|------|-------|------|
| 1 | LTP | 51 | Last price only |
| 2 | Quote | 123 | OHLC + Volume |
| 3 | SnapQuote | 379 | Full market depth |

### Binary Data Format (Little Endian)

```
LTP Mode (51 bytes):
├── Byte 0: Subscription Mode (1)
├── Byte 1: Exchange Type
├── Bytes 2-26: Token (25 bytes, null-terminated)
├── Bytes 27-34: Sequence Number (int64)
├── Bytes 35-42: Exchange Timestamp (int64, epoch ms)
└── Bytes 43-50: LTP (int64, divide by 100)

Quote Mode (123 bytes):
├── ... LTP fields ...
├── Bytes 51-58: Last Trade Quantity (int64)
├── Bytes 59-66: Average Price (int64, /100)
├── Bytes 67-74: Volume (int64)
├── Bytes 75-82: Total Buy Quantity (double)
├── Bytes 83-90: Total Sell Quantity (double)
├── Bytes 91-98: Open (int64, /100)
├── Bytes 99-106: High (int64, /100)
├── Bytes 107-114: Low (int64, /100)
└── Bytes 115-122: Close (int64, /100)
```

### Heartbeat

Send `"ping"` every 30 seconds, receive `"pong"` response.

### Limits

- Max 3 concurrent WebSocket connections per client code
- Max 1000 token subscriptions per session

---

## 📝 Order Types

### Product Types

| Type | Description |
|------|-------------|
| `INTRADAY` | Square off same day |
| `DELIVERY` | Equity delivery |
| `CARRYFORWARD` | F&O carryforward |
| `MARGIN` | Margin trading |

### Order Types

| Type | Description |
|------|-------------|
| `MARKET` | Execute at current market price |
| `LIMIT` | Execute at specified price |
| `STOPLOSS_LIMIT` | SL with limit price |
| `STOPLOSS_MARKET` | SL market |

### Variety Types

| Variety | Description |
|---------|-------------|
| `NORMAL` | Regular order |
| `STOPLOSS` | SL order |
| `ROBO` | Bracket order (target + SL) |

### Duration

| Duration | Description |
|----------|-------------|
| `DAY` | Valid for the day |
| `IOC` | Immediate or Cancel |

---

## 📊 Order Examples

### Market Order

```python
order = {
    "variety": "NORMAL",
    "tradingsymbol": "NIFTY2612725200CE",
    "symboltoken": "12345",
    "transactiontype": "BUY",
    "exchange": "NFO",
    "ordertype": "MARKET",
    "producttype": "INTRADAY",
    "duration": "DAY",
    "price": "0",
    "squareoff": "0",
    "stoploss": "0",
    "quantity": "25"
}
response = smart_api.placeOrder(order)
```

### Limit Order

```python
order = {
    "variety": "NORMAL",
    "tradingsymbol": "NIFTY2612725200CE",
    "symboltoken": "12345",
    "transactiontype": "BUY",
    "exchange": "NFO",
    "ordertype": "LIMIT",
    "producttype": "INTRADAY",
    "duration": "DAY",
    "price": "125.50",
    "quantity": "25"
}
```

### Stop Loss Order

```python
order = {
    "variety": "STOPLOSS",
    "tradingsymbol": "NIFTY2612725200CE",
    "symboltoken": "12345",
    "transactiontype": "SELL",
    "exchange": "NFO",
    "ordertype": "STOPLOSS_MARKET",
    "producttype": "INTRADAY",
    "duration": "DAY",
    "triggerprice": "100.00",
    "quantity": "25"
}
```

### Bracket Order (ROBO)

```python
order = {
    "variety": "ROBO",
    "tradingsymbol": "NIFTY2612725200CE",
    "symboltoken": "12345",
    "transactiontype": "BUY",
    "exchange": "NFO",
    "ordertype": "LIMIT",
    "producttype": "INTRADAY",
    "duration": "DAY",
    "price": "125.00",
    "squareoff": "5",      # Target 5 points
    "stoploss": "3",       # SL 3 points
    "trailingstoploss": "1",  # Trail by 1 point
    "quantity": "25"
}
```

---

## 📈 Option Greeks

### Request

```python
params = {
    "name": "NIFTY",
    "expirydate": "27JAN2026"
}
response = smart_api.optionGreek(params)
```

### Response

```json
{
  "status": true,
  "data": [
    {
      "tradingsymbol": "NIFTY27JAN2625200CE",
      "symboltoken": "12345",
      "delta": 0.52,
      "gamma": 0.0023,
      "theta": -15.5,
      "vega": 12.3,
      "impliedvolatility": 14.5
    }
  ]
}
```

---

## 🛡️ Error Handling

### Error Codes

| Code | Message |
|------|---------|
| `AB1000` | Invalid API key |
| `AB1001` | Session expired |
| `AB1002` | Invalid client code |
| `AB1003` | Insufficient funds |
| `AB1004` | Invalid order |
| `AB1005` | Rate limit exceeded |

### Recommended Handling

```python
try:
    response = smart_api.placeOrder(order)
    if response.get('status'):
        order_id = response['data']['orderid']
        print(f"Order placed: {order_id}")
    else:
        print(f"Error: {response.get('message')}")
except Exception as e:
    print(f"Exception: {e}")
```

---

## 📋 Exchange Codes

| Exchange | Code | Description |
|----------|------|-------------|
| NSE | NSE | NSE Cash Market |
| BSE | BSE | BSE Cash Market |
| NFO | NFO | NSE F&O |
| BFO | BFO | BSE F&O |
| MCX | MCX | Multi Commodity Exchange |
| CDS | CDS | Currency Derivatives |

---

## 🔧 Rate Limits Summary

| Endpoint | Per Second | Per Minute |
|----------|------------|------------|
| login | 1 | - |
| placeOrder | 9 | 20 |
| modifyOrder | 9 | 20 |
| cancelOrder | 9 | 20 |
| getOrderBook | 1 | - |
| getLtpData | 10 | - |
| quote | 10 | - |
| getCandleData | 3 | 180 |
| optionGreek | 1 | - |
| getProfile | 3 | - |
| getRMS | 2 | - |

---

## 📚 Symbol Format

### Options

Format: `{UNDERLYING}{EXPIRY}{STRIKE}{OPTIONTYPE}`

| Part | Example | Description |
|------|---------|-------------|
| UNDERLYING | NIFTY | Index/Stock name |
| EXPIRY | 26127 | YY + MonthCode + DD |
| STRIKE | 25200 | Strike price |
| OPTIONTYPE | CE/PE | Call/Put |

**Example**: `NIFTY2612725200CE` = NIFTY Jan 27, 2026 25200 CE

### Month Codes

| Month | Code |
|-------|------|
| JAN | 1 |
| FEB | 2 |
| MAR | 3 |
| APR | 4 |
| MAY | 5 |
| JUN | 6 |
| JUL | 7 |
| AUG | 8 |
| SEP | 9 |
| OCT | O |
| NOV | N |
| DEC | D |

---

## 🔗 Quick Reference

### Client Initialization

```python
from brokers.angel_one import AngelOneClient

client = AngelOneClient(
    api_key="your_api_key",
    client_id="your_client_id",
    password="your_password",
    totp_secret="your_totp_secret"
)

# Login
client.login()

# Get LTP
ltp = client.get_ltp("NFO", "NIFTY2612725200CE", "12345")

# Place order
order = client.place_order(
    symbol="NIFTY2612725200CE",
    exchange="NFO",
    transaction_type="BUY",
    quantity=25,
    order_type="MARKET"
)

# WebSocket streaming
def on_tick(tick):
    print(f"LTP: {tick['ltp']}")

client.start_websocket(on_tick=on_tick)
client.subscribe([("NFO", "12345", 1)])  # Mode 1 = LTP
```

---

**Last Updated**: January 2026

- **MCX**: Multi Commodity Exchange
- **CDS**: Currency Derivatives

## Rate Limits
- REST API: Check official docs for current limits
- WebSocket: Real-time streaming

## Error Handling
Always wrap API calls in try-except blocks:
```python
try:
    response = smart_api.placeOrder(order_params)
    if response['status']:
        print(f"Order placed: {response['data']['orderid']}")
except Exception as e:
    print(f"Error: {str(e)}")
```

## Best Practices for Scalping

1. **Use WebSocket** for real-time data
2. **Place Market Orders** for quick execution
3. **Implement Stop Loss** for risk management
4. **Monitor Order Status** continuously
5. **Handle API Errors** gracefully
6. **Respect Rate Limits** to avoid blocks

## Important Notes

⚠️ **Risk Warning**: Scalping involves high risk. Test thoroughly in paper trading first.

⚠️ **API Limits**: Do not exceed rate limits to avoid account suspension.

⚠️ **Market Hours**: NSE operates 9:15 AM - 3:30 PM IST (Mon-Fri)

⚠️ **Credentials**: Keep your API credentials secure. Never commit them to version control.
