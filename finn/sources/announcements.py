"""Exchange filings for one symbol. NSE first (keyed by symbol), BSE as fallback (needs scrip code).

Both are normalised to one shape:
  {id, symbol, company, ts (ISO, IST), headline, text, url, exch, exch_cat}
"""
import hashlib
from datetime import datetime, timedelta, timezone

from .. import cache, config, http

IST = timezone(timedelta(hours=5, minutes=30))


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=IST).isoformat(timespec="seconds")


def _nse_time(rec: dict) -> datetime:
    for field, fmt in (("an_dt", "%d-%b-%Y %H:%M:%S"), ("sort_date", "%Y-%m-%d %H:%M:%S"),
                       ("exchdisstime", "%d-%b-%Y %H:%M:%S"), ("dt", "%d%m%Y%H%M%S")):
        try:
            return datetime.strptime(str(rec.get(field, "")).strip(), fmt)
        except ValueError:
            continue
    raise ValueError("no timestamp")


def parse_nse(payload, symbol: str) -> list[dict]:
    rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("rows") or []
    out = []
    for r in rows:
        try:
            ts = _nse_time(r)
        except ValueError:
            continue
        url = r.get("attchmntFile") or ""
        raw = f"{symbol}|{r.get('seq_id') or ''}|{ts}|{r.get('desc')}|{url}"
        out.append({
            "id": "n" + hashlib.sha1(raw.encode()).hexdigest()[:12],
            "symbol": symbol, "company": r.get("sm_name") or symbol, "ts": _iso(ts),
            "headline": (r.get("desc") or "").strip(),
            "text": (r.get("attchmntText") or "").strip(),
            "url": url, "exch": "NSE", "exch_cat": (r.get("desc") or "").strip(),
        })
    return out


def parse_bse(payload, symbol: str) -> list[dict]:
    out = []
    for r in (payload or {}).get("Table") or []:
        stamp = r.get("DissemDT") or r.get("NEWS_DT") or r.get("DT_TM") or ""
        try:
            ts = datetime.fromisoformat(stamp.split(".")[0])
        except ValueError:
            continue
        att = r.get("ATTACHMENTNAME") or ""
        head = (r.get("NEWSSUB") or "").strip()
        if " - " in head:                      # "Company - 500325 - Subject"
            head = head.split(" - ", 2)[-1]
        out.append({
            "id": "b" + hashlib.sha1(str(r.get("NEWSID") or head + stamp).encode()).hexdigest()[:12],
            "symbol": symbol, "company": r.get("SLONGNAME") or symbol, "ts": _iso(ts),
            "headline": head, "text": (r.get("HEADLINE") or r.get("MORE") or "").strip(),
            "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
            "exch": "BSE",
            "exch_cat": " / ".join(x for x in (r.get("CATEGORYNAME"), r.get("SUBCATNAME")) if x),
        })
    return out


def fetch(symbol: str, start: datetime, end: datetime, bse_code=None) -> tuple[list[dict], bool]:
    """Filings in [start, end], newest first -> (items, from_saved_copy).

    NSE first; if it refuses, BSE (bse_code may be a callable so the lookup only happens
    when needed). Every success is merged into a per-symbol store, and if both exchanges
    are unreachable the store answers instead, flagged as a saved copy.
    """
    items, err = None, None
    try:
        url = ("https://www.nseindia.com/api/corporate-announcements?index=equities"
               f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}&symbol={symbol.replace('&', '%26')}")
        items = parse_nse(http.fetch(url, "json", ttl=600, headers={
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}), symbol)
    except Exception as e:  # noqa: BLE001
        err = e
    if items is None:
        code = bse_code() if callable(bse_code) else bse_code
        if code:
            try:
                items = []
                for page in range(1, 4):
                    url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
                           f"?pageno={page}&strCat=-1&strPrevDate={start:%Y%m%d}&strScrip={code}"
                           f"&strSearch=P&strToDate={end:%Y%m%d}&strType=C&subcategory=-1")
                    got = parse_bse(http.fetch(url, "json", ttl=600, headers={
                        "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}), symbol)
                    items += got
                    if len(got) < 50:
                        break
            except Exception as e:  # noqa: BLE001
                items, err = None, e
    store_key, saved = f"ann:{symbol}", False
    store = cache.get(store_key, stale_ok=True) or []
    if items is None:
        if not store:
            raise RuntimeError(f"announcements unavailable for {symbol}: {err}")
        items, saved = store, True
    elif not config.SAMPLE:
        merged = {it["id"]: it for it in store}
        merged.update({it["id"]: it for it in items})
        cache.put(store_key, sorted(merged.values(), key=lambda x: x["ts"], reverse=True)[:400])
    lo, hi = _iso(start), _iso(end)
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        if lo <= it["ts"] <= hi and it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out, saved
