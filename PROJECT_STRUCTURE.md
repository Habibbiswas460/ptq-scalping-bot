# 📁 PTQ SCALPING BOT - PROJECT STRUCTURE
## SMART SCALP v3.4 - File Organization

```
PTQ-scalping bot/
│
├── 🚀 ENTRY POINT
│   └── app.py                    # Main entry - Run: python app.py
│
├── ⚙️ CONFIG
│   ├── .env                      # 🔐 All settings (credentials + config)
│   └── config/
│       ├── constants.py          # Loads .env → Python variables
│       └── validator.py          # Startup config validation
│
├── 🧠 CORE (Trading Engine)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── main.py               # Main trading loop
│   │   ├── backtest.py           # Backtesting engine
│   │   │
│   │   ├── 📁 engines/           # Signal Engines
│   │   │   ├── __init__.py
│   │   │   ├── entry_engine.py   # Entry signal logic
│   │   │   ├── exit_engine.py    # Exit signal logic
│   │   │   └── state_machine.py  # Bot state management
│   │   │
│   │   ├── 📁 risk/              # Risk Management
│   │   │   ├── __init__.py
│   │   │   ├── risk_manager.py   # VIX filter, drawdown, sizing
│   │   │   ├── kill_switch.py    # Emergency stop (thread-safe)
│   │   │   ├── validators.py     # Data & PTQ validation
│   │   │   ├── greeks_calc.py    # Greeks from API
│   │   │   └── session_trend.py  # Session trend tracking
│   │   │
│   │   ├── 📁 services/          # Services
│   │   │   ├── __init__.py
│   │   │   ├── database.py       # SQLite trade logging
│   │   │   ├── telegram_bot.py   # Telegram notifications
│   │   │   ├── mode_switch.py    # Adaptive mode switching
│   │   │   └── session_manager.py# Session management
│   │   │
│   │   ├── 📁 trading/           # Trade Execution
│   │   │   ├── __init__.py
│   │   │   ├── broker.py         # Angel One interface + WebSocket
│   │   │   └── trade_manager.py  # Trade execution wrapper
│   │   │
│   │   └── 📁 data/              # Runtime Data
│   │       └── trades.db         # SQLite database
│
├── 📈 STRATEGIES
│   └── strategies/
│       ├── __init__.py
│       └── smart_scalp_v3.py     # 🏆 SMART SCALP v3.4 (10+10 factors)
│
├── 🔌 BROKERS
│   └── brokers/
│       └── angel_one/
│           ├── __init__.py
│           ├── client.py          # SmartAPI client
│           ├── exceptions.py      # Custom exceptions
│           └── DOCUMENTATION.md   # API reference
│
├── 🛠️ UTILITIES
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py             # Helper functions
│       ├── logger.py              # Logging system
│       ├── greeks.py              # BSM calculator (cached)
│       ├── analytics.py           # Performance analytics
│       └── monitoring.py          # Health monitoring (BotMonitor)
│
├── 🧪 TESTS (75 tests)
│   └── tests/
│       ├── __init__.py
│       ├── test_greeks.py
│       ├── test_greeks_caching.py
│       ├── test_kill_switch.py
│       ├── test_batch_market_data.py
│       ├── test_phases_3_4_5.py
│       ├── test_analytics.py
│       └── test_websocket.py
│
├── 💾 DATA & LOGS
│   ├── data/
│   │   └── trades.db             # SQLite database
│   └── logs/
│       └── YYYY-MM-DD/           # Daily logs
│           ├── trades.csv
│           ├── trades.json
│           ├── summary.json
│           └── events.json
│
└── 📚 DOCUMENTATION
    ├── README.md                  # Project overview
    ├── DOCUMENTATION.md           # Technical docs index
    ├── PROJECT_STRUCTURE.md       # THIS FILE
    └── FILE_STRUCTURE_GUIDE.md    # Detailed reading guide
```

---

## 📋 FILE CATEGORIES

### 🔐 Configuration (2 files)
| File | Purpose |
|------|---------|
| `.env` | All settings: credentials, capital, SL/TP, indicators |
| `config/constants.py` | Loads .env into Python constants |
| `config/validator.py` | Validates config at startup |

### 🧠 Core - Engines (3 files)
| File | Purpose |
|------|---------|
| `core/engines/entry_engine.py` | Entry signal (score ≥ 5, confidence ≥ 70%) |
| `core/engines/exit_engine.py` | Exit: SL -6, TP +12, breakeven, TSL |
| `core/engines/state_machine.py` | States: IDLE → IN_TRADE → COOLDOWN |

### 🧠 Core - Risk (5 files)
| File | Purpose |
|------|---------|
| `core/risk/risk_manager.py` | VIX filter, drawdown, position sizing |
| `core/risk/kill_switch.py` | Emergency stop (₹450 kill / ₹1.5K max loss / 3 consec SL) |
| `core/risk/validators.py` | Data hygiene & PTQ validation |
| `core/risk/greeks_calc.py` | Options Greeks (Delta, Gamma, Theta) |
| `core/risk/session_trend.py` | Session trend & CE/PE gates |

### 🧠 Core - Services (4 files)
| File | Purpose |
|------|---------|
| `core/services/database.py` | SQLite trade logging |
| `core/services/telegram_bot.py` | Telegram alerts & send_alert() |
| `core/services/mode_switch.py` | AGGRESSIVE → SAFE → LOCKDOWN |
| `core/services/session_manager.py` | Trading session control |

### 🧠 Core - Trading (2 files)
| File | Purpose |
|------|---------|
| `core/trading/broker.py` | Angel One interface, WebSocket, orders |
| `core/trading/trade_manager.py` | Trade execution wrapper |

### 📈 Strategy (1 file)
| File | Purpose |
|------|---------|
| `strategies/smart_scalp_v3.py` | 🏆 Multi-factor scoring (10 bull + 10 bear) |

### 🔌 Broker (2 files)
| File | Purpose |
|------|---------|
| `brokers/angel_one/client.py` | SmartAPI wrapper |
| `brokers/angel_one/exceptions.py` | Error handling |

### 🛠️ Utilities (5 files)
| File | Purpose |
|------|---------|
| `utils/helpers.py` | Common helper functions |
| `utils/logger.py` | Logging system |
| `utils/greeks.py` | BSM calculator (cached) |
| `utils/analytics.py` | Performance analytics |
| `utils/monitoring.py` | Health monitoring (BotMonitor) |

---

## 🚀 HOW TO RUN

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Run the bot
python app.py

# 3. Run tests
python -m pytest tests/ -v
```

---

## 📊 CONFIG FLOW

```
.env (all settings)
    ↓
config/constants.py (load to Python)
    ↓
config/validator.py (validate at startup)
    ↓
All core modules import from constants
```

---

## 📈 TRADING FLOW

```
app.py
    ↓
core/main.py (main loop)
    ↓
core/engines/state_machine.py (state management)
    ↓
├── core/engines/entry_engine.py + strategies/smart_scalp_v3.py
├── core/trading/broker.py (orders + slippage guard)
├── core/engines/exit_engine.py (SL/TP/TSL)
├── core/risk/risk_manager.py + core/risk/kill_switch.py
└── core/services/telegram_bot.py + core/services/database.py
```

---

## 💡 KEY FEATURES

| Feature | Location |
|---------|----------|
| 🏆 SMART SCALP v3.4 | `strategies/smart_scalp_v3.py` |
| 📊 Multi-factor Scoring | Score ≥ 5, Confidence ≥ 70% |
| 🛡️ TSL Step Levels | 10 profit lock steps |
| 🚨 Kill Switch | `core/risk/kill_switch.py` |
| 📈 Greeks Filter | `core/risk/greeks_calc.py` |
| 📱 Telegram Alerts | `core/services/telegram_bot.py` |
| 💾 Trade History | `core/services/database.py` (SQLite) |
| 🔄 Adaptive Modes | AGGRESSIVE → SAFE → LOCKDOWN |
| 🧪 Test Suite | 75 tests passing |

---

**Total: ~30 Python files | 8 folders | Fully .env configured | v3.4**
