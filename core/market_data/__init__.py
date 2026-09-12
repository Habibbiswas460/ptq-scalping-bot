"""Broker-agnostic tick pipeline: validate, route, cache, enrich.

Everything here works off a tick dict keyed at minimum by `token` and `ltp` — the
canonical shape in brokers/base/tick_schema.py, or (until a broker's normalizer is
wired into the live path) the raw tick a broker's message_parser produces, since both
carry those two fields. Nothing here is broker-specific; a second broker's ticks flow
through the same classes once normalized.
"""
