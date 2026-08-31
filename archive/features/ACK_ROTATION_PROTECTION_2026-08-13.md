# ACK / Strike Rotation Protection Report

Date: 2026-08-13  
Scope: Verified SmartAPI WebSocket behavior, rotation-induced transport stress, and production guard implementation

## Executive summary

The verified evidence supports the following conclusion:

- Strike rotation by itself is not a direct trade-execution fault.
- Rotation is a data-stream and subscription churn trigger.
- When SmartAPI ACKs are delayed or missing, the same rotation path creates a burst of unsubscribe/subscribe work, reconnect pressure, and stale-market-data risk.
- Therefore, the correct solution is not to remove rotation entirely, but to protect it with transport-health guardrails.

This is the right production interpretation: rotation is an optimization feature, but it must be suppressed when the WebSocket layer is unstable.

## Verified facts

### 1) SmartAPI explicitly supports same-connection subscribe/unsubscribe

From the SmartAPI WebSocket docs:

- no need to kill the connection and reconnect for subscribing and unsubscribing
- the existing open connection can be used to subscribe and unsubscribe in real time
- duplicate subscriptions are gracefully ignored
- heartbeat ping every 30 seconds is required to keep connection alive

This fact matters because our project was effectively converting a normal symbol-switch action into a churn-heavy reconnect pattern.

### 2) Rotation path is re-subscription churn

Relevant runtime code:
- [core/trading/broker.py](../../core/trading/broker.py)
- [brokers/angel_one/client.py](../../brokers/angel_one/client.py)

During strike rotation, the bot:

1. resolves a new strike
2. changes the active symbol/token
3. unsubscribes the old token
4. subscribes the new token
5. waits for SmartAPI ACK

This means rotation is not a no-op state update. It is an active data-path reconfiguration.

### 3) ACK timeout turns into local-cache fallback

In the SmartAPI client, each subscribe/unsubscribe registers a correlation ID and waits for ACK. If no ACK arrives within timeout, the client logs the failure and falls back to local-cache state.

This is important because a rotation can look harmless in strategy logic while still creating a hidden transport problem:

- delayed ACK
- local cache fallback
- stale tick reuse
- reconnect pressure
- data distortion risk

### 4) The project has no evidence of direct execution kill from rotation alone

The evidence in the project indicates that:

- rotation correlates with ACK spikes and reconnect churn
- rotation is not proven to directly break order placement or exit execution by itself
- the more defensible conclusion is indirect impact via stale or degraded market data during transport stress

That distinction matters. Rotation is not the same as an order execution bug.

## Why the execution path is not directly broken

Trade execution and market-data stream are separate layers.

Execution layer:
- order placement / modification / exit
- current symbol and strategy state
- order validation and risk checks

Transport/data layer:
- WebSocket subscription state
- ACK timing
- heartbeat health
- reconnect timing
- stale tick / old token tick contamination

So the correct conclusion is:

- Rotation does not directly “execute a wrong trade” by itself.
- But if rotation causes transport instability, the bot may act on stale or distorted feed data and make wrong decisions indirectly.

In short: rotation is not inherently the execution bug; it is a risk amplifier for data quality and subscription stability.

## Implementation applied

The fix was applied in the broker layer to protect the rotation logic from transport stress, evolving across two stages.

### Stage 1: Added Safeguards (2026-08-13)

In [core/trading/broker.py](../../core/trading/broker.py):

- recent rotation cooldown
- skip rotation while WebSocket circuit breaker is open
- skip rotation if reconnect happened very recently
- skip rotation if recent ACK timeout or transport stress is detected

In [brokers/angel_one/client.py](../../brokers/angel_one/client.py):

- ACK timeout callback triggers the broker disconnect path so transport stress is tracked immediately

### Stage 2: Make-Before-Break Overlapping (2026-08-14)

Following further paper run validation, it was confirmed that sequential strict rotation (`Unsubscribe old` -> `Subscribe new`) was intrinsically risking a data gap and unnecessary `ACK Timeout` bursts.

SmartAPI explicitly supports:
- Concurrent subscriptions
- Safe overlap without breaking the connection

The implemented solution is **Overlapping Subscription (Make-Before-Break)**:
1. When rotating, the system FIRST subscribes to the new token.
2. The system waits for the new token to successfully stream or ACK.
3. The system SECONDARILY unsubscribes from the old token.

This guarantees zero data starvation during strike rotation and mitigates the risk of missing a valid market move due to transport transition lag.

This means the system no longer keeps rotating aggressively while the socket is unstable.

## Regression validation

Validation command executed:

```bash
cd '/home/lora/projects/PTQ-scalping bot' && source venv/bin/activate && pytest tests/test_websocket.py -q
```

Result:

- pass
- 100% of relevant WebSocket regression tests passed

See also:
- [tests/test_websocket.py](../../tests/test_websocket.py)

## Final conclusion

The correct senior-level verdict is:

> Strike rotation is not inherently a direct execution failure. Its real risk is that it amplifies WebSocket stress, ACK timeouts, stale data, and reconnect churn. The correct protection is to gate rotation behind transport-health cooldowns and to avoid rotating when the socket has recently been unstable.

That is the implementation now enforced in the code and validated by the regression tests.

## Related project evidence

- [archive/features/ACK_ROTATION_EVIDENCE_2026-08-12.md](ACK_ROTATION_EVIDENCE_2026-08-12.md)
- [core/engines/state_machine.py](../../core/engines/state_machine.py)
- [core/trading/broker.py](../../core/trading/broker.py)
- [brokers/angel_one/client.py](../../brokers/angel_one/client.py)
- [prc/PRC_STRIKE_ROTATION_INVESTIGATION.md](../../prc/PRC_STRIKE_ROTATION_INVESTIGATION.md)
