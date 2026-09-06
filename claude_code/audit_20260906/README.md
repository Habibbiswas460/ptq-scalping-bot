# Full project audit — 2026-09-06 (IN PROGRESS)

Seven parallel audits of the whole project. This directory is the durable record so the
work survives a session boundary.

## Status

| # | scope | agent status | report file |
|---|-------|--------------|-------------|
| 1 | Database & data integrity        | **DONE** | `01-data.md` |
| 2 | Architecture & code quality      | **DONE** | `02-architecture.md` |
| 3 | Strategy & entry signal          | **DONE** | `03-strategy.md` |
| 4 | Trade management, exits, risk    | **DONE** | `04-trade-management.md` |
| 5 | Research & visual instrument     | **DONE** | `05-instrument.md` |
| 6 | Broker integration & market data | **DONE** | `06-broker.md` |
| 7 | Operations, security, compliance | **DONE** | `07-ops.md` |

`verified.md` holds MY OWN checks of agent claims — agents are not taken at face value.
Where a claim was overstated it is corrected there, with evidence.

## Constraints every agent was given

- read-only on the project
- must NOT run run.sh / app.py / core.main, and must NOT log in to the broker
  (a stray paper run on 2026-09-06 accidentally connected to the live account)
- every claim needs a number or a `file.py:line`
- must state explicitly what could not be verified

## If the session ended before this finished

Agents are session-scoped: any still "running" above died with the session and must be
re-run. The finished reports in this directory stand on their own. The remaining work is:
re-run the missing scopes, reconcile against `verified.md`, then build the HTML report.
