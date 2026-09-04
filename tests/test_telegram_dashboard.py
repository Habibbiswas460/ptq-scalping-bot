"""Telegram dashboard: preferences, heartbeat, session errors, and the debug-log fix.

Everything here runs with enabled=False so no network call is ever made — send_message only
queues, and the queue is inspected directly.
"""
import json
import os

import pytest

from core.services.telegram_bot import TelegramBot
from core.services.telegram_prefs import TelegramPrefs, SCHEMA, INTERVAL_KEY, INTERVAL_CHOICES


@pytest.fixture
def bot(tmp_path):
    # enabled=True so send_message queues, but start() is never called, so the background
    # worker that would talk to the network does not exist
    b = TelegramBot('token', '4242', enabled=True)
    b.prefs = TelegramPrefs(str(tmp_path / 'prefs.json'))
    return b


def _queued(b):
    out = []
    while not b._message_queue.empty():
        out.append(b._message_queue.get_nowait())
    return out


# ── the original complaint: debug logs reaching the chat ──────────────────
def test_no_raw_log_forwarding_remains():
    """The keyword tail forwarded any line containing 'SIGNAL', which matched every
    '[DEBUG] No signal: ...' line the strategy writes — thousands per quiet session."""
    src = open('core/services/telegram_bot.py').read()
    assert '_check_live_logs' not in src
    assert 'important_keywords' not in src
    assert 'main_log' not in src, "the main log must never be tailed into the chat"


def test_error_log_tail_skips_debug_lines(tmp_path, bot):
    log = tmp_path / 'errors.log'
    log.write_text("# Log started\n")

    class L:
        error_log = str(log)
    bot.set_logger(L())

    bot._tail_error_log()                      # first look only records the position
    assert bot.error_count() == 0

    log.write_text("# Log started\n"
                   "[10:00:01] [DEBUG] No signal: chop filter\n"
                   "[10:00:02] [ERROR] WebSocket error: connection reset\n")
    bot._tail_error_log()
    assert bot.error_count() == 1
    assert 'WebSocket' in bot._build_errors_text()
    assert 'No signal' not in bot._build_errors_text()


# ── heartbeat ─────────────────────────────────────────────────────────────
def test_heartbeat_is_off_until_enabled_and_then_respects_the_interval(bot):
    # Set the starting state explicitly rather than assuming the ambient .env default —
    # TELEGRAM_HEARTBEAT is a real setting and flips with the environment.
    if bot.prefs.get('heartbeat'):
        bot.prefs.toggle('heartbeat')
    assert bot._heartbeat_due() is False         # disabled -> never due

    bot.prefs.toggle('heartbeat')                # -> on
    assert bot._heartbeat_due() is True          # never sent -> due immediately

    bot._last_heartbeat = 10**12                 # pretend one just went out
    assert bot._heartbeat_due() is False


def test_heartbeat_text_survives_a_missing_state(bot):
    assert 'Heartbeat' in bot._build_heartbeat_text()


def test_heartbeat_text_reports_errors_when_there_are_any(bot):
    bot.record_error('boom')
    assert 'error(s) this session' in bot._build_heartbeat_text()


# ── session errors ────────────────────────────────────────────────────────
def test_errors_are_bounded_and_escaped(bot):
    for i in range(80):
        bot.record_error(f'failure {i} <tag>')
    assert bot.error_count() == 50              # deque maxlen, not unbounded growth
    text = bot._build_errors_text()
    assert '&lt;tag&gt;' in text and '<tag>' not in text


def test_blank_errors_are_ignored_and_clear_works(bot):
    bot.record_error('   ')
    bot.record_error('')
    assert bot.error_count() == 0
    bot.record_error('real one')
    assert bot.error_count() == 1
    bot.clear_errors()
    assert bot.error_count() == 0


def test_error_count_shows_on_the_menu_button(bot):
    def button_texts():
        return [b['text'] for row in bot._main_keyboard()['inline_keyboard'] for b in row]
    assert '🐞 Errors' in button_texts()
    bot.record_error('x')
    assert '🐞 Errors (1)' in button_texts()


# ── preferences actually gate the notifications ───────────────────────────
def test_notify_preferences_are_honoured(bot):
    """TELEGRAM_NOTIFY_ENTRIES / _EXITS / DAILY_SUMMARY existed in config and .env but nothing
    ever read them, so turning one off had no effect at all."""
    trade = {'direction': 'CE', 'entry_price': 120.0, 'qty': 65, 'score': 66,
             'confidence': 82, 'entry_reason': 'test', 'exit_price': 121.0,
             'hold_time_sec': 30}
    bot.notify_entry(trade)
    assert len(_queued(bot)) == 1

    bot.prefs.toggle('notify_entries')          # -> off
    bot.notify_entry(trade)
    assert _queued(bot) == []

    bot.prefs.toggle('notify_exits')            # -> off
    bot.notify_exit(trade, -150.0, 'SOFT LOSS')
    assert _queued(bot) == []


def test_errors_are_recorded_even_when_alerts_are_muted(bot):
    bot.prefs.toggle('notify_errors')           # -> off
    bot.notify_error('silent but recorded')
    assert _queued(bot) == []
    assert bot.error_count() == 1


# ── preference persistence ────────────────────────────────────────────────
def test_preferences_persist_across_restarts(tmp_path):
    path = str(tmp_path / 'p.json')
    a = TelegramPrefs(path)
    flipped = a.toggle('heartbeat')              # whatever the .env default was, flip it
    target = a.cycle_interval()
    b = TelegramPrefs(path)
    assert b.get('heartbeat') is flipped
    assert b.get(INTERVAL_KEY) == target


def test_corrupt_preferences_file_falls_back_to_env_defaults(tmp_path):
    path = tmp_path / 'p.json'
    path.write_text('{ not json at all')
    p = TelegramPrefs(str(path))
    assert p.get('notify_entries') == SCHEMA['notify_entries'][1]


def test_interval_cycles_through_the_supported_values(tmp_path):
    p = TelegramPrefs(str(tmp_path / 'p.json'))
    seen = {p.cycle_interval() for _ in range(len(INTERVAL_CHOICES))}
    assert seen == set(INTERVAL_CHOICES)


def test_unknown_preference_key_is_rejected(tmp_path):
    p = TelegramPrefs(str(tmp_path / 'p.json'))
    assert p.toggle('nope') is False
    assert 'nope' not in p.as_dict()


# ── menu wiring ───────────────────────────────────────────────────────────
def test_every_callback_on_the_menu_has_a_handler(bot):
    """Analytics and WS status had handlers but no buttons; this keeps the two in step."""
    data = [b['callback_data'] for row in bot._main_keyboard()['inline_keyboard'] for b in row]
    data += [b['callback_data'] for row in bot._prefs_keyboard()['inline_keyboard'] for b in row]
    data += [b['callback_data'] for row in bot._errors_keyboard()['inline_keyboard'] for b in row]
    for d in data:
        if d.startswith('pf:'):
            assert d[3:] in SCHEMA
        else:
            assert d in bot._callbacks, f"button '{d}' has no handler"


def test_callback_data_stays_within_telegrams_64_byte_limit(bot):
    for kb in (bot._main_keyboard(), bot._prefs_keyboard(), bot._errors_keyboard()):
        for row in kb['inline_keyboard']:
            for b in row:
                assert len(b['callback_data'].encode()) <= 64


# ── heartbeat defaults come from .env ─────────────────────────────────────
def test_heartbeat_default_comes_from_env(monkeypatch, tmp_path):
    """With no prefs file the heartbeat follows TELEGRAM_HEARTBEAT, so enabling it in .env is
    enough — the user does not have to press the button after every fresh install."""
    import importlib
    import config.constants as C
    import core.services.telegram_prefs as P

    monkeypatch.setenv('TELEGRAM_HEARTBEAT', 'true')
    monkeypatch.setenv('TELEGRAM_HEARTBEAT_MIN', '30')
    importlib.reload(C)
    importlib.reload(P)
    try:
        p = P.TelegramPrefs(str(tmp_path / 'a.json'))
        assert p.get('heartbeat') is True
        assert p.get(P.INTERVAL_KEY) == 30

        monkeypatch.setenv('TELEGRAM_HEARTBEAT', 'false')
        importlib.reload(C)
        importlib.reload(P)
        assert P.TelegramPrefs(str(tmp_path / 'b.json')).get('heartbeat') is False
    finally:
        importlib.reload(C)
        importlib.reload(P)


def test_out_of_range_interval_falls_back(monkeypatch, tmp_path):
    """The menu cycles the interval by index into INTERVAL_CHOICES, so an unsupported .env
    value would leave that button stuck."""
    import importlib
    import config.constants as C
    import core.services.telegram_prefs as P

    monkeypatch.setenv('TELEGRAM_HEARTBEAT_MIN', '7')
    importlib.reload(C)
    importlib.reload(P)
    try:
        p = P.TelegramPrefs(str(tmp_path / 'c.json'))
        assert p.get(P.INTERVAL_KEY) in P.INTERVAL_CHOICES
        assert p.cycle_interval() in P.INTERVAL_CHOICES
    finally:
        importlib.reload(C)
        importlib.reload(P)


def test_a_saved_preference_still_beats_the_env_default(monkeypatch, tmp_path):
    """Once the user has toggled it from the chat, their choice wins over .env."""
    import importlib
    import config.constants as C
    import core.services.telegram_prefs as P

    monkeypatch.setenv('TELEGRAM_HEARTBEAT', 'true')
    importlib.reload(C)
    importlib.reload(P)
    try:
        path = str(tmp_path / 'd.json')
        a = P.TelegramPrefs(path)
        assert a.get('heartbeat') is True
        a.toggle('heartbeat')                      # user turns it off from the menu
        assert P.TelegramPrefs(path).get('heartbeat') is False
    finally:
        importlib.reload(C)
        importlib.reload(P)
