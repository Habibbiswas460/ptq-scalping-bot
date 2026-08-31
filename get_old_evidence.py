import sqlite3
import os
from datetime import datetime

DB_PATH = 'core/data/trades.db'

def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT order_id, entry_time, exit_time, symbol, side, qty, entry_price, exit_price, pnl, pnl_pct, mfe, mae, exit_reason
        FROM trades
        WHERE entry_time >= '2026-07-27' AND entry_time <= '2026-08-07 23:59:59'
        AND status = 'CLOSED'
    """)
    rows = c.fetchall()
    
    print("=== OLD PILOT TRADES (27-Jul to 07-Aug) ===")
    if not rows:
        print("No old trades found in DB.")
    else:
        wins = [r for r in rows if r['pnl'] and r['pnl'] > 0]
        losses = [r for r in rows if r['pnl'] and r['pnl'] <= 0]
        sum_pnl = sum(r['pnl'] for r in rows if r['pnl'])
        sum_win = sum(r['pnl'] for r in wins if r['pnl'])
        sum_loss = sum(r['pnl'] for r in losses if r['pnl'])
        print(f"Total Trades: {len(rows)}")
        print(f"Wins: {len(wins)}, Losses: {len(losses)}")
        print(f"Total PnL: {sum_pnl:.2f}")
        print(f"Win Rate: {(len(wins)/len(rows))*100:.2f}%")
        avg_win = sum_win / len(wins) if wins else 0
        avg_loss = sum_loss / len(losses) if losses else 0
        print(f"Avg Winner: {avg_win:.2f}")
        print(f"Avg Loser: {avg_loss:.2f}")
        print(f"Expectancy: {sum_pnl / len(rows):.2f}")
        pf = abs(sum_win / sum_loss) if sum_loss != 0 else float('inf')
        print(f"Profit Factor: {pf:.2f}")
    conn.close()

if __name__ == "__main__":
    run()

