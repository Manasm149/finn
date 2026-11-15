"""One SQLite file: a TTL key-value cache plus the LLM usage ledger.

Filings, transcripts and model outputs never change once published, so most
keys are cached forever; only prices and "what's new" lists expire.
"""
import json
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
_db = sqlite3.connect(config.DATA_DIR / ("sample.db" if config.SAMPLE else "finn.db"),
                      check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_db.execute("CREATE TABLE IF NOT EXISTS usage (ts REAL, tier TEXT, model TEXT, "
            "tin INT, tout INT, cached INT, task TEXT)")
_db.commit()
stats = {"hit": 0, "miss": 0}

FOREVER = 10 * 365 * 86400


def get(key: str, ttl: float = FOREVER, stale_ok: bool = False):
    with _lock:
        row = _db.execute("SELECT v, ts FROM kv WHERE k=?", (key,)).fetchone()
    if row and (stale_ok or time.time() - row[1] < ttl):
        stats["hit"] += 1
        return json.loads(row[0])
    stats["miss"] += 1
    return None


def age(key: str):
    with _lock:
        row = _db.execute("SELECT ts FROM kv WHERE k=?", (key,)).fetchone()
    return time.time() - row[0] if row else None


def put(key: str, value) -> None:
    with _lock:
        _db.execute("REPLACE INTO kv VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        _db.commit()


def cached(key: str, ttl: float, fn):
    """Return fresh cache, else compute. If computing fails, fall back to a stale copy."""
    hit = get(key, ttl)
    if hit is not None:
        return hit
    try:
        value = fn()
    except Exception:
        stale = get(key, stale_ok=True)
        if stale is not None:
            return stale
        raise
    put(key, value)
    return value


def log_usage(tier, model, tin, tout, cached_, task):
    with _lock:
        _db.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?)",
                    (time.time(), tier, model, tin, tout, int(cached_), task))
        _db.commit()


def usage_summary(since: float = 0.0) -> dict:
    with _lock:
        rows = _db.execute("SELECT tier, SUM(tin), SUM(tout), SUM(cached), COUNT(*) "
                           "FROM usage WHERE ts>=? GROUP BY tier", (since,)).fetchall()
    out = {"calls": 0, "cached": 0, "usd": 0.0, "tiers": {}}
    for tier, tin, tout, c, n in rows:
        pin, pout = config.PRICE.get(tier, (0, 0))
        # cached calls cost nothing: only count tokens for the uncached ones
        with _lock:
            live = _db.execute("SELECT COALESCE(SUM(tin),0), COALESCE(SUM(tout),0) FROM usage "
                               "WHERE ts>=? AND tier=? AND cached=0", (since, tier)).fetchone()
        usd = live[0] / 1e6 * pin + live[1] / 1e6 * pout
        out["tiers"][tier] = {"calls": n, "cached": c, "in": live[0], "out": live[1], "usd": round(usd, 5)}
        out["calls"] += n
        out["cached"] += c
        out["usd"] += usd
    out["usd"] = round(out["usd"], 5)
    return out
