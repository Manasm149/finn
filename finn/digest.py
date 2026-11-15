"""Push side: one call that answers "what changed in my book, and what of it matters?"."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import alerts, cache, classify, config, enrich, http
from .sources import announcements, prices, screener

IST = timezone(timedelta(hours=5, minutes=30))
_MON = {m.lower(): i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_DATES = [
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+([A-Za-z]{3,9})[\s,\-/]+(\d{4})\b"), "dmy"),
    (re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"), "mdy"),
    (re.compile(r"\b(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{4})\b"), "num"),
]


def now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def future_date(text: str, after: datetime):
    """First date in the text that is still ahead of us (a board meeting, a record date)."""
    found = []
    for rx, kind in _DATES:
        for m in rx.finditer(text or ""):
            try:
                if kind == "dmy":
                    d = datetime(int(m.group(3)), _MON[m.group(2)[:3].lower()], int(m.group(1)))
                elif kind == "mdy":
                    d = datetime(int(m.group(3)), _MON[m.group(1)[:3].lower()], int(m.group(2)))
                else:
                    d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (KeyError, ValueError):
                continue
            if after.date() <= d.date() <= (after + timedelta(days=120)).date():
                found.append(d)
    return min(found).strftime("%Y-%m-%d") if found else None


def _load(symbol: str, since: datetime, until: datetime) -> dict:
    out = {"symbol": symbol, "bars": None, "filings": None, "errors": []}
    try:
        out["bars"] = prices.history(symbol)
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"symbol": symbol, "what": "prices", "error": str(e)[:140]})
    try:
        def bse():
            try:
                return screener.company(symbol)["bse_code"]
            except Exception:  # noqa: BLE001
                return None
        out["filings"], saved = announcements.fetch(symbol, since, until, bse_code=bse)
        if saved:
            out["errors"].append({"symbol": symbol, "what": "filings",
                                  "error": "exchange unreachable: showing the last saved copy"})
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"symbol": symbol, "what": "filings", "error": str(e)[:140]})
    return out


def build(holdings: list[dict], start: datetime, end: datetime, rules: dict) -> dict:
    weights = {h["symbol"]: h.get("weight", 0) for h in holdings}
    since = min(start, end - timedelta(days=21))      # look further back for upcoming dates
    with ThreadPoolExecutor(max_workers=8) as pool:
        loaded = list(pool.map(lambda s: _load(s, since, end), weights))

    quotes, movers, errors, names = {}, [], [], {}
    d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    for L in loaded:
        errors += L["errors"]
        bars = L["bars"]
        if not bars:
            continue
        latest = alerts.scan(L["symbol"], bars, rules["vol"], rules["px"], rules["lookback"])
        if not latest:
            continue
        quotes[L["symbol"]] = {k: latest[k] for k in ("close", "pct", "volx", "spark", "wk", "date")}
        sessions = [i for i, b in enumerate(bars) if d0 <= b["d"] <= d1]
        hits = []
        for i in sessions[-15:]:
            a = alerts.scan(L["symbol"], bars[: i + 1], rules["vol"], rules["px"], rules["lookback"])
            if a and a["fired"]:
                hits.append(a)
        if not sessions and latest["fired"] and (end - start) <= timedelta(hours=72):
            latest["stale"] = True                  # weekend: the last session is still the news
            hits.append(latest)
        for a in hits:
            a["text"], a["say"] = alerts.describe(a), alerts.headline(a)
            a["weight"] = weights[L["symbol"]]
            movers.append(a)

    last_move = {}
    for a in sorted(movers, key=lambda x: x["date"]):
        last_move[a["symbol"]] = a
    lo, hi = start.isoformat(), end.isoformat()
    items, upcoming, seen_up = [], [], set()
    for L in loaded:
        for f in L["filings"] or []:
            names.setdefault(f["symbol"], f["company"])
            mv = last_move.get(f["symbol"])
            # a move from the day before a filing (someone knew) to two days after (everyone knew)
            if mv and not (-1 <= (datetime.fromisoformat(mv["date"]) - datetime.fromisoformat(f["ts"][:10])).days <= 2):
                mv = None
            p = classify.prioritise(f, weights.get(f["symbol"], 0), mv, rules)
            if p["sub"] in ("date_notice", "record_date", "declared", "action"):
                when = future_date(f"{f['headline']} {f['text']}", end)
                if when and (f["symbol"], when) not in seen_up:
                    seen_up.add((f["symbol"], when))
                    kind = "Results" if p["sub"] == "date_notice" else "Record date"
                    upcoming.append({"symbol": f["symbol"], "date": when, "what": kind, "id": p["id"],
                                     "url": f["url"], "line": p["line"]})
            if lo <= f["ts"][:19] <= hi:
                items.append(p)

    # One event often arrives as three filings (outcome, press release, deck). Show it once.
    lead: dict[tuple, dict] = {}
    for p in sorted(items, key=lambda x: (-x["rank"], x["ts"])):
        key = (p["symbol"], p["cat"], p["ts"][:10])
        if p["tier"] != "buried" and key in lead:
            lead[key].setdefault("related", []).append(
                {"headline": p["headline"], "url": p["url"], "ts": p["ts"], "line": p["line"]})
            p["folded"] = True
        elif p["tier"] != "buried":
            lead[key] = p
    shown = [p for p in items if not p.get("folded")]
    matters = sorted((p for p in shown if p["tier"] == "matters"), key=lambda x: (-x["rank"], x["ts"]))
    know = sorted((p for p in shown if p["tier"] == "know"), key=lambda x: (-x["rank"], x["ts"]))
    for p in matters:
        if p["cat"] == "results" and p["sub"] == "numbers":
            try:
                fc = p["first_cut"] = enrich.first_cut(p["symbol"], p["ts"])
                rev, pat = fc["rows"][0], fc["rows"][3]
                if fc["fresh"] and rev["yoy"] is not None and pat["yoy"] is not None:
                    word = lambda v: f"{'up' if v >= 0 else 'down'} {abs(v):.0f}%"  # noqa: E731
                    p["filed_as"] = p["line"]
                    p["line"] = f"{fc['period']}: revenue {word(rev['yoy'])} and profit {word(pat['yoy'])} on a year ago"
            except Exception as e:  # noqa: BLE001
                p["first_cut_error"] = str(e)[:120]
    groups: dict[str, dict] = {}
    for p in items:
        if p["tier"] == "buried":
            g = groups.setdefault(p["cat"], {"cat": p["cat"], "label": p["label"], "items": []})
            g["items"].append({k: p[k] for k in ("id", "symbol", "ts", "headline", "line", "url", "sub", "why")})
    for g in groups.values():      # say what kind of "Results" or "News" got buried
        if g["cat"] != "unclassified":
            subs = sorted({i["sub"].replace("_", " ") for i in g["items"]})
            g["label"] += ": " + ", ".join(subs)
    buried = sorted(groups.values(), key=lambda g: -len(g["items"]))
    for s in weights:
        names.setdefault(s, cache.get(f"name:{s}") or s)
        if names[s] != s:
            cache.put(f"name:{s}", names[s])
    n_buried = sum(len(g["items"]) for g in buried)
    return {
        "asof": now().isoformat(timespec="seconds"), "sample": config.SAMPLE,
        "window": {"from": lo, "to": hi}, "rules": rules,
        "counts": {"total": len(items), "matters": len(matters), "know": len(know), "buried": n_buried,
                   "folded": len(items) - len(shown), "movers": len(movers)},
        "movers": sorted(movers, key=lambda a: -(abs(a["pct"]) + a["volx"])),
        "matters": matters, "know": know, "buried": buried,
        "upcoming": sorted(upcoming, key=lambda u: u["date"])[:8],
        "ticks": [{"id": p["id"], "tier": p["tier"]} for p in sorted(items, key=lambda x: x["ts"])],
        "quotes": quotes, "names": names, "weights": weights,
        "errors": errors, "sources": {h: s["ok"] for h, s in http.status.items()},
    }


def find(filing_id: str, holdings: list[dict]) -> dict | None:
    """Re-locate a filing by id (served from the announcement cache, so this is cheap)."""
    end = now()
    d = build(holdings, end - timedelta(days=30), end, dict(config.DEFAULT_RULES))
    for p in d["matters"] + d["know"]:
        if p["id"] == filing_id:
            return p
    return None
