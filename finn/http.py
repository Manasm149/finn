"""All outbound HTTP goes through here: browser-like headers, retries, cache, sample mode."""
import threading
import time

import requests

from . import cache, config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_sessions: dict[str, requests.Session] = {}
_lock = threading.Lock()
status: dict[str, dict] = {}   # host -> {ok, at, error}: surfaced in the UI


def _session(host: str) -> requests.Session:
    with _lock:
        s = _sessions.get(host)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                              "Accept": "application/json, text/html;q=0.9, */*;q=0.8"})
            _sessions[host] = s
            if host == "www.nseindia.com":   # NSE's API only answers a session that has its cookies
                try:
                    s.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                          timeout=12)
                except requests.RequestException:
                    pass
        return s


def _note(host, ok, error=""):
    status[host] = {"ok": ok, "at": time.time(), "error": str(error)[:160]}


def fetch(url: str, kind: str = "json", ttl: float = 0, headers: dict | None = None,
          timeout: float = 12, tries: int = 2):
    """kind: json | text | bytes. bytes are never cached here (callers cache derived text)."""
    if config.SAMPLE:
        from . import sample
        return sample.respond(url, kind)
    key = f"http:{url}"
    if ttl and kind != "bytes":
        hit = cache.get(key, ttl)
        if hit is not None:
            return hit
    host = url.split("/")[2]
    # Circuit breaker: a host that just failed is not hammered again for 45 seconds, so one
    # blocked source costs the digest one timeout, not one per holding.
    st = status.get(host)
    if kind != "bytes" and st and not st["ok"] and time.time() - st["at"] < 45:
        stale = cache.get(key, stale_ok=True)
        if stale is not None:
            return stale
        raise RuntimeError(f"{host}: unreachable ({st['error']})")
    last = None
    for attempt in range(tries):
        try:
            r = _session(host).get(url, headers=headers or {}, timeout=timeout)
            if r.status_code in (401, 403) and host == "www.nseindia.com":
                with _lock:
                    _sessions.pop(host, None)   # cookies expired: warm up again
            r.raise_for_status()
            out = r.json() if kind == "json" else r.text if kind == "text" else r.content
            _note(host, True)
            if ttl and kind != "bytes":
                cache.put(key, out)
            return out
        except Exception as e:   # noqa: BLE001 - any failure is retried, then reported
            last = e
            time.sleep(0.6 * (attempt + 1))
    _note(host, False, last)
    if kind != "bytes":
        stale = cache.get(key, stale_ok=True)
        if stale is not None:
            return stale
    raise RuntimeError(f"{host}: {last}")
