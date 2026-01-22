"""
PTQ Scalping Bot - Trade Analytics & Reporting
Comprehensive analysis of trading performance
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
import statistics


class TradeAnalytics:
    """Analyze trading performance from log data"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
    
    def load_trades(self, date: str = None) -> List[Dict]:
        """Load trades from JSON log file"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        trades_file = os.path.join(self.log_dir, date, "trades.json")
        
        if not os.path.exists(trades_file):
            return []
        
        trades = []
        with open(trades_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return trades
    
    def get_paired_trades(self, trades: List[Dict]) -> List[Dict]:
        """Pair entry and exit trades"""
        entries = {}
        paired = []
        
        for trade in trades:
            if trade['event'] == 'ENTRY':
                entries[trade['order_id']] = trade
            elif trade['event'] == 'EXIT':
                order_id = trade['order_id']
                if order_id in entries:
                    entry = entries[order_id]
                    paired.append({
                        'order_id': order_id,
                        'symbol': entry.get('symbol', ''),
                        'side': entry.get('side', 'BUY'),
                        'qty': entry.get('qty', 1),
                        'entry_time': entry['timestamp'],
                        'entry_price': entry['entry_price'],
                        'entry_reason': entry.get('entry_reason', ''),
                        'exit_time': trade['timestamp'],
                        'exit_price': trade['exit_price'],
                        'exit_reason': trade['exit_reason'],
                        'pnl': trade['pnl'],
                        'pnl_pct': trade['pnl_pct'],
                        'hold_time_sec': trade['hold_time_sec'],
                        'greeks': entry.get('greeks', {})
                    })
                    del entries[order_id]
        
        return paired
    
    def calculate_metrics(self, paired_trades: List[Dict]) -> Dict[str, Any]:
        """Calculate comprehensive trading metrics"""
        if not paired_trades:
            return self._empty_metrics()
        
        # Basic counts
        total_trades = len(paired_trades)
        winners = [t for t in paired_trades if t['pnl'] > 0]
        losers = [t for t in paired_trades if t['pnl'] < 0]
        breakeven = [t for t in paired_trades if t['pnl'] == 0]
        
        # PnL metrics
        total_pnl = sum(t['pnl'] for t in paired_trades)
        pnl_list = [t['pnl'] for t in paired_trades]
        
        # Win metrics
        win_pnls = [t['pnl'] for t in winners]
        loss_pnls = [abs(t['pnl']) for t in losers]
        
        avg_win = statistics.mean(win_pnls) if win_pnls else 0
        avg_loss = statistics.mean(loss_pnls) if loss_pnls else 0
        max_win = max(win_pnls) if win_pnls else 0
        max_loss = max(loss_pnls) if loss_pnls else 0
        
        # Win rate
        win_rate = (len(winners) / total_trades * 100) if total_trades > 0 else 0
        
        # Profit factor
        gross_profit = sum(win_pnls) if win_pnls else 0
        gross_loss = sum(loss_pnls) if loss_pnls else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Risk-reward ratio
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        # Expectancy (average profit per trade)
        expectancy = total_pnl / total_trades if total_trades > 0 else 0
        
        # Hold time analysis
        hold_times = [t['hold_time_sec'] for t in paired_trades]
        avg_hold_time = statistics.mean(hold_times) if hold_times else 0
        
        win_hold_times = [t['hold_time_sec'] for t in winners]
        loss_hold_times = [t['hold_time_sec'] for t in losers]
        avg_win_hold = statistics.mean(win_hold_times) if win_hold_times else 0
        avg_loss_hold = statistics.mean(loss_hold_times) if loss_hold_times else 0
        
        # Drawdown calculation
        cumulative_pnl = []
        running_pnl = 0
        peak_pnl = 0
        max_drawdown = 0
        
        for trade in paired_trades:
            running_pnl += trade['pnl']
            cumulative_pnl.append(running_pnl)
            
            if running_pnl > peak_pnl:
                peak_pnl = running_pnl
            
            drawdown = peak_pnl - running_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Consecutive wins/losses
        max_consec_wins = self._max_consecutive(paired_trades, win=True)
        max_consec_losses = self._max_consecutive(paired_trades, win=False)
        
        # Exit reason analysis
        exit_reasons = defaultdict(int)
        for trade in paired_trades:
            reason = self._categorize_exit_reason(trade['exit_reason'])
            exit_reasons[reason] += 1
        
        # Time-based analysis
        hourly_pnl = self._hourly_analysis(paired_trades)
        
        return {
            'summary': {
                'total_trades': total_trades,
                'winners': len(winners),
                'losers': len(losers),
                'breakeven': len(breakeven),
                'win_rate': round(win_rate, 2),
                'profit_factor': round(profit_factor, 2),
                'risk_reward': round(risk_reward, 2),
                'expectancy': round(expectancy, 2)
            },
            'pnl': {
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'max_win': round(max_win, 2),
                'max_loss': round(max_loss, 2),
                'gross_profit': round(gross_profit, 2),
                'gross_loss': round(gross_loss, 2),
                'max_drawdown': round(max_drawdown, 2)
            },
            'time': {
                'avg_hold_time_sec': round(avg_hold_time, 1),
                'avg_win_hold_sec': round(avg_win_hold, 1),
                'avg_loss_hold_sec': round(avg_loss_hold, 1)
            },
            'streaks': {
                'max_consecutive_wins': max_consec_wins,
                'max_consecutive_losses': max_consec_losses
            },
            'exit_reasons': dict(exit_reasons),
            'hourly_pnl': hourly_pnl,
            'cumulative_pnl': cumulative_pnl,
            'trades': paired_trades
        }
    
    def _empty_metrics(self) -> Dict:
        """Return empty metrics structure"""
        return {
            'summary': {
                'total_trades': 0, 'winners': 0, 'losers': 0,
                'breakeven': 0, 'win_rate': 0, 'profit_factor': 0,
                'risk_reward': 0, 'expectancy': 0
            },
            'pnl': {
                'total_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'max_win': 0, 'max_loss': 0, 'gross_profit': 0,
                'gross_loss': 0, 'max_drawdown': 0
            },
            'time': {
                'avg_hold_time_sec': 0, 'avg_win_hold_sec': 0, 'avg_loss_hold_sec': 0
            },
            'streaks': {'max_consecutive_wins': 0, 'max_consecutive_losses': 0},
            'exit_reasons': {},
            'hourly_pnl': {},
            'cumulative_pnl': [],
            'trades': []
        }
    
    def _max_consecutive(self, trades: List[Dict], win: bool) -> int:
        """Calculate max consecutive wins or losses"""
        max_count = 0
        current_count = 0
        
        for trade in trades:
            is_win = trade['pnl'] > 0
            if (win and is_win) or (not win and not is_win and trade['pnl'] != 0):
                current_count += 1
                max_count = max(max_count, current_count)
            else:
                current_count = 0
        
        return max_count
    
    def _categorize_exit_reason(self, reason: str) -> str:
        """Categorize exit reason into groups"""
        reason_lower = reason.lower()
        
        if 'stop loss' in reason_lower or 'sl' in reason_lower:
            return 'Stop Loss'
        elif 'tp-1' in reason_lower or 'tp1' in reason_lower:
            return 'TP-1 (Partial)'
        elif 'tp-2' in reason_lower or 'tp2' in reason_lower:
            return 'TP-2 (Partial)'
        elif 'tp-3' in reason_lower or 'full exit' in reason_lower:
            return 'TP-3 (Full)'
        elif 'trailing' in reason_lower:
            return 'Trailing Stop'
        elif 'breakeven' in reason_lower:
            return 'Breakeven'
        elif 'time' in reason_lower:
            return 'Time Exit'
        elif 'delta' in reason_lower or 'gamma' in reason_lower or 'theta' in reason_lower:
            return 'Greeks Exit'
        elif 'kill' in reason_lower:
            return 'Kill Switch'
        elif 'manual' in reason_lower:
            return 'Manual'
        elif 'close' in reason_lower:
            return 'Market Close'
        else:
            return 'Other'
    
    def _hourly_analysis(self, trades: List[Dict]) -> Dict[str, Dict]:
        """Analyze performance by hour"""
        hourly = defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0})
        
        for trade in trades:
            try:
                hour = trade['entry_time'].split(' ')[1].split(':')[0]
                hourly[hour]['trades'] += 1
                hourly[hour]['pnl'] += trade['pnl']
                if trade['pnl'] > 0:
                    hourly[hour]['wins'] += 1
                elif trade['pnl'] < 0:
                    hourly[hour]['losses'] += 1
            except:
                continue
        
        # Calculate win rate per hour
        for hour in hourly:
            total = hourly[hour]['trades']
            wins = hourly[hour]['wins']
            hourly[hour]['win_rate'] = round(wins / total * 100, 1) if total > 0 else 0
            hourly[hour]['pnl'] = round(hourly[hour]['pnl'], 2)
        
        return dict(hourly)
    
    def generate_report(self, date: str = None) -> str:
        """Generate a formatted text report"""
        trades = self.load_trades(date)
        paired = self.get_paired_trades(trades)
        metrics = self.calculate_metrics(paired)
        
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        report = []
        report.append("=" * 70)
        report.append(f"📊 PTQ SCALPING BOT - TRADING REPORT")
        report.append(f"📅 Date: {date}")
        report.append("=" * 70)
        report.append("")
        
        # Summary
        s = metrics['summary']
        report.append("📈 PERFORMANCE SUMMARY")
        report.append("-" * 40)
        report.append(f"Total Trades:      {s['total_trades']}")
        report.append(f"Winners:           {s['winners']} ({s['win_rate']}%)")
        report.append(f"Losers:            {s['losers']}")
        report.append(f"Breakeven:         {s['breakeven']}")
        report.append(f"Profit Factor:     {s['profit_factor']}")
        report.append(f"Risk/Reward:       {s['risk_reward']}")
        report.append(f"Expectancy:        ₹{s['expectancy']}/trade")
        report.append("")
        
        # PnL
        p = metrics['pnl']
        report.append("💰 PROFIT & LOSS")
        report.append("-" * 40)
        report.append(f"Total PnL:         ₹{p['total_pnl']:+,.2f}")
        report.append(f"Gross Profit:      ₹{p['gross_profit']:,.2f}")
        report.append(f"Gross Loss:        ₹{p['gross_loss']:,.2f}")
        report.append(f"Max Drawdown:      ₹{p['max_drawdown']:,.2f}")
        report.append(f"Avg Win:           ₹{p['avg_win']:,.2f}")
        report.append(f"Avg Loss:          ₹{p['avg_loss']:,.2f}")
        report.append(f"Best Trade:        ₹{p['max_win']:,.2f}")
        report.append(f"Worst Trade:       ₹{p['max_loss']:,.2f}")
        report.append("")
        
        # Time
        t = metrics['time']
        report.append("⏱️ HOLD TIME ANALYSIS")
        report.append("-" * 40)
        report.append(f"Avg Hold Time:     {t['avg_hold_time_sec']:.1f}s ({t['avg_hold_time_sec']/60:.1f}min)")
        report.append(f"Avg Win Hold:      {t['avg_win_hold_sec']:.1f}s")
        report.append(f"Avg Loss Hold:     {t['avg_loss_hold_sec']:.1f}s")
        report.append("")
        
        # Streaks
        st = metrics['streaks']
        report.append("🔥 STREAKS")
        report.append("-" * 40)
        report.append(f"Max Win Streak:    {st['max_consecutive_wins']}")
        report.append(f"Max Loss Streak:   {st['max_consecutive_losses']}")
        report.append("")
        
        # Exit reasons
        report.append("🚪 EXIT REASON BREAKDOWN")
        report.append("-" * 40)
        for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
            pct = count / s['total_trades'] * 100 if s['total_trades'] > 0 else 0
            report.append(f"  {reason:20} {count:3} ({pct:.1f}%)")
        report.append("")
        
        # Hourly analysis
        if metrics['hourly_pnl']:
            report.append("📊 HOURLY BREAKDOWN")
            report.append("-" * 40)
            report.append(f"{'Hour':<6} {'Trades':>7} {'PnL':>12} {'Win%':>8}")
            for hour in sorted(metrics['hourly_pnl'].keys()):
                h = metrics['hourly_pnl'][hour]
                report.append(f"{hour}:00  {h['trades']:>7} {h['pnl']:>+12.2f} {h['win_rate']:>7.1f}%")
            report.append("")
        
        # Trade list
        report.append("📝 TRADE DETAILS")
        report.append("-" * 70)
        report.append(f"{'#':<4} {'Time':<12} {'Entry':>8} {'Exit':>8} {'PnL':>10} {'Hold':>8} {'Reason'}")
        report.append("-" * 70)
        
        for i, trade in enumerate(paired, 1):
            entry_time = trade['entry_time'].split(' ')[1][:8]
            pnl = trade['pnl']
            pnl_str = f"₹{pnl:+.2f}"
            hold = f"{trade['hold_time_sec']:.1f}s"
            reason = trade['exit_reason'][:25] + "..." if len(trade['exit_reason']) > 25 else trade['exit_reason']
            
            report.append(
                f"{i:<4} {entry_time:<12} {trade['entry_price']:>8.2f} "
                f"{trade['exit_price']:>8.2f} {pnl_str:>10} {hold:>8} {reason}"
            )
        
        report.append("")
        report.append("=" * 70)
        report.append(f"Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def save_report(self, date: str = None, format: str = 'both') -> str:
        """Save report to file"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        trades = self.load_trades(date)
        paired = self.get_paired_trades(trades)
        metrics = self.calculate_metrics(paired)
        
        report_dir = os.path.join(self.log_dir, date)
        os.makedirs(report_dir, exist_ok=True)
        
        files_saved = []
        
        # Save JSON metrics
        if format in ['json', 'both']:
            json_file = os.path.join(report_dir, "analytics.json")
            # Remove trades from metrics to avoid duplication
            metrics_for_json = {k: v for k, v in metrics.items() if k != 'trades'}
            with open(json_file, 'w') as f:
                json.dump(metrics_for_json, f, indent=2)
            files_saved.append(json_file)
        
        # Save text report
        if format in ['txt', 'both']:
            txt_file = os.path.join(report_dir, "report.txt")
            report = self.generate_report(date)
            with open(txt_file, 'w') as f:
                f.write(report)
            files_saved.append(txt_file)
        
        return files_saved


def analyze_today():
    """Quick function to analyze today's trades"""
    analytics = TradeAnalytics()
    report = analytics.generate_report()
    print(report)
    
    # Save files
    files = analytics.save_report()
    print(f"\n📁 Reports saved to: {files}")
    
    return analytics


if __name__ == "__main__":
    analyze_today()
