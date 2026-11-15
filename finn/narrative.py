"""Pull side, part 2: what management said versus what the numbers did.

The split of labour is the point of this module:
  reading    -> find the sentences where management commits to a number  (model, or heuristics)
  checking   -> every quote must be found verbatim in the transcript       (code)
  counting   -> compare the target with reported figures                   (code, never the model)
  judging    -> a short read across the whole record                       (model, optional)

So a model can miss a promise, but it cannot invent one or get the arithmetic wrong.
"""
import re

from . import cache, llm
from .enrich import MONTHS, OPER, PAT, SALES, col_ym, row
from .sources import docs, screener

METRIC_LABEL = {"revenue_growth": "Revenue growth", "margin": "EBITDA margin",
                "pat_growth": "Profit growth", "capex": "Capex"}
BANDS = [  # how managements say numbers without saying numbers
    (r"high[- ]single[- ]digits?", 7, 9), (r"mid[- ]single[- ]digits?", 4, 6), (r"low[- ]single[- ]digits?", 1, 3),
    (r"low[- ]double[- ]digits?", 10, 12), (r"double[- ]digits?", 10, None),
    (r"low[- ]teens", 11, 13), (r"mid[- ]teens", 14, 16), (r"high[- ]teens", 17, 19),
]
FORWARD = re.compile(r"guid|expect|target|aim|aspir|outlook|we will|we shall|we should|we are looking|looking at|"
                     r"on track|confident|maintain|sustain|going forward|next year|this year|full year|for the year|"
                     r"fy\s?'?\d\d|commit|anticipat|intend|plan to|endeavou?r", re.I)
PCT = r"(?:%|percent|per cent)"
RANGE = re.compile(rf"(\d+(?:\.\d+)?)\s*{PCT}?\s*(?:to|-|–|—)\s*(\d+(?:\.\d+)?)\s*{PCT}", re.I)
SINGLE = re.compile(rf"(\d+(?:\.\d+)?)\s*{PCT}", re.I)
FLOOR = re.compile(r"at least|north of|upwards of|more than|in excess of|above|over|minimum|not less than|exceed", re.I)
CAP = re.compile(r"below|under|less than|not more than|within|up to", re.I)
CRORE = re.compile(r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:crores?|cr\b)", re.I)
SPEAKER = re.compile(r"^\s*([A-Z][A-Za-z.'\- ]{2,40}):\s", re.M)


# ---------- reading the transcript --------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", s.lower()).strip()


def _fy_of_call(date: str) -> int:
    """'Oct 2026' -> 2027: the fiscal year in progress when the call happened."""
    mon, year = date.split()
    return int(year) + (1 if MONTHS[mon[:3]] >= 4 else 0)


def sentences(pages: list[str]):
    """Yield (page_no, speaker, is_management, sentence)."""
    full = "\n".join(pages)
    analysts = {m.strip().lower() for m in re.findall(
        r"(?:line of|question (?:is )?from)\s+(?:Mr\.?|Ms\.?|Mrs\.?)?\s*([A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){0,2})", full)}
    speaker = ""
    for n, page in enumerate(pages, 1):
        text = re.sub(r"[ \t]+", " ", page)
        marks = [(m.start(), m.group(1).strip()) for m in SPEAKER.finditer(text)] + [(len(text), None)]
        chunks = [(text[:marks[0][0]], speaker)]
        for (a, who), (b, _) in zip(marks, marks[1:]):
            chunks.append((text[a:b], who))
        for chunk, who in chunks:
            if who:
                speaker = who
                chunk = chunk.split(":", 1)[1] if ":" in chunk else chunk
            low = speaker.lower()
            mgmt = bool(speaker) and low != "moderator" and not any(a and (a in low or low in a) for a in analysts)
            for s in re.split(r"(?<=[.?!])\s+(?=[A-Z\"“])", re.sub(r"\s+", " ", chunk)):
                s = s.strip()
                if 30 <= len(s) <= 420:
                    yield n, speaker, mgmt or not analysts, s


def _period(sent: str, call_fy: int):
    s = sent.lower()
    m = re.search(r"\bfy\s?'?(?:20)?(\d\d)\b|fiscal(?: year)?\s?'?(?:20)?(\d\d)\b|20\d\d-(\d\d)\b", s)
    if m:
        return f"FY{next(g for g in m.groups() if g)}", False
    if re.search(r"medium[- ]term|long[- ]term|next (three|3|four|4|five|5|few|couple of) years|over the next|by 20[3-9]\d", s):
        return "medium term", False
    if re.search(r"next (year|fiscal|financial year)", s):
        return f"FY{(call_fy + 1) % 100:02d}", False
    if re.search(r"this (year|fiscal|financial year)|current (year|fiscal|financial year)|full[- ]year|for the year|year as a whole", s):
        return f"FY{call_fy % 100:02d}", False
    return f"FY{call_fy % 100:02d}", True          # unstated: assume the year in progress, and say so


def _target(sent: str):
    """-> (metric, lo, hi) or None. Percent targets for growth and margin, crore for capex."""
    s = sent.lower()
    if re.search(r"capex|capital expenditure", s):
        amounts = [float(a.replace(",", "")) for a in CRORE.findall(sent)]
        amounts = [a for a in amounts if a >= 10]
        if amounts:
            return "capex", min(amounts), max(amounts)
    lo = hi = None
    m = RANGE.search(sent)
    span = None
    if m:
        lo, hi, span = float(m.group(1)), float(m.group(2)), m.span()
    else:
        for rx, a, b in BANDS:
            mm = re.search(rx, s)
            if mm:
                lo, hi, span = a, b, mm.span()
                break
        if span is None:
            m = SINGLE.search(sent)
            if m:
                lo = hi = float(m.group(1))
                span = m.span()
                before = s[max(0, span[0] - 28): span[0]]
                if FLOOR.search(before):
                    hi = None
                elif CAP.search(before):
                    lo = None
    if span is None or (lo is not None and lo > 80):
        return None
    near = s[max(0, span[0] - 110): span[1] + 70]
    just_before = s[max(0, span[0] - 45): span[0]]      # what the number is *of*
    if re.search(r"gross margin|net margin|pat margin|tax rate|market share|utili[sz]ation|payout|attrition|roce|roe\b|"
                 r"capacity|headcount|volume", just_before):
        return None
    if re.search(r"margin", near):
        return "margin", lo, hi
    grow = re.search(r"grow|increase|expan", near)
    if grow and re.search(r"revenue|top[- ]?line|sales|turnover", near):
        return "revenue_growth", lo, hi
    if grow and re.search(r"\bpat\b|profit|bottom[- ]?line|earnings", near):
        return "pat_growth", lo, hi
    return None


def heuristic_promises(pages: list[str], call_date: str) -> list[dict]:
    fy = _fy_of_call(call_date)
    out = []
    for page, speaker, mgmt, s in sentences(pages):
        if not mgmt or not FORWARD.search(s) or s.endswith("?"):
            continue
        t = _target(s)
        if not t:
            continue
        period, assumed = _period(s, fy)
        out.append({"metric": t[0], "lo": t[1], "hi": t[2], "period": period, "assumed_period": assumed,
                    "quote": s, "speaker": speaker, "page": page})
    return out


def model_promises(pages: list[str], call_date: str) -> list[dict] | None:
    """Fast-tier extraction over pre-filtered passages (about a fifth of the transcript)."""
    fy = _fy_of_call(call_date)
    keep, rows = [], list(sentences(pages))
    for i, (page, speaker, mgmt, s) in enumerate(rows):
        if mgmt and (FORWARD.search(s) and re.search(r"\d|digit|teens", s)
                     and re.search(r"margin|grow|revenue|capex|profit|sales|guid", s, re.I)):
            ctx = " ".join(r[3] for r in rows[max(0, i - 1): i + 2])
            keep.append(f"[p{page}] {speaker}: {ctx}")
    if not keep:
        return []
    passages = "\n".join(dict.fromkeys(keep))[:14000]
    got = llm.json_call("fast", "promises", (
        f"These are excerpts from a company's earnings call held in {call_date} (fiscal year in progress: "
        f"FY{fy % 100:02d}; Indian fiscal years end in March).\n"
        "List every explicit, numeric commitment or guidance that MANAGEMENT gives about the company's own "
        "future headline numbers. Skip analyst questions, past results, and vague optimism.\n"
        'Return JSON {"promises": [{"metric": "revenue_growth"|"margin"|"pat_growth"|"capex", '
        '"lo": number|null, "hi": number|null, "period": "FYnn"|"medium term", '
        '"quote": "<one sentence copied exactly from the excerpt>"}]}.\n'
        "lo/hi are percentages for growth and margin, rupees crore for capex. Use null for an open end "
        '("at least 20%" -> lo 20, hi null).\n\n' + passages), max_tokens=1200)
    if not isinstance(got, dict):
        return None
    index = [(p, sp, _norm(s), s) for p, sp, _, s in rows]
    out = []
    for pr in got.get("promises") or []:
        if not isinstance(pr, dict) or pr.get("metric") not in METRIC_LABEL:
            continue
        q = _norm(str(pr.get("quote") or ""))
        hit = next((r for r in index if q and (q in r[2] or r[2] in q) and len(r[2]) > 25), None)
        if not hit:                                   # the quote is not in the transcript: discard
            continue
        try:
            lo = float(pr["lo"]) if pr.get("lo") is not None else None
            hi = float(pr["hi"]) if pr.get("hi") is not None else None
        except (TypeError, ValueError):
            continue
        out.append({"metric": pr["metric"], "lo": lo, "hi": hi,
                    "period": str(pr.get("period") or f"FY{fy % 100:02d}"), "assumed_period": False,
                    "quote": hit[3], "speaker": hit[1], "page": hit[0]})
    return out


# ---------- counting -------------------------------------------------------------------------

def actuals(co: dict) -> dict:
    """{'FY26': {...annual}, ('FY27', 2): {...quarter}} from the reported tables."""
    out = {}
    pl, q = co["profit-loss"], co["quarters"]
    for i, c in enumerate(pl["cols"]):
        ym = col_ym(c)
        if ym and ym[1] == 3:
            out[f"FY{ym[0] % 100:02d}"] = {k: row(pl, names)[i] for k, names in
                                           (("sales", SALES), ("op", OPER), ("pat", PAT))}
    for i, c in enumerate(q["cols"]):
        ym = col_ym(c)
        if ym:
            fy = ym[0] + 1 if ym[1] > 3 else ym[0]
            qn = {6: 1, 9: 2, 12: 3, 3: 4}[ym[1]] if ym[1] in (3, 6, 9, 12) else None
            if qn:
                out[(f"FY{fy % 100:02d}", qn)] = {k: row(q, names)[i] for k, names in
                                                  (("sales", SALES), ("op", OPER), ("pat", PAT))}
    return out


def _measure(metric: str, period: str, act: dict):
    """-> (value, final?, quarters_counted) or None when the tables cannot answer."""
    if not re.fullmatch(r"FY\d\d", period) or metric == "capex":
        return None
    prev = f"FY{(int(period[2:]) - 1) % 100:02d}"
    field = {"revenue_growth": "sales", "pat_growth": "pat"}.get(metric)

    def val(cur, base):
        if metric == "margin":
            return cur["op"] / cur["sales"] * 100 if cur.get("op") is not None and cur.get("sales") else None
        a, b = cur.get(field), base.get(field) if base else None
        return (a / b - 1) * 100 if a is not None and b and b > 0 else None

    if period in act and (metric == "margin" or prev in act):
        v = val(act[period], act.get(prev))
        return (v, True, 4) if v is not None else None
    qs = [n for n in (1, 2, 3, 4) if (period, n) in act]
    if not qs or (metric != "margin" and not all((prev, n) in act for n in qs)):
        return None
    cur = {k: sum(act[(period, n)][k] or 0 for n in qs) for k in ("sales", "op", "pat")}
    base = {k: sum(act[(prev, n)][k] or 0 for n in qs) for k in ("sales", "op", "pat")} if metric != "margin" else None
    v = val(cur, base)
    return (v, len(qs) == 4, len(qs)) if v is not None else None


def _fmt_target(metric, lo, hi):
    if metric == "capex":
        f = lambda x: f"₹{x:,.0f} cr"  # noqa: E731
        return f(lo) if lo == hi else f"{f(lo)}–{f(hi)}"
    n = lambda x: f"{x:g}"  # noqa: E731
    if lo is None:
        return f"under {n(hi)}%"
    if hi is None:
        return f"{n(lo)}%+"
    return f"{n(lo)}%" if lo == hi else f"{n(lo)}–{n(hi)}%"


def _status(lo, hi, v, final, metric):
    tol = 0.3 if metric == "margin" else 0.5
    if lo is not None and v < lo - tol:
        return "missed" if final else "behind"
    if hi is not None and v > hi + tol and lo is not None:
        return "beat" if final else "ahead"
    return "met" if final else "on track"


def ledger(promises_by_call: list[tuple[dict, list[dict]]], act: dict) -> list[dict]:
    """Group statements about the same target, keep the revision trail, and score each."""
    groups: dict[tuple, list] = {}
    for call, items in promises_by_call:                 # calls arrive oldest first
        for p in items:
            groups.setdefault((p["metric"], p["period"]), []).append((call, p))
    out = []
    for (metric, period), said in groups.items():
        first_call, first = said[0]
        trail, last = [], first
        for call, p in said[1:]:
            if (p["lo"], p["hi"]) != (last["lo"], last["hi"]) and call["date"] != first_call["date"]:
                lo0, lo1 = last["lo"] or last["hi"] or 0, p["lo"] or p["hi"] or 0
                trail.append({"date": call["date"], "target": _fmt_target(metric, p["lo"], p["hi"]),
                              "move": "raised" if lo1 > lo0 else "cut", "quote": p["quote"],
                              "url": call["transcript"], "page": p["page"]})
                last = p
        m = _measure(metric, period, act)
        entry = {
            "metric": metric, "label": METRIC_LABEL[metric], "period": period,
            "assumed_period": first["assumed_period"],
            "target": _fmt_target(metric, first["lo"], first["hi"]),
            "said": {"date": first_call["date"], "quote": first["quote"], "speaker": first["speaker"],
                     "page": first["page"], "url": first_call["transcript"]},
            "revisions": trail, "status": "open", "actual": None, "detail": "",
        }
        if m:
            v, final, k = m
            entry["actual"] = round(v, 1)
            entry["status"] = _status(first["lo"], first["hi"], v, final, metric)
            entry["final"] = final
            if trail:
                entry["status_vs_latest"] = _status(last["lo"], last["hi"], v, final, metric)
            entry["detail"] = (f"{period} reported" if final else f"{period} after {k} of 4 quarters")
        elif period == "medium term":
            entry["status"], entry["detail"] = "long-dated", "No end date to measure against yet"
        elif metric == "capex":
            entry["status"], entry["detail"] = "unmeasured", "Capex is not broken out in the standardised statements"
        else:
            entry["detail"] = f"{period} not reported yet"
        out.append(entry)
    order = {"missed": 0, "behind": 1, "beat": 2, "met": 3, "ahead": 4, "on track": 5, "open": 6,
             "long-dated": 7, "unmeasured": 8}
    return sorted(out, key=lambda e: (order[e["status"]], e["period"]))


def scorecard(entries: list[dict]) -> dict:
    kept = sum(e["status"] in ("met", "beat") for e in entries)
    missed = sum(e["status"] == "missed" for e in entries)
    live = sum(e["status"] in ("on track", "ahead", "behind") for e in entries)
    cuts = sum(any(r["move"] == "cut" for r in e["revisions"]) for e in entries)
    return {"kept": kept, "missed": missed, "live": live, "behind": sum(e["status"] == "behind" for e in entries),
            "cuts": cuts, "total": len(entries)}


# ---------- orchestration -------------------------------------------------------------------

def _business(co: dict, say) -> dict | None:
    """Business snapshot from the latest annual report: only the pages that describe segments."""
    reports = co["docs"]["annual_reports"]
    if not (llm.ready() and reports):
        return None
    say("Reading the annual report")
    try:
        pages = docs.pages(reports[0]["url"], max_pages=140)
    except Exception:  # noqa: BLE001
        return None
    scored = sorted(((len(re.findall(r"segment|revenue mix|business overview|geograph|% of revenue|product portfolio",
                                     p, re.I)), i) for i, p in enumerate(pages)), reverse=True)[:5]
    picked = sorted(i for score, i in scored if score >= 2)
    if not picked:
        return None
    body = "\n\n".join(f"[page {i + 1}]\n{pages[i][:2600]}" for i in picked)
    got = llm.json_call("fast", "business", (
        "From these annual-report pages, describe the business. Use only this text.\n"
        'Return JSON {"what": "<what the company does, at most 35 words>", "segments": [{"name": str, '
        '"share": "<% of revenue if stated, else null>", "note": "<at most 12 words>"}], '
        '"geography": "<one line or null>"}. At most 6 segments.\n\n' + body), max_tokens=600)
    if not isinstance(got, dict) or not got.get("what"):
        return None
    got["source"] = {"title": reports[0]["title"], "url": reports[0]["url"], "pages": [i + 1 for i in picked]}
    return got


def _synthesis(name: str, entries: list[dict], flags: list[dict]) -> dict | None:
    if not llm.ready():
        return None
    facts = {"promises": [{k: e[k] for k in ("label", "period", "target", "status", "actual", "detail")}
                          | {"revisions": [f"{r['move']} to {r['target']} in {r['date']}" for r in e["revisions"]]}
                          for e in entries],
             "observations": [f"{f['title']}: {f['evidence']}" for f in flags]}
    import json
    got = llm.json_call("smart", "synthesis", (
        f"You are assessing {name} for an investor. Below are (a) management's numeric promises with the "
        "reported outcome, already checked, and (b) observations computed from the financial statements. "
        "Use only these facts; do not add anything you know about the company.\n"
        'Return JSON {"read": "<2 sentences: does management deliver what it says, and where does its story '
        'diverge from the numbers>", "bull": [3 points], "bear": [3 points]}. '
        "Each point at most 18 words and must cite a number from the facts.\n\n" + json.dumps(facts)),
        max_tokens=500)
    return got if isinstance(got, dict) and got.get("read") else None


def run(symbol: str, say=lambda msg: None) -> dict:
    """Full narrative pass for one company. `say` reports progress to the UI."""
    co = screener.company(symbol)
    calls = [c for c in co["docs"]["concalls"] if c.get("transcript")][:5]
    key = f"narr:{co['symbol']}:{calls[0]['date'] if calls else 'none'}:{llm.model_for('fast') if llm.ready() else 'rules'}"
    hit = cache.get(key, 7 * 86400)
    if hit:
        return hit
    from . import research
    r = research.build(symbol)
    by_call, read, method = [], [], "rules"
    for call in reversed(calls):                         # oldest first so revisions read forward
        say(f"Reading the {call['date']} call")
        try:
            pages = docs.pages(call["transcript"], max_pages=60)
        except Exception as e:  # noqa: BLE001
            read.append({"date": call["date"], "ok": False, "error": str(e)[:100]})
            continue
        if not any(p.strip() for p in pages):
            read.append({"date": call["date"], "ok": False, "error": "no text layer (scanned PDF)"})
            continue
        items = model_promises(pages, call["date"]) if llm.ready() else None
        if items is None:
            items = heuristic_promises(pages, call["date"])
        else:
            method = "model"
        by_call.append((call, items))
        read.append({"date": call["date"], "ok": True, "pages": len(pages), "found": len(items),
                     "url": call["transcript"]})
    say("Checking promises against reported numbers")
    entries = ledger(by_call, actuals(co))
    out = {"symbol": co["symbol"], "ledger": entries, "score": scorecard(entries), "calls": read,
           "method": method, "business": None, "synthesis": None}
    if entries or r["flags"]:
        say("Weighing the record")
        out["synthesis"] = _synthesis(co["name"], entries, r["flags"])
    out["business"] = _business(co, say)
    if any(c["ok"] for c in read) or not calls:
        cache.put(key, out)
    return out
