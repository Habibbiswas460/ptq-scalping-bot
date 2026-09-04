"""EXP-07 — how much information can each entry component carry AT ALL?

A ranking component can only discriminate if it varies. This measures the variance of every
score and confidence sub-component across every persisted signal row on the tick-days, before
any outcome is involved. It is a structural fact about the data, not a statistical test.
"""
import sqlite3, json, collections
DB = "/home/lora/projects/PTQ-scalping bot/core/data/trades.db"
con = sqlite3.connect(DB); cur = con.cursor()
DAYS = ("2026-09-02", "2026-09-03", "2026-09-04")

for col, label in (("score_breakdown", "SCORE sub-components"),
                   ("confidence_breakdown", "CONFIDENCE sub-components")):
    print("=" * 104)
    print(f"{label} — distinct values across every persisted signal row ({', '.join(DAYS)})")
    print("=" * 104)
    cur.execute(f"SELECT {col} FROM signals WHERE date(timestamp) IN (?,?,?) AND {col} IS NOT NULL "
                f"AND {col}<>''", DAYS)
    vals = collections.defaultdict(collections.Counter)
    n = 0
    for (blob,) in cur.fetchall():
        try:
            d = json.loads(blob)
        except Exception:
            continue
        n += 1
        for k, v in d.items():
            if isinstance(v, (int, float)):
                vals[k][round(float(v), 2)] += 1
    print(f"  rows parsed: {n}")
    print(f"  {'component':<26}{'distinct':>9}{'most common':>26}{'share':>8}   verdict")
    for k in sorted(vals):
        c = vals[k]
        top, cnt = c.most_common(1)[0]
        share = 100 * cnt / sum(c.values())
        verdict = ("CONSTANT — no information" if len(c) == 1 else
                   f"near-constant ({share:.0f}% one value)" if share >= 95 else
                   "varies")
        print(f"  {k:<26}{len(c):>9}{str(top):>26}{share:>7.1f}%   {verdict}")
    print()

print("=" * 104)
print("Distinct (score, confidence) pairs actually produced, per day and direction")
print("=" * 104)
cur.execute("SELECT date(timestamp) d, ifnull(nullif(direction,''),'(none)') dir, score, confidence, "
            "count(*) n FROM signals WHERE date(timestamp) IN (?,?,?) GROUP BY d,dir,score,confidence "
            "ORDER BY d,dir,n DESC", DAYS)
cur_d = None
for d, dr, sc, cf, n in cur.fetchall():
    if (d, dr) != cur_d:
        print(f"  {d}  {dr}:")
        cur_d = (d, dr)
    print(f"      score={sc}  confidence={cf}   n={n}")
