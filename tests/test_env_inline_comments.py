"""Regression: config/validator's .env loader writes straight into os.environ, so its parse
wins for every module that reads configuration after validate_config() runs at startup.

It used to keep inline comments inside the value, so

    TRADING_START=09:15   # opened for the full-session experiment

became the literal "09:15   # opened for the full-session experiment". Consumers that
int()-parse it hit ValueError and take their silent fallback — the setting looks applied while
the old default is actually in force. Found by a pre-flight on 2026-09-04, where it would have
quietly re-closed the morning trading window that had just been opened.
"""
import os
import pytest

from config.validator import _strip_inline_comment, ConfigValidator


@pytest.mark.parametrize("raw,expected", [
    ("09:15   # was 09:20", "09:15"),
    ("15:25", "15:25"),
    ("false      # note: never enforced", "false"),
    ("  9:15\t# tab-separated comment", "9:15"),
    ('"a # b"', "a # b"),          # quoted values are taken verbatim
    ("'keep # me'", "keep # me"),
    ("abc#def", "abc#def"),        # no whitespace before '#' is not a comment
    ("", ""),
])
def test_inline_comments_are_stripped_like_dotenv(raw, expected):
    assert _strip_inline_comment(raw) == expected


def test_a_commented_time_value_stays_int_parseable(tmp_path, monkeypatch):
    """End-to-end: a commented time in .env must survive the loader intact."""
    env = tmp_path / ".env"
    env.write_text(
        "TRADING_START=09:15   # opened for the full-session experiment\n"
        "TRADING_END=15:25     # matches the 15:25 market-close exit\n"
    )
    monkeypatch.delenv("TRADING_START", raising=False)
    monkeypatch.delenv("TRADING_END", raising=False)
    v = ConfigValidator(str(env)) if "env_path" in ConfigValidator.__init__.__code__.co_varnames \
        else ConfigValidator()
    v.env_path = str(env)
    v._env_vars = {}
    v.load_env()
    assert v.get_env_value("TRADING_START") == "09:15"
    assert os.environ["TRADING_START"] == "09:15"
    # the actual failure mode: this used to raise ValueError and fall back to the old default
    assert tuple(map(int, os.environ["TRADING_START"].split(":"))) == (9, 15)
    assert tuple(map(int, os.environ["TRADING_END"].split(":"))) == (15, 25)
