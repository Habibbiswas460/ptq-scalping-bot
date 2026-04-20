# PTQ Scalping Bot - Documentation Index

## 📚 Documentation Overview

Complete documentation for the PTQ Scalping Bot v3.4 with SMART SCALP v3.4 strategy.

---

## 🚀 Latest Updates

### v3.4 - Comprehensive Hardening (March 2026)
- ATR-adaptive early loss cut (3/4/5 pts based on volatility)
- Live slippage guard on entry/exit orders
- Intraday spike detector (1.5% in 10s → 60s pause)
- Thread-safe kill switch and mode switch
- Broker exit retry (3 attempts + MARKET fallback)
- Conservative entry gate (score threshold 5+, confidence 70%+)
- All config values from `.env` (no hardcoded stale values)
- 75/75 tests passing

### v3.3 - Performance Fixes
- Fixed kill switch persistence bug
- Fixed stale data in exit engine
- Improved trailing stop loss logic
- Config validator for startup checks

### API Optimization Phases (All Complete)
- **Phase 1**: Greeks Caching - 90% reduction
- **Phase 2**: Batch Market Data - 99% reduction
- **Phase 3**: Symbol Cache (24h TTL) - 98% reduction
- **Phase 4**: Position Cache (5s TTL) - 65% reduction
- **Phase 5**: WebSocket Redundancy (3 connections) - Reliability

---

## System Overview

PTQ Scalping Bot is an institutional-grade NIFTY options scalping system featuring:

- **SMART SCALP v3.4**: Multi-factor scoring with 10 bullish + 10 bearish factors
- **Angel One Integration**: Exclusive broker for all market data and orders
- **Adaptive Modes**: AGGRESSIVE → SAFE → LOCKDOWN
- **Risk Management**: Fixed SL/TP (6/12), kill switch, daily limits
- **Paper Trading**: Full simulation with real NIFTY spot prices
- **API Optimization**: 95.5% reduction in API calls (5 phases complete)

---

## Key Specifications

| Specification | Value |
|---------------|-------|
| Version | 3.4 |
| Broker | Angel One SmartAPI |
| Symbol | NIFTY Weekly Options (NFO) |
| Risk-Reward | 1:2 (6pt SL, 12pt TP) |
| Min Score | 5+ (out of 10) |
| Min Confidence | 70% (85% after 3 SL) |
| CE Quantity | 65 (1 lot × 65) |
| PE Quantity | 65 (1 lot × 65) |
| Capital | ₹30,000 |
| Kill Switch | ₹450, ₹1,500 max daily loss, OR 3 consec losses |
| Trading Hours | 9:20 AM - 3:10 PM |

---

## Project Structure

```
PTQ-scalping bot/
├── app.py                  # Entry point
├── config/                 # Configuration
│   ├── constants.py        # All settings from .env
│   └── validator.py        # Startup validation
├── core/                   # Core trading logic
│   ├── main.py             # Main loop
│   ├── backtest.py         # Backtesting engine
│   ├── engines/            # Signal engines
│   │   ├── entry_engine.py # Entry signals
│   │   ├── exit_engine.py  # Exit handling
│   │   └── state_machine.py# State management
│   ├── risk/               # Risk management
│   │   ├── risk_manager.py # VIX, drawdown, sizing
│   │   ├── kill_switch.py  # Emergency stop
│   │   ├── validators.py   # Data validation
│   │   ├── greeks_calc.py  # Greeks calculation
│   │   └── session_trend.py# Trend tracking
│   ├── services/           # Services
│   │   ├── database.py     # SQLite logging
│   │   ├── telegram_bot.py # Telegram notifications
│   │   ├── mode_switch.py  # Adaptive modes
│   │   └── session_manager.py # Session tracking
│   └── trading/            # Trade execution
│       ├── broker.py       # Broker interface + WebSocket
│       └── trade_manager.py# Trade wrapper
├── strategies/             # Trading strategies
│   └── smart_scalp_v3.py   # SMART SCALP v3.4
├── brokers/angel_one/      # Angel One client
│   ├── client.py           # SmartAPI wrapper
│   └── exceptions.py       # Error handling
├── utils/                  # Utilities
│   ├── greeks.py           # BSM calculator (cached)
│   ├── analytics.py        # Performance analytics
│   ├── helpers.py          # Helper functions
│   ├── logger.py           # Logging system
│   └── monitoring.py       # Health monitoring
├── tests/                  # 75 tests
└── logs/                   # Daily logs
```

---

## Configuration

All settings are in the `.env` file. No JSON config files needed.

```bash
# Copy example and edit
cp .env.example .env
```

`config/constants.py` loads all `.env` values into Python constants.
`config/validator.py` validates settings at startup.

### Key Config Sections in .env
- **Broker credentials**: ANGEL_CLIENT_ID, PASSWORD, API_KEY, TOTP_SECRET
- **Trading mode**: PAPER_TRADING, USE_LIVE_DATA
- **Capital & risk**: TOTAL_CAPITAL, RISK_PER_TRADE_PCT, MAX_DAILY_LOSS
- **SL/TP**: SL_POINTS=6, TP_POINTS=12
- **Position sizing**: CE_QUANTITY=195, PE_QUANTITY=130
- **Strategy**: MIN_SCORE=4, MIN_CONFIDENCE=70
- **Kill switch**: KILL_SWITCH_LOSS=3000, KILL_SWITCH_CONSEC_LOSS=3
- **Cooldowns**: COOLDOWN_NORMAL=180, COOLDOWN_AFTER_SL=300
- **Telegram**: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

---

## Trading Modes

| Mode | Condition | Behavior |
|------|-----------|----------|
| AGGRESSIVE | Default | Standard parameters |
| SAFE | After consecutive losses | Tighter filters, reduced size |
| LOCKDOWN | Daily loss limit hit | No new trades |

---

## Exit Logic (v3.4)

| Exit Type | Condition |
|-----------|-----------|
| Hard SL | -6 points from entry |
| Take Profit | +12 points from entry |
| Breakeven | At +5 pts → lock +2 pts profit |
| Trailing SL | 3 pts below max profit |
| Step TSL | 10 step levels (5:2, 8:4, 10:5, ...) |
| Early Loss Cut | ATR-adaptive (3/4/5 pts in 30s) |
| RSI Exit | CE: RSI > 80, PE: RSI < 20 |
| Max Hold | 900 seconds (15 min) |

---

## Cooldown Periods

| Event | Cooldown |
|-------|----------|
| Normal trade | 180s (3 min) |
| After profit | 120s (2 min) |
| After SL | 300s (5 min) |
| After 3 consecutive losses | 1200s (20 min) |

---

## Testing

```bash
# Run all 75 tests
python -m pytest tests/ -v

# Individual test files
python tests/test_greeks.py
python tests/test_greeks_caching.py
python tests/test_kill_switch.py
python tests/test_batch_market_data.py
python tests/test_phases_3_4_5.py
python tests/test_analytics.py
python tests/test_websocket.py
```

---

## Support

1. Check logs: `logs/YYYY-MM-DD/`
2. Verify `.env` credentials
3. Market hours: 9:15 AM - 3:30 PM IST
4. Run tests: `python -m pytest tests/`

---

## Disclaimer

⚠️ **Trading involves risk.** This software is for educational purposes. Past performance does not guarantee future results. Use at your own risk.
