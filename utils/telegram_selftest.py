"""Exercise the Telegram dashboard without starting the trading bot.

The bot itself sleeps in pre-market standby outside market hours, so there is no way to check
the chat integration from the running system except during a session. This connects only to
Telegram: no broker login, no websocket, no orders, no market dependency.

    python utils/telegram_selftest.py [minutes]

Sends a startup card with the live keyboard, seeds one sample error so the 🐞 menu has
something in it, then stays up for `minutes` so buttons and commands can be pressed for real.
"""
import sys
import time
from datetime import datetime

sys.path.insert(0, __file__.rsplit('/utils/', 1)[0])

from config.constants import (
    TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    TELEGRAM_HEARTBEAT, TELEGRAM_HEARTBEAT_MIN,
)
from core.services.telegram_bot import init_telegram
from core.services.telegram_prefs import INTERVAL_KEY


class _FakeState:
    """Stand-in for the trading state so the dashboard renders with plausible numbers."""
    state = "SELFTEST"
    daily_pnl_inr = 0.0
    trades_today = 0
    wins_today = 0
    losses_today = 0
    consecutive_losses = 0
    current_trade = None
    day_type = "NORMAL"
    loop_count = 0


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

    print("Telegram self-test")
    print(f"  enabled : {TELEGRAM_ENABLED}")
    print(f"  token   : {'set' if TELEGRAM_BOT_TOKEN else 'MISSING'} ({len(TELEGRAM_BOT_TOKEN)} chars)")
    print(f"  chat id : {'set' if TELEGRAM_CHAT_ID else 'MISSING'}")
    print(f"  heartbeat default: {TELEGRAM_HEARTBEAT} every {TELEGRAM_HEARTBEAT_MIN} min")
    if not (TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("  -> not configured; nothing sent")
        return 1

    tg = init_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, True)
    tg.set_state_reference(_FakeState(), broker=None)
    print(f"  prefs   : heartbeat={tg.prefs.get('heartbeat')} "
          f"interval={tg.prefs.get(INTERVAL_KEY)}min")

    # one sample error so the 🐞 menu is not empty while you look at it
    tg.record_error("self-test sample error — not a real failure", source="selftest")

    tg.send_message(
        f"🧪 <b>Telegram self-test</b> · {datetime.now().strftime('%d %b %H:%M:%S')}\n"
        f"{'━' * 26}\n"
        "The trading bot is <b>not</b> running — this is the dashboard only.\n\n"
        "Try the buttons: 🐞 Errors has one sample entry, ⚙️ Settings toggles are live "
        "and persist.\n"
        f"Heartbeat is <b>{'ON' if tg.prefs.get('heartbeat') else 'OFF'}</b> "
        f"(every {tg.prefs.get(INTERVAL_KEY)} min).\n\n"
        f"<i>Listening for {minutes:.0f} more minutes.</i>",
        reply_markup=tg._main_keyboard(),
    )
    tg.send_message(tg._build_heartbeat_text())

    print(f"  sent. listening {minutes:.0f} min — press buttons in Telegram now")
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline:
            time.sleep(2)
    except KeyboardInterrupt:
        print("  interrupted")
    tg.send_message("🧪 <b>Self-test finished</b> — buttons will stop responding now.")
    time.sleep(3)
    tg.stop()
    print(f"  done. errors recorded this run: {tg.error_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
