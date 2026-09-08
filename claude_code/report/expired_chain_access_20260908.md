# Can this project get 1-minute data for EXPIRED NIFTY options?

**Date:** 2026-09-08
**Question:** two reports in this repo contradict each other about whether expired weekly
option chains are obtainable. Settle it by probing, not by reading.
**Code:** `research/backtest/upstox_expired.py` · **Tests:** `tests/test_upstox_expired.py` (47, no network)
**Constraints honoured:** nothing outside the three new files was written. No `.env` value
printed. No account created, no plan or trial activated, no payment authorised. No git
operation, no order API. A live paper session was running throughout; total network spend
was **12 HTTP requests**, paced 6s apart.

---

## 1. The answer, in four lines

| | |
|---|---|
| **Obtainable?** | **Yes in principle, no today.** The route exists and is documented for 1-minute expired NIFTY options. It is closed to this project right now. |
| **What blocks it** | Not the exchange. Three vendor-side gates in series: an **Upstox trading account** (this project has none), an **OAuth access token** (daily), and — documented, not observed — an **Upstox Plus** plan. |
| **Cost** | Subscription **₹0 today** per Upstox's own T&C ("The Plus Plan can be activated for free initially"), with notice promised before it becomes chargeable. The real price is a KYC'd Upstox account plus a daily token refresh. Plus also moves that account's brokerage ₹20 → ₹30/order, which is free to us only while no order is routed through Upstox. |
| **How far back** | **~6 months** of expiries, vendor-stated; 2 years "in the future", vendor-stated. **Neither is verified** — no token existed to check with. |

**Who was right:** *neither report's headline survives.* `backtest_data_20260908.md` §2's
**measurements are correct and I reproduced every one of them**; its **inference is wrong**.
`strategy_sources_20260908.md` §1.1 is **right that the API exists** and right to call the
"hard boundary" wrong, but its "*are* reachable" overstates a route that answers **401 to
every request this project can make**. §5 has the exact wording each got wrong.

---

## 2. What I actually tested

Twelve unauthenticated requests from this host, 2026-09-08 ~13:20 IST. Reproduce the core
four in about 20 seconds:

```
./venv/bin/python -m research.backtest.upstox_expired probe
```

| # | request | result | reading |
|---|---|---|---|
| A | `GET /v2/expired-instruments/expiries?instrument_key=NSE_INDEX\|Nifty 50` | **401 UDAPI100050** "Invalid token used to access API" | route exists, caller refused |
| B | same, with `Authorization: Bearer not-a-real-token-000` | **401 UDAPI100050**, byte-identical | the gate is a real token check, not a missing-header check |
| C | `GET /v3/expired-instruments/expiries?...` | **404 UDAPI100060** "Resource not Found." | the server *can* say "no such route". It does not say that about v2 |
| D | `GET /v2/expired-instruments/option/contract?...&expiry_date=2026-08-05` | **401 UDAPI100050** | " |
| E | `GET /v2/expired-instruments/historical-candle/NSE_FO\|55555\|05-08-2026/1minute/...` | **401 UDAPI100050** | " |
| F | `GET /v3/historical-candle/NSE_FO\|55555\|05-08-2026/minutes/1/...` (free, keyless) | **400 UDAPI1021** "Instrument key is of invalid format" | the free route cannot **parse** an expired key |
| G | `GET /v3/historical-candle/NSE_FO\|55555/minutes/1/...` (free, stale plain token) | **400 UDAPI100011** "Invalid Instrument key" | " |
| H | `GET /v3/historical-candle/NSE_INDEX\|Nifty 50/minutes/1/2026-08-05/2026-08-04` | **200**, real 1-minute bars | control: the network and the free tier are fine |
| I | `GET /v3/historical-candle/NSE_FO\|42615/minutes/1/2026-09-02/2026-09-04` | **200, 1155 rows** | control: a **listed** option works free and keyless |

**The load-bearing contrast is C versus A.** The same server, the same auth state, one
minute apart: `404` for a route that does not exist, `401` for a route that exists and is
refusing this caller. That single pair falsifies "exchange-side archive boundary". An
exchange that had discarded the data would not need to check my token first.

**The second contrast is F/G versus I.** The free v3 endpoint does not merely lack expired
*data* — it rejects the expired *key format* outright. No amount of probing v3, and no
list of guessed tokens, can ever reach an expired contract through it. The seven blind
token probes in `backtest_data_20260908.md` §2 were therefore a test that could only ever
return zero, whatever the archive contained.

**Also verified locally, offline:** `core/data/scripmaster_nifty_nfo.json` (saved
2026-09-08 09:10) holds 2,091 contracts across 18 expiries, the earliest being
**08SEP2026 — today**. Nothing already expired. So §2's claim that the master cannot name
an expired contract is exactly right, and there is no archived snapshot on this host to
recover old tokens from. `data/historical/candles.db` confirms the consequence: every
option row in it belongs to the single `08SEP2026` chain, 2026-08-19…2026-09-04. That is
the 13 sessions.

### What I did NOT test, and cannot

Everything behind the token: real retention depth, real row counts, whether the premiums
reconcile with Angel, and **whether the Plus gate is actually enforced**. `UDAPI1149`
("available exclusively with an Upstox Plus plan subscription") is documented on the
endpoint page and never appeared in any response here, because a 401 fires first. It stays
labelled *documented, unobserved* everywhere in the code.

I could not test it because testing it requires opening an Upstox account and activating a
plan. That is the owner's call, not mine, and the brief forbids it.

---

## 3. What I read (clearly separated from the above)

| claim | source | status |
|---|---|---|
| "This API is available exclusively with an Upstox Plus plan subscription" | Upstox docs, *Get Expiries* | read |
| "covering up to six months of historical expiries" | same page | read |
| "OHLC for expired contracts" listed under Plus, "–" on Basic | upstox.com/plus comparison table | read |
| "The Plus Plan can be activated for free initially. If the plan becomes chargeable in the future, we will notify you in advance of the applicable date." | Upstox Plus T&C PDF, §3 Pricing | read, verbatim |
| Plus brokerage: Equity Options **₹30 per order** (Basic: ₹20) | same PDF, §3 | read, verbatim |
| a 24-hour cooling-off period after each plan switch | same PDF, §2 | read |
| "OHLC data for expired contracts is available from the date the first trade occurred for that contract up to its expiry date" | Upstox staff, community thread 9245 | read |
| "we provide historical expiry data for the last six months… we plan to retain and make available up to 2 years of data for expired contracts in the future" | same thread | read |
| "for minute-level intervals, we recommend keeping the from_date and to_date range within one month" | same thread | read |
| key format `NSE_FO\|<token>\|DD-MM-YYYY`; intervals `1minute…day` | Upstox docs, *Expired Historical Candle Data* | read |
| `rajmaurya0904/bhav` exists (pushed 2026-07-19) and wraps exactly these four endpoints | GitHub API + its README | read |

Two things worth flagging in that list. First, **`bhav` does not prove free access**: its
own README says *"an Upstox Pro account with historical data API access, and an access
token (expires daily around 03:30 IST — generate a fresh one each session)"*, and offers a
bundled Excel dataset for anyone without one. It is corroboration that the endpoints work
**with** a token, which is exactly what my 401s already implied — not evidence they work
without one.

Second, **a price ambiguity I could not resolve.** The T&C PDF says free initially;
`upstox.com/plus/` markets a "7-day free trial" on advanced features. Those two are not
obviously the same thing, and the difference decides whether this is free forever, free
now, or free for a week. **Do not act on the ₹0 figure without confirming it in the
account's own tariff sheet**, which Upstox says is emailed on activation. I did not
activate anything to find out.

---

## 4. What it would buy, if the owner decides it is worth it

Every quantitative result in this project rests on **13 sessions of one option chain**.
Six months of NIFTY weeklies is roughly **26 expiries and ~125 sessions**. If the session
is the clustering unit, confidence intervals narrow by about **√(125/13) ≈ 3.1×**; if the
expiry is, by about **√(26/13) ≈ 1.4×**. Either way it does not change the sign of a
verdict that three independent studies already agree on — it changes whether "no edge" is
a measurement or a suspicion.

Two things it does **not** fix, and they should be said plainly before anyone spends effort:

1. **No historical order book.** This endpoint returns OHLCV + OI. There is still no bid,
   no ask, no spread. A backtest over it must keep charging a *modelled* slippage and
   labelling it an assumption — the same limitation that produced the synthetic bid/ask
   correction. `provenance()` grades `bid`/`ask`/`spread` as `missing`, deliberately.
2. **It carries open interest, which Angel's `getCandleData` does not.** That is a genuine
   gain — OI is the input this project has never had populated — but it is unverified
   until a token exists.

**What activation would require, in order:** an Upstox trading account (KYC) → Plus
activated on it → a developer app (client id/secret, redirect URI) → an OAuth login
minting a token that dies daily ~03:30 IST → `UPSTOX_ACCESS_TOKEN` in the environment.
Steps 1–2 are the owner's decisions and involve a tariff sheet. Nothing in this repo does
any of them.

---

## 5. Verdict on the two reports, in their own words

**`backtest_data_20260908.md` §2 — "The hard boundary: expired option contracts are unreachable"**

- ✅ "The ScripMaster holds **only unexpired contracts**" — confirmed independently today.
- ✅ "Blind token probes … returned **zero rows** on every one" — reproduced, and now
  *explained*: the free v3 route returns `UDAPI1021`/`UDAPI100011` for expired and unknown
  keys respectively. The probe could not have succeeded regardless of the archive.
- ✅ "A listed contract returns data only from its **listing date**" — confirmed.
- ❌ "**Upstox hits the identical boundary** … this is an **exchange-side archive
  boundary**." Wrong. Both vendors hit the same boundary because the same *class* of
  endpoint was tested on both: a current-instrument endpoint. Two vendors agreeing is
  corroboration only when the tests are independent, and these were not.
- ❌ "**There is no route, free or credentialed**, to a NIFTY weekly option that has already
  expired." Wrong on "credentialed". A credentialed route exists and answers 401.

The correct sentence is: *no **free, uncredentialed** route reaches an expired NIFTY
weekly; a credentialed one exists behind an Upstox account, OAuth and (documented) Plus.*

**`strategy_sources_20260908.md` §1.1 — "the hard boundary is wrong"**

- ✅ Right that §2's conclusion is wrong, and right about the endpoint family, the key
  format, the 1-minute interval and the ~6-month depth.
- ✅ Honest about the gap: it flagged the `UDAPI1149`/Plus question as "a caveat I could
  not resolve" and recorded that it could not verify the Plus price.
- ❌ "Expired NIFTY weekly option chains ***are* reachable**, at 1-minute granularity" —
  overstated as a statement about *this project*. They are reachable by an account this
  project does not have. Every request available to us returns 401.
- ⚠ Citing `rajmaurya0904/bhav` as "working code against four endpoints" is accurate but
  easy to misread: that code works *because it holds a token*. It is a reference client,
  not an existence proof of open access.

**Both reports should be read with §1 of this one appended.** Neither is safe to quote
unamended.

---

## 6. The code

`research/backtest/upstox_expired.py` — written against the conventions of `sources.py`,
`fetch.py` and `store.py`, and honest about its own status.

- `probe()` / `classify_probe()` — re-runs the measurement above from code, so the finding
  can be **re-established** later rather than trusted from this document. It sends no
  `Authorization` header, and a test enforces that: if it ever grew one, the 401s would
  stop meaning anything.
- `expiries()` / `option_contracts()` / `expired_candles()` / `expired_range()` — the four
  endpoints. Candles are reversed to oldest-first to match `sources.upstox_candles()`, and
  OI (field 7) is carried, because Angel has none.
- `expired_range()` walks 30-day chunks. **A chunk that fails is recorded with the vendor's
  error code and skipped** — never retried into a different window, never back-filled from
  another source. The hole stays a hole and `store.detect_gaps()` writes it. Same policy as
  `sources.upstox_range()`, deliberately.
- Rows are written under `source="upstox_expired"`, distinct from `"upstox"`, so the two
  views can never silently overwrite each other.
- `credential_status()` returns **names and booleans only**, never a value. Tested.
- `ExpiredSourceError` carries the vendor's own code, so "you have no token", "your plan
  does not include this" and "that contract does not exist" stay three different answers
  instead of one failed fetch.
- `provenance()` grades `option_ohlc`, `option_volume` and `oi` as **`unverified`**, not
  `real`. Nothing fetched through this route may be promoted until
  `verify_against_broker()` has actually run.
- `verify_against_broker()` — **written and never run.** It reconciles expired-route closes
  against the Angel bars already in `candles.db` over shared minutes. The bar it must clear
  is the one the index cross-check already set: 100.0% identical closes, max |diff| 0.00.
  It returns `NO OVERLAP` rather than a pass when there is nothing to compare, and reports
  disagreement as a **result**, not an exception.
- `sanity_check_premiums()` — structural checks (positive prices, OHLC brackets, session
  grid, series actually moves). Necessary, nowhere near sufficient; the reconciliation is
  what decides.

`tests/test_upstox_expired.py` — **47 tests, all passing, none touching the network.** Every
transport is a canned opener. The two that matter most freeze the 2026-09-08 measurement
shape (401-not-404) and guard against a token ever appearing in a return value.

**Not delivered, because it was not reachable:** the sample fetch, the cross-check against
`candles.db`, and the premium sanity run on real bars. Steps 3's "verify it is real" could
not be executed. The verification code exists so that it is one token away, and until it
has run, nothing here should be treated as a second opinion on anything.

---

## 7. Loose ends worth an hour, in priority order

1. **Confirm the Plus price in the account's own tariff sheet** before treating ₹0 as fact.
   The T&C and the marketing page do not obviously agree.
2. **`git log -p core/data/scripmaster_nifty_nfo.json`** — if that cache file was ever
   committed and rewritten over time, its history contains Angel tokens for contracts that
   have since expired, which would be a *free* route to test whether Angel's
   `getCandleData` serves an expired token. I could not run it (no git operations in this
   brief), and the working copy is a single snapshot dated today. This is the one remaining
   free lead and it is cheap to check.
3. **Whether Angel serves an expired token at all.** Untestable today anyway: it needs a
   SmartAPI login, and a live paper session held that session. Do it after the close.
4. `marketcalls/ExpiryTrack` — a bulk downloader for this same API. Same gate; useful only
   after a token exists.
