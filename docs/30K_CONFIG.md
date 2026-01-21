# ₹30K Configuration Summary

**Date:** January 2026  
**Status:** Production-ready  
**Philosophy:** Survival first - "loss ছোট রাখা যায়"

---

## 💰 Core Parameters

### Capital Management
```
Total Capital:        ₹30,000
Risk per Trade:       ₹300 (1%)
Position Size:        Calculated based on SL distance
Max Daily Loss:       ₹1,500 (5%)
Kill Switch:          ₹900 (3R)
```

### Trade Limits
```
Max Trades/Hour:      3
Max Trades/Day:       10-12 (normal), 8 (expiry), 5 (monthly), 3 (event)
Trade Frequency:      Max 1 trade per 20 minutes (3/hour)
```

### Risk-Reward Ratios
```
Stop Loss:            ₹250-300 per trade
Profit Target 1:      ₹150 (exit 50% position)
Profit Target 2:      ₹300-350 (exit remaining 50%)
Trailing Stop:        After ₹180 profit (optional)

Minimum R:R:          1:1
Target R:R:           1:2
```

---

## ⏰ Session Management

### Trading Windows (IST)
```
✓ Morning Session:    09:20 AM - 11:00 AM  (100 minutes)
✓ Afternoon Session:  11:15 AM - 02:15 PM  (180 minutes)

✗ Market Open:        09:15 AM - 09:20 AM  (avoid volatility)
✗ Mid-day Break:      11:00 AM - 11:15 AM  (consolidation)
✗ Late Afternoon:     02:15 PM - 03:30 PM  (avoid volatility)
```

### Cooldown Periods
```
Normal Exit:          180 seconds (3 minutes)
After SL Hit:         300 seconds (5 minutes)
After 2 SLs:          900 seconds (15 minutes)
Kill Switch:          Manual reset required
```

---

## 📊 Day-Type Configuration

### NORMAL Days (Thursday, Monday, Tuesday)
```
Max Trades:           12
Stop Loss:            ₹300
Profit Targets:       ₹150 / ₹300
Delta Range:          0.35 - 0.60
Gamma Limit:          ≤ 0.07
Max Trade Duration:   45 minutes
```

### EXPIRY Days (Wednesday)
```
Max Trades:           8
Stop Loss:            ₹250
Profit Targets:       ₹125 / ₹250
Delta Range:          0.40 - 0.55
Gamma Limit:          ≤ 0.12
Max Trade Duration:   30 minutes
Session:              Morning only (09:20-11:00)
```

### MONTHLY_EXPIRY Days (Last Thursday)
```
Max Trades:           5
Stop Loss:            ₹200
Profit Targets:       ₹100 / ₹200
Delta Range:          0.45 - 0.55
Gamma Limit:          ≤ 0.10
Max Trade Duration:   20 minutes
Session:              Morning only (09:20-10:30)
```

### EVENT Days (RBI, Budget, Election Results)
```
Max Trades:           3
Stop Loss:            ₹150
Profit Targets:       ₹75 / ₹150
Delta Range:          0.45 - 0.50
Gamma Limit:          ≤ 0.05
Max Trade Duration:   15 minutes
Status:               Consider avoiding entirely
```

---

## 🎯 Greeks Filter Limits

### Delta (Directional Exposure)
```
Entry Range (Normal):     0.35 - 0.60
Entry Range (Expiry):     0.40 - 0.55
Exit if < 0.25 or > 0.75

Interpretation:
- Delta 0.35-0.40: Slightly OTM, safer
- Delta 0.45-0.55: ATM, balanced
- Delta 0.55-0.60: Slightly ITM, aggressive
```

### Gamma (Acceleration Risk)
```
Max (Normal):             ≤ 0.07
Max (Expiry):             ≤ 0.12
Exit if > 0.15

Interpretation:
- High Gamma = Rapid delta changes
- Avoid during high volatility
- More strict on normal days
```

### Theta (Time Decay)
```
Max Theta/second:         ≤ 0.03%
Exit if > 0.05%

Calculation:
- Theta per day ÷ 86400 seconds
- Higher decay = faster option value loss
- Critical near expiry
```

### Vega (Volatility Sensitivity)
```
Max (Normal):             ≤ 0.30
Max (Expiry):             ≤ 0.20

Interpretation:
- High Vega = Sensitive to IV changes
- Lower limit near expiry
- Avoid during event risk
```

---

## 🛡️ Kill Switch Configuration

### Automatic Triggers
```
Daily Loss ≥ ₹900     → KILL_SWITCH (3R hit)
Tick Latency > 150ms  → KILL_SWITCH (data quality issue)
Bid-Ask Spread > 0.5% → KILL_SWITCH (liquidity issue)
```

### Manual Triggers
```
Consecutive SLs: 3+   → Consider manual kill
Unusual Market:       → Manual kill recommended
Technical Issues:     → Immediate manual kill
```

### Recovery Process
```
1. Bot enters KILL_SWITCH state
2. All positions force-closed
3. No new trades allowed
4. Manual intervention required:
   - Review logs
   - Identify cause
   - Fix issue
   - Reset kill_switch_triggered flag
   - Restart bot
```

---

## 📈 Entry Signal Criteria (PTQ Method)

### Pre-Entry Checks
```
✓ Market hours: 9:15-15:30
✓ Trading session: Allowed window
✓ Daily trade limit: Not exceeded
✓ Hourly limit: < 3 trades
✓ Not in cooldown
✓ Daily loss < kill switch
✓ Greeks within range
✓ Spread < 0.5%
✓ Latency < 150ms
```

### Entry Validation
```
1. Signal generation (PTQ logic - to be implemented)
2. Symbol selection (liquid options)
3. Greeks check (Delta, Gamma, Theta, Vega)
4. Data hygiene (spread, latency)
5. Position sizing (based on SL distance)
6. Order placement
7. State transition: IDLE → ENTRY_READY → IN_TRADE
```

---

## 📉 Exit Management

### Exit Priority Order
```
1. Kill Switch        → Immediate exit (emergency)
2. Stop Loss          → Exit at -₹300
3. Profit Target 1    → Exit 50% at +₹150
4. Profit Target 2    → Exit remaining at +₹300
5. Greeks Exit        → Exit if Greeks exceed limits
6. Time Exit          → Exit at max duration
7. Manual Exit        → Ctrl+C (keyboard interrupt)
```

### Exit Logic Details

**Stop Loss Hit:**
```
- Full position exit
- Record: -₹300 loss
- Cooldown: 300 seconds (5 min)
- Update: consecutive_losses++
- Check: If 2 consecutive → 900s cooldown
```

**Profit Target 1 (+₹150):**
```
- Exit 50% position
- Move SL to breakeven
- Record: +₹75 realized
- Continue: Monitor for TP2
- Trailing: Optional after TP1
```

**Profit Target 2 (+₹300):**
```
- Exit remaining 50%
- Record: +₹150 additional (total +₹225)
- Cooldown: 180 seconds (3 min)
- Reset: consecutive_losses = 0
```

**Greeks Exit:**
```
Exit if ANY condition:
- Delta < 0.25 or > 0.75
- Gamma > 0.15
- Theta/sec > 0.05%

Reason: Option characteristics degraded
Cooldown: 180 seconds
```

**Time Exit:**
```
Exit at max duration:
- NORMAL: 45 minutes
- EXPIRY: 30 minutes
- MONTHLY: 20 minutes
- EVENT: 15 minutes

Reason: Avoid overnight / extended exposure
Cooldown: 180 seconds
```

---

## 📊 Expected Performance

### Daily Targets
```
Conservative:         ₹200-300 (0.7-1.0%)
Moderate:             ₹300-500 (1.0-1.7%)
Aggressive:           ₹500-800 (1.7-2.7%)

Recommendation: Target ₹300-400 daily (1-1.3%)
```

### Weekly Targets
```
Conservative:         ₹1,000-1,500 (3-5%)
Moderate:             ₹1,500-2,500 (5-8%)
Aggressive:           ₹2,500-4,000 (8-13%)

Recommendation: Target ₹1,500-2,000 weekly (5-7%)
```

### Monthly Targets
```
Conservative:         ₹4,000-6,000 (13-20%)
Moderate:             ₹6,000-10,000 (20-33%)
Aggressive:           ₹10,000-15,000 (33-50%)

Recommendation: Target ₹6,000-8,000 monthly (20-27%)
```

### Performance Metrics
```
Win Rate:             60-70% (aim for 65%)
Average Win:          ₹200-250
Average Loss:         ₹250-300
Profit Factor:        1.5-2.0
Max Drawdown:         ₹900 (kill switch)
Recovery Time:        1-3 days after drawdown
```

---

## ⚠️ Risk Scenarios

### Scenario 1: Consecutive Losses
```
Trade 1: -₹300 (SL hit) → 5 min cooldown
Trade 2: -₹300 (SL hit) → 15 min cooldown
Total Loss: -₹600

Action:
- 15 minute mandatory cooldown
- Review strategy
- Consider stopping for the day
- Remaining buffer: ₹300 before kill switch
```

### Scenario 2: Kill Switch Hit
```
Loss Accumulation: -₹900 (3 SLs or equivalent)

System Response:
- Automatic KILL_SWITCH state
- Force close all positions
- No new trades allowed
- Daily summary generated

Recovery:
- Review logs/trades
- Identify pattern
- Wait for next day
- Start fresh with reset
```

### Scenario 3: Winning Streak
```
Trade 1: +₹225 (TP1+TP2)
Trade 2: +₹225 (TP1+TP2)
Trade 3: +₹225 (TP1+TP2)
Total Profit: +₹675

Risk:
- Overconfidence
- Increasing position size
- Ignoring rules

Action:
- Stick to ₹300 risk
- Maintain discipline
- Book profits
- Stop at daily limit
```

---

## 🎯 Success Factors

### Critical Do's
```
✓ Follow entry signals strictly
✓ Respect stop losses (no averaging)
✓ Take partial profits at TP1
✓ Maintain trade journal daily
✓ Review logs weekly
✓ Adjust Greeks for day-type
✓ Respect cooldown periods
✓ Honor kill switch
```

### Critical Don'ts
```
✗ Override SL mentally
✗ Trade outside sessions
✗ Increase risk after losses
✗ Ignore consecutive loss cooldown
✗ Trade without Greeks check
✗ Exceed daily trade limit
✗ Bypass kill switch
✗ Revenge trading
```

---

## 📝 Daily Checklist

### Pre-Market (Before 9:15 AM)
```
[ ] Check bot_config.json loaded correctly
[ ] Verify Angel One credentials working
[ ] Confirm day type (NORMAL/EXPIRY/EVENT)
[ ] Review previous day's summary
[ ] Check market holidays/events
[ ] Ensure logs folder accessible
[ ] Test paper trading first
```

### During Market (9:15-15:30)
```
[ ] Monitor state transitions
[ ] Watch for kill switch triggers
[ ] Review each trade entry/exit
[ ] Check PnL after each trade
[ ] Verify cooldown periods respected
[ ] Monitor tick latency
[ ] Track consecutive losses
```

### Post-Market (After 15:30)
```
[ ] Review daily summary
[ ] Analyze winning/losing trades
[ ] Calculate actual vs expected PnL
[ ] Identify pattern improvements
[ ] Update trade journal
[ ] Backup logs
[ ] Plan adjustments if needed
```

---

## 🔧 Tuning Guidelines

### If Win Rate < 50%
```
Problem: Entry signals poor quality
Actions:
- Review PTQ logic
- Tighten Greeks filters
- Avoid choppy sessions
- Focus on trending moves
```

### If Average Loss > ₹300
```
Problem: SL too wide or not respected
Actions:
- Reduce SL to ₹250
- Check slippage
- Improve order execution
- Exit faster on adverse moves
```

### If Frequent Kill Switches
```
Problem: Too aggressive or poor market
Actions:
- Reduce to ₹200 risk/trade
- Lower kill switch to ₹600
- Reduce max trades to 8/day
- Avoid choppy markets
```

### If Few Trades Taken
```
Problem: Filters too strict
Actions:
- Widen Delta range (0.30-0.65)
- Increase Gamma limit (0.08-0.10)
- Add more trading sessions
- Review entry logic
```

---

## 📈 Growth Path

### Phase 1: Survival (Month 1-2)
```
Goal: Don't lose money
Capital: ₹30,000
Risk: ₹200-300/trade
Target: Break-even to +10%
Focus: Learn patterns, respect rules
```

### Phase 2: Consistency (Month 3-4)
```
Goal: Consistent positive returns
Capital: ₹30,000-35,000
Risk: ₹300/trade
Target: +15-25%
Focus: Optimize entry timing
```

### Phase 3: Scaling (Month 5-6)
```
Goal: Scale with discipline
Capital: ₹35,000-40,000
Risk: ₹300-400/trade
Target: +25-40%
Focus: Fine-tune Greeks, add strategies
```

### Phase 4: Compounding (Month 7+)
```
Goal: Compound gains
Capital: ₹40,000+
Risk: 1% of current capital
Target: +50%+ annualized
Focus: Risk management mastery
```

---

## 🔐 Backup & Recovery

### Configuration Backup
```bash
# Backup config
cp config/bot_config.json config/bot_config_backup_$(date +%Y%m%d).json

# Restore config
cp config/bot_config_backup_YYYYMMDD.json config/bot_config.json
```

### Logs Backup
```bash
# Archive old logs
tar -czf logs_backup_$(date +%Y%m%d).tar.gz logs/

# Keep last 30 days only
find logs/ -type d -mtime +30 -exec rm -rf {} +
```

### Disaster Recovery
```
1. Bot crash → Check error.log → Restart
2. Data corruption → Restore config backup
3. Wrong orders → Manual broker intervention
4. Kill switch → Wait for next day
5. System failure → Paper trade until stable
```

---

## 📞 Support & Resources

### Log Files Location
```
logs/YYYY-MM-DD/
├── bot.log         → Full execution log
├── trades.log      → Entry/exit log
├── trades.json     → Structured data
├── states.log      → State transitions
├── errors.log      → Error tracking
└── summary.json    → Daily metrics
```

### Configuration File
```
config/bot_config.json → All parameters
```

### Key Metrics to Track
```
- Win rate (target: 60-70%)
- Average win/loss ratio
- Profit factor
- Max drawdown
- Recovery time
- Sharpe ratio (if calculating)
```

---

**Last Updated:** January 2026  
**Configuration Version:** 2.0  
**Author:** PTQ Scalping Bot Team  
**Status:** Production-ready for ₹30K capital

---

*"হারের সংখ্যা কম রাখো, profit এমনিতেই আসবে"*

*"Keep losses small, profits will follow naturally"*
