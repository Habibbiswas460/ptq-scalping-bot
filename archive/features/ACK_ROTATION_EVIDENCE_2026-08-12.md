# ACK / Strike Rotation Evidence Report

Date: 2026-08-12
Scope: SmartAPI WebSocket ACK behavior, strike rotation side effects, and mitigation direction

## Executive summary

The runtime evidence supports a focused conclusion:

- Strike rotation improves premium alignment in many cases.
- However, strike rotation also creates subscription/unsubscription churn and concentrates ACK timeout and fallback traffic around rotation windows.
- The observed evidence does not establish a direct active-session tick-stream collapse or execution halt caused solely by strike rotation.
- The more defensible interpretation is that strike rotation is a transport-load amplifier, not a direct fatal fault by itself.

In short: rotation is not the root cause of a full system break, but it is a meaningful risk amplifier for WebSocket ACK stress.

## Evidence chain

### 1) Rotation is triggered by a timer

Relevant code:
- `core/engines/state_machine.py`
- `STRIKE_ROTATION_INTERVAL = 60`

The idle-state loop checks strike rotation every 60 seconds and invokes the broker rotation logic if the current strike is out of range or drifted too far from spot.

### 2) Rotation changes token and re-subscribes

Relevant code:
- `core/trading/broker.py`

During rotation:
- old strike is replaced by the new strike
- current symbol/token is rebuilt
- WebSocket unsubscribe is attempted for the old token
- WebSocket subscribe is attempted for the new token

This means rotation is not a passive state update; it is an active data-stream reconfiguration step.

### 3) WebSocket subscribe/unsubscribe waits for SmartAPI ACK

Relevant code:
- `brokers/angel_one/client.py`

The client logic does this:
- register a correlation ID
- send subscribe/unsubscribe message
- wait for ACK using `_wait_for_ack(correlation_id, timeout=5.0)`
- if no ACK arrives, log timeout and fall back to local-cache state

This means a rotation is inherently coupled to ACK timing and subscription recovery.

### 4) The project’s own audit supports this interpretation

Relevant report:
- `prc/PRC_STRIKE_ROTATION_INVESTIGATION.md`

The audit conclusion states:
- strike rotation improved premium normalization
- it also introduced measurable transport-side load
- no clear active-session tick loss was established from rotation
- no direct runtime degradation was clearly established in the observed window

## Why ACK warnings cluster around rotation time

The observed pattern is structurally consistent with the code:

1. rotation triggers new token subscription
2. new subscribe/unsubscribe messages create burst traffic
3. SmartAPI ACK may be delayed or absent under load
4. broker logs `ACK Timeout` and local-cache fallback
5. system keeps running using fallback state

This creates a direct time-correlation between rotation windows and ACK warnings, even if the system remains operational.

## Risk interpretation

### Likely real risk
- WebSocket churn
- ACK timeout concentration
- fallback state activation
- reconnect timing pressure

### Not yet proven
- direct trade position loss caused by rotation alone
- direct session-wide feed collapse caused by rotation alone
- causal trade destruction attributable only to strike rotation

## Recommended protection strategy

The correct fix is not to disable strike rotation entirely, but to make it safer and less disruptive.

### Strong mitigation plan

1. Rotation must be guarded by cooldown
   - minimum time between rotations
   - e.g. 2–5 minutes depending on volatility and connection health

2. Rotation should pause when stream is unstable
   - recent ACK timeout
   - recent reconnect event
   - active WebSocket circuit breaker open

3. Rotation should be secondary to transport stability
   - the system should prefer current symbol continuity over aggressive premium optimization when the feed is stressed

4. Use circuit-breaker and fallback logic as first-class protection
   - current safeguards already exist in the broker and risk layer
   - rotation should plug into the same health signal path

5. Overlapping Subscription (Make-Before-Break)
   - Ensure new token subscription overlaps with the old one.
   - Do not unsubscribe the old token before the new one is validated to avoid data starvation.

## Final conclusion

The evidence supports the following conclusion:

Strike rotation is a meaningful optimization feature, but it also acts as a transport-pressure trigger. The ACK warnings seen around rotation times are not random noise; they are consistent with the actual rotation + re-subscribe flow. However, the evidence does not yet show that rotation directly kills trades or positions. The right corrective path is to add guardrails, cooldowns, and health-based suppression around rotation so transport stability is preserved while the premium-alignment benefit remains available.

## Attachments / related project evidence

- `prc/PRC_STRIKE_ROTATION_INVESTIGATION.md`
- `core/engines/state_machine.py`
- `core/trading/broker.py`
- `brokers/angel_one/client.py`
- `core/risk/kill_switch.py`
- `core/trading/broker.py` circuit-breaker logic
