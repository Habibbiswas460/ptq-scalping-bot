#!/usr/bin/env python3
"""
PTQ Scalping Bot - Analysis CLI Tool
Run: python analyze.py [date]
"""

import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.analytics import TradeAnalytics


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║          📊 PTQ SCALPING BOT - TRADE ANALYZER                    ║
╚══════════════════════════════════════════════════════════════════╝
""")


def list_available_dates(log_dir: str = "logs"):
    """List all dates with log data"""
    if not os.path.exists(log_dir):
        print("❌ No logs directory found")
        return []
    
    dates = []
    for item in os.listdir(log_dir):
        item_path = os.path.join(log_dir, item)
        if os.path.isdir(item_path) and item.startswith("20"):
            trades_file = os.path.join(item_path, "trades.json")
            if os.path.exists(trades_file):
                dates.append(item)
    
    return sorted(dates, reverse=True)


def interactive_mode():
    """Interactive analysis mode"""
    print_banner()
    
    analytics = TradeAnalytics()
    
    while True:
        print("\n📋 MENU:")
        print("  1. Analyze today's trades")
        print("  2. Analyze specific date")
        print("  3. Compare multiple days")
        print("  4. List available dates")
        print("  5. Generate full report")
        print("  6. Quick stats")
        print("  0. Exit")
        
        choice = input("\n👉 Enter choice: ").strip()
        
        if choice == "0":
            print("\n👋 Goodbye!")
            break
        
        elif choice == "1":
            date = datetime.now().strftime("%Y-%m-%d")
            print(f"\n📅 Analyzing: {date}")
            report = analytics.generate_report(date)
            print(report)
            
            save = input("\n💾 Save report? (y/n): ").strip().lower()
            if save == 'y':
                files = analytics.save_report(date)
                print(f"✅ Saved to: {files}")
        
        elif choice == "2":
            dates = list_available_dates()
            if dates:
                print("\n📅 Available dates:")
                for i, d in enumerate(dates, 1):
                    print(f"  {i}. {d}")
                
                idx = input("\n👉 Enter number or date (YYYY-MM-DD): ").strip()
                try:
                    if idx.isdigit() and 1 <= int(idx) <= len(dates):
                        date = dates[int(idx) - 1]
                    else:
                        date = idx
                    
                    print(f"\n📅 Analyzing: {date}")
                    report = analytics.generate_report(date)
                    print(report)
                except Exception as e:
                    print(f"❌ Error: {e}")
            else:
                print("❌ No trade data found")
        
        elif choice == "3":
            dates = list_available_dates()
            if len(dates) < 2:
                print("❌ Need at least 2 days of data to compare")
                continue
            
            print("\n📊 MULTI-DAY COMPARISON")
            print("-" * 50)
            
            total_pnl = 0
            total_trades = 0
            total_wins = 0
            total_losses = 0
            
            print(f"{'Date':<12} {'Trades':>8} {'Win%':>8} {'PnL':>12}")
            print("-" * 50)
            
            for date in dates[:10]:  # Last 10 days
                trades = analytics.load_trades(date)
                paired = analytics.get_paired_trades(trades)
                metrics = analytics.calculate_metrics(paired)
                
                s = metrics['summary']
                p = metrics['pnl']
                
                total_pnl += p['total_pnl']
                total_trades += s['total_trades']
                total_wins += s['winners']
                total_losses += s['losers']
                
                print(f"{date:<12} {s['total_trades']:>8} {s['win_rate']:>7.1f}% ₹{p['total_pnl']:>+10.2f}")
            
            print("-" * 50)
            overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
            print(f"{'TOTAL':<12} {total_trades:>8} {overall_win_rate:>7.1f}% ₹{total_pnl:>+10.2f}")
        
        elif choice == "4":
            dates = list_available_dates()
            if dates:
                print("\n📅 Available dates:")
                for d in dates:
                    trades_file = os.path.join("logs", d, "trades.json")
                    trade_count = sum(1 for _ in open(trades_file)) if os.path.exists(trades_file) else 0
                    print(f"  • {d} ({trade_count} entries)")
            else:
                print("❌ No trade data found")
        
        elif choice == "5":
            date = input("📅 Enter date (YYYY-MM-DD) or press Enter for today: ").strip()
            if not date:
                date = datetime.now().strftime("%Y-%m-%d")
            
            files = analytics.save_report(date, format='both')
            print(f"\n✅ Reports saved:")
            for f in files:
                print(f"   📁 {f}")
        
        elif choice == "6":
            date = datetime.now().strftime("%Y-%m-%d")
            trades = analytics.load_trades(date)
            paired = analytics.get_paired_trades(trades)
            metrics = analytics.calculate_metrics(paired)
            
            s = metrics['summary']
            p = metrics['pnl']
            
            print(f"""
╔════════════════════════════════════════╗
║        📊 QUICK STATS - {date}        ║
╠════════════════════════════════════════╣
║  Trades:     {s['total_trades']:<25}║
║  Win Rate:   {s['win_rate']:.1f}%{' ' * 21}║
║  Total PnL:  ₹{p['total_pnl']:+,.2f}{' ' * (18 - len(f"{p['total_pnl']:+,.2f}"))}║
║  Profit Factor: {s['profit_factor']}{' ' * (19 - len(str(s['profit_factor'])))}║
╚════════════════════════════════════════╝
""")
        
        else:
            print("❌ Invalid choice")


def main():
    if len(sys.argv) > 1:
        # Command line mode
        date = sys.argv[1]
        if date == "--help" or date == "-h":
            print("""
PTQ Trade Analyzer

Usage:
  python analyze.py              # Interactive mode
  python analyze.py today        # Analyze today
  python analyze.py 2026-01-22   # Analyze specific date
  python analyze.py --list       # List available dates
  python analyze.py --save       # Save today's report
""")
            return
        
        analytics = TradeAnalytics()
        
        if date == "--list":
            dates = list_available_dates()
            print("📅 Available dates:")
            for d in dates:
                print(f"  • {d}")
        elif date == "--save":
            date = datetime.now().strftime("%Y-%m-%d")
            files = analytics.save_report(date)
            print(f"✅ Saved: {files}")
        elif date == "today":
            report = analytics.generate_report()
            print(report)
        else:
            report = analytics.generate_report(date)
            print(report)
    else:
        # Interactive mode
        interactive_mode()


if __name__ == "__main__":
    main()
