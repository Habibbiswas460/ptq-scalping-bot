# PTQ Research Instrument

A permanent, read-only research layer over the trading database. It exists to answer one
question with evidence:

> The market gave us X points of movement — where exactly did that stop becoming P&L?

It is not a dashboard. Nothing here reports "today's P&L" as a headline; every number is
attached to a provenance state and a confidence, and no chart turns itself into a conclusion.

## Commands

```bash
python -m research.session 2026-09-04           # one session, all layers
python -m research.session 2026-09-04 --deep    # also price what each pre-filter blocked (slow)
python -m research.session --all                # every session that carries data
python -m research.compare_report               # all sessions side by side
python -m research.compare_report 2026-09-03 2026-09-04   # before / after
python -m research.experiment                   # the experiment ledger
python -m research.experiment EXP-11            # one experiment record
python -m research.synthesis                    # the master chain, all sessions
```

Output lands in `claude_code/research_output/` (gitignored). Self-contained HTML: inline SVG,
no plotting dependency, no network fetch beyond webfonts.

## Layers

| module | answers |
|---|---|
| `db` | what is persisted (read-only; every statement is a SELECT) |
| `provenance` | is this field real, reconstructed, estimated, missing or invalid |
| `candles` | OHLC at 10s/30s/1m/5m, **as-of safe** |
| `market` | legs, movement map, session profile |
| `opportunities` | every valid instant, not only the ones traded |
| `replay` | what would this instant have produced under the production ladder |
| `prefilters` | which gate rejected what, and what it cost |
| `signals` | does a score component vary, cover, contribute, discriminate |
| `entries` | causal pre-entry features, uncensored post-entry excursions |
| `transmission` | how much spot movement reaches the option |
| `execution` | spread and quote quality — clearly separated as assumptions |
| `compare` | session rows and before/after |
| `ledger` | the experiment record, including retractions |
| `synthesis` | the whole chain priced end to end |
| `render`, `svg` | presentation |

## The two rules that matter

**As-of safety is structural, not documentary.** `candles.build(upto=t)` filters the tick
series before aggregating, so an entry bar cannot contain a post-entry tick, and `as_of()`
cannot return a later observation. A completed-candle artifact once produced a p=0.0042
finding in this project that collapsed to p=0.54 when recomputed causally — the guard exists
because of that, and `tests/test_research_layer.py` asserts it.

**Available movement is never read from `trades.mfe`.** That column stops updating at the
exit, so using it to judge an exit guarantees the answer. Availability is always recomputed
from ticks over a fixed horizon.

## Provenance states

`REAL` measured · `RECONSTRUCTED` derived deterministically · `ESTIMATED` a model standing in
for data · `MISSING` unavailable · `INVALID` known-defective · `LIVE-ONLY` exists going forward.

Known at the time of writing: bid/ask is **ESTIMATED** (the `ltp ± 0.3%/2` fallback fires on
every tick), `oi` and `regime` are **MISSING**, delta is **RECONSTRUCTED** (Black-Scholes
solved from LTP, not broker-quoted). No rupee figure in any report is net of a measured
execution cost.

## Adding a session

Nothing. Sessions are discovered from the database; a new one joins every report automatically.

## Adding an experiment

```python
from research.ledger import upsert
upsert({"id": "EXP-12", "date": "...", "hypothesis": "...", "baseline": "8b7490e",
        "variable": "...", "control": "...", "treatment": "...", "dataset": "...",
        "n": "...", "result": "...", "confidence": "...", "decision": "...", "next": "..."})
```

The ledger is append-only. A finding that is later overturned is marked `retracted` or
`superseded_by` and stays visible.

## What this layer will not do

It will not propose a threshold. An optimum found on one dataset is a candidate, not a
decision: it goes through hypothesis → controlled experiment → out-of-sample check → decision,
and the ledger records the outcome either way.
