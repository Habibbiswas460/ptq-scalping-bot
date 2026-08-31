Updated todo list

Searched for regex `def.*report|__main__|argparse` (`**/core/validation/**/*.py`), 14 results

লাইভ সেশন চালানোর পর এভাবে দেখতে পারবেন:

## ১. দ্রুত terminal command (সবচেয়ে সহজ)

```bash
cd '/home/lora/projects/PTQ-scalping bot' && sqlite3 core/data/trades.db <<'SQL'
.headers on
.mode column
SELECT decision_id, status, direction, virtual_entry_time, virtual_entry_price,
       virtual_exit_price, pnl, exit_reason
FROM dvf_trades
ORDER BY id DESC LIMIT 20;
SQL
```

এটা সবচেয়ে সাম্প্রতিক ২০টা virtual trade (open/closed দুটোই) দেখাবে।

## ২. শুধু আজকের virtual trades

```bash
sqlite3 core/data/trades.db "SELECT decision_id, direction, virtual_entry_price, virtual_exit_price, pnl, exit_reason FROM dvf_trades WHERE date(virtual_entry_time) = date('now') ORDER BY id;"
```

## ৩. এখনো OPEN আছে এমন virtual position (লাইভ সেশন চলাকালীন যাচাই করতে)

```bash
sqlite3 core/data/trades.db "SELECT decision_id, direction, virtual_entry_price, sl_price, tp_price FROM dvf_trades WHERE status='OPEN';"
```
(নোট: `sl_price`/`tp_price` কলাম দুটো শুধু in-memory registry-তে থাকে, DB টেবিলে সেভ হয় না — DB-তে OPEN রো থেকে শুধু entry দেখা যাবে, exit না হওয়া পর্যন্ত।)

## ৪. `dvf_signals` সাথে join করে পুরো decision context দেখতে (signal কেন accept হয়েছিল + virtual ফলাফল একসাথে)

```bash
sqlite3 core/data/trades.db <<'SQL'
.headers on
.mode column
SELECT s.timestamp, s.direction, s.weighted_score, s.confidence, s.market_quality_grade,
       t.pnl, t.exit_reason
FROM dvf_signals s
JOIN dvf_trades t ON t.decision_id = s.decision_id
ORDER BY s.timestamp DESC LIMIT 20;
SQL
```

## ৫. Python-এ দেখতে চাইলে

```python
from core.services.database import get_dvf_trades
for t in get_dvf_trades(limit=20):
    print(t)
```

পরবর্তী paper-mode সেশন চালিয়ে অন্তত একটা accepted সিগন্যাল এলেই command ১ দিয়ে চেক করে দেখতে পারবেন rows আসছে কিনা।