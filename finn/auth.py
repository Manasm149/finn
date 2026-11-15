"""Authentication, authorization and rate limiting.

Design constraints, and how they shaped this:
  * Reviewers must open the link and use it with no sign-up. So reading is open to
    guests; signing in unlocks what costs money (model reading) and higher limits.
  * The free host wipes its disk on every restart. So accounts are not stored in a
    database: they come from configuration (FINN_USERS, password hashes only), and
    sessions are stateless signed tokens that survive restarts as long as FINN_SECRET does.
  * One process. Rate-limit buckets and the audit trail live in memory; the scaling
    path (Redis) is in docs/SYSTEM_DESIGN.md.

Roles are ordered: guest < analyst < admin. A route declares the lowest role it accepts.
"""
import functools
import os
import secrets
import threading
import time
from collections import deque

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = {"guest": 0, "analyst": 1, "admin": 2}
TOKEN_DAYS = 7

# Who can do what. Shown in the UI and in docs, so it stays the single source of truth.
CAPABILITIES = {
    "guest": ["Read the digest, alerts and research", "Rules-based reading of filings and transcripts",
              "Standard rate limits"],
    "analyst": ["Everything a guest can do", "Model reading of filings and transcripts (costs money)",
                "Higher rate limits"],
    "admin": ["Everything an analyst can do", "Operations: metrics, latency, sign-in audit"],
}

# Per role: bucket -> (capacity, refill per second). Buckets are charged only for work
# that actually runs: a cached answer costs nothing, so it costs no quota either.
LIMITS = {
    "guest":   {"api": (60, 1.0), "heavy": (6, 6 / 600), "login": (5, 5 / 300)},
    "analyst": {"api": (240, 4.0), "heavy": (60, 60 / 600), "login": (5, 5 / 300)},
    "admin":   {"api": (600, 10.0), "heavy": (200, 200 / 600), "login": (5, 5 / 300)},
}

_DUMMY_HASH = generate_password_hash(secrets.token_hex(8))   # equalises timing for unknown users


# ---------- configuration ---------------------------------------------------------------

def _secret() -> str:
    s = os.environ.get("FINN_SECRET", "")
    if not s:
        # Works, but every restart signs everyone out. Set FINN_SECRET in production.
        s = os.environ.setdefault("_FINN_EPHEMERAL_SECRET", secrets.token_urlsafe(32))
    return s


def users() -> dict[str, dict]:
    """FINN_USERS="name:role:hash;name:role:hash". Hashes come from `python -m finn.users add`."""
    out = {}
    for entry in os.environ.get("FINN_USERS", "").split(";"):
        parts = entry.strip().split(":", 2)
        if len(parts) == 3 and parts[1] in ROLES and parts[0]:
            out[parts[0].lower()] = {"name": parts[0].lower(), "role": parts[1], "hash": parts[2]}
    return out


def mode() -> str:
    """'accounts' when users are configured; 'open' otherwise (local use: everyone is an analyst)."""
    return "accounts" if users() else "open"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="finn-session")


# ---------- authentication ---------------------------------------------------------------

def issue(user: dict) -> str:
    return _serializer().dumps({"u": user["name"], "n": secrets.token_hex(4)})


def verify(token: str) -> dict | None:
    """Token -> user, or None. The role is read from configuration on every request, so
    removing a user or demoting them takes effect immediately, without a token blacklist."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    return users().get(str(data.get("u", "")))


def check_password(name: str, password: str) -> dict | None:
    u = users().get((name or "").strip().lower())
    if not u:
        check_password_hash(_DUMMY_HASH, password or "")    # same work either way: no user enumeration
        return None
    return u if check_password_hash(u["hash"], password or "") else None


def identify() -> None:
    """Runs before every request: sets g.user, g.role and g.who (the rate-limit identity)."""
    g.user, g.role = None, "guest"
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        u = verify(header[7:].strip())
        if u:
            g.user, g.role = u["name"], u["role"]
        else:
            g.bad_token = True
    elif mode() == "open":
        g.role = "analyst"
    g.who = f"user:{g.user}" if g.user else f"ip:{client_ip()}"


def client_ip() -> str:
    # Behind Render's proxy the client address is the first X-Forwarded-For hop.
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "unknown"


# ---------- authorization ----------------------------------------------------------------

def at_least(role: str) -> bool:
    return ROLES[getattr(g, "role", "guest")] >= ROLES[role]


def require(role: str):
    """Route decorator: 401 if not signed in when sign-in is needed, 403 if the role is too low."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            if at_least(role):
                return fn(*a, **k)
            if not g.user:
                return jsonify({"error": "Sign in to do this.", "need": role}), 401
            return jsonify({"error": f"This needs the {role} role; you are {g.role}.", "need": role}), 403
        return inner
    return wrap


def models_allowed() -> bool:
    """Model reading costs money, so it is an analyst capability."""
    return at_least("analyst")


# ---------- rate limiting ----------------------------------------------------------------

class TokenBucket:
    """Per-identity token buckets. Allows bursts up to `capacity`, then `rate` per second."""

    def __init__(self):
        self._b: dict[tuple, list] = {}
        self._lock = threading.Lock()

    def take(self, who: str, bucket: str, role: str, cost: float = 1.0) -> float:
        """0 if allowed; otherwise the seconds to wait."""
        cap, rate = LIMITS[role][bucket]
        now = time.monotonic()
        with self._lock:
            tokens, at = self._b.get((who, bucket), (cap, now))
            tokens = min(cap, tokens + (now - at) * rate)
            if tokens >= cost:
                self._b[(who, bucket)] = [tokens - cost, now]
                return 0.0
            self._b[(who, bucket)] = [tokens, now]
            return (cost - tokens) / rate

    def reset(self):
        with self._lock:
            self._b.clear()


limiter = TokenBucket()


def throttle(bucket: str, cost: float = 1.0):
    """None if allowed, else a 429 response with Retry-After."""
    wait = limiter.take(g.who, bucket, g.role, cost)
    if not wait:
        return None
    from . import ops
    ops.count("rate_limited")
    secs = max(1, round(wait))
    resp = jsonify({"error": f"Too many requests. Try again in {secs} seconds.", "retry_after": secs})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(secs)
    return resp


# ---------- audit trail ------------------------------------------------------------------

audit: deque = deque(maxlen=200)


def record(event: str, name: str, ok: bool) -> None:
    audit.appendleft({"ts": time.time(), "event": event, "user": (name or "")[:40], "ok": ok, "ip": client_ip()})


def hash_password(password: str) -> str:
    return generate_password_hash(password)
