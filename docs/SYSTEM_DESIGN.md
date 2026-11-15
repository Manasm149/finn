# FINN system design

What FINN is built to do, how a request flows through it, and how each concern
(identity, access, abuse, cost, failure, observability) is handled at today's scale
and what changes at the next one.

## 1. Requirements that drive the design

| Requirement | Consequence |
|---|---|
| A reviewer opens a link on a phone and it works, with no sign-up | Reading is open to guests; accounts unlock what costs money |
| Free hosting: one small instance, disk wiped on restart, sleeps when idle | Server holds no user data; accounts in config; sessions are signed tokens; warmed cache ships in the image |
| Upstream sources are unofficial and sometimes refuse cloud IPs | Every fetch has a retry, a circuit breaker and a stale fallback; the UI says when it is showing a saved copy |
| Model calls cost money and free tiers rate-limit | Models only read; a role gates them; a daily cap switches them off; outputs are cached forever |
| Answers must be checkable | Every number is computed by code; every quote is verified against its source |

## 2. Architecture

```
            phone (PWA: HTML + JS + CSS, no build step)
            holds: portfolio, rules, triage state, session token
                          │ HTTPS, Authorization: Bearer <token>
                          ▼
 ┌──────────────────────── finn.app (Flask, gunicorn: 1 worker × 8 threads) ─────────────────────────┐
 │ before_request: request id → identify(token → user, role) → model permission → rate limit (api)   │
 │                                                                                                    │
 │  /api/digest ─ single-flight ─► digest.py ─► classify.py, alerts.py, enrich.py                     │
 │  /api/research ───────────────► research.py (pure arithmetic on statements)                        │
 │  /api/narrative ─ background job (context copied) ─► narrative.py ─► llm.py (if permitted)         │
 │  /api/ask ────────────────────► ask.py (BM25 over transcripts ─► llm.py if permitted)              │
 │  /api/auth/*, /api/admin/metrics (admin), /healthz, /readyz                                        │
 │                                                                                                    │
 │ after_request: security headers → metrics (latency per route) → one JSON log line                  │
 └───────────────┬───────────────────────────────────────────────┬────────────────────────────────────┘
                 │                                               │
     sources/* via http.py                              cache.py: one SQLite file
     (retry, circuit breaker, stale fallback)           TTL key-value + model usage ledger
     Yahoo · NSE → BSE · screener.in · PDFs
```

## 3. Request lifecycle

1. **Request ID.** Taken from `X-Request-ID` or generated; returned in the response
   header, written to the log line, and shown in any 500 so a user report maps to a log.
2. **Identify.** A bearer token is verified (signature and age). The role is then read
   from configuration, not from the token, so demoting or removing a user takes effect
   on their next request without a revocation list. An invalid token gets a 401 with
   `signed_out`, and the app drops it and continues as a guest.
3. **Permission.** Whether this request may call a model is set in a context variable;
   background jobs copy the context, so a guest's request can never start a paid job.
4. **Rate limit.** A token bucket per identity (user, or client IP for guests).
5. **Route.** Expensive work is coalesced and charged against a second, smaller bucket.
6. **Finish.** Security headers, latency recorded, one structured log line.

## 4. Authentication

- **Accounts from configuration.** `FINN_USERS="name:role:hash;..."`. Passwords are
  hashed with scrypt (Werkzeug) by `python -m finn.users add NAME ROLE`; plaintext is
  never stored, printed or logged. This survives the free host wiping its disk.
- **Sessions are stateless signed tokens** (`itsdangerous`, HMAC with `FINN_SECRET`,
  7-day expiry). Any instance can verify any token, with no session store. Rotating
  `FINN_SECRET` signs everyone out.
- **No user enumeration.** A wrong password and an unknown user return the same
  message and the same status, and an unknown user still costs one hash computation,
  so response time does not reveal which usernames exist.
- **Brute-force protection.** Sign-in has its own bucket: 5 attempts, refilling one a
  minute, per client IP. Every attempt that reaches the password check, successful or not, goes to the audit trail.
- **Open mode.** With no accounts configured, everyone is an analyst. That is the right
  default on your own machine, and the server says so at start-up.

## 5. Authorization

Ordered roles; a route declares the lowest role it accepts (`@auth.require("admin")`).
A signed-out caller gets 401 ("sign in"); a signed-in caller without the role gets 403.

| Capability | guest | analyst | admin |
|---|:-:|:-:|:-:|
| Digest, alerts, research, ask (rules path) | ✓ | ✓ | ✓ |
| Model reading of filings and transcripts (costs money) | | ✓ | ✓ |
| Request quota: burst / sustained | 60 / 1 per s | 240 / 4 per s | 600 / 10 per s |
| Heavy work (new research run, digest rebuild) per 10 min | 6 | 60 | 200 |
| Operations: latency, error and limit counts, sign-in audit | | | ✓ |

The model gate is enforced where the money is spent (`llm.ready()`), not in the UI, so
no client can bypass it by calling the API directly.

## 6. Rate limiting and abuse

- **Token bucket** per (identity, bucket): bursts are allowed up to the capacity, then
  a steady refill. A 429 carries `Retry-After`, and the app shows it as a sentence.
- **Charged only for real work.** A digest served from the 60-second cache or a
  research job that already exists costs no heavy quota, so normal browsing never hits
  a limit; repeatedly forcing fresh rebuilds does.
- **Input bounds.** At most 40 symbols per request, tickers checked against a pattern,
  thresholds clamped, questions truncated to 300 characters, search to 60.

## 7. Caching

| Data | Where | Lifetime | Why |
|---|---|---|---|
| Prices | SQLite | 30 min | End-of-day data does not move faster |
| Filing lists | SQLite + per-symbol store | 10 min, store kept | Feels live; the store is the fallback when an exchange refuses |
| Fundamentals pages | SQLite | 12 h | Change after results only |
| PDF page text | SQLite | forever | Published documents never change |
| Model outputs | SQLite, by prompt hash | forever | Same prompt, same answer, zero cost |
| Promise ledger per company | SQLite | 7 days, keyed by latest call | Recomputed when a new call appears |
| Built digest | memory | 60 s | Absorbs bursts from many phones |

**Single-flight**: when many phones ask for the same digest at once (market open), the
first request computes it and the rest wait for that result instead of each fetching
from the exchanges. Counted as "coalesced" in the operations view.

## 8. Resilience

- **Retries** with back-off on every upstream call; NSE's cookie session is re-warmed on 401/403.
- **Circuit breaker.** A host that just failed is not called again for 45 seconds, so
  one blocked source costs one timeout per digest, not one per holding.
- **Fallback chain for filings.** NSE → BSE → the last saved copy, labelled as such.
- **Graceful degradation.** No model, a blocked source, a scanned PDF or a missing
  transcript each removes one feature and says which, rather than failing the screen.
  When every exchange is unreachable the app says that, instead of "nothing happened".
- **Health.** `/healthz` (liveness, for the host) and `/readyz` (cache writable; source
  health reported but not required, because FINN degrades rather than going down).

## 9. Cost controls

Rules first (classification, ranking, alerts, all arithmetic: zero cost); a fast model
only on pre-filtered text (~20% of a transcript); a stronger model once per company on
~1 KB of verified facts; outputs cached forever; model use gated to analysts; and a
daily cap (`FINN_LLM_DAILY_CALLS`, `FINN_LLM_DAILY_USD`) after which reading falls back
to rules until the next UTC day. The Engine panel shows calls, cache hits and spend.

## 10. Security

- **Content Security Policy**: scripts only from this origin and no inline handlers
  anywhere (a test enforces it); connections only back to this server; no framing.
- `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, HSTS behind HTTPS.
- All dynamic text is HTML-escaped before rendering.
- Secrets only in environment variables; `.env` is git-ignored; password hashes only.
- **Accepted risk:** the token is kept in `localStorage`, which script injection could
  read. The CSP and escaping are the mitigation; an `HttpOnly` cookie plus CSRF tokens
  is the stronger design once there is a real user base.

## 11. Observability

- One JSON line per API request: time, request ID, route, status, latency, user, role.
- In-process metrics: p50/p95/max latency per route (last 500 requests), status-class
  counts, rate-limited, coalesced, errors, cache hit rate, model usage, source health,
  background job states, and the last 200 sign-in attempts. Admins see them in the app
  (Rules → Operations) or at `/api/admin/metrics`.

## 12. Capacity, today

One digest for 18 holdings needs at most ~36 upstream calls cold (prices and filings
per symbol, run 8 at a time) and none warm. A research run reads up to five transcript
PDFs once, then never again. One free instance comfortably serves a handful of
concurrent users; upstream rate limits, not CPU, are the binding constraint.

## 13. What changes at the next scale

| Concern | Today (one instance) | Next (many instances) |
|---|---|---|
| Accounts | Config + scrypt hashes | Users table in Postgres; OAuth/OIDC (Google) sign-in |
| Sessions | Signed bearer token in localStorage | HttpOnly secure cookie + CSRF token, short-lived access + refresh tokens |
| Rate limits, single-flight, jobs | In memory | Redis (counters with TTL, locks) |
| Cache | SQLite file | Redis for hot keys; object storage for PDF text |
| Background work | Threads in the web process | Queue (Redis/RQ or Celery) + workers; a scheduler polls exchanges once for all users |
| Push | Notifications while open; Telegram via cron | Web Push with stored subscriptions, fanned out from the scheduler |
| Per-user data | On the phone | Server-side portfolios and rules, so alerts reach every device |
| Observability | JSON logs + in-app metrics | OpenTelemetry traces, Prometheus metrics, alerting on p95 and error rate |

The step that matters most is the scheduler: poll each exchange once a minute for the
union of all users' holdings, classify once, and fan out to users, so cost grows with
the number of companies, not the number of users.
