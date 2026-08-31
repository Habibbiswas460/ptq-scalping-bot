"""
PTQ Scalping Bot - Backtest Framework v3.4
==========================================
Historical backtesting for SMART SCALP v3.4 strategy.

Features:
- 5-minute candle replay
- Tick-level simulation
- Performance metrics (win rate, profit factor, drawdown)
- Export results to CSV

Usage:
    python -m core.backtest --start 2024-01-01 --end 2024-03-01 --capital 30000
"""

import os
import json
import csv
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from core.runtime import runtime_state
from core.engines import exit_engine
from core.engines.exit_engine import check_exit_conditions, HARD_SL_POINTS, TP_POINTS_FIXED
from core.engines.state_machine import _calculate_rsi
from utils.greeks import GreeksCalculator


@dataclass
class BacktestTrade:
    """Single backtest trade record"""
    trade_id: int
    entry_time: datetime
    exit_time: Optional[datetime] = None
    direction: str = 'CE'  # CE or PE
    entry_price: float = 0.0
    exit_price: float = 0.0
    qty: int = 65
    sl_price: float = 0.0
    tp_price: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ''
    mfe: float = 0.0
    mae: float = 0.0
    signal_details: Dict = field(default_factory=dict)


@dataclass  
class BacktestResult:
    """Backtest results summary"""
    start_date: str
    end_date: str
    first_trade_date: str
    last_trade_date: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float
    expectancy: float
    trades: List[BacktestTrade] = field(default_factory=list)


class Backtester:
    """
    Backtester for PTQ Scalping Bot strategies.
    Simulates historical trading with realistic execution.
    """
    
    def __init__(self,
                 initial_capital: float = 30000,
                 lot_size: int = 65,
                 max_trades_per_day: int = 15,
                 commission_per_trade: float = 40,  # ₹40 round-trip brokerage/charges
                 slippage_pct: float = 0.1,  # 0.1% slippage
                 day_type: str = "NORMAL",
                 default_iv: float = 0.20,
                 default_tte_sec: float = 3 * 24 * 3600,  # 3-day fallback; historical OHLC has no real expiry date
                 use_position_size_engine: bool = False,
                 position_size_risk_budget_pct: float = 0.02,
                 position_size_daily_cap_pct: Optional[float] = None):

        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.lot_size = lot_size
        self.max_trades_per_day = max_trades_per_day
        self.commission_round_trip = commission_per_trade
        self.commission_per_side = commission_per_trade / 2.0
        self.slippage_pct = slippage_pct
        # Exit logic itself (SL/TP/trailing/breakeven/RSI/greeks/time) is no
        # longer configurable here — it's delegated to
        # core.engines.exit_engine.check_exit_conditions(), the exact function
        # the live bot uses, sourced from the same config/constants.py +
        # .env as live (see findings.md §2.1). This is intentional: a
        # backtest with its own separate exit rules couldn't tell you how the
        # real exit logic would have performed historically.
        self.day_type = day_type
        self.default_iv = default_iv
        self.default_tte_sec = default_tte_sec
        self.use_position_size_engine = use_position_size_engine
        self.position_size_risk_budget_pct = position_size_risk_budget_pct
        self.position_size_daily_cap_pct = position_size_daily_cap_pct

        # State
        self.trades: List[BacktestTrade] = []
        self.current_trade: Optional[Dict] = None  # dict shape expected by check_exit_conditions()
        self.trade_count = 0
        self.daily_trades = 0
        self.current_date = None
        
        # Equity tracking
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.peak_equity = initial_capital
        self.max_drawdown = 0.0
        
        # Strategy instance
        self._strategy = None
        self._position_size_engine = None
        if self.use_position_size_engine:
            from core.engines.position_size_engine import PositionSizeEngine
            engine_cfg = {}
            if self.position_size_daily_cap_pct is not None:
                engine_cfg = {
                    'safety_caps': {
                        'daily_risk_cap_pct': float(self.position_size_daily_cap_pct),
                    }
                }
            self._position_size_engine = PositionSizeEngine(config=engine_cfg)

        # Spot-to-option proxy state for spot-only datasets.
        self._spot_reference_price: Optional[float] = None
        self._option_reference_price: float = 180.0
        self._spot_to_option_delta: float = 0.08
        self._data_start_ts: Optional[datetime] = None
        self._data_end_ts: Optional[datetime] = None
    
    def _get_strategy(self):
        """Lazy load strategy to avoid circular imports"""
        if self._strategy is None:
            from strategies.smart_scalp_v3 import SmartScalpV3
            self._strategy = SmartScalpV3()
        return self._strategy
    
    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply realistic slippage to fill price.
        
        v3.4: Two-component model:
        1. Fixed spread cost: ₹0.25 per side (typical NIFTY option tick)
        2. Proportional slippage: 0.1% of price (market impact)
        This prevents backtest from showing inflated profits.
        """
        spread_cost = 0.25  # Minimum 1-tick spread cost per side
        proportional = price * (self.slippage_pct / 100)
        total_slip = spread_cost + proportional
        if side == 'BUY':
            return price + total_slip  # Worse fill for buys
        else:
            return price - total_slip  # Worse fill for sells

    def _resolve_option_price(self, candle: Dict) -> float:
        """Resolve tradable option-like price from candle data.

        If the input looks like a spot index series (e.g., close ~ 20,000+),
        derive a synthetic option premium stream so entry filters/SL/TP can operate.
        """
        close_price = float(candle.get('close', candle.get('ltp', 100)) or 100)
        explicit_option_price = candle.get('option_ltp')
        if explicit_option_price is not None:
            return max(5.0, float(explicit_option_price))

        # Option premium-like data normally remains in sub-1000 range.
        if close_price <= 1500:
            return max(5.0, close_price)

        spot_price = float(candle.get('spot_price', close_price) or close_price)
        if self._spot_reference_price is None:
            self._spot_reference_price = spot_price

        # Linear delta proxy to map spot moves into premium moves.
        implied_option = self._option_reference_price + (
            (spot_price - self._spot_reference_price) * self._spot_to_option_delta
        )
        return max(5.0, min(500.0, implied_option))
    
    def _build_greeks(self, spot_price: float, direction: str) -> Dict:
        """Synthesize BSM greeks from spot/strike/IV/TTE for the exit engine's
        greek_exit() check. Historical OHLC candles don't carry real option
        expiry/IV, so this uses the same ATM-strike-from-spot approximation
        and IV/TTE fallbacks the live exit path uses
        (exit_engine._validated_greeks_for_exit) when it can't reach the
        broker's own Greeks."""
        if spot_price <= 0:
            return {}
        strike = round(spot_price / 50.0) * 50
        option_type = 'PE' if direction == 'PE' else 'CE'
        tte_years = self.default_tte_sec / (365.25 * 24 * 3600)
        return GreeksCalculator.calculate(
            spot_price=spot_price,
            strike_price=strike,
            time_to_expiry=tte_years,
            volatility=self.default_iv,
            option_type=option_type,
        )

    def _check_exit(self, timestamp: datetime, current_price: float, spot_price: float, ticks_history: List[Dict]) -> Tuple[bool, str]:
        """Check exit conditions via the SAME check_exit_conditions() the live
        bot uses (core.engines.exit_engine), fed with a synthetic tick/greeks
        pair built from this candle. Returns (should_exit, exit_reason)."""
        if not self.current_trade:
            return False, ''

        trade = self.current_trade
        tick = {
            'ltp': current_price,
            'spot_price': spot_price,
            'iv': self.default_iv,
            'tte_sec': self.default_tte_sec,
        }
        greeks = self._build_greeks(spot_price, trade.get('direction', 'CE'))
        rsi = _calculate_rsi(ticks_history)

        # exit_engine's hold-time/market-close checks use datetime.now() live
        # (correct there — trades happen in real time). Replaying history
        # needs those checks anchored to the candle's own timestamp instead,
        # or every hold-time calculation would be measured against today's
        # real wall clock. See findings.md §2.1.
        exit_engine._clock_override = timestamp
        try:
            return check_exit_conditions(trade, tick, greeks, self.day_type, logger=None, rsi=rsi)
        finally:
            exit_engine._clock_override = None
    
    def process_candle(self, candle: Dict, ticks_history: List[Dict]) -> Optional[Dict]:
        """
        Process a single candle and generate signals/exits.
        
        Args:
            candle: OHLCV candle data
            ticks_history: Last N ticks for indicator calculation
        
        Returns:
            Trade result if trade completed, None otherwise
        """
        timestamp = candle.get('timestamp', datetime.now())
        
        # Reset daily counter on new day
        if self.current_date != timestamp.date():
            self.current_date = timestamp.date()
            self.daily_trades = 0
        
        current_price = self._resolve_option_price(candle)
        spot_price = float(candle.get('spot_price', candle.get('close', current_price)) or current_price)

        # Check existing position first
        if self.current_trade:
            should_exit, exit_reason = self._check_exit(timestamp, current_price, spot_price, ticks_history)

            if should_exit:
                return self._exit_trade(timestamp, current_price, exit_reason)

        # Check for new entry signal (if no position and under daily limit)
        if self.current_trade is None and self.daily_trades < self.max_trades_per_day:
            strategy = self._get_strategy()
            signal, direction, confidence, details = strategy.generate_signal(ticks_history)
            required_conf = int(getattr(strategy, 'min_confidence', 70) or 70)

            if signal == 1 and confidence >= required_conf:
                indicators = runtime_state.get_indicators()
                if not indicators:
                    indicators = strategy.calculate_indicators(ticks_history)
                entry_params = strategy.get_entry_params(direction, confidence, indicators)
                return self._enter_trade(timestamp, current_price, direction, confidence, details, entry_params)

        return None
    
    def _enter_trade(self, timestamp: datetime, price: float, direction: str,
                     confidence: int, details: Dict, entry_params: Dict) -> Optional[Dict]:
        """Enter a new trade"""
        entry_price = self._apply_slippage(price, 'BUY')

        # SL points here are only a position-sizing input (risk amount / SL
        # points), not an exit trigger — the actual exit decision comes
        # entirely from check_exit_conditions() in _check_exit(), same as live.
        sl_points = HARD_SL_POINTS
        qty = self.lot_size

        if self.use_position_size_engine and self._position_size_engine is not None:
            weighted_score = float(details.get('weighted_score', details.get('score', 0)) or 0)
            market_quality = float(details.get('market_quality_score', details.get('market_quality', 0)) or 0)
            regime = str(entry_params.get('regime', details.get('regime', 'UNKNOWN')) or 'UNKNOWN')
            allocation = self._position_size_engine.calculate(
                capital=self.current_capital,
                risk_budget={
                    # Provide explicit risk amount so backtest can scale position sizing
                    # even if strategy config clamps daily risk pct at a lower ceiling.
                    'remaining_risk_amount': self.current_capital * max(0.0, self.position_size_risk_budget_pct),
                    'daily_risk_budget_pct': self.position_size_risk_budget_pct,
                },
                weighted_score=weighted_score,
                confidence=confidence,
                market_quality=market_quality,
                regime=regime,
                volatility={'vix': 14.0},
                recovery_mode={'active': False},
                daily_loss_state={'loss_utilization': 0.0},
                sl_points=sl_points,
                lot_size=self.lot_size,
            )
            qty = int(allocation.get('position_size', 0) or 0)
            if qty <= 0:
                return None
            details = {**details, 'allocation': allocation}

        self.trade_count += 1
        self.daily_trades += 1

        # Dict shape expected by check_exit_conditions()/check_hard_sl() —
        # mutated in place with price_diff/current_pnl/mfe_inr/mae_inr/
        # current_tsl/tsl_status/etc. as the trade progresses.
        self.current_trade = {
            'trade_id': self.trade_count,
            'entry_time': timestamp,
            'direction': direction,
            'side': 'BUY',
            'entry_price': entry_price,
            'qty': qty,
            'signal_details': {'confidence': confidence, **details},
        }

        # Charge half the round-trip cost at entry and half at exit.
        self.current_capital -= self.commission_per_side

        return None  # Trade not complete yet
    
    def _exit_trade(self, timestamp: datetime, exit_price: float, 
                    exit_reason: str) -> Optional[Dict]:
        """Exit current trade and calculate P&L"""
        trade = self.current_trade
        if not trade:
            return None

        entry_price = trade['entry_price']
        qty = trade['qty']

        # Apply slippage. The exit DECISION (when/why) comes from
        # check_exit_conditions(); the actual fill price/pnl is still
        # backtest's own execution-cost model — mirroring how live keeps
        # exit_engine's decision separate from broker.py's real fill price.
        actual_exit = self._apply_slippage(exit_price, 'SELL')

        price_diff = actual_exit - entry_price
        pnl = price_diff * qty

        # Charge the remaining half of round-trip execution costs at exit.
        pnl -= self.commission_per_side

        record = BacktestTrade(
            trade_id=trade['trade_id'],
            entry_time=trade['entry_time'],
            exit_time=timestamp,
            direction=trade.get('direction', 'CE'),
            entry_price=entry_price,
            exit_price=actual_exit,
            qty=qty,
            sl_price=entry_price - HARD_SL_POINTS,
            tp_price=entry_price + TP_POINTS_FIXED,
            pnl=pnl,
            exit_reason=exit_reason,
            mfe=trade.get('mfe_inr', 0.0),
            mae=trade.get('mae_inr', 0.0),
            signal_details=trade.get('signal_details', {}),
        )

        # Update capital
        self.current_capital += pnl

        # Update equity tracking
        self.equity_curve.append((timestamp, self.current_capital))
        if self.current_capital > self.peak_equity:
            self.peak_equity = self.current_capital

        current_dd = self.peak_equity - self.current_capital
        if current_dd > self.max_drawdown:
            self.max_drawdown = current_dd

        # Record trade
        self.trades.append(record)
        self.current_trade = None

        return {
            'trade_id': record.trade_id,
            'timestamp': timestamp,
            'direction': record.direction,
            'entry': entry_price,
            'exit': actual_exit,
            'pnl': round(pnl, 2),
            'exit_reason': exit_reason
        }
    
    def run_backtest(self, historical_data: List[Dict]) -> BacktestResult:
        """
        Run backtest on historical candle data.
        
        Args:
            historical_data: List of OHLCV candles sorted by timestamp
        
        Returns:
            BacktestResult with performance metrics
        """
        print(f"🔬 Starting backtest with {len(historical_data)} candles...")
        print(f"   Capital: ₹{self.initial_capital:,.0f} | Exit logic: core.engines.exit_engine (live-parity) | Day type: {self.day_type}")

        if not historical_data:
            self._data_start_ts = None
            self._data_end_ts = None
            return self._calculate_results()

        self._data_start_ts = historical_data[0].get('timestamp')
        self._data_end_ts = historical_data[-1].get('timestamp')
        
        # Process candles
        ticks_history = []
        for i, candle in enumerate(historical_data):
            # Build tick history (last 60 candles for indicators)
            option_price = self._resolve_option_price(candle)
            spot_price = float(candle.get('spot_price', candle.get('close', 100)) or candle.get('close', 100))
            volume = int(candle.get('volume', 10000) or 0)
            if volume <= 0:
                # Spot historical files often carry zero volume; use a neutral fallback for MQ checks.
                volume = 10000
            # Create a realistic synthetic quote so spread quality checks can run.
            spread = max(0.1, option_price * 0.001)
            bid = max(0.05, option_price - (spread / 2.0))
            ask = option_price + (spread / 2.0)

            tick = {
                'ltp': option_price,
                'spot_price': spot_price,
                'bid': bid,
                'ask': ask,
                'spread_pct': ((ask - bid) / bid) * 100.0 if bid > 0 else 99.0,
                'volume': volume,
                'timestamp': candle.get('timestamp')
            }
            ticks_history.append(tick)
            if len(ticks_history) > 120:
                ticks_history = ticks_history[-120:]
            
            # Process candle
            self.process_candle(candle, ticks_history)
            
            # Progress
            if i % 1000 == 0 and i > 0:
                print(f"   Processed {i}/{len(historical_data)} candles...")
        
        # Force close any open position at end
        if self.current_trade:
            last_candle = historical_data[-1]
            self._exit_trade(
                last_candle.get('timestamp', datetime.now()),
                self._resolve_option_price(last_candle),
                'END_OF_DATA'
            )
        
        # Calculate results
        result = self._calculate_results()
        
        print(f"\n📊 Backtest Complete!")
        print(f"   Trades: {result.total_trades} | Win Rate: {result.win_rate:.1f}%")
        print(f"   P&L: ₹{result.total_pnl:,.2f} | Profit Factor: {result.profit_factor:.2f}")
        print(f"   Max DD: ₹{result.max_drawdown:,.0f} ({result.max_drawdown_pct:.1f}%)")
        
        return result
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate performance metrics"""
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        avg_win = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0
        
        expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss) if self.trades else 0
        
        max_dd_pct = (self.max_drawdown / self.peak_equity * 100) if self.peak_equity > 0 else 0
        
        # Simple Sharpe estimation (assuming daily returns)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev_eq = self.equity_curve[i-1][1]
                curr_eq = self.equity_curve[i][1]
                if prev_eq > 0:
                    returns.append((curr_eq - prev_eq) / prev_eq)
            
            if returns:
                avg_ret = sum(returns) / len(returns)
                if len(returns) > 1:
                    std_ret = (sum((r - avg_ret)**2 for r in returns) / (len(returns)-1)) ** 0.5
                    sharpe = (avg_ret / std_ret) * (252 ** 0.5) if std_ret > 0 else 0  # Annualized
                else:
                    sharpe = 0
            else:
                sharpe = 0
        else:
            sharpe = 0
        
        start_date = self._data_start_ts.strftime('%Y-%m-%d') if isinstance(self._data_start_ts, datetime) else ''
        end_date = self._data_end_ts.strftime('%Y-%m-%d') if isinstance(self._data_end_ts, datetime) else ''
        first_trade_date = self.trades[0].entry_time.strftime('%Y-%m-%d') if self.trades else ''
        last_trade_date = self.trades[-1].exit_time.strftime('%Y-%m-%d') if self.trades and self.trades[-1].exit_time else ''
        
        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            first_trade_date=first_trade_date,
            last_trade_date=last_trade_date,
            initial_capital=self.initial_capital,
            final_capital=self.current_capital,
            total_pnl=self.current_capital - self.initial_capital,
            total_trades=len(self.trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            profit_factor=profit_factor if profit_factor != float('inf') else 999.99,
            max_drawdown=self.max_drawdown,
            max_drawdown_pct=max_dd_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            sharpe_ratio=sharpe,
            expectancy=expectancy,
            trades=self.trades
        )
    
    def export_results(self, result: BacktestResult, output_dir: str = 'logs/backtest'):
        """Export backtest results to CSV and JSON"""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Export summary JSON
        summary = {
            'start_date': result.start_date,
            'end_date': result.end_date,
            'first_trade_date': result.first_trade_date,
            'last_trade_date': result.last_trade_date,
            'initial_capital': result.initial_capital,
            'final_capital': round(result.final_capital, 2),
            'total_pnl': round(result.total_pnl, 2),
            'total_trades': result.total_trades,
            'win_rate_pct': round(result.win_rate, 2),
            'profit_factor': round(result.profit_factor, 2),
            'max_drawdown': round(result.max_drawdown, 2),
            'max_drawdown_pct': round(result.max_drawdown_pct, 2),
            'sharpe_ratio': round(result.sharpe_ratio, 2),
            'expectancy': round(result.expectancy, 2)
        }
        
        with open(f'{output_dir}/summary_{timestamp}.json', 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Export trades CSV
        with open(f'{output_dir}/trades_{timestamp}.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['trade_id', 'entry_time', 'exit_time', 'direction',
                           'entry_price', 'exit_price', 'qty', 'pnl', 'exit_reason', 'mfe', 'mae'])
            for trade in result.trades:
                writer.writerow([
                    trade.trade_id,
                    trade.entry_time.isoformat() if trade.entry_time else '',
                    trade.exit_time.isoformat() if trade.exit_time else '',
                    trade.direction,
                    trade.entry_price,
                    trade.exit_price,
                    trade.qty,
                    round(trade.pnl, 2),
                    trade.exit_reason,
                    round(trade.mfe, 2),
                    round(trade.mae, 2),
                ])
        
        print(f"📁 Results exported to {output_dir}/")


def load_historical_data(filepath: str) -> List[Dict]:
    """
    Load historical data from CSV file.
    Expected columns: timestamp, open, high, low, close, volume
    """
    data = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            volume = int(row.get('volume', 10000) or 0)
            if volume <= 0:
                volume = 10000

            candle = {
                'timestamp': datetime.fromisoformat(row['timestamp']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': volume,
                'spot_price': float(row.get('spot_price', float(row['close'])))
            }
            data.append(candle)
    return data


# CLI Entry point
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='PTQ Scalping Bot Backtester')
    parser.add_argument('--data', type=str, required=True, help='Path to historical data CSV')
    parser.add_argument('--capital', type=float, default=30000, help='Initial capital')
    parser.add_argument('--day-type', type=str, default='NORMAL', help='Day type passed to the exit engine (NORMAL or EXPIRY)')
    parser.add_argument('--use-position-size-engine', action='store_true', help='Use PositionSizeEngine for dynamic quantity')
    parser.add_argument('--position-size-risk-budget-pct', type=float, default=0.02, help='Risk budget pct for position size engine (e.g. 0.02 = 2%%)')
    parser.add_argument('--position-size-daily-cap-pct', type=float, default=None, help='Override allocator daily risk cap pct for testing (e.g. 0.05)')
    parser.add_argument('--output', type=str, default='logs/backtest', help='Output directory')

    args = parser.parse_args()

    # Load data
    print(f"📂 Loading historical data from {args.data}...")
    historical_data = load_historical_data(args.data)
    print(f"   Loaded {len(historical_data)} candles")

    # Run backtest. SL/TP/trailing/breakeven/RSI/greeks/time-exit rules all
    # come from core.engines.exit_engine (same as live) — see the Backtester
    # docstring/comments for why this isn't a CLI-configurable knob anymore.
    backtester = Backtester(
        initial_capital=args.capital,
        day_type=args.day_type,
        use_position_size_engine=args.use_position_size_engine,
        position_size_risk_budget_pct=args.position_size_risk_budget_pct,
        position_size_daily_cap_pct=args.position_size_daily_cap_pct,
    )
    result = backtester.run_backtest(historical_data)
    
    # Export results
    backtester.export_results(result, args.output)
