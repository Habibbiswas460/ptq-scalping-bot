# PTQ Scalping Bot - Lightweight

## ✅ Current Status

- **API**: Connected & Tested ✓
- **Live Data**: Enabled (NIFTY @ ₹25,232.50)
- **Mode**: Paper Trading with Live Market Data
- **Credentials**: Configured ✓

## 🚀 Quick Start

```bash
./run.sh
```

## 🧪 Test API Connection

```bash
python quick_api_test.py
```

This will verify:
- Angel One login ✓
- Live data fetch ✓
- Current NIFTY price

## �📊 Bot Configuration

**Mode**: Paper Trading (Safe Testing)  
**Capital**: ₹30,000  
**Strategy**: Multi-Level PTQ Exit

### Exit Strategy
- **TP-1**: ₹100 → Exit 30%
- **TP-2**: ₹200 → Exit 40% + SL to BE
- **TP-3**: ₹350 → Exit final 30%
- **SL**: ₹250

### Trailing Stop
- **Tier 1** (₹75+): Lock 30%
- **Tier 2** (₹150+): Lock 50%
- **Tier 3** (₹250+): Lock 60%

### Risk Limits
- Risk/Trade: ₹300 (1%)
- Max Trades: 8/hour, 25/day
- Max Daily Loss: ₹1,200 (4%)
- Kill Switch: ₹1,800 (6%)

## 📁 Structure

```
├── main.py              (46KB) - Main bot
├── run.sh               (1KB)  - Quick start
├── quick_api_test.py    (2KB)  - API connection test
├── config/
│   ├── bot_config.json        - Bot settings
│   └── credentials.json       - Angel One credentials ✓
├── brokers/
│   └── angel_one/             - Angel One integration ✓
└── utils/
    ├── greeks.py              - Greeks calculator
    └── logger.py              - Logging
```

## 🎯 To Go Live

**Current**: Paper Trading with Live Data ✓

To enable real orders:
1. Test thoroughly in paper mode first (recommended: 2-3 days)
2. Edit `main.py` line 30-31:
   ```python
   PAPER_TRADING = False  # Enable live trading
   TEST_MODE = False       # Use real market hours
   ```
3. Start with small capital
4. Monitor closely

---

## 🔧 Recent Updates

- ✅ API integration tested & working
- ✅ Live market data enabled (NIFTY @ ₹25,232.50)
- ✅ PTQ filters optimized for real data
- ✅ Multi-level exit strategy active
- ✅ 3-tier trailing stops configured
- ✅ Angel One credentials configured

---

**Status**: ✅ Live Data Mode - Ready for Trading
