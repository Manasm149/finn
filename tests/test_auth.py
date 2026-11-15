"""Authentication, authorization, rate limiting and the operational surface."""
import pytest

from finn import auth
from finn.app import app

PW = "correct horse battery"


@pytest.fixture()
def accounts(monkeypatch):
    h = auth.hash_password(PW)
    monkeypatch.setenv("FINN_USERS", f"ana:analyst:{h};root:admin:{h}")
    monkeypatch.setenv("FINN_SECRET", "test-secret")
    auth.limiter.reset()
    yield app.test_client()
    auth.limiter.reset()


def login(c, name, pw=PW):
    return c.post("/api/auth/login", json={"username": name, "password": pw})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_guest_can_read_but_not_operate(accounts):
    me = accounts.get("/api/auth/me").get_json()
    assert me["role"] == "guest" and me["mode"] == "accounts" and me["models"] is False
    assert accounts.get("/api/digest?hours=24").status_code == 200
    assert accounts.get("/api/admin/metrics").status_code == 401


def test_login_and_roles(accounts):
    r = login(accounts, "ANA")                        # usernames are case-insensitive
    assert r.status_code == 200 and r.get_json()["me"]["role"] == "analyst"
    tok = r.get_json()["token"]
    assert accounts.get("/api/auth/me", headers=bearer(tok)).get_json()["user"] == "ana"
    assert accounts.get("/api/admin/metrics", headers=bearer(tok)).status_code == 403
    admin = login(accounts, "root").get_json()["token"]
    m = accounts.get("/api/admin/metrics", headers=bearer(admin)).get_json()
    assert m["counts"]["requests"] > 0 and any(a["user"] == "ana" and a["ok"] for a in m["audit"])


def test_bad_credentials_look_identical(accounts):
    wrong_pw, no_user = login(accounts, "ana", "nope"), login(accounts, "nobody", "nope")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()


def test_tampered_or_foreign_tokens_are_rejected(accounts, monkeypatch):
    tok = login(accounts, "ana").get_json()["token"]
    r = accounts.get("/api/meta", headers=bearer(tok[:-2] + "xx"))
    assert r.status_code == 401 and r.get_json()["signed_out"]
    monkeypatch.setenv("FINN_SECRET", "rotated")          # rotating the secret signs everyone out
    assert accounts.get("/api/meta", headers=bearer(tok)).status_code == 401


def test_removing_a_user_revokes_their_token(accounts, monkeypatch):
    tok = login(accounts, "ana").get_json()["token"]
    monkeypatch.setenv("FINN_USERS", f"root:admin:{auth.hash_password(PW)}")
    assert accounts.get("/api/meta", headers=bearer(tok)).status_code == 401


def test_login_is_rate_limited(accounts):
    codes = [login(accounts, "ana", "wrong").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429
    r = login(accounts, "ana")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_guests_get_a_smaller_quota_than_analysts():
    auth.limiter.reset()
    guest = [auth.limiter.take("ip:1", "heavy", "guest") for _ in range(8)]
    analyst = [auth.limiter.take("user:a", "heavy", "analyst") for _ in range(8)]
    assert guest[:6] == [0.0] * 6 and guest[6] > 0 and analyst == [0.0] * 8
    auth.limiter.reset()


def test_open_mode_when_no_accounts(monkeypatch):
    monkeypatch.delenv("FINN_USERS", raising=False)
    c = app.test_client()
    assert c.get("/api/auth/me").get_json()["role"] == "analyst"
    assert c.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 400


def test_security_headers_and_request_id():
    c = app.test_client()
    r = c.get("/", headers={"X-Request-ID": "abc123"})
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Request-ID"] == "abc123"
    assert c.get("/healthz").get_json() == {"ok": True} and c.get("/readyz").status_code == 200


def test_no_inline_script_handlers():
    """The CSP forbids inline handlers, so the app must not contain any."""
    from pathlib import Path
    web = Path(__file__).resolve().parent.parent / "web"
    for f in ("index.html", "app.js"):
        assert "onclick=\"" not in (web / f).read_text()


def test_single_flight_coalesces_concurrent_work():
    import threading
    import time

    from finn import ops
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return 42
    out = []
    ts = [threading.Thread(target=lambda: out.append(ops.flight.do("k", slow))) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [42] * 5 and len(calls) == 1


def test_model_budget_cap(monkeypatch):
    from finn import config, llm
    monkeypatch.setattr(config, "LLM_DAILY_CALLS", 0)
    assert llm.over_budget() is None
    monkeypatch.setattr(config, "LLM_DAILY_CALLS", 1)
    from finn import cache
    cache.log_usage("fast", "m", 10, 10, False, "t")
    assert "daily cap" in llm.over_budget()
