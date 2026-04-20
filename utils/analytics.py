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
        parse_errors = 0
        with open(trades_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        parse_errors += 1
                        if parse_errors <= 3:  # Log first 3 errors only
                            print(f"[WARN] JSON parse error in {trades_file} line {line_num}: {e}")
                        continue
        if parse_errors > 3:
            print(f"[WARN] {parse_errors} total JSON parse errors in {trades_file}")
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


def analyze_period(days: int = 7):
    """Analyze trades over multiple days"""
    analytics = TradeAnalytics()
    
    # Collect trades from multiple days
    all_trades = []
    dates_analyzed = []
    
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trades = analytics.load_trades(date)
        if trades:
            paired = analytics.get_paired_trades(trades)
            all_trades.extend(paired)
            dates_analyzed.append(date)
    
    if not all_trades:
        print(f"📊 No trades found in the last {days} days")
        return None
    
    # Calculate aggregate metrics
    metrics = analytics.calculate_metrics(all_trades)
    
    # Print summary
    print("=" * 70)
    print(f"📊 PTQ SCALPING BOT - {days}-DAY ANALYSIS")
    print(f"📅 Period: {dates_analyzed[-1]} to {dates_analyzed[0]}")
    print(f"📆 Days with trades: {len(dates_analyzed)}")
    print("=" * 70)
    print("")
    
    s = metrics['summary']
    p = metrics['pnl']
    
    print("📈 PERFORMANCE SUMMARY")
    print("-" * 40)
    print(f"Total Trades:      {s['total_trades']}")
    print(f"Win Rate:          {s['win_rate']}%")
    print(f"Total PnL:         ₹{p['total_pnl']:+,.2f}")
    print(f"Avg PnL/Day:       ₹{p['total_pnl']/len(dates_analyzed):+,.2f}")
    print(f"Profit Factor:     {s['profit_factor']}")
    print(f"Max Drawdown:      ₹{p['max_drawdown']:,.2f}")
    print("")
    
    # Best/Worst hours
    hourly = metrics['hourly_pnl']
    if hourly:
        print("📊 BEST & WORST TRADING HOURS")
        print("-" * 40)
        sorted_hours = sorted(hourly.items(), key=lambda x: x[1]['pnl'], reverse=True)
        if sorted_hours:
            best = sorted_hours[0]
            worst = sorted_hours[-1]
            print(f"Best Hour:   {best[0]}:00 - PnL: ₹{best[1]['pnl']:+,.2f} ({best[1]['win_rate']}% win rate, {best[1]['trades']} trades)")
            print(f"Worst Hour:  {worst[0]}:00 - PnL: ₹{worst[1]['pnl']:+,.2f} ({worst[1]['win_rate']}% win rate, {worst[1]['trades']} trades)")
        print("")
    
    # Exit reason breakdown
    print("🚪 EXIT REASONS")
    print("-" * 40)
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        pct = count / s['total_trades'] * 100 if s['total_trades'] > 0 else 0
        print(f"  {reason:20} {count:3} ({pct:.1f}%)")
    print("")
    
    return metrics


def analyze_weekly():
    """Analyze last 7 days of trading"""
    return analyze_period(7)


def analyze_monthly():
    """Analyze last 30 days of trading"""
    return analyze_period(30)


def get_best_worst_hours(days: int = 30) -> Dict[str, Any]:
    """Find the best and worst trading hours based on historical data"""
    analytics = TradeAnalytics()
    
    # Collect all hourly data
    all_hourly = defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0, 'losses': 0})
    
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trades = analytics.load_trades(date)
        if trades:
            paired = analytics.get_paired_trades(trades)
            for trade in paired:
                try:
                    hour = trade['entry_time'].split(' ')[1].split(':')[0]
                    all_hourly[hour]['trades'] += 1
                    all_hourly[hour]['pnl'] += trade['pnl']
                    if trade['pnl'] > 0:
                        all_hourly[hour]['wins'] += 1
                    elif trade['pnl'] < 0:
                        all_hourly[hour]['losses'] += 1
                except:
                    continue
    
    # Calculate win rates
    result = {}
    for hour in all_hourly:
        total = all_hourly[hour]['trades']
        wins = all_hourly[hour]['wins']
        all_hourly[hour]['win_rate'] = round(wins / total * 100, 1) if total > 0 else 0
        all_hourly[hour]['avg_pnl'] = round(all_hourly[hour]['pnl'] / total, 2) if total > 0 else 0
        result[hour] = dict(all_hourly[hour])
    
    # Sort by profitability
    sorted_hours = sorted(result.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    return {
        'hourly_stats': result,
        'best_hours': sorted_hours[:3] if len(sorted_hours) >= 3 else sorted_hours,
        'worst_hours': sorted_hours[-3:] if len(sorted_hours) >= 3 else sorted_hours[::-1]
    }


def print_trading_calendar(days: int = 30):
    """Print a calendar view of trading days with PnL"""
    analytics = TradeAnalytics()
    
    print("=" * 70)
    print("📅 TRADING CALENDAR")
    print("=" * 70)
    print(f"{'Date':<12} {'Trades':>8} {'Wins':>6} {'Win%':>8} {'PnL':>12} {'Status'}")
    print("-" * 70)
    
    total_pnl = 0
    trading_days = 0
    winning_days = 0
    
    for i in range(days - 1, -1, -1):  # Oldest to newest
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trades = analytics.load_trades(date)
        
        if trades:
            paired = analytics.get_paired_trades(trades)
            if paired:
                trading_days += 1
                day_pnl = sum(t['pnl'] for t in paired)
                total_pnl += day_pnl
                wins = len([t for t in paired if t['pnl'] > 0])
                win_rate = wins / len(paired) * 100 if paired else 0
                
                if day_pnl > 0:
                    winning_days += 1
                    status = "🟢 PROFIT"
                elif day_pnl < 0:
                    status = "🔴 LOSS"
                else:
                    status = "⚪ EVEN"
                
                print(f"{date:<12} {len(paired):>8} {wins:>6} {win_rate:>7.1f}% {day_pnl:>+11.2f} {status}")
    
    print("-" * 70)
    day_win_rate = winning_days / trading_days * 100 if trading_days > 0 else 0
    print(f"{'TOTAL':<12} {trading_days:>8} days {winning_days:>6} win  {day_win_rate:>6.1f}% {total_pnl:>+11.2f}")
    print("=" * 70)


def interactive_analytics():
    """Interactive analytics menu"""
    while True:
        print("")
        print("=" * 50)
        print("📊 PTQ ANALYTICS MENU")
        print("=" * 50)
        print("  1. Today's Report")
        print("  2. Weekly Analysis (7 days)")
        print("  3. Monthly Analysis (30 days)")
        print("  4. Trading Calendar")
        print("  5. Best/Worst Hours")
        print("  6. Exit & Return")
        print("-" * 50)
        
        choice = input("Select option (1-6): ").strip()
        
        if choice == '1':
            analyze_today()
        elif choice == '2':
            analyze_weekly()
        elif choice == '3':
            analyze_monthly()
        elif choice == '4':
            print_trading_calendar()
        elif choice == '5':
            hours_data = get_best_worst_hours()
            print("\n📊 BEST TRADING HOURS (by total PnL):")
            for hour, stats in hours_data['best_hours']:
                print(f"  {hour}:00 - {stats['trades']} trades, ₹{stats['pnl']:+,.2f} PnL, {stats['win_rate']}% win rate")
            print("\n📊 WORST TRADING HOURS (by total PnL):")
            for hour, stats in hours_data['worst_hours']:
                print(f"  {hour}:00 - {stats['trades']} trades, ₹{stats['pnl']:+,.2f} PnL, {stats['win_rate']}% win rate")
        elif choice == '6':
            print("Returning...")
            break
        else:
            print("Invalid option!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == '--weekly':
            analyze_weekly()
        elif sys.argv[1] == '--monthly':
            analyze_monthly()
        elif sys.argv[1] == '--calendar':
            print_trading_calendar()
        elif sys.argv[1] == '--interactive':
            interactive_analytics()
        else:
            analyze_today()
    else:
        analyze_today()
