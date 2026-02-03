# PTQ Scalping Bot - Documentation Index

## 📚 Documentation Overview

Complete documentation for the PTQ Scalping Bot v2.0 with SMART SCALP v3.0 strategy.

---

## Quick Links

| Document | Description |
|----------|-------------|
| [README.md](README.md) | Main project overview and quick setup |
| [docs/QUICK_START.md](docs/QUICK_START.md) | 5-minute setup guide |
| [docs/TECHNICAL_DOCS.md](docs/TECHNICAL_DOCS.md) | Complete technical reference |
| [docs/30K_CONFIG.md](docs/30K_CONFIG.md) | ₹30K capital configuration guide |
| [docs/SMART_SCALP_V3_STRATEGY.md](docs/SMART_SCALP_V3_STRATEGY.md) | Strategy details and scoring |
| [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md) | Angel One API integration |

---

## System Overview

PTQ Scalping Bot is an institutional-grade NIFTY options scalping system featuring:

- **SMART SCALP v3.0**: Multi-factor scoring with 10 bullish + 10 bearish factors
- **Angel One Integration**: Exclusive broker for all market data and orders
- **Adaptive Modes**: NORMAL → CAUTIOUS → AGGRESSIVE → RECOVERY
- **Risk Management**: Fixed SL/TP, kill switch, daily limits
- **Paper Trading**: Full simulation with real NIFTY spot prices

---

## Key Specifications

| Specification | Value |
|---------------|-------|
| Broker | Angel One SmartAPI |
| Symbol | NIFTY Weekly Options |
| Symbol Format | `NIFTY{DDMMMYY}{STRIKE}{CE/PE}` |
| Example | `NIFTY03FEB2625400CE` |
| Win Rate | 58.5% |
| Profit Factor | 2.06x |
| Risk-Reward | 1:2 (8pt SL, 16pt TP) |

---

## Project Structure

```
PTQ-scalping bot/
├── app.py                  # Entry point
├── core/                   # Core trading logic
│   ├── broker.py           # Broker interface
│   ├── main.py             # Main loop
│   ├── entry_engine.py     # Entry signals
│   ├── exit_engine.py      # Exit handling
│   ├── trade_manager.py    # Trade execution
│   └── risk_manager.py     # Risk controls
├── strategies/             # Trading strategies
│   └── smart_scalp_v3.py   # SMART SCALP v3.0
├── brokers/angel_one/      # Angel One client
├── config/                 # Configuration
├── utils/                  # Utilities
├── logs/                   # Trade logs
└── docs/                   # Documentation
```

---

## Getting Started

```bash
# 1. Activate environment
source venv/bin/activate

# 2. Configure credentials
# Edit config/credentials.json

# 3. Run in paper mode
python app.py
```

---

## Configuration

### Paper Trading (Default)
```json
{
  "broker": {
    "paper_trading": true,
    "use_live_data": true
  }
}
```

### Live Trading
```json
{
  "broker": {
    "paper_trading": false,
    "use_live_data": true
  }
}
```

---

## Support

1. Check logs: `logs/YYYY-MM-DD/`
2. Verify credentials: `config/credentials.json`
3. Market hours: 9:15 AM - 3:30 PM IST

---

## Disclaimer

⚠️ **Trading involves risk.** This software is for educational purposes. Past performance does not guarantee future results. Use at your own risk.
