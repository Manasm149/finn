"""Threshold alerts on end-of-day data. The investor defines "unusual"; this watches for it."""
from statistics import mean


def scan(symbol: str, bars: list[dict], vol_x: float = 2.0, px_pct: float = 4.0, lookback: int = 20):
    """Stats for the latest session, plus `fired` listing which thresholds were crossed."""
    if len(bars) < 3:
        return None
    last, prev = bars[-1], bars[-2]
    pct = (last["c"] / prev["c"] - 1) * 100 if prev["c"] else 0.0
    window = [b["v"] for b in bars[-1 - lookback:-1] if b["v"]]
    avg = mean(window) if window else 0
    volx = last["v"] / avg if avg else 0.0
    fired = []
    if abs(pct) >= px_pct:
        fired.append("price")
    if volx >= vol_x:
        fired.append("volume")
    # How rare is this? Count sessions back to the last move at least this large.
    rarity = None
    if fired:
        n = 0
        for i in range(len(bars) - 2, 0, -1):
            p = (bars[i]["c"] / bars[i - 1]["c"] - 1) * 100 if bars[i - 1]["c"] else 0
            if abs(p) >= abs(pct):
                break
            n += 1
        rarity = n
    closes = [b["c"] for b in bars[-252:]]
    return {
        "symbol": symbol, "date": last["d"], "close": last["c"], "pct": round(pct, 2),
        "volx": round(volx, 2), "volume": last["v"], "fired": fired, "rarity": rarity,
        "sessions": len(bars) - 1,
        "hi52": max(closes), "lo52": min(closes),
        "at_high": last["c"] >= max(closes) * 0.999, "at_low": last["c"] <= min(closes) * 1.001,
        "spark": [b["c"] for b in bars[-30:]],
        "wk": round((last["c"] / bars[-6]["c"] - 1) * 100, 2) if len(bars) > 6 else None,
    }


def describe(a: dict) -> str:
    """Context only: the size of the move is already on screen next to this text."""
    bits = []
    if "price" in a["fired"] and a["rarity"] and a["rarity"] >= 20:
        if a["rarity"] >= a["sessions"] - 1 and a["sessions"] >= 200:
            bits.append("biggest daily move in over a year")
        else:
            bits.append(f"biggest daily move in {a['rarity']} sessions")
    if a["at_high"]:
        bits.append("at a 52-week high")
    elif a["at_low"]:
        bits.append("at a 52-week low")
    if not bits:
        if a["fired"] == ["volume"]:
            bits.append("heavy volume without a big price move")
        elif "volume" in a["fired"]:
            bits.append("price and volume both past your thresholds")
        else:
            bits.append("past your price threshold on ordinary volume")
    return ", ".join(bits)


def headline(a: dict) -> str:
    """Spoken / notification form: says the move itself."""
    parts = []
    if "price" in a["fired"]:
        parts.append(f"{'up' if a['pct'] > 0 else 'down'} {abs(a['pct']):.1f} percent")
    if "volume" in a["fired"]:
        parts.append(f"{a['volx']:.1f} times usual volume")
    return " on ".join(parts)
