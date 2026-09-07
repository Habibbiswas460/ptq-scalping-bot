"""Telegram's Stop button did neither of the two things it reported.

It wrote `state.state = "KILL_SWITCH"` directly from the Telegram thread:

1. If a position was open, that overwrote `"IN_TRADE"` — and only the IN_TRADE
   branch of the main loop ever calls the exit path, so the position was orphaned.
   The bot stopped watching a trade it still held.
2. main.py's "kill check passed -> recover to IDLE" branch then set the state back
   to IDLE on the very next loop iteration, because no *automatic* kill condition
   held. Trading silently resumed seconds after the operator stopped it.

The fix separates operator intent (`manual_stop`) from the machine's state.
"""

import re

import pytest

from core.engines.state_machine import TradingState
from core.services.telegram_bot import TelegramBot


@pytest.fixture
def bot():
    b = TelegramBot('token', '4242', enabled=True)
    b.bot_state = TradingState()
    return b


def test_manual_stop_defaults_to_false():
    assert TradingState().manual_stop is False


@pytest.mark.asyncio
async def test_stop_records_intent_without_touching_the_state_machine(bot):
    bot.bot_state.state = "IN_TRADE"
    bot.bot_state.current_trade = {"order_id": "x", "qty": 65}

    await bot._cmd_stop('4242')

    assert bot.bot_state.manual_stop is True
    assert bot.bot_state.state == "IN_TRADE", (
        "overwriting IN_TRADE is what orphaned the open position"
    )


@pytest.mark.asyncio
async def test_resume_clears_intent_without_forcing_idle(bot):
    bot.bot_state.state = "IN_TRADE"
    bot.bot_state.manual_stop = True

    await bot._cmd_resume('4242')

    assert bot.bot_state.manual_stop is False
    assert bot.bot_state.state == "IN_TRADE"


@pytest.mark.asyncio
async def test_the_button_callbacks_behave_the_same_as_the_commands(bot):
    bot.bot_state.state = "IN_TRADE"

    await bot._cb_stop_trading('cb1', 1)
    assert bot.bot_state.manual_stop is True
    assert bot.bot_state.state == "IN_TRADE"

    await bot._cb_resume_trading('cb2', 1)
    assert bot.bot_state.manual_stop is False


# ── the main loop's side of the contract ────────────────────────────────────
# The loop itself cannot be unit-tested without a broker and a live feed, so these
# assert on its source: that a manual stop closes the position and that the
# recovery branch no longer undoes it.

def _main_src():
    return open('core/main.py').read()


def test_a_manual_stop_closes_an_open_position_through_the_normal_exit_path():
    src = _main_src()
    block = re.search(
        r"if getattr\(state, 'manual_stop', False\):(.*?)\n            if kill_triggered:",
        src, re.S)
    assert block, "the manual-stop branch must run before the automatic kill switch"
    body = block.group(1)
    assert 'close_current_trade(' in body, "an open position must be closed, not abandoned"
    assert 'continue' in body, "no entry logic may run while stopped"


def test_the_recovery_branch_no_longer_undoes_a_manual_stop():
    src = _main_src()
    assert (
        'if state.state == "KILL_SWITCH" and not getattr(state, \'manual_stop\', False):'
        in src
    ), "recover-to-IDLE must not clear an operator stop"


def test_telegram_never_assigns_the_state_machine_state():
    """The root cause was cross-thread writes to state.state. There should be none."""
    src = open('core/services/telegram_bot.py').read()
    assert 'bot_state.state =' not in src, (
        "Telegram must record intent, not drive the state machine"
    )
