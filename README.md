# PTQ Scalping Bot v3.4

## SMART SCALP v3.4 - Institutional Grade NIFTY Options Scalping

A sophisticated Python-based automated trading bot for NIFTY options scalping using Angel One SmartAPI. Features multi-factor scoring system with institutional-grade confluence detection.

---

## 📊 Performance Summary

| Metric | Value |
|--------|-------|
| Win Rate | 58.5% (CE: 62%, PE: 54%) |
| Profit Factor | 2.06x |
| Risk-Reward | 1:2 (6pt SL, 12pt TP) |
| API Optimization | 95.5% reduction (5 phases) |

---

## 🏗️ Architecture

```
PTQ-scalping bot/
├── app.py                          # Entry point
├── run.sh                          # Startup script
├── requirements.txt                # Dependencies
├── .env                            # All config & credentials (gitignored)
│
├── config/                         # Configuration
│   ├── constants.py                # Loads .env → Python variables
│   └── validator.py                # Startup validation
│
├── core/                           # Core trading logic
│   ├── __init__.py
│   ├── main.py                     # Main trading loop
│   ├── backtest.py                 # Backtesting engine
│   │
│   ├── engines/                    # Signal engines
│   │   ├── entry_engine.py         # Entry signal generation
│   │   ├── exit_engine.py          # Exit signal handling
│   │   └── state_machine.py        # Trading state management
│   │
│   ├── risk/                       # Risk management
│   │   ├── risk_manager.py         # VIX filter, drawdown, sizing
│   │   ├── kill_switch.py          # Emergency stop system
│   │   ├── validators.py           # PTQ validation rules
│   │   ├── greeks_calc.py          # Option Greeks calculation
│   │   └── session_trend.py        # Session trend tracking
│   │
│   ├── services/                   # Services
│   │   ├── database.py             # SQLite trade logging
│   │   ├── telegram_bot.py         # Telegram notifications
│   │   ├── mode_switch.py          # Adaptive mode switching
│   │   └── session_manager.py      # Session tracking
│   │
│   └── trading/                    # Trade execution
│       ├── broker.py               # Angel One interface + WebSocket
│       └── trade_manager.py        # Trade execution wrapper
│
├── strategies/                     # Trading strategies
│   └── smart_scalp_v3.py          # SMART SCALP v3.4 strategy
│
├── brokers/                        # Broker integrations
│   └── angel_one/
│       ├── client.py               # SmartAPI client
│       ├── exceptions.py           # Custom exceptions
│       └── DOCUMENTATION.md        # API documentation
│
├── utils/                          # Utilities
│   ├── greeks.py                   # BSM Greeks calculator (cached)
│   ├── logger.py                   # Logging system
│   ├── helpers.py                  # Helper functions
│   ├── analytics.py                # Performance analytics
│   └── monitoring.py               # Health monitoring
│
├── tests/                          # Test suite (75 tests)
│   ├── test_greeks.py
│   ├── test_greeks_caching.py
│   ├── test_kill_switch.py
│   ├── test_batch_market_data.py
│   ├── test_phases_3_4_5.py
│   ├── test_analytics.py
│   └── test_websocket.py
│
├── logs/                           # Daily trade logs
│   └── YYYY-MM-DD/
│       ├── trades.csv
│       ├── trades.json
│       ├── summary.json
│       └── events.json
│
└── data/                           # Persistent data
    └── trades.db                   # SQLite database
```

---

## 🔧 Tech Stack

- **Language**: Python 3.12+
- **Broker**: Angel One SmartAPI
- **Data Source**: Angel One (Real-time LTP, OHLC, Greeks)
- **Options**: NIFTY Weekly Options (NFO)
- **Strategy**: SMART SCALP v3.4 Multi-Factor Scoring
- **Config**: `.env` file (all settings)

---

## 🎯 SMART SCALP v3.4 Strategy

### Multi-Factor Scoring System

The strategy evaluates **10 bullish factors** and **10 bearish factors**:

#### Bullish Factors (CE Entry)
1. EMA 5 > EMA 9 > EMA 21 (Trend alignment)
2. Price above EMA 50 (Major trend bullish)
3. RSI 40-70 with bullish momentum
4. MACD histogram rising
5. Price near Bollinger lower band (oversold)
6. Volume spike > 1.5x average
7. ATR expansion (volatility breakout)
8. Keltner Channel squeeze breakout
9. Higher highs and higher lows
10. Previous candle bullish engulfing

#### Bearish Factors (PE Entry)
1. EMA 5 < EMA 9 < EMA 21 (Trend alignment)
2. Price below EMA 50 (Major trend bearish)
3. RSI 30-60 with bearish momentum
4. MACD histogram falling
5. Price near Bollinger upper band (overbought)
6. Volume spike on down moves
7. ATR expansion on breakdown
8. Keltner Channel breakdown
9. Lower highs and lower lows
10. Previous candle bearish engulfing

### Entry Requirements

| Requirement | Value |
|-------------|-------|
| Minimum Score | 5+ points (out of 10) |
| Minimum Confidence | 70%+ (85% after 3 SL) |
| Time Window | 9:20 AM - 3:10 PM |
| VIX Filter | 10-25 (avoid extreme volatility) |
| Premium Range | ₹90 - ₹350 |

### Position Sizing

| Option Type | Quantity | Lots |
|-------------|----------|------|
| CE Entry | 65 | 1 lot × 65 |
| PE Entry | 65 | 1 lot × 65 |

---

## 💰 Capital Configuration (₹30K)

### Risk Parameters

| Parameter | Value |
|-----------|-------|
| Total Capital | ₹30,000 |
| Risk Per Trade | 1.5% |
| Max Daily Loss | ₹1,500 (5%) |
| Kill Switch | ₹450 |
| Kill Switch Consec Loss | 3 trades |

### Fixed Stop Loss & Target

| Parameter | Value |
|-----------|-------|
| SL Points | 6 pts |
| TP Points | 12 pts |
| Risk-Reward | 1:2 |
| Breakeven Trigger | +5 pts → lock +2 pts |
| Trailing Distance | 3 pts below max profit |
| TSL Steps | 10 step levels |

---

## ⚙️ Installation

### 1. Clone Repository
```bash
git clone <repo-url>
cd "PTQ-scalping bot"
```

### 2. Create Virtual Environment
```bash
python3.12 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Settings

All configuration is in `.env` file:
```bash
# Copy example and edit
cp .env.example .env
nano .env
```

Key settings in `.env`:
```bash
# Broker Credentials
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_API_KEY=your_api_key
ANGEL_TOTP_SECRET=your_totp_secret

# Trading Mode
PAPER_TRADING=true
USE_LIVE_DATA=false

# Capital & Risk
TOTAL_CAPITAL=30000
SL_POINTS=6
TP_POINTS=12
CE_QUANTITY=65
PE_QUANTITY=65

# Strategy
MIN_SCORE=5
MIN_CONFIDENCE=70

# Telegram (Optional)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 5. Run the Bot
```bash
./run.sh
# Or directly:
python app.py
```

---

## 📝 Configuration

### Paper Trading Mode (Default)

Set in `.env`:
```bash
PAPER_TRADING=true
USE_LIVE_DATA=false
```

### Live Trading Mode

```bash
PAPER_TRADING=false
USE_LIVE_DATA=true
```

⚠️ **WARNING**: Live trading uses real money. Test thoroughly in paper mode first.

---

## 🔄 Trading Loop

```
1. Market Open (9:15 AM)
   │
2. Connect to Angel One
   │
3. Get NIFTY Spot Price
   │
4. Find Nearest Weekly Expiry
   │
5. Build Option Symbol
   │
6. Main Loop (9:20 AM - 3:10 PM):
   │
   ├─→ Get Real-time Tick
   │    │
   │    ├─→ Calculate Indicators
   │    │
   │    ├─→ Score Entry Factors (10 bullish + 10 bearish)
   │    │
   │    ├─→ Check Risk Limits + Kill Switch
   │    │
   │    └─→ Generate Signal (if score ≥ 5 & confidence ≥ 70%)
   │
   ├─→ Execute Trade (if signal)
   │    │
   │    ├─→ Place Order (with slippage validation)
   │    │
   │    ├─→ Set SL at -6 pts
   │    │
   │    ├─→ Monitor Exit (breakeven at +5, trail at +3)
   │    │
   │    └─→ Step Trailing SL (10 levels)
   │
   └─→ Repeat until Market Close
   
7. Generate Daily Summary
```

---

## 📊 Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| EMA 5 | 5 | Fast trend |
| EMA 9 | 9 | Signal line |
| EMA 21 | 21 | Medium trend |
| EMA 50 | 50 | Major trend |
| RSI | 14 | Momentum |
| MACD | 12, 26, 9 | Trend strength |
| Bollinger Bands | 20, 2σ | Volatility |
| Keltner Channel | 20, 1.5 ATR | Squeeze detection |
| ATR | 14 | Stop loss sizing |
| Volume SMA | 20 | Volume analysis |

---

## 🛡️ Risk Management

### Kill Switch
- Activates at ₹450 kill-switch loss, ₹1,500 max daily loss, OR 3 consecutive losses
- Stops all trading for the day
- Logs emergency state + Telegram alert

### Trade Limits
- Max 10 trades per hour
- Max 15 trades per day
- 180s cooldown after trade
- 300s cooldown after stop loss
- 1200s cooldown after 3 consecutive losses

### Adaptive Modes
The bot switches modes based on performance:
- **AGGRESSIVE**: Standard parameters (default)
- **SAFE**: After consecutive losses (tighter filters, reduced size)
- **LOCKDOWN**: After hitting daily loss limit (no new trades)

### Live Slippage Guard
- Validates entry/exit slippage against MAX_SLIPPAGE_PCT
- Sends Telegram alert on excessive slippage
- Intraday spike detector (1.5% in 10s → 60s pause)

---

## 📋 Logging

### Trade Logs
Location: `logs/YYYY-MM-DD/trades.csv`

### Daily Summary
Location: `logs/YYYY-MM-DD/summary.json`

### Events
Location: `logs/YYYY-MM-DD/events.json`

---

## 🚀 Quick Start

```bash
source venv/bin/activate
python app.py
```

---

## 🧪 Testing

```bash
# Run all 75 tests
python -m pytest tests/ -v

# Run specific test
python tests/test_greeks.py
python tests/test_kill_switch.py
```

---

## ⚡ API Optimizations (5 Phases Complete)

| Phase | Optimization | Reduction |
|-------|-------------|-----------|
| 1 | Greeks Caching | 90% |
| 2 | Batch Market Data | 99% |
| 3 | Symbol Cache (24h TTL) | 98% |
| 4 | Position Cache (5s TTL) | 65% |
| 5 | WebSocket Redundancy (3x) | Reliability |

**Total: 95.5% API call reduction** (4,500 → 200 calls/day)

---

## ⚠️ Disclaimer

This bot is for educational purposes only. Trading in derivatives involves significant risk of loss. Past performance does not guarantee future results. Use at your own risk.
