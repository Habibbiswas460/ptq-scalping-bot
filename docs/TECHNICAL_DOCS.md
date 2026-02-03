# PTQ Scalping Bot - Technical Documentation

## Complete Technical Reference for SMART SCALP v3.0

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Broker Integration](#broker-integration)
3. [Symbol Format & Expiry](#symbol-format--expiry)
4. [Strategy Engine](#strategy-engine)
5. [Risk Management](#risk-management)
6. [Configuration Reference](#configuration-reference)
7. [API Reference](#api-reference)
8. [Troubleshooting](#troubleshooting)

---

## System Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        PTQ Scalping Bot                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │   Broker    │───▶│   Entry     │───▶│   Trade     │        │
│  │  Interface  │    │   Engine    │    │   Manager   │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│         │                  │                  │                │
│         │                  │                  │                │
│         ▼                  ▼                  ▼                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ Angel One   │    │ SMART SCALP │    │    Risk     │        │
│  │   Client    │    │   v3.0      │    │   Manager   │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│         │                  │                  │                │
│         └──────────────────┴──────────────────┘                │
│                            │                                    │
│                     ┌─────────────┐                            │
│                     │   Logger    │                            │
│                     └─────────────┘                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Market Data** → Angel One SmartAPI → BrokerInterface
2. **Tick Data** → Entry Engine → SMART SCALP v3.0 Strategy
3. **Signal** → Trade Manager → Order Execution
4. **Position** → Exit Engine → Exit Monitoring
5. **Result** → Risk Manager → Mode Adjustment

---

## Broker Integration

### Angel One SmartAPI Client

**File**: `brokers/angel_one/client.py`

#### Authentication

```python
from brokers.angel_one import AngelOneClient

client = AngelOneClient(
    api_key="YOUR_API_KEY",
    client_id="YOUR_CLIENT_ID",
    password="YOUR_PASSWORD",
    totp_secret="YOUR_TOTP_SECRET"
)

# Login (auto-generates TOTP)
if client.login():
    print("Connected!")
```

#### Market Data Methods

| Method | Description | Parameters |
|--------|-------------|------------|
| `get_ltp(exchange, symbol, token)` | Get Last Traded Price | NSE/NFO, symbol, token |
| `get_ohlc(exchange, symbol, token)` | Get OHLC data | NSE/NFO, symbol, token |
| `get_full_quote(exchange, symbol, token)` | Complete quote with OI | NSE/NFO, symbol, token |
| `search_symbol(query, exchange)` | Search for instruments | search string, NFO |
| `get_option_greeks(exchange, symbol, expiry)` | Delta, Gamma, Theta, Vega | NFO, NIFTY, expiry |

#### Order Methods

| Method | Description | Parameters |
|--------|-------------|------------|
| `place_order(...)` | Place new order | variety, symbol, qty, etc. |
| `modify_order(...)` | Modify existing order | order_id, new params |
| `cancel_order(order_id, variety)` | Cancel order | order_id |
| `get_order_book()` | All orders for the day | None |
| `get_positions()` | Current positions | None |

#### Token Reference

| Instrument | Token | Exchange |
|------------|-------|----------|
| NIFTY Spot | 99926000 | NSE |
| NIFTY 50 Index | 26000 | NSE |
| India VIX | 26017 | NSE |
| NIFTY Options | Dynamic | NFO |

---

## Symbol Format & Expiry

### NIFTY Option Symbol Format

```
NIFTY{DDMMMYY}{STRIKE}{CE/PE}
```

**Components:**
- `NIFTY` - Underlying
- `DDMMMYY` - Expiry date (e.g., 03FEB26)
- `STRIKE` - Strike price (e.g., 25400)
- `CE/PE` - Call or Put

**Examples:**
```
NIFTY03FEB2625400CE  →  NIFTY 25400 CE, expiry 03 Feb 2026
NIFTY03FEB2625350PE  →  NIFTY 25350 PE, expiry 03 Feb 2026
NIFTY06FEB2625500CE  →  NIFTY 25500 CE, expiry 06 Feb 2026
```

### Expiry Detection Algorithm

**File**: `core/broker.py` → `_find_nearest_expiry()`

```python
def _find_nearest_expiry(self) -> str:
    """
    Find nearest available NIFTY expiry by searching Angel One.
    Handles holiday-shifted expiries (not always Thursday).
    """
    today = datetime.now()
    
    # Search day-by-day for next 14 days
    for days_ahead in range(1, 15):
        check_date = today + timedelta(days=days_ahead)
        expiry_str = check_date.strftime("%d%b%y").upper()
        
        # Search for contracts with this expiry
        test_symbol = f"NIFTY{expiry_str}25000CE"
        results = self.broker_client.search_symbol(test_symbol, "NFO")
        
        # If found contracts (>10), this is a valid expiry
        if results and len(results) > 10:
            return expiry_str
    
    return fallback_thursday_expiry()
```

### Holiday-Shifted Expiries

Indian market holidays can shift weekly expiry:

| Holiday | Normal Expiry | Shifted To |
|---------|---------------|------------|
| Republic Day (26 Jan) | Thu 30 Jan | Tue 28 Jan or previous |
| Independence Day (15 Aug) | Thu 15 Aug | Wed 14 Aug |
| Diwali (variable) | Thu | Previous trading day |

**Example (Jan 2026):**
- 26 Jan = Republic Day (Sunday, observed Monday)
- 30 Jan = Thursday (would be weekly expiry)
- Actual expiry = 03 Feb (Tuesday) - shifted due to budget session

---

## Strategy Engine

### SMART SCALP v3.0

**File**: `strategies/smart_scalp_v3.py`

#### Scoring System

The strategy uses a 10-point scoring system:

```python
# Bullish Score (for CE entry)
bullish_factors = [
    (ema5 > ema9 > ema21, 1.0),           # EMA alignment
    (price > ema50, 1.0),                  # Above major trend
    (40 < rsi < 70 and rsi_rising, 1.0),  # RSI bullish zone
    (macd_hist > macd_hist_prev, 1.0),    # MACD rising
    (price < bb_lower * 1.02, 1.0),       # Near BB lower
    (volume > vol_sma * 1.5, 1.0),        # Volume spike
    (atr > atr_avg * 1.2, 1.0),           # ATR expansion
    (keltner_squeeze_breakout, 1.5),      # KC breakout (weighted)
    (higher_highs and higher_lows, 1.0),  # Price structure
    (bullish_engulfing, 1.0),             # Candlestick pattern
]

bullish_score = sum(weight for cond, weight in bullish_factors if cond)
```

#### Entry Requirements

```python
# Minimum requirements for entry
MIN_SCORE = 5          # At least 5 out of 10 factors
MIN_CONFIDENCE = 60    # At least 60% confidence

# Confidence calculation
confidence = (score / 10) * confidence_multiplier
# Where confidence_multiplier = 12 (so score 5 = 60%)

# Entry decision
should_enter = (score >= MIN_SCORE) and (confidence >= MIN_CONFIDENCE)
```

#### Indicator Calculations

```python
# EMAs (Exponential Moving Averages)
ema_fast = EMA(prices, 5)
ema_signal = EMA(prices, 9)
ema_medium = EMA(prices, 21)
ema_slow = EMA(prices, 50)

# RSI (Relative Strength Index)
rsi = RSI(prices, 14)

# MACD (Moving Average Convergence Divergence)
macd_line = EMA(prices, 12) - EMA(prices, 26)
macd_signal = EMA(macd_line, 9)
macd_hist = macd_line - macd_signal

# Bollinger Bands
bb_mid = SMA(prices, 20)
bb_std = STD(prices, 20)
bb_upper = bb_mid + 2 * bb_std
bb_lower = bb_mid - 2 * bb_std

# ATR (Average True Range)
atr = ATR(highs, lows, closes, 14)

# Keltner Channel
kc_mid = EMA(prices, 20)
kc_upper = kc_mid + 1.5 * atr
kc_lower = kc_mid - 1.5 * atr
```

---

## Risk Management

### Multi-Layer Protection

```
┌─────────────────────────────────────────────┐
│              RISK MANAGEMENT                │
├─────────────────────────────────────────────┤
│                                             │
│  Layer 1: Kill Switch                       │
│  ├─ Daily Loss > ₹1,200 → STOP ALL         │
│  └─ Emergency condition → STOP ALL          │
│                                             │
│  Layer 2: Trade Limits                      │
│  ├─ Max 3 trades/hour                       │
│  ├─ Max 6 trades/day                        │
│  └─ Cooldown: 30s normal, 60s after SL     │
│                                             │
│  Layer 3: Position Risk                     │
│  ├─ Fixed 8-point Stop Loss                │
│  ├─ Fixed 16-point Take Profit             │
│  └─ 1:2 Risk-Reward ratio                  │
│                                             │
│  Layer 4: Capital Protection               │
│  ├─ Max 2% risk per trade (₹600)           │
│  ├─ Max 3% daily loss (₹900)               │
│  └─ Max 10% drawdown (₹3,000)              │
│                                             │
│  Layer 5: VIX Filter                        │
│  ├─ VIX < 10 → No trades (low vol)         │
│  ├─ VIX > 25 → No trades (too volatile)    │
│  └─ VIX 10-25 → Normal trading             │
│                                             │
└─────────────────────────────────────────────┘
```

### Kill Switch

**File**: `core/kill_switch.py`

```python
def emergency_check(daily_pnl: float, state: TradingState) -> bool:
    """
    Check if kill switch should be activated.
    Returns True if trading should stop immediately.
    """
    # Check daily loss limit
    if daily_pnl <= -KILL_SWITCH_LOSS:  # -₹1,200
        logger.critical("🚨 KILL SWITCH ACTIVATED - Daily loss limit hit!")
        state.emergency_stop = True
        return True
    
    # Check consecutive losses
    if state.consecutive_losses >= 3:
        logger.warning("⚠️ 3 consecutive losses - Entering cautious mode")
        # Don't stop, but reduce position size
    
    return False
```

### Adaptive Mode

**File**: `core/mode_switch.py`

| Mode | Trigger | Behavior |
|------|---------|----------|
| NORMAL | Default | Standard parameters |
| CAUTIOUS | 2 consecutive losses | Tighter entry filters |
| AGGRESSIVE | 3 consecutive wins | Wider targets |
| RECOVERY | 50% of daily loss used | Conservative entries |

---

## Configuration Reference

### bot_config.json Structure

```json
{
  "broker": {
    "name": "angel_one",
    "paper_trading": true,
    "use_live_data": true,
    "credentials_file": "config/credentials.json"
  },
  
  "capital": {
    "total_capital": 30000,
    "risk_per_trade_pct": 2.0,
    "risk_per_trade_amount": 600,
    "max_daily_loss_amount": 900,
    "max_drawdown_pct": 10.0
  },
  
  "trading": {
    "symbol": "NIFTY",
    "exchange": "NFO",
    "option_type": "CE",
    "strike_selection": "ATM",
    "lot_size": 65,
    "quantity": 4
  },
  
  "risk_management": {
    "max_trades_per_hour": 3,
    "max_trades_per_day": 6,
    "sl_points": 8,
    "tp_points": 16,
    "tp_multiplier": 2.0
  },
  
  "strategy": {
    "name": "smart_scalp_institutional",
    "version": "3.0",
    "scoring_system": {
      "min_score_to_trade": 5,
      "min_confidence_pct": 60
    }
  },
  
  "kill_switch": {
    "enabled": true,
    "daily_loss_amount": 1200
  }
}
```

### credentials.json Structure

```json
{
  "angel_one": {
    "api_key": "YOUR_API_KEY",
    "client_id": "YOUR_CLIENT_ID",
    "password": "YOUR_PIN",
    "totp_token": "YOUR_TOTP_SECRET"
  }
}
```

**Getting Credentials:**
1. Login to [Angel One SmartAPI](https://smartapi.angelone.in/)
2. Create new app to get API Key
3. Client ID = Your Angel One client code
4. Password = Your 4-digit PIN
5. TOTP Secret = Base32 secret from authenticator setup

---

## API Reference

### BrokerInterface

**File**: `core/broker.py`

```python
class BrokerInterface:
    """Main interface for all broker operations"""
    
    def connect(self) -> bool:
        """
        Connect to Angel One and initialize trading session.
        Returns True if connection successful.
        """
    
    def get_tick(self) -> Dict:
        """
        Get current market tick data.
        Returns: {
            'ltp': float,           # Last traded price
            'spot_price': float,    # NIFTY spot
            'volume': int,          # Volume
            'timestamp': datetime,  # Time
            'bid': float,           # Best bid
            'ask': float            # Best ask
        }
        """
    
    def place_trade(self, direction: str, quantity: int, 
                   sl_points: float, tp_points: float) -> bool:
        """
        Place a trade with stop loss and take profit.
        direction: 'LONG' or 'SHORT'
        """
    
    def exit_trade(self, reason: str) -> float:
        """
        Exit current trade.
        Returns P&L from the trade.
        """
```

### EntryEngine

**File**: `core/entry_engine.py`

```python
def entry_signal(tick: Dict, recent_ticks: List[Dict], 
                day_type: str) -> Tuple[bool, str]:
    """
    Generate entry signal using SMART SCALP v3.0.
    
    Args:
        tick: Current tick data
        recent_ticks: Last 120 ticks (2 minutes)
        day_type: 'NORMAL', 'EXPIRY', 'VOLATILE'
    
    Returns:
        (should_enter: bool, message: str)
        
    Example:
        should_enter, msg = entry_signal(tick, ticks, 'NORMAL')
        if should_enter:
            print(f"ENTRY SIGNAL: {msg}")
    """
```

### RiskManager

**File**: `core/risk_manager.py`

```python
class RiskManager:
    """Manages all risk controls"""
    
    def can_trade(self) -> Tuple[bool, str]:
        """Check if new trade is allowed"""
    
    def check_vix_filter(self) -> Tuple[bool, str]:
        """Check India VIX levels"""
    
    def calculate_position_size(self, option_type: str) -> int:
        """Calculate quantity based on risk"""
    
    def update_after_trade(self, pnl: float):
        """Update risk metrics after trade closes"""
```

---

## Troubleshooting

### Common Issues

#### 1. "Angel One login failed"
```
Causes:
- Invalid credentials
- TOTP secret expired
- API key invalid

Fix:
1. Verify credentials.json
2. Regenerate TOTP secret from Angel One app
3. Check API key status in SmartAPI dashboard
```

#### 2. "No contracts found for expiry"
```
Causes:
- Market closed
- Holiday shifted expiry
- Wrong symbol format

Fix:
1. Run during market hours
2. Check if expiry detection found correct date
3. Verify broker connection is active
```

#### 3. "VIX check failed"
```
Causes:
- VIX outside 10-25 range
- VIX data not available

Fix:
1. Wait for VIX to normalize
2. Check Angel One connection
3. Disable VIX filter in config (not recommended)
```

#### 4. "Kill switch activated"
```
Causes:
- Daily loss exceeded ₹1,200

Fix:
1. Wait for next trading day
2. Review losing trades
3. Adjust strategy parameters
```

### Debug Commands

```bash
# Test broker connection
python -c "
from brokers.angel_one import AngelOneClient
import json
with open('config/credentials.json') as f:
    creds = json.load(f)['angel_one']
client = AngelOneClient(**creds)
print('Login:', client.login())
print('NIFTY:', client.get_ltp('NSE', 'NIFTY', '99926000'))
"

# Check expiry detection
python -c "
from core.broker import broker
broker.connect()
print('Expiry:', broker._current_expiry)
print('Symbol:', broker.current_symbol)
"

# Test strategy scoring
python -c "
from strategies.smart_scalp_v3 import SmartScalpV3
strategy = SmartScalpV3()
# Create dummy ticks
ticks = [{'ltp': 25300 + i, 'volume': 10000} for i in range(60)]
indicators = strategy.calculate_indicators(ticks)
print('Indicators:', indicators.keys())
"
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | Jan 2026 | Pure Angel One integration, removed Yahoo Finance |
| 1.5 | Dec 2025 | Added SMART SCALP v3.0 strategy |
| 1.0 | Nov 2025 | Initial release with PTQ strategy |

---

## Contact

For technical issues, check:
1. Logs in `logs/YYYY-MM-DD/`
2. Angel One API status
3. Market hours (9:15 AM - 3:30 PM IST)
