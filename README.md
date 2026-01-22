# 🚀 PTQ Scalping Bot

**Professional NIFTY Options Scalping Bot** with Angel One Broker Integration

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📊 **PTQ Strategy** | Price + Time + Quantity validated entries |
| 💰 **Paper Trading** | Test strategies without real money |
| 📈 **Live Data** | Real-time NIFTY spot via Yahoo Finance |
| 🎯 **Multi-Level TP** | 3-tier profit targets with partial exits |
| 🛡️ **Risk Management** | Dynamic SL, trailing stop, kill switch |
| 📉 **Greeks Monitoring** | Delta, Gamma, Theta based exits |
| 📋 **Trade Analytics** | Comprehensive performance analysis |
| 💾 **State Persistence** | Resume from last state after restart |

---

## 📁 Project Structure

```
PTQ-scalping bot/
├── app.py                    # Entry point
├── analyze.py                # Trade analyzer CLI
├── run.sh                    # Quick start script
│
├── config/
│   ├── constants.py          # All trading parameters
│   ├── bot_config.json       # JSON configuration
│   └── credentials.json      # API credentials (git ignored)
│
├── core/
│   ├── main.py               # Main trading loop
│   ├── broker.py             # Broker I/O operations
│   ├── validators.py         # Data & PTQ validation
│   ├── entry_engine.py       # Entry signal logic
│   ├── exit_engine.py        # Exit logic (SL/TP/Trailing)
│   ├── state_machine.py      # Trading state management
│   ├── kill_switch.py        # Emergency safety checks
│   └── greeks_calc.py        # Greeks calculator
│
├── utils/
│   ├── greeks.py             # BSM model calculator
│   ├── logger.py             # Enhanced logging
│   ├── analytics.py          # Trade analysis
│   └── helpers.py            # Utility functions
│
├── brokers/
│   └── angel_one/            # Angel One API client
│
├── logs/                     # Trading logs by date
│   └── YYYY-MM-DD/
│       ├── trades.json       # Raw trade data
│       ├── trades.csv        # Excel compatible
│       ├── analytics.json    # Performance metrics
│       └── report.txt        # Human readable report
│
└── tests/                    # Unit tests
```

---

## 🚀 Quick Start

### 1. Setup Environment

```bash
git clone https://github.com/Habibbiswas460/ptq-scalping-bot.git
cd ptq-scalping-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Credentials

```bash
cp config/credentials.json.example config/credentials.json
# Edit with your Angel One API keys
```

### 3. Run Bot

```bash
# Using run script (recommended)
./run.sh

# Or directly
python app.py
```

---

## ⚙️ Configuration (₹30K Setup)

| Parameter | Value | Description |
|-----------|-------|-------------|
| Capital | ₹30,000 | Total trading capital |
| Risk/Trade | ₹300 (1%) | Max risk per trade |
| Stop Loss | ₹250 | Fixed stop loss amount |
| TP-1 | ₹100 | First target (30% exit) |
| TP-2 | ₹200 | Second target (40% exit) |
| TP-3 | ₹350 | Final target (30% exit) |
| Kill Switch | ₹1,800 (6%) | Auto shutdown limit |
| Max Trades | 25/day, 8/hour | Trading limits |

---

## 📊 Trade Analysis

### Run Analyzer

```bash
# Interactive mode
python analyze.py

# Analyze today
python analyze.py today

# Analyze specific date
python analyze.py 2026-01-22

# List available dates
python analyze.py --list
```

### Sample Output

```
📊 PTQ SCALPING BOT - TRADING REPORT
======================================================================
📈 PERFORMANCE SUMMARY
----------------------------------------
Total Trades:      11
Winners:           1 (9.09%)
Profit Factor:     1.62
Expectancy:        ₹23.82/trade

💰 PROFIT & LOSS
----------------------------------------
Total PnL:         ₹+262.00
Best Trade:        ₹687.00
Max Drawdown:      ₹421.50
```

---

## 🔧 PTQ Strategy

The bot uses **P-T-Q validation** for entries:

### P - Price
- VWAP breakout/rejection
- Candle body analysis
- Chop filter (min range)

### T - Time
- Session filters (avoid first 15 min)
- Theta decay threshold
- Market close protection

### Q - Quantity
- Volume expansion (>1.02x avg)
- Spread check (<0.2%)
- Liquidity confirmation

---

## 🛡️ Risk Management

```
┌─────────────────────────────────────┐
│ 🎯 MULTI-TIER EXIT SYSTEM           │
├─────────────────────────────────────┤
│ TP-1 (₹100)  → Exit 30%             │
│ TP-2 (₹200)  → Exit 40% + BE SL     │
│ TP-3 (₹350)  → Exit remaining 30%   │
├─────────────────────────────────────┤
│ 📉 TRAILING STOPS                   │
├─────────────────────────────────────┤
│ @ ₹75   → Lock 30% profit           │
│ @ ₹150  → Lock 50% profit           │
│ @ ₹250  → Lock 60% profit           │
├─────────────────────────────────────┤
│ 🛑 KILL SWITCHES                    │
├─────────────────────────────────────┤
│ Daily Loss > ₹1,800 → Stop trading  │
│ Spread > 0.5%       → Exit & pause  │
│ Latency > 150ms     → Exit & pause  │
└─────────────────────────────────────┘
```

---

## 📈 Greeks-Based Exits

| Greek | Limit | Action |
|-------|-------|--------|
| Delta | < 0.02 | Kill trade immediately |
| Gamma | > 0.15 (expiry) | Exit position |
| Theta/sec | > 0.001 | Exit position |

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_greeks.py -v
```

---

## 📝 Log Files

Each trading day creates:

| File | Format | Use |
|------|--------|-----|
| `trades.json` | JSON | Raw data for analysis |
| `trades.csv` | CSV | Open in Excel |
| `analytics.json` | JSON | Metrics & stats |
| `report.txt` | Text | Human readable report |
| `events.json` | JSON | All bot events |
| `bot.log` | Text | Full activity log |

---

## ⚠️ Disclaimer

This bot is for **educational purposes only**. Trading in options involves significant risk. Past performance does not guarantee future results. Use at your own risk.

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🤝 Author

**Habib Biswas**

- GitHub: [@Habibbiswas460](https://github.com/Habibbiswas460)
