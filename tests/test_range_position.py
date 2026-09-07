"""The range-position experiment: correct arithmetic, and off by default.

Measured on this project's own ticks, entering in the top 20% of an option's
60-second range is the worst-priced entry available (-0.359 gross points) and the
bottom 20% the best (+0.192, the only positive cell of 27) — while the scoring
stack that decides entries is a momentum/breakout detector, i.e. aimed at the
worst end. This module lets that be tested as one variable.

It is a hypothesis, not a finding: the samples behind it overlap heavily, and even
if real it is 22% of the improvement needed to clear costs. So the gate ships OFF,
and a test pins that.
"""

from core.engines.range_position import range_position


def _t(i, price, symbol="NIFTY09SEP2624000CE"):
    return {"symbol": symbol, "timestamp": 1_000.0 * i, "ltp": price}


def test_a_price_at_the_top_of_its_range_reads_one():
    ticks = [_t(i, 100 + i) for i in range(20)]
    pos, detail = range_position(ticks, "NIFTY09SEP2624000CE")
    assert pos == 1.0
    assert "over" in detail


def test_a_price_at_the_bottom_of_its_range_reads_zero():
    ticks = [_t(i, 120 - i) for i in range(20)]
    pos, _ = range_position(ticks, "NIFTY09SEP2624000CE")
    assert pos == 0.0


def test_the_midpoint_reads_one_half():
    ticks = [_t(i, p) for i, p in enumerate([100] * 9 + [120] * 9 + [110])]
    pos, _ = range_position(ticks, "NIFTY09SEP2624000CE")
    assert abs(pos - 0.5) < 1e-9


def test_ticks_for_another_contract_are_not_borrowed():
    """The rolling buffer holds whichever contract was subscribed, which is not
    always the one about to be traded. A range measured on the wrong contract is
    worse than no range at all."""
    ticks = [_t(i, 100 + i, symbol="OTHER") for i in range(20)]
    pos, why = range_position(ticks, "NIFTY09SEP2624000CE")
    assert pos is None
    assert "no ticks for" in why


def test_ticks_outside_the_window_are_excluded():
    old = [_t(i, 500) for i in range(10)]                       # long ago, far away
    recent = [_t(1_000 + i, 100 + i) for i in range(20)]        # the last 20 seconds
    pos, detail = range_position(old + recent, "NIFTY09SEP2624000CE", window_sec=60.0)
    assert pos == 1.0, detail
    assert "500" not in detail


def test_too_few_samples_is_unknown_not_zero():
    pos, why = range_position([_t(i, 100 + i) for i in range(4)],
                              "NIFTY09SEP2624000CE")
    assert pos is None and "need 10" in why


def test_a_flat_range_is_unknown_not_a_position():
    """Every position in a flat range is simultaneously 0.0 and 1.0."""
    pos, why = range_position([_t(i, 100) for i in range(20)],
                              "NIFTY09SEP2624000CE")
    assert pos is None and "flat range" in why


def test_malformed_ticks_are_skipped_not_fatal():
    ticks = [_t(i, 100 + i) for i in range(20)]
    ticks.insert(5, {"symbol": "NIFTY09SEP2624000CE", "timestamp": "oops", "ltp": None})
    ticks.insert(9, {"symbol": "NIFTY09SEP2624000CE"})
    pos, _ = range_position(ticks, "NIFTY09SEP2624000CE")
    assert pos == 1.0


def test_no_symbol_and_no_ticks_are_unknown():
    assert range_position([_t(0, 100)], "")[0] is None
    assert range_position([], "X")[0] is None


# ── the shipping state ──────────────────────────────────────────────────────

def test_the_gate_is_off_by_default():
    from config.constants import ENTRY_RANGE_FILTER_ENABLED
    assert ENTRY_RANGE_FILTER_ENABLED is False, (
        "this is a hypothesis with overlapping samples that does not clear the "
        "cost bar even if true; it must not govern a live session until it has "
        "been registered and scored on a held-out session"
    )


def test_the_gate_fails_open_when_the_range_cannot_be_measured():
    """A filter that blocks entries because it could not measure something is a
    halt wearing a filter's clothing. This project has already shipped one."""
    src = open("core/engines/entry_engine.py").read()
    i = src.index("if ENTRY_RANGE_FILTER_ENABLED:")
    block = src[i:i + 1400]
    assert "if pos is None:" in block
    unknown = block[block.index("if pos is None:"):block.index("elif pos >")]
    assert "return False" not in unknown, "an unmeasurable range must not block the entry"
