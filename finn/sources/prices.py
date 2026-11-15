"""End-of-day price and volume. Yahoo's chart endpoint (what yfinance wraps), .NS then .BO."""
from datetime import datetime, timedelta, timezone

from .. import cache, http

IST = timezone(timedelta(hours=5, minutes=30))


def _parse(payload: dict) -> list[dict]:
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        c, v = q["close"][i], q["volume"][i]
        if c is None:
            continue
        bars.append({"d": datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d"),
                     "o": q["open"][i], "h": q["high"][i], "l": q["low"][i],
                     "c": round(c, 2), "v": int(v or 0)})
    return bars


def history(symbol: str, rng: str = "1y") -> list[dict]:
    """Daily bars, oldest first. Cached 30 min: EOD data does not move faster than that."""
    def load():
        err = None
        for suffix in (".NS", ".BO"):
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}{suffix}"
                   f"?range={rng}&interval=1d")
            try:
                bars = _parse(http.fetch(url, "json"))
                if bars:
                    return bars
            except Exception as e:  # noqa: BLE001
                err = e
        try:   # last resort: the yfinance package, if installed
            import yfinance as yf
            df = yf.Ticker(symbol + ".NS").history(period=rng, interval="1d")
            return [{"d": i.strftime("%Y-%m-%d"), "o": float(r.Open), "h": float(r.High),
                     "l": float(r.Low), "c": round(float(r.Close), 2), "v": int(r.Volume)}
                    for i, r in df.iterrows()]
        except Exception:  # noqa: BLE001
            raise RuntimeError(f"no price data for {symbol}: {err}")
    return cache.cached(f"px:{symbol}:{rng}", 1800, load)
