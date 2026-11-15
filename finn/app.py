"""HTTP API + static frontend.

Request path: begin (request id, timer) -> identify (token -> user, role) -> limits ->
route -> finish (security headers, metrics, one JSON log line).

The server keeps no per-user data: the phone holds the portfolio, rules and triage
state, and a session is a signed token. So any instance can serve any request, and a
restart loses nothing but caches.
"""
import contextvars
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, request, send_from_directory

from . import ask, auth, cache, classify, config, digest, enrich, http, llm, narrative, ops, research
from .sources import screener

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False     # keep our own ordering (filing types by importance)
_digests: dict[str, tuple[float, dict]] = {}
_items: dict[str, dict] = {}
_jobs: dict[str, dict] = {}


# ---------- request lifecycle ------------------------------------------------------------

@app.before_request
def before():
    ops.begin()
    auth.identify()
    llm.allowed.set(auth.models_allowed())
    if request.path.startswith("/api/") and not request.path.startswith("/api/auth/"):
        if g.get("bad_token"):
            return jsonify({"error": "Your session has expired. Sign in again.", "signed_out": True}), 401
        return auth.throttle("api")
    return None


@app.after_request
def after(resp):
    if request.path.startswith("/api/") or request.path.startswith("/health"):
        resp.headers["Cache-Control"] = "no-store"
    return ops.finish(resp)


@app.errorhandler(Exception)
def crashed(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    ops.count("errors")
    app.logger.exception("unhandled error rid=%s", g.get("rid"))
    return jsonify({"error": "Something went wrong on the server.", "request_id": g.get("rid")}), 500


# ---------- inputs -----------------------------------------------------------------------

def _holdings() -> list[dict]:
    """?symbols=TCS:7,INFY:5 from the client, else the default book."""
    raw = request.values.get("symbols", "")
    out = []
    for part in raw.split(","):
        if part.strip():
            sym, _, w = part.partition(":")
            sym = sym.strip().upper()
            if not sym.replace("&", "").replace("-", "").isalnum() or len(sym) > 20:
                continue
            try:
                out.append({"symbol": sym, "weight": max(0.0, min(100.0, float(w or 0)))})
            except ValueError:
                continue
    return out[:40] or config.portfolio()


def _rules() -> dict:
    r = dict(config.DEFAULT_RULES)
    a = request.args
    try:
        r["vol"] = min(20, max(1.1, float(a.get("vol", r["vol"]))))
        r["px"] = min(30, max(0.5, float(a.get("px", r["px"]))))
        r["lookback"] = min(120, max(5, int(a.get("lookback", r["lookback"]))))
    except ValueError:
        pass
    r["watch"] = [c for c in a.get("watch", "").split(",") if c in classify.LABELS]
    r["mute"] = [c for c in a.get("mute", "").split(",") if c in classify.LABELS]
    return r


def _me() -> dict:
    return {"user": g.user, "role": g.role, "mode": auth.mode(), "models": llm.ready(),
            "can": auth.CAPABILITIES[g.role]}


# ---------- auth -------------------------------------------------------------------------

@app.post("/api/auth/login")
def login():
    if (limited := auth.throttle("login")) is not None:
        return limited
    body = request.get_json(silent=True) or {}
    name, password = str(body.get("username", ""))[:40], str(body.get("password", ""))[:200]
    if auth.mode() == "open":
        return jsonify({"error": "This server has no accounts configured; everyone already has analyst access."}), 400
    user = auth.check_password(name, password)
    auth.record("login", name.strip().lower(), bool(user))
    if not user:
        return jsonify({"error": "That username and password do not match."}), 401
    g.user, g.role = user["name"], user["role"]
    llm.allowed.set(auth.models_allowed())
    return jsonify({"token": auth.issue(user), "expires_in": auth.TOKEN_DAYS * 86400, "me": _me()})


@app.get("/api/auth/me")
def me():
    return jsonify(_me())


# ---------- health and operations --------------------------------------------------------

@app.get("/healthz")
def healthz():
    """Liveness: the process answers. Used by the host's health check."""
    return jsonify({"ok": True})


@app.get("/readyz")
def readyz():
    """Readiness: the cache is writable. Sources are reported, not required: FINN degrades."""
    try:
        cache.put("ready:probe", time.time())
        db = True
    except Exception:  # noqa: BLE001
        db = False
    return jsonify({"ready": db, "cache": db, "sources": http.status}), (200 if db else 503)


@app.get("/api/admin/metrics")
@auth.require("admin")
def metrics():
    return jsonify({**ops.snapshot(), "cache": cache.stats, "llm": llm.meter(),
                    "sources": http.status, "jobs": {k: v["state"] for k, v in _jobs.items()},
                    "audit": list(auth.audit)[:25], "mode": auth.mode()})


# ---------- product API ------------------------------------------------------------------

@app.get("/api/meta")
def meta():
    return jsonify({"sample": config.SAMPLE, "llm": llm.meter(), "rules": config.DEFAULT_RULES,
                    "portfolio": config.portfolio(), "labels": classify.LABELS,
                    "cache": cache.stats, "me": _me()})


@app.get("/api/digest")
def get_digest():
    end = digest.now()
    a = request.args
    try:
        if a.get("from"):
            start = datetime.fromisoformat(a["from"])
            if a.get("to"):
                end = min(end, datetime.fromisoformat(a["to"]) + timedelta(hours=23, minutes=59))
        else:
            start = end - timedelta(hours=min(24 * 90, max(1, float(a.get("hours", 24)))))
    except ValueError:
        return jsonify({"error": "Dates must look like 2026-11-14."}), 400
    if start >= end:
        return jsonify({"error": "The window ends before it starts."}), 400
    holdings, rules = _holdings(), _rules()
    key = repr((sorted((h["symbol"], h["weight"]) for h in holdings), sorted(rules.items(), key=str),
                start.strftime("%Y%m%d%H") if a.get("from") else a.get("hours", "24"), a.get("to", "")))
    hit = _digests.get(key)
    if hit and time.time() - hit[0] < 60 and not a.get("fresh"):
        ops.count("digest_cache_hit")
        return jsonify(hit[1])
    if (limited := auth.throttle("heavy", 0.25)) is not None:      # a full rebuild is real work
        return limited

    def build():
        d = digest.build(holdings, start, end, rules)
        for p in d["matters"] + d["know"]:
            _items[p["id"]] = p
        _digests[key] = (time.time(), d)
        return d
    return jsonify(ops.flight.do(key, build))


@app.get("/api/filing/<fid>")
def filing(fid):
    item = _items.get(fid) or digest.find(fid, _holdings())
    if not item:
        return jsonify({"error": "That filing is no longer in the window."}), 404
    return jsonify(cache.cached(f"detail:{fid}:{llm.ready()}", cache.FOREVER, lambda: enrich.filing_detail(item)))


@app.get("/api/search")
def search():
    q = request.args.get("q", "").strip()[:60]
    if len(q) < 2:
        return jsonify([])
    try:
        return jsonify(screener.search(q))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Search is unavailable ({e})."}), 502


@app.get("/api/research/<symbol>")
def get_research(symbol):
    try:
        return jsonify(research.build(symbol))
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Could not load fundamentals for {symbol.upper()}: {e}. Try again in a minute."}), 502


@app.get("/api/narrative/<symbol>")
def get_narrative(symbol):
    """Starts the transcript pass on first call; poll the same URL for progress.

    Jobs are keyed by symbol and reading mode, so a guest's rules-only run and an
    analyst's model run never overwrite each other. Only starting a job costs quota.
    """
    sym = symbol.upper()[:20]
    key = f"{sym}:{'model' if llm.ready() else 'rules'}"
    job = _jobs.get(key)
    if not job or (job["state"] == "error" and request.args.get("retry")):
        if (limited := auth.throttle("heavy")) is not None:
            return limited
        job = _jobs[key] = {"state": "running", "steps": [], "result": None, "error": None}
        if config.SERVERLESS:          # no reliable background threads: do the work now, answer when done
            try:
                job["result"], job["state"] = narrative.run(sym, job["steps"].append), "done"
            except Exception as e:  # noqa: BLE001
                job["state"], job["error"] = "error", str(e)[:200]
            return jsonify(job)

        def work():
            try:
                job["result"] = narrative.run(sym, job["steps"].append)
                job["state"] = "done"
            except Exception as e:  # noqa: BLE001
                job["state"], job["error"] = "error", str(e)[:200]
        ctx = contextvars.copy_context()           # carry the caller's model permission into the thread
        threading.Thread(target=ctx.run, args=(work,), daemon=True).start()
    return jsonify(job)


@app.post("/api/ask")
def post_ask():
    body = request.get_json(silent=True) or {}
    q = str(body.get("q", "")).strip()[:300]
    if not q:
        return jsonify({"type": "none", "message": "Ask about a company, or say “what changed”."})
    try:
        return jsonify(ask.route(q, _holdings()))
    except Exception as e:  # noqa: BLE001
        return jsonify({"type": "none", "message": f"That did not work: {e}"})


# ---------- static -----------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(config.WEB_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(config.WEB_DIR, path)


def main():
    import os

    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.protocol_version = "HTTP/1.1"     # keep-alive: phones reuse the connection
    if auth.mode() == "open":
        print("FINN: no FINN_USERS configured, so everyone gets analyst access (fine on your own machine).")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), threaded=True)


if __name__ == "__main__":
    main()
