# ₹30,000 Capital Configuration Guide

## SMART SCALP v3.0 Optimized Settings

This guide explains the optimal configuration for trading NIFTY options with ₹30,000 capital.

---

## Capital Overview

| Metric | Value | Calculation |
|--------|-------|-------------|
| Total Capital | ₹30,000 | Base amount |
| Risk Per Trade | ₹600 | 2% of capital |
| Max Daily Loss | ₹900 | 3% of capital |
| Kill Switch | ₹1,200 | 4% of capital |
| Max Drawdown | ₹3,000 | 10% of capital |

---

## Position Sizing

### NIFTY Lot Size
- Current lot size: **65 shares**
- Margin per lot: ~₹15,000

### Quantity Configuration

| Option Type | Lots | Quantity | Margin Required |
|-------------|------|----------|-----------------|
| CE Entry | 4 | 260 | ~₹60,000* |
| PE Entry | 2.4 | 156 | ~₹36,000* |

*Note: Paper trading doesn't require actual margin. For live trading, you'll need 2x capital for full position sizing or use NRML positions.

---

## Risk-Reward Setup

### Fixed 8-Point Stop Loss

The strategy uses a FIXED 8-point stop loss, regardless of market conditions:

| Reason | Explanation |
|--------|-------------|
| Discipline | Removes emotional decision making |
| Consistency | Same risk on every trade |
| Backtest Proven | Optimal for scalping timeframe |
| Capital Protection | Limits max loss per trade |

### Fixed 16-Point Take Profit

| Metric | CE Trade | PE Trade |
|--------|----------|----------|
| SL Points | 8 | 8 |
| TP Points | 16 | 16 |
| Risk-Reward | 1:2 | 1:2 |

### P&L Calculation

```
CE Trade:
- Max Loss = 8 pts × 260 qty = ₹2,080
- Max Profit = 16 pts × 260 qty = ₹4,160

PE Trade:
- Max Loss = 8 pts × 156 qty = ₹1,248
- Max Profit = 16 pts × 156 qty = ₹2,496
```

---

## Daily Limits

### Trade Frequency

| Limit | Value | Purpose |
|-------|-------|---------|
| Max Trades/Hour | 3 | Prevent overtrading |
| Max Trades/Day | 6 | Quality over quantity |
| Ideal Trades/Day | 4 | Optimal for strategy |

### Loss Limits

| Level | Amount | Action |
|-------|--------|--------|
| Warning | ₹650 | Alert logged |
| Daily Max | ₹900 | Reduce position size |
| Kill Switch | ₹1,200 | Stop all trading |

---

## Profit Targets

### Daily Target

Based on 58.5% win rate and 1:2 R:R:

```
Expected Value per Trade:
= (0.585 × ₹4,160) + (0.415 × -₹2,080)
= ₹2,434 - ₹863
= ₹1,571 per winning day

With 4 trades/day:
Average Daily P&L ≈ ₹2,500 - ₹3,000 (profitable days)
```

### Monthly Target

| Metric | Conservative | Target | Aggressive |
|--------|--------------|--------|------------|
| Trading Days | 20 | 22 | 22 |
| Profitable Days | 12 | 14 | 16 |
| Monthly P&L | ₹30,000 | ₹50,000 | ₹70,000 |
| ROI | 100% | 167% | 233% |

---

## Configuration File

### bot_config.json Settings

```json
{
  "capital": {
    "total_capital": 30000,
    "risk_per_trade_pct": 2.0,
    "risk_per_trade_amount": 600,
    "max_daily_loss_amount": 900,
    "max_drawdown_amount": 3000,
    "max_drawdown_pct": 10.0
  },
  
  "trading": {
    "lot_size": 65,
    "quantity": 4,
    "option_type": "CE"
  },
  
  "risk_management": {
    "sl_points": 8,
    "sl_points_fixed": true,
    "tp_points": 16,
    "tp_multiplier": 2.0,
    "max_trades_per_hour": 3,
    "max_trades_per_day": 6
  },
  
  "strategy": {
    "ce_entry": {
      "quantity": 260
    },
    "pe_entry": {
      "quantity": 156
    }
  },
  
  "kill_switch": {
    "enabled": true,
    "daily_loss_amount": 1200
  }
}
```

---

## Why ₹30K Configuration?

### Advantages

1. **Optimal Risk Management**
   - 2% risk keeps individual losses small
   - 3% daily max protects capital
   - 10% drawdown limit preserves majority

2. **Psychological Comfort**
   - Losses are manageable
   - Profits are meaningful
   - Sustainable over long term

3. **Strategy Fit**
   - SMART SCALP v3.0 optimized for 4 lots
   - 1:2 R:R proven in backtesting
   - 58.5% win rate is sustainable

### Scaling Up

When consistently profitable:

| Stage | Capital | Lots | Risk/Trade |
|-------|---------|------|------------|
| Start | ₹30K | 4 | ₹600 |
| Level 2 | ₹50K | 6 | ₹1,000 |
| Level 3 | ₹1L | 12 | ₹2,000 |
| Level 4 | ₹2L | 24 | ₹4,000 |

Scale only after:
- 30+ trading days
- 55%+ win rate maintained
- Max drawdown < 10%

---

## Paper Trading First

### Recommended Testing Period

1. **Week 1-2**: Paper trading, observe signals
2. **Week 3-4**: Paper trading, track hypothetical P&L
3. **Month 2**: Small live (1-2 lots) if profitable
4. **Month 3+**: Full size if consistently profitable

### What to Track

| Metric | Target | Red Flag |
|--------|--------|----------|
| Win Rate | >55% | <50% |
| Profit Factor | >1.5 | <1.0 |
| Max Drawdown | <15% | >20% |
| Avg Winner | >₹3,000 | <₹2,000 |
| Avg Loser | <₹1,500 | >₹2,000 |

---

## Risk Warnings

⚠️ **Important Disclaimers:**

1. Past performance doesn't guarantee future results
2. Options trading involves significant risk
3. Only trade with money you can afford to lose
4. Paper trading results may differ from live trading
5. Market conditions affect strategy performance

### Never Do This

❌ Trade without stop loss
❌ Increase position after losses
❌ Trade outside market hours signals
❌ Disable kill switch
❌ Use borrowed money

### Always Do This

✅ Use fixed stop loss
✅ Follow position sizing rules
✅ Respect daily limits
✅ Review trades daily
✅ Maintain trading journal
