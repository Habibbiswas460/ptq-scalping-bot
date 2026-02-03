# 📁 PTQ SCALPING BOT - PROJECT STRUCTURE
## SMART SCALP v3.0 - File Organization

```
PTQ-scalping bot/
│
├── 🚀 ENTRY POINT
│   └── app.py                    # Main entry - Run: python app.py
│
├── ⚙️ CONFIG
│   ├── .env                      # 🔐 All settings (credentials + config)
│   ├── .env.example              # Template for .env
│   └── config/
│       └── constants.py          # Loads .env → Python variables
│
├── 🧠 CORE (Trading Engine)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── main.py               # Main trading loop
│   │   ├── broker.py             # Angel One API interface
│   │   ├── state_machine.py      # Bot state management
│   │   ├── entry_engine.py       # Entry signal logic
│   │   ├── exit_engine.py        # Exit signal logic
│   │   ├── trade_manager.py      # Trade execution
│   │   ├── risk_manager.py       # Risk & P&L management
│   │   ├── kill_switch.py        # Emergency stop
│   │   ├── greeks_calc.py        # Options Greeks calculator
│   │   ├── validators.py         # Data validation
│   │   ├── session_manager.py    # Trading session control
│   │   ├── mode_switch.py        # Trading mode switcher
│   │   ├── database.py           # SQLite trade logging
│   │   ├── dashboard.py          # FastAPI Web UI
│   │   └── telegram_bot.py       # Telegram notifications
│
├── 📈 STRATEGIES
│   └── strategies/
│       ├── __init__.py
│       └── smart_scalp_v3.py     # 🏆 Main strategy (10+10 factors)
│
├── 🔌 BROKERS
│   └── brokers/
│       └── angel_one/
│           ├── __init__.py
│           ├── client.py          # SmartAPI client
│           └── exceptions.py      # Custom exceptions
│
├── 🛠️ UTILITIES
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py             # Helper functions
│       ├── logger.py              # Logging system
│       ├── greeks.py              # Greeks utilities
│       └── analytics.py           # Analytics & reports
│
├── 🧪 TESTS
│   └── tests/
│       ├── __init__.py
│       └── test_greeks.py         # Greeks tests
│
├── 💾 DATA & LOGS
│   ├── data/
│   │   └── trades.db              # SQLite database
│   └── logs/
│       ├── bot_state.json         # Current state
│       └── YYYY-MM-DD/            # Daily logs
│           ├── summary.json
│           └── trades.json
│
├── 📚 DOCUMENTATION
│   ├── README.md                  # Project overview
│   ├── DOCUMENTATION.md           # Technical docs
│   └── docs/
│       └── 30K_CONFIG.md          # ₹30K config guide
│
└── 🔧 PROJECT FILES
    ├── requirements.txt           # Python dependencies
    ├── run.sh                     # Shell startup script
    ├── .gitignore                 # Git ignore rules
    └── venv/                      # Virtual environment
```

---

## 📋 FILE CATEGORIES

### 🔐 Configuration (2 files)
| File | Purpose |
|------|---------|
| `.env` | All settings: credentials, capital, SL/TP, indicators |
| `config/constants.py` | Loads .env into Python constants |

### 🧠 Core Trading (14 files)
| File | Purpose |
|------|---------|
| `core/main.py` | Main trading loop orchestration |
| `core/broker.py` | Angel One API connection & orders |
| `core/state_machine.py` | Bot state (IDLE→ENTRY→TRADE→EXIT) |
| `core/entry_engine.py` | Entry signal generation |
| `core/exit_engine.py` | Exit signal logic (SL/TP/TSL) |
| `core/trade_manager.py` | Trade execution & tracking |
| `core/risk_manager.py` | Risk management & P&L |
| `core/kill_switch.py` | Emergency stop conditions |
| `core/greeks_calc.py` | Options Greeks (Delta, Gamma, Theta) |
| `core/validators.py` | Data hygiene & validation |
| `core/session_manager.py` | Trading session timing |
| `core/mode_switch.py` | Normal/Aggressive mode |
| `core/database.py` | SQLite trade logging |
| `core/dashboard.py` | FastAPI web dashboard |
| `core/telegram_bot.py` | Telegram alerts |

### 📈 Strategy (1 file)
| File | Purpose |
|------|---------|
| `strategies/smart_scalp_v3.py` | 🏆 Multi-factor scoring (10 bull + 10 bear) |

### 🔌 Broker (2 files)
| File | Purpose |
|------|---------|
| `brokers/angel_one/client.py` | SmartAPI wrapper |
| `brokers/angel_one/exceptions.py` | Error handling |

### 🛠️ Utilities (4 files)
| File | Purpose |
|------|---------|
| `utils/helpers.py` | Common helper functions |
| `utils/logger.py` | Logging system |
| `utils/greeks.py` | Greeks utilities |
| `utils/analytics.py` | Reports & analytics |

---

## 🚀 HOW TO RUN

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Run the bot
python app.py

# 3. Access Dashboard
# http://localhost:8080
```

---

## 📊 CONFIG FLOW

```
.env (all settings)
    ↓
config/constants.py (load to Python)
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
core/state_machine.py (state management)
    ↓
├── core/entry_engine.py + strategies/smart_scalp_v3.py
├── core/trade_manager.py + core/broker.py
├── core/exit_engine.py (SL/TP/TSL)
├── core/risk_manager.py + core/kill_switch.py
└── core/dashboard.py + core/telegram_bot.py
```

---

## 💡 KEY FEATURES

| Feature | Location |
|---------|----------|
| 🏆 SMART SCALP v3.0 | `strategies/smart_scalp_v3.py` |
| 📊 Multi-factor Scoring | 10 bullish + 10 bearish factors |
| 🛡️ TSL Step Levels | 8 profit lock steps |
| 🚨 Kill Switch | `core/kill_switch.py` |
| 📈 Greeks Filter | `core/greeks_calc.py` |
| 🖥️ Web Dashboard | `core/dashboard.py` (:8080) |
| 📱 Telegram Alerts | `core/telegram_bot.py` |
| 💾 Trade History | `core/database.py` (SQLite) |

---

**Total: 27 Python files | 7 folders | Fully .env configured**
