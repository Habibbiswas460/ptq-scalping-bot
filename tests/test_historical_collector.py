"""Tests for the isolated historical collector.

Markets are closed while this is written, so every test here drives the
collector with hand-built binary frames in the real Angel One WebSocket 2.0
wire format (offsets verified against angel-one/smartapi-python). That
exercises the actual parsing/derivation logic rather than a mock of it.

The frames are synthetic TEST FIXTURES of the wire protocol; no synthetic
*market* values are ever accepted into a dataset — the whole point of
several of these tests is proving the collector records NULL instead of
fabricating when the feed doesn't supply a field.
"""

import struct

import pytest

from core.historical.collector import (
    HistoricalCollector,
    WS_MODE_QUOTE,
    WS_MODE_SNAP_QUOTE,
    build_chain,
    derive_bid_ask,
    epoch_ms_to_ist_string,
    parse_best_5,
    parse_snapquote,
    validate_oi_populated,
)
from core.historical.gate import check_backtest_ready
from core.historical.quality_checks import check_quote_authenticity, run_all_checks
from core.historical.storage import HistoricalStore

# 2026-08-17 09:15:00.250 IST (verified round-trip through the converter)
BASE_EPOCH_MS = 1786938300250


def _best5_packet(flag: int, quantity: int, price_paise: int, orders: int = 5) -> bytes:
    return (struct.pack("<H", flag) + struct.pack("<q", quantity) +
            struct.pack("<q", price_paise) + struct.pack("<H", orders))


def _make_frame(token: str, ltp_paise: int, mode: int = WS_MODE_SNAP_QUOTE,
                epoch_ms: int = BASE_EPOCH_MS, oi: int = 12345,
                volume: int = 5000, bids=None, asks=None) -> bytes:
    """Build a wire-format frame. bids/asks are lists of (price_paise, qty)."""
    buf = bytearray(400)
    buf[0] = mode
    buf[1] = 2  # exchange type
    tok = token.encode()
    buf[2:2 + len(tok)] = tok
    struct.pack_into("<q", buf, 27, 1)             # sequence
    struct.pack_into("<q", buf, 35, epoch_ms)      # exchange timestamp
    struct.pack_into("<q", buf, 43, ltp_paise)     # ltp

    if mode >= WS_MODE_QUOTE:
        struct.pack_into("<q", buf, 67, volume)

    if mode >= WS_MODE_SNAP_QUOTE:
        struct.pack_into("<q", buf, 131, oi)
        bids = bids if bids is not None else [(9950, 100), (9940, 50)]
        asks = asks if asks is not None else [(10090, 120), (10100, 80)]
        offset = 147
        for price, qty in bids:
            buf[offset:offset + 20] = _best5_packet(0, qty, price)
            offset += 20
        for price, qty in asks:
            buf[offset:offset + 20] = _best5_packet(1, qty, price)
            offset += 20
        return bytes(buf[:379])

    return bytes(buf[:123])


# ---------------------------------------------------------------------------
# Timestamp precision (must come from the feed, never invented)
# ---------------------------------------------------------------------------

def test_millisecond_precision_preserved_from_exchange_timestamp():
    assert epoch_ms_to_ist_string(BASE_EPOCH_MS).endswith(".250")


def test_timestamp_converted_to_ist():
    ts = epoch_ms_to_ist_string(BASE_EPOCH_MS)
    assert ts.startswith("2026-08-17 09:15:00")


def test_whole_second_stays_zero_milliseconds_not_faked():
    """If the feed sends a whole second, we report .000 rather than
    manufacturing sub-second detail."""
    assert epoch_ms_to_ist_string(BASE_EPOCH_MS - 250).endswith(".000")


# ---------------------------------------------------------------------------
# Real bid/ask derivation - and fail-closed behaviour
# ---------------------------------------------------------------------------

def test_bid_ask_derived_from_best5_depth():
    frame = _make_frame("111", 10000, bids=[(9950, 100), (9940, 50)],
                        asks=[(10090, 120), (10100, 80)])
    parsed = parse_snapquote(frame)
    assert parsed["bid"] == 99.50
    assert parsed["ask"] == 100.90


def test_bid_ask_ignores_ambiguous_flag_semantics():
    """The official client swaps buy/sell labels, so derivation must rely on
    price ordering. Inverting the flags must yield the SAME bid/ask."""
    normal = parse_snapquote(_make_frame("111", 10000,
                                         bids=[(9950, 100)], asks=[(10090, 120)]))
    # flags inverted: 'bids' sent with flag 1, 'asks' with flag 0
    buf = bytearray(_make_frame("111", 10000, bids=[], asks=[]))
    buf[147:167] = _best5_packet(1, 100, 9950)
    buf[167:187] = _best5_packet(0, 120, 10090)
    inverted = parse_snapquote(bytes(buf))
    assert (normal["bid"], normal["ask"]) == (inverted["bid"], inverted["ask"]) == (99.50, 100.90)


def test_bid_ask_none_on_crossed_book():
    packets = [{"flag": 0, "price": 101.0, "quantity": 10, "orders": 1},
               {"flag": 1, "price": 99.0, "quantity": 10, "orders": 1}]
    # groups overlap in a way that is not cleanly separable both directions
    packets.append({"flag": 0, "price": 98.0, "quantity": 10, "orders": 1})
    packets.append({"flag": 1, "price": 102.0, "quantity": 10, "orders": 1})
    assert derive_bid_ask(packets) == (None, None)


def test_bid_ask_none_on_one_sided_book():
    packets = [{"flag": 0, "price": 99.5, "quantity": 10, "orders": 1}]
    assert derive_bid_ask(packets) == (None, None)


def test_bid_ask_none_on_empty_book():
    assert derive_bid_ask([]) == (None, None)


def test_zero_price_padding_ignored():
    packets = parse_best_5(_best5_packet(0, 0, 0) * 10)
    assert derive_bid_ask(packets) == (None, None)


def test_collector_never_synthesises_bid_ask():
    """The defect this whole effort exists to prevent: bid/ask must never be
    derived from ltp. With an empty book, both must be NULL."""
    frame = _make_frame("111", 10000, bids=[], asks=[])
    parsed = parse_snapquote(frame)
    assert parsed["bid"] is None and parsed["ask"] is None
    # and specifically NOT the ltp +/- 0.3% synthetic pattern
    assert parsed["bid"] != pytest.approx(100.0 - (100.0 * 0.003) / 2)


# ---------------------------------------------------------------------------
# OI: genuinely parsed, never silently defaulted (explicit requirement)
# ---------------------------------------------------------------------------

def test_oi_parsed_exactly_from_payload():
    parsed = parse_snapquote(_make_frame("111", 10000, oi=987654))
    assert parsed["oi"] == 987654


def test_oi_absent_not_zero_when_mode_lacks_it():
    """Quote mode carries no OI. It must be ABSENT, not defaulted to 0 —
    otherwise a missing field masquerades as a real zero."""
    parsed = parse_snapquote(_make_frame("111", 10000, mode=WS_MODE_QUOTE))
    assert "oi" not in parsed or parsed["oi"] is None


def test_validate_oi_flags_all_zero_as_suspect():
    rows = [{"instrument_type": "CE", "oi": 0} for _ in range(50)]
    result = validate_oi_populated(rows)
    assert result["ok"] is False
    assert "default" in result["reason"]


def test_validate_oi_flags_missing_values():
    rows = [{"instrument_type": "CE", "oi": None} for _ in range(50)]
    result = validate_oi_populated(rows)
    assert result["ok"] is False
    assert "carry OI" in result["reason"]


def test_validate_oi_passes_on_real_values():
    rows = [{"instrument_type": "CE", "oi": 1000 + i} for i in range(50)]
    result = validate_oi_populated(rows)
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Chain construction
# ---------------------------------------------------------------------------

def test_build_chain_covers_atm_plus_minus_200_both_sides():
    chain = build_chain(24013.0, "2026-08-20")
    strikes = sorted({c["strike"] for c in chain})
    assert strikes == [23800, 23850, 23900, 23950, 24000, 24050, 24100, 24150, 24200]
    assert len(chain) == 18  # 9 strikes x CE/PE
    assert {c["instrument_type"] for c in chain} == {"CE", "PE"}


def test_chain_plus_spot_is_within_broker_token_limit():
    """19 tokens vs Angel One's documented 1000-per-connection limit."""
    chain = build_chain(24000.0, "2026-08-20")
    assert len(chain) + 1 == 19
    assert len(chain) + 1 < 1000


# ---------------------------------------------------------------------------
# Collector wiring: spot as real rows, subscription payload, isolation
# ---------------------------------------------------------------------------

def _configured_collector(store):
    collector = HistoricalCollector(store=store, auth={
        "auth_token": "x", "api_key": "x", "client_id": "x", "feed_token": "x"})
    chain = build_chain(24000.0, "2026-08-20")
    tokens = {c["symbol"]: str(1000 + i) for i, c in enumerate(chain)}
    collector.configure(chain, lambda s: tokens.get(s), spot_token="99")
    return collector, tokens


def test_subscribe_message_uses_snap_quote_mode(tmp_path):
    collector, _ = _configured_collector(HistoricalStore(store_dir=str(tmp_path)))
    msg = collector.subscribe_message()
    assert msg["params"]["mode"] == WS_MODE_SNAP_QUOTE
    assert msg["action"] == 1
    total = sum(len(t["tokens"]) for t in msg["params"]["tokenList"])
    assert total == 19


def test_spot_recorded_as_its_own_instrument_row(tmp_path):
    """Spot must exist as SPOT rows, not only as a denormalised column,
    or the gate's alignment check has nothing to verify against."""
    collector, _ = _configured_collector(HistoricalStore(store_dir=str(tmp_path)))
    row = collector.handle_binary(_make_frame("99", 2400000))
    assert row["instrument_type"] == "SPOT"
    assert row["ltp"] == 24000.0


def test_option_row_gets_fresh_spot_ref(tmp_path):
    collector, tokens = _configured_collector(HistoricalStore(store_dir=str(tmp_path)))
    collector.handle_binary(_make_frame("99", 2400000, epoch_ms=BASE_EPOCH_MS))
    opt = collector.handle_binary(_make_frame("1000", 10000, epoch_ms=BASE_EPOCH_MS + 200))
    assert opt["spot_ref"] == 24000.0


def test_stale_spot_ref_is_null_not_carried_forward(tmp_path):
    """A spot price older than the alignment tolerance must not be stamped
    onto an option row - that would fabricate alignment."""
    collector, _ = _configured_collector(HistoricalStore(store_dir=str(tmp_path)))
    collector.handle_binary(_make_frame("99", 2400000, epoch_ms=BASE_EPOCH_MS))
    opt = collector.handle_binary(_make_frame("1000", 10000, epoch_ms=BASE_EPOCH_MS + 60_000))
    assert opt["spot_ref"] is None


def test_untracked_token_ignored(tmp_path):
    collector, _ = _configured_collector(HistoricalStore(store_dir=str(tmp_path)))
    assert collector.handle_binary(_make_frame("777777", 10000)) is None


def test_collector_imports_nothing_from_trading_path():
    """Isolation contract, asserted mechanically against real imports.

    Checks the AST rather than raw text, because the module docstring
    legitimately *discusses* the trading path it is isolated from.
    """
    import ast
    import inspect
    import core.historical.collector as mod

    tree = ast.parse(inspect.getsource(mod))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)

    forbidden = ("state_machine", "entry_engine", "exit_engine", "risk_manager",
                 "strategies", "core.trading", "core.engines", "core.risk")
    for name in imported:
        for bad in forbidden:
            assert bad not in name, f"collector must not import {name}"


# ---------------------------------------------------------------------------
# End-to-end: collected data must satisfy the hardened gate
# ---------------------------------------------------------------------------

def test_collected_data_passes_hardened_gate(tmp_path):
    """Drives the collector with a realistic 1-second session across the full
    chain and asserts the result reaches READY - proving the collector's
    output shape actually satisfies the gate it must eventually clear."""
    store = HistoricalStore(store_dir=str(tmp_path))
    collector, tokens = _configured_collector(store)

    for i in range(20):
        epoch = BASE_EPOCH_MS + i * 1000
        collector.handle_binary(_make_frame("99", 2400000, epoch_ms=epoch))
        for sym, tok in tokens.items():
            # prints alternate at bid and ask, as real trades do
            ltp_paise = 9950 if i % 2 == 0 else 10090
            collector.handle_binary(_make_frame(tok, ltp_paise, epoch_ms=epoch + 100,
                                                oi=5000 + i))
    collector.flush()

    rows = list(store.query_range("2026-08-17", "2026-08-17"))
    assert len(rows) > 0

    oi_check = validate_oi_populated(rows)
    assert oi_check["ok"] is True, oi_check

    assert check_quote_authenticity(rows).passed is True

    gate = check_backtest_ready(store, "2026-08-17", "2026-08-17")
    assert gate.ready is True, [(c.name, c.details[:1]) for c in gate.failing_checks]


def test_synthetic_style_quotes_would_fail_the_gate(tmp_path):
    """Control: had the collector reproduced the old synthetic pattern, the
    gate must reject it."""
    store = HistoricalStore(store_dir=str(tmp_path))
    collector, tokens = _configured_collector(store)
    rows = []
    for i in range(20):
        epoch = BASE_EPOCH_MS + i * 1000
        collector.handle_binary(_make_frame("99", 2400000, epoch_ms=epoch))
        for tok in tokens.values():
            r = collector.handle_binary(_make_frame(tok, 10000, epoch_ms=epoch + 100))
            if r:
                rows.append(r)
    # rewrite quotes into the old ltp +/- 0.3% synthetic shape
    for r in rows:
        spread = r["ltp"] * 0.003
        r["bid"] = round(r["ltp"] - spread / 2, 2)
        r["ask"] = round(r["ltp"] + spread / 2, 2)
    assert check_quote_authenticity(rows).passed is False
