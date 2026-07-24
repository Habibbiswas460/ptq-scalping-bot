# Production Evidence Report

Date: 2026-07-06
Scope: WebSocket Reliability Hardening (infrastructure only)
Status: Ready for paper deployment with monitored ACK fallback

## 1. Evidence Sources

- Code changes:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py)
  - [core/trading/broker.py](core/trading/broker.py)
  - [tests/test_websocket.py](tests/test_websocket.py)
- Runtime logs and artifacts:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log)
  - [logs/2026-07-06/summary.json](logs/2026-07-06/summary.json)
  - [logs/readiness/latest_readiness.json](logs/readiness/latest_readiness.json)
  - [logs/2026-07-06/pytest_full_20260706.txt](logs/2026-07-06/pytest_full_20260706.txt)

## 2. Implementation Evidence (Code)

### 2.1 Client ACK and cache reliability hardening

- Added explicit WS lifecycle and pending ACK state:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L220)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L224)
- Stop path now clears runtime WS state and pending ACK maps:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1307)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1321)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1324)
- Pre-send ACK waiter registration and timeout handling:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1361)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1417)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1432)
- Token dedup/sanitization and cache sync/remove helpers:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1369)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1381)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1395)
- Subscribe hardening (duplicate skip, usability guards, fallback cache sync):
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1461)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1488)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1521)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1536)
- Unsubscribe hardening with symmetric ACK/fallback behavior:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1549)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1602)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1616)
- ACK observability and unmatched ACK diagnostics:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1677)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1684)
- Manual-close and non-primary-close reconnect suppression:
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1716)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1731)
  - [brokers/angel_one/client.py](brokers/angel_one/client.py#L1734)

### 2.2 Broker reconnect/shutdown hardening

- Added shutdown control flags and event state:
  - [core/trading/broker.py](core/trading/broker.py#L105)
  - [core/trading/broker.py](core/trading/broker.py#L108)
- Reset shutdown flags on connect:
  - [core/trading/broker.py](core/trading/broker.py#L126)
  - [core/trading/broker.py](core/trading/broker.py#L128)
- Startup split-subscribe sequencing (spot first, option second):
  - [core/trading/broker.py](core/trading/broker.py#L582)
  - [core/trading/broker.py](core/trading/broker.py#L590)
  - [core/trading/broker.py](core/trading/broker.py#L593)
- Suppress reconnect behavior during shutdown:
  - [core/trading/broker.py](core/trading/broker.py#L617)
  - [core/trading/broker.py](core/trading/broker.py#L619)
  - [core/trading/broker.py](core/trading/broker.py#L634)
  - [core/trading/broker.py](core/trading/broker.py#L647)
- Heartbeat monitor obeys shutdown/stop event:
  - [core/trading/broker.py](core/trading/broker.py#L723)
- Logout cleanup now shutdown-aware with heartbeat join:
  - [core/trading/broker.py](core/trading/broker.py#L1782)
  - [core/trading/broker.py](core/trading/broker.py#L1784)
  - [core/trading/broker.py](core/trading/broker.py#L1795)

## 3. Test Evidence

### 3.1 Regression tests added/validated

- Reconnect guard tests:
  - [tests/test_websocket.py](tests/test_websocket.py#L121)
- Split subscribe startup tests:
  - [tests/test_websocket.py](tests/test_websocket.py#L150)
- Client reliability tests:
  - [tests/test_websocket.py](tests/test_websocket.py#L204)
- Broker reliability tests:
  - [tests/test_websocket.py](tests/test_websocket.py#L278)

### 3.2 Full test suite proof

- Full suite output saved in workspace:
  - [logs/2026-07-06/pytest_full_20260706.txt](logs/2026-07-06/pytest_full_20260706.txt)
- Result: completed to 100% and command exited with code 0.

## 4. Runtime Evidence

### 4.1 Split subscribe behavior observed in runtime

- Earlier behavior (single mixed token subscribe in one attempt):
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L54943)
- Hardened split behavior (spot then option in separate subscribe attempts):
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55126)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55130)

### 4.2 ACK behavior and fallback evidence

- ACK timeout lines with correlation IDs:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55208)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55213)
- Explicit fallback path used on no ACK:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55209)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55214)
- Cache synchronization during fallback is visible:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55210)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55245)

### 4.3 Reconnect reliability evidence

- Heartbeat-triggered reconnect:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55231)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55233)
- Successful reconnect confirmation:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55257)
- Runtime cache clear during reconnect/lifecycle cleanup:
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55237)
  - [logs/2026-07-06/bot.log](logs/2026-07-06/bot.log#L55265)

## 5. Operational Gate Evidence

### 5.1 Readiness checker (pass)

- Readiness report artifact:
  - [logs/readiness/latest_readiness.json](logs/readiness/latest_readiness.json)
- Key pass points:
  - overall_ready = true
  - WebSocket connected
  - REST API pass
  - Spot/CE/PE feed pass
  - Tick latency median 494ms, p95 996ms
  - Circuit breaker open false
  - Paper mode enabled with live data

### 5.2 Session summary context

- Session summary artifact:
  - [logs/2026-07-06/summary.json](logs/2026-07-06/summary.json)
- This file confirms session counters and kill-switch statistics for the day.

## 6. Residual Risks

1. Upstream ACK frames remain intermittently absent, so fallback path remains a required reliability layer.
2. Runtime monitoring should continue for:
   - ACK timeout rate
   - reconnect frequency
   - cache rebuild/clear churn

## 7. Production Readiness Verdict

- Readiness Score: 88/100
- Verdict: GO for paper deployment with monitored fallback
- Constraint: Keep ACK-timeout and reconnect dashboards/log alerts active in early deployment windows.
