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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


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
    signal_details: Dict = field(default_factory=dict)


@dataclass  
class BacktestResult:
    """Backtest results summary"""
    start_date: str
    end_date: str
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
                 sl_points: float = 6,
                 tp_points: float = 12,
                 lot_size: int = 65,
                 max_trades_per_day: int = 15,
                 commission_per_trade: float = 40,  # ₹40 per order (both sides)
                 slippage_pct: float = 0.1,  # 0.1% slippage
                 trailing_sl_enabled: bool = True,
                 trailing_activation_points: float = 5,  # Activate after 5pt move
                 trailing_step_points: float = 2):  # Trail every 2pt step
        
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.sl_points = sl_points
        self.tp_points = tp_points
        self.lot_size = lot_size
        self.max_trades_per_day = max_trades_per_day
        self.commission = commission_per_trade
        self.slippage_pct = slippage_pct
        self.trailing_sl_enabled = trailing_sl_enabled
        self.trailing_activation_points = trailing_activation_points
        self.trailing_step_points = trailing_step_points
        
        # State
        self.trades: List[BacktestTrade] = []
        self.current_trade: Optional[BacktestTrade] = None
        self.trade_count = 0
        self.daily_trades = 0
        self.current_date = None
        self._trade_high_water: float = 0.0  # Track best price in current trade for TSL
        
        # Equity tracking
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.peak_equity = initial_capital
        self.max_drawdown = 0.0
        
        # Strategy instance
        self._strategy = None
    
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
    
    def _check_sl_tp(self, current_price: float) -> Tuple[bool, str, float]:
        """
        Check if SL, TSL, or TP is hit for current trade.
        Includes trailing stop loss simulation.
        Returns: (should_exit, exit_reason, exit_price)
        """
        if not self.current_trade:
            return False, '', 0.0
        
        trade = self.current_trade
        
        # Update high-water mark for trailing SL
        if current_price > self._trade_high_water:
            self._trade_high_water = current_price
        
        # Fixed SL hit
        if current_price <= trade.sl_price:
            return True, 'SL_HIT', trade.sl_price
        
        # Fixed TP hit
        if current_price >= trade.tp_price:
            return True, 'TP_HIT', trade.tp_price
        
        # Trailing Stop Loss check
        if self.trailing_sl_enabled:
            move_from_entry = self._trade_high_water - trade.entry_price
            if move_from_entry >= self.trailing_activation_points:
                # Calculate trailing SL level: high-water minus step buffer
                trailing_sl = self._trade_high_water - self.trailing_step_points
                # Only trail upward (trailing_sl must be above original SL)
                if trailing_sl > trade.sl_price and current_price <= trailing_sl:
                    return True, 'TRAILING_SL', trailing_sl
        
        return False, '', 0.0
    
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
        
        current_price = candle.get('close', candle.get('ltp', 100))
        
        # Check existing position first
        if self.current_trade:
            should_exit, exit_reason, exit_price = self._check_sl_tp(current_price)
            
            if should_exit:
                return self._exit_trade(timestamp, exit_price, exit_reason)
        
        # Check for new entry signal (if no position and under daily limit)
        if self.current_trade is None and self.daily_trades < self.max_trades_per_day:
            strategy = self._get_strategy()
            signal, direction, confidence, details = strategy.generate_signal(ticks_history)
            
            if signal == 1 and confidence >= 70:  # Min confidence threshold
                return self._enter_trade(timestamp, current_price, direction, confidence, details)
        
        return None
    
    def _enter_trade(self, timestamp: datetime, price: float, direction: str, 
                     confidence: int, details: Dict) -> Optional[Dict]:
        """Enter a new trade"""
        entry_price = self._apply_slippage(price, 'BUY')
        
        self.trade_count += 1
        self.daily_trades += 1
        
        self.current_trade = BacktestTrade(
            trade_id=self.trade_count,
            entry_time=timestamp,
            direction=direction,
            entry_price=entry_price,
            qty=self.lot_size,
            sl_price=entry_price - self.sl_points,
            tp_price=entry_price + self.tp_points,
            signal_details={'confidence': confidence, **details}
        )
        self._trade_high_water = entry_price  # Reset high-water for new trade
        
        # Apply entry commission
        self.current_capital -= self.commission
        
        return None  # Trade not complete yet
    
    def _exit_trade(self, timestamp: datetime, exit_price: float, 
                    exit_reason: str) -> Optional[Dict]:
        """Exit current trade and calculate P&L"""
        trade = self.current_trade
        if not trade:
            return None
        
        # Apply slippage
        actual_exit = self._apply_slippage(exit_price, 'SELL')
        
        # Calculate P&L
        price_diff = actual_exit - trade.entry_price
        pnl = price_diff * trade.qty
        
        # Apply exit commission
        pnl -= self.commission
        
        # Update trade record
        trade.exit_time = timestamp
        trade.exit_price = actual_exit
        trade.exit_reason = exit_reason
        trade.pnl = pnl
        
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
        self.trades.append(trade)
        self.current_trade = None
        
        return {
            'trade_id': trade.trade_id,
            'timestamp': timestamp,
            'direction': trade.direction,
            'entry': trade.entry_price,
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
        print(f"   Capital: ₹{self.initial_capital:,.0f} | SL: {self.sl_points}pts | TP: {self.tp_points}pts")
        
        # Process candles
        ticks_history = []
        for i, candle in enumerate(historical_data):
            # Build tick history (last 60 candles for indicators)
            tick = {
                'ltp': candle.get('close', 100),
                'spot_price': candle.get('spot_price', candle.get('close', 100) * 100),
                'volume': candle.get('volume', 10000),
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
                last_candle.get('close', 100),
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
        
        start_date = self.trades[0].entry_time.strftime('%Y-%m-%d') if self.trades else ''
        end_date = self.trades[-1].exit_time.strftime('%Y-%m-%d') if self.trades and self.trades[-1].exit_time else ''
        
        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
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
                           'entry_price', 'exit_price', 'qty', 'pnl', 'exit_reason'])
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
                    trade.exit_reason
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
            candle = {
                'timestamp': datetime.fromisoformat(row['timestamp']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': int(row.get('volume', 10000)),
                'spot_price': float(row.get('spot_price', float(row['close']) * 100))
            }
            data.append(candle)
    return data


# CLI Entry point
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='PTQ Scalping Bot Backtester')
    parser.add_argument('--data', type=str, required=True, help='Path to historical data CSV')
    parser.add_argument('--capital', type=float, default=30000, help='Initial capital')
    parser.add_argument('--sl', type=float, default=6, help='Stop loss points')
    parser.add_argument('--tp', type=float, default=12, help='Take profit points')
    parser.add_argument('--output', type=str, default='logs/backtest', help='Output directory')
    
    args = parser.parse_args()
    
    # Load data
    print(f"📂 Loading historical data from {args.data}...")
    historical_data = load_historical_data(args.data)
    print(f"   Loaded {len(historical_data)} candles")
    
    # Run backtest
    backtester = Backtester(
        initial_capital=args.capital,
        sl_points=args.sl,
        tp_points=args.tp
    )
    result = backtester.run_backtest(historical_data)
    
    # Export results
    backtester.export_results(result, args.output)
