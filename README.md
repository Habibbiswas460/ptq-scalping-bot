# PTQ Scalping Bot

A professional NIFTY options scalping bot integrated with Angel One broker.

## Features

- **Paper Trading Mode**: Test strategies without real money
- **Live Data**: Real-time NIFTY spot prices via Yahoo Finance
- **PTQ Strategy**: Price + Time + Quantity validated entries
- **Greeks-based Exit**: Delta, Gamma, Theta monitoring
- **Risk Management**: Stop loss, take profit, trailing stop
- **Kill Switch**: Automatic shutdown on excessive losses
- **State Persistence**: Resumes from last state after restart

## Project Structure

```
PTQ-scalping bot/
├── app.py                  # Entry point
├── core/
│   └── main.py             # Main trading logic
├── config/
│   ├── bot_config.json     # Bot configuration
│   ├── config_loader.py    # Config loading utility
│   └── credentials.json    # API credentials (not in git)
├── state/
│   └── state_persistence.py # State save/load
├── brokers/
│   └── angel_one/          # Angel One broker integration
├── utils/
│   ├── greeks.py           # Options Greeks calculator
│   ├── logger.py           # Logging utility
│   └── utility.py          # Helper functions
├── tests/                  # Unit tests
├── logs/                   # Trading logs
└── requirements.txt        # Dependencies
```

## Quick Start

### 1. Clone & Setup

```bash
git clone <repo-url>
cd PTQ-scalping\ bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy credentials example:
```bash
cp config/credentials.json.example config/credentials.json
```

Edit `config/credentials.json` with your Angel One API credentials.

### 3. Run

```bash
python app.py
```

Or use the run script:
```bash
./run.sh
```

## Configuration

Edit `config/bot_config.json` to customize:

- **Capital**: `total_capital`, `risk_per_trade_amount`
- **Trading**: `symbol`, `lot_size`, `quantity`
- **Risk**: `stop_loss_amount`, `max_trades_per_day`
- **Session**: Trading hours, blackout periods

## Risk Parameters (₹30K Config)

| Parameter | Value |
|-----------|-------|
| Capital | ₹30,000 |
| Risk/Trade | ₹300 (1%) |
| Stop Loss | ₹250 |
| Kill Switch | ₹900 (3%) |
| Max Trades | 8/day |

## Testing

```bash
pytest tests/ -v
```

## Logs

Logs are saved in `logs/` directory:
- `bot_state.json` - Current state
- `YYYY-MM-DD/` - Daily logs

## Safety

- **Paper Trading**: Set `PAPER_TRADING = True` in `core/main.py`
- **Test Mode**: Set `TEST_MODE = True` to bypass market hours
- **Kill Switch**: Automatic stop on 3% daily loss

## License

Private - Not for distribution

## Disclaimer

This software is for educational purposes only. Trading involves risk. Use at your own risk.
