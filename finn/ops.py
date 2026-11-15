"""Operability: request IDs, structured logs, metrics, security headers, request coalescing.

Everything here is in-process and dependency-free on purpose; docs/SYSTEM_DESIGN.md
says what each piece becomes when there is more than one process.
"""
import json
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict, deque
from concurrent.futures import Future

from flask import g, request

STARTED = time.time()
_lock = threading.Lock()
_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
_counts: Counter = Counter()
_status: Counter = Counter()

# Content Security Policy: scripts only from this origin (no inline handlers anywhere),
# fonts only from Google Fonts, API calls only back to this server.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; "
       "worker-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def count(name: str, n: int = 1) -> None:
    with _lock:
        _counts[name] += n


def route_name() -> str:
    rule = request.url_rule.rule if request.url_rule else "static"
    return f"{request.method} {rule}" if rule.startswith("/api") or rule.startswith("/health") else "static"


def begin() -> None:
    g.t0 = time.perf_counter()
    g.rid = (request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:32]


def finish(resp):
    ms = (time.perf_counter() - g.get("t0", time.perf_counter())) * 1000
    name = route_name()
    with _lock:
        _latency[name].append(ms)
        _status[resp.status_code // 100 * 100] += 1
        _counts["requests"] += 1
    resp.headers["X-Request-ID"] = g.get("rid", "")
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    if name != "static":     # one JSON line per API call: greppable, and parseable by any log tool
        print(json.dumps({"ts": round(time.time(), 3), "rid": g.get("rid"), "route": name,
                          "path": request.path, "status": resp.status_code, "ms": round(ms, 1),
                          "user": g.get("user"), "role": g.get("role")}), file=sys.stdout, flush=True)
    return resp


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 1)


def snapshot() -> dict:
    with _lock:
        routes = {k: {"n": len(v), "p50": _pct(v, 50), "p95": _pct(v, 95), "max": round(max(v), 1)}
                  for k, v in _latency.items() if k != "static" and v}
        return {"uptime_s": round(time.time() - STARTED), "counts": dict(_counts),
                "status": {str(k): v for k, v in _status.items()},
                "routes": dict(sorted(routes.items(), key=lambda kv: -(kv[1]["p95"] or 0)))}


class SingleFlight:
    """Concurrent identical requests share one computation.

    When the market opens, many phones ask for the same digest at once. The first
    request computes it; the rest wait for that result instead of each fetching
    18 companies from the exchanges.
    """

    def __init__(self):
        self._inflight: dict[str, Future] = {}
        self._lock = threading.Lock()

    def do(self, key: str, fn):
        with self._lock:
            fut = self._inflight.get(key)
            leader = fut is None
            if leader:
                fut = self._inflight[key] = Future()
        if not leader:
            count("coalesced")
            return fut.result()
        try:
            fut.set_result(fn())
        except Exception as e:  # noqa: BLE001
            fut.set_exception(e)
        finally:
            with self._lock:
                self._inflight.pop(key, None)
        return fut.result()


flight = SingleFlight()
