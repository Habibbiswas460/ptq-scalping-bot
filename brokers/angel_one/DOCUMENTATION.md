# Angel One SmartAPI Documentation

## Overview
Angel One SmartAPI provides REST API and WebSocket for trading operations.

## Official Resources
- **API Documentation**: https://smartapi.angelbroking.com/docs/
- **Python SDK**: https://github.com/angelbroking-github/smartapi-python
- **Developer Portal**: https://smartapi.angelbroking.com/

## Getting Started

### 1. Register for API
1. Visit Angel One website
2. Enable API access from your account
3. Get your API credentials:
   - API Key
   - Client ID
   - Password
   - TOTP Secret (for 2FA)

### 2. Installation
```bash
pip install smartapi-python
```

### 3. Authentication
```python
from smartapi import SmartConnect
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
feed_token = smart_api.getfeedToken()
```

## Key Features

### Order Placement
- **Market Orders**: Execute at current market price
- **Limit Orders**: Execute at specified price
- **Stop Loss Orders**: Risk management
- **Product Types**: INTRADAY, DELIVERY, CARRYFORWARD

### Market Data
- **LTP (Last Traded Price)**: Real-time price
- **Market Depth**: Order book data
- **Historical Data**: Candle data
- **Quote**: Complete quote information

### WebSocket
- Real-time tick data
- Order updates
- Position updates

## Order Types

### Market Order
```python
order = {
    "variety": "NORMAL",
    "tradingsymbol": "SBIN-EQ",
    "exchange": "NSE",
    "transactiontype": "BUY",
    "ordertype": "MARKET",
    "quantity": 1,
    "producttype": "INTRADAY"
}
```

### Limit Order
```python
order = {
    "variety": "NORMAL",
    "tradingsymbol": "SBIN-EQ",
    "exchange": "NSE",
    "transactiontype": "BUY",
    "ordertype": "LIMIT",
    "price": 550.00,
    "quantity": 1,
    "producttype": "INTRADAY"
}
```

## Exchange Codes
- **NSE**: National Stock Exchange (Equity)
- **BSE**: Bombay Stock Exchange
- **NFO**: NSE Futures & Options
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
