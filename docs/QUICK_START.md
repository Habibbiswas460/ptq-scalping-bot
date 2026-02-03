# Quick Start Guide

## Get PTQ Scalping Bot Running in 5 Minutes

---

## Prerequisites

- Python 3.12+
- Angel One trading account
- SmartAPI subscription (free)

---

## Step 1: Setup Environment

```bash
# Navigate to project
cd "PTQ-scalping bot"

# Create virtual environment
python3.12 -m venv venv

# Activate
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Step 2: Configure Credentials

Create `config/credentials.json`:

```json
{
  "angel_one": {
    "api_key": "YOUR_API_KEY",
    "client_id": "YOUR_CLIENT_ID",
    "password": "YOUR_4_DIGIT_PIN",
    "totp_token": "YOUR_TOTP_SECRET"
  }
}
```

### Getting Credentials

1. **API Key**: Login to [SmartAPI](https://smartapi.angelone.in/) → Create App → Copy API Key
2. **Client ID**: Your Angel One client code (e.g., "A123456")
3. **Password**: Your 4-digit MPIN
4. **TOTP Secret**: From authenticator app setup (Base32 string)

---

## Step 3: Verify Configuration

Default settings in `config/bot_config.json`:

```json
{
  "broker": {
    "paper_trading": true,  // ← Safe mode, no real orders
    "use_live_data": true   // ← Uses real NIFTY prices
  }
}
```

---

## Step 4: Run the Bot

```bash
# Simple way
python app.py

# Or use the run script
./run.sh
```

---

## Expected Output

```
==================================================
PTQ Scalping Bot v2.0 - Angel One
==================================================
Mode: PAPER TRADING
✅ Angel One connected - Real NIFTY: ₹25,342.75
✓ Using Strike: 25350
✓ Expiry: 03FEB26 | Symbol: NIFTY03FEB2625350CE
✓ Greeks API fetcher initialized

============================================================
🏆 SMART SCALP v3.0 - ₹30K CONFIG
============================================================
📈 Strategy: Multi-factor Scoring System
💰 Capital: ₹30,000 | Risk/Trade: ₹600
📊 CE: 260 qty | PE: 156 qty
🎯 Min Score: 5 | Min Conf: 60%
🛡️ SL: 8-8 pts | TP: 2.0-2.5x
🛑 Kill Switch: ₹900 | Max Loss: ₹900
⏱ Cooldown: 30s / 60s (after SL)
📅 Day Type: NORMAL
🎛 Mode: NORMAL 🟢
------------------------------------------------------------
🔄 Entering main trading loop...
```

---

## Step 5: Monitor

The bot will:
1. Connect to Angel One
2. Get real NIFTY spot price
3. Find nearest weekly expiry
4. Start scanning for entry signals
5. Execute paper trades when conditions met

### Log Files

- Today's trades: `logs/YYYY-MM-DD/trades.json`
- Today's summary: `logs/YYYY-MM-DD/summary.json`

---

## Market Hours

The bot only trades during market hours:
- **Open**: 9:15 AM IST
- **Close**: 3:30 PM IST

Outside market hours, the bot will wait or exit.

---

## Common Issues

### "Login failed"
- Check credentials.json
- Verify TOTP secret is correct
- Ensure API key is active

### "Market not open"
- Run during market hours (9:15 AM - 3:30 PM IST)
- Or wait for market to open

### "No contracts found"
- Broker connection may have failed
- Try restarting the bot

---

## Next Steps

1. **Watch the bot** for a few sessions in paper mode
2. **Review trades** in logs folder
3. **Understand signals** by watching console output
4. **Go live** only after consistent paper profits

---

## Quick Commands

```bash
# Start bot
python app.py

# Test broker connection
python test_live_data.py

# Check logs
cat logs/$(date +%Y-%m-%d)/summary.json

# Stop bot
Ctrl+C
```

---

## Help

- Full docs: [docs/TECHNICAL_DOCS.md](docs/TECHNICAL_DOCS.md)
- 30K config: [docs/30K_CONFIG.md](docs/30K_CONFIG.md)
- Broker docs: [brokers/angel_one/DOCUMENTATION.md](brokers/angel_one/DOCUMENTATION.md)
