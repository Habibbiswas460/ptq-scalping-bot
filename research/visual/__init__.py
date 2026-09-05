"""Permanent visual record layer.

The research modules one level up *compute* — they read the trading database and derive
candles, legs, cascades and quality on every run. This package *persists* what they derive,
once per session, in a schema a future dashboard can read without re-deriving anything.

    Raw / historical DB  ->  normalized series  ->  as-of candle builder
                         ->  persistent visual records  ->  HTML/SVG viewer  ->  (dashboard)

Three rules hold everywhere in here:

1. The trading database is never written to. `research.db.Book` opens it read-only and this
   package writes to its own file, so a builder bug cannot damage a session's record.
2. Nothing is fabricated. A bar exists only where source observations exist; everything else
   is recorded as MISSING with the reason, never gap-filled, never forward-filled.
3. Entry-time context is as-of. Post-entry movement lives in separate, explicitly named
   fields so a chart can never quietly explain a decision with what came after it.
"""
