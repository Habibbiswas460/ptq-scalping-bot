# P0 LIVE SESSION RESCUE REPORT

Date: 2026-08-17 (Live Session / Paper Mode)
Scope: WebSocket Stability, ACK Timeout Loop, Historical Market-Closed Gap

## 1. Problem Discovery (Live Diagnostic)
During the live paper session on 17 August 2026, the bot entered a severe, continuous disconnect/reconnect spiral immediately upon startup. The following symptoms were observed:
- `Heartbeat FAILED: No tick for 30s` continuously triggering reconnects during the 09:10 - 09:15 AM pre-market phase.
- `ACK Timeout` during every subscribe attempt causing an immediate, hard severance of the WebSocket connection.
- `Historical API loaded 1 canonical 5-min candles` instead of the expected 100 historical warm-up candles.

## 2. Root Cause Analysis
The diagnostics revealed that three deeply interconnected infrastructure layers collided to destroy transport stability:

1. **The ACK Disconnect Loop:** `client.py`'s `_wait_for_ack` was wired to call a hard disconnect callback whenever a subscription ACK timed out. Because SmartAPI often fails to return perfectly matching correlation IDs (or returns text late under load), the 5-second timeout blindly crashed the socket during every successful rotation or login, masking the successful "Make-Before-Break" overlap logic natively implemented.
2. **Pre-Market Heartbeat Severance:** The heartbeat monitor rigidly forced a hard disconnect anytime 30 seconds passed without a valid market tick. During the 09:10-09:15 pre-market phase wait (and weekends), there are zero ticks by design. The monitor interpreted this organically quiet interval as a dead connection.
3. **Historical API Weekend Gap:** The P0 implementation requested `days_back=2`. Executed on Monday morning, this only reached back to Saturday morning—a period where the market was closed, meaning almost 0 canonical candles existed to seed the structural memory.

## 3. Emergency Safe Fixes Applied
Immediate non-destructive patches were injected and deployed to the live paper instance to stabilize the connection layer without damaging any execution scoring logic.

- **ACK Rescue:** The ACK timeout in `client.py` no longer triggers the `_broker_ws_disconnect_cb("ACK timeout")`. Instead, it fires `_broker_ws_ack_timeout_cb`, pushing transport stress tracking to the broker's native cool-down mechanisms safely, leaving the underlying socket alive and active.
- **Heartbeat Rescue:** `_start_ws_heartbeat_monitor` was mathematically modified natively in `broker.py`. If `(has_usable_cache and original_tick_age < 120)` OR the time is strictly BEFORE 09:15 AM, OR the day is the weekend, the bot overrides the silent tick-void and suppresses the hard disconnect crash gracefully.
- **Historical Data Rescue:** Scaled the historical `days_back` argument parameter natively inside `main.py` from 2 days to **5 days**. This guarantees that Monday mornings easily bridge the market gap to Thursday/Friday OHLC histories, enforcing complete stabilization of the `EMA 50` indicator.

## 4. Verdict & Verification
**Infrastructure: RESCUED (GREEN)**
The WebSocket is strictly stabilized and cleanly retains the previously instituted Make-Before-Break strategy. The infrastructure patches cleared 100% of the regression rules successfully (`pytest -vv -x` status pass). The session was allowed to continue safely mapping valid ticks and capturing 100 periods of warmup context confidently.
