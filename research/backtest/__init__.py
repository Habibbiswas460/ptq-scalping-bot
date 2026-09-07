"""Free historical candles, and a replay of the real engines over them.

Three things live here and they are deliberately separate:

  sources.py   what the public internet will actually give us for NIFTY, measured
  store.py     where it lands, with per-fetch provenance and explicit gap rows
  harness.py   a replay that imports the SHIPPING entry and exit code rather than
               re-implementing it, so a result here is a statement about this bot

Nothing in this package writes to the trading database, places an order, or invents a
bar. A minute the source did not return is recorded in `gaps`, never interpolated.
"""
