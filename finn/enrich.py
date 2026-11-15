"""What a surfaced filing carries beyond its headline.

results            -> first cut: Revenue / EBITDA / PBT / PAT, QoQ and YoY
management_change  -> who, which role, and the profile the company must attach to the filing
everything else    -> the one-liner from classify.one_line is usually enough
"""
import re
from datetime import date, datetime
from urllib.parse import quote

from . import config, llm
from .sources import docs, screener

MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
SALES = ("Sales", "Revenue")
OPER = ("Operating Profit", "Financing Profit")
OPM = ("OPM %", "Financing Margin %")
PBT = ("Profit before tax",)
PAT = ("Net Profit",)


def row(table: dict, names) -> list:
    for n in names:
        if n in table["rows"]:
            return table["rows"][n]
    return [None] * len(table["cols"])


def col_ym(col: str):
    """'Sep 2026' -> (2026, 9); 'TTM' -> None."""
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{4})", col or "")
    return (int(m.group(2)), MONTHS[m.group(1)]) if m and m.group(1) in MONTHS else None


def quarter_label(y: int, m: int) -> str:
    """Indian fiscal year ends in March: Sep 2026 is Q2 FY27."""
    fy = y + 1 if m > 3 else y
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    return f"Q{q} FY{fy % 100:02d}" if q else f"{m}/{y}"


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None


def first_cut(symbol: str, filed: str | None = None) -> dict | None:
    """Headline numbers for the latest reported quarter, from the standardised quarterly table.

    `fresh` is False when the table has not caught up with the filing yet - then the
    card says so instead of showing last quarter's numbers under this quarter's filing.
    """
    co = screener.company(symbol)
    q = co["quarters"]
    idx = [i for i, c in enumerate(q["cols"]) if col_ym(c)]
    if len(idx) < 2:
        return None
    i = idx[-1]
    y, m = col_ym(q["cols"][i])
    fresh = True
    if filed:
        d = datetime.fromisoformat(filed).date()
        ends = [date(d.year, mm, 1) for mm in (3, 6, 9, 12)] + [date(d.year - 1, 12, 1)]
        expect = max(e for e in ends if (e.year, e.month) < (d.year, d.month))
        fresh = (y, m) >= (expect.year, expect.month)
    rows = []
    for name, keys in (("Revenue", SALES), ("EBITDA", OPER), ("PBT", PBT), ("PAT", PAT)):
        s = row(q, keys)
        now = s[i]
        prev = s[i - 1] if i >= 1 else None
        yago = s[i - 4] if i >= 4 else None
        rows.append({"k": name, "v": now, "qoq": _pct(now, prev), "yoy": _pct(now, yago)})
    opm = row(q, OPM)
    return {
        "period": quarter_label(y, m), "basis": co["basis"], "fresh": fresh, "rows": rows,
        "margin": {"now": opm[i], "q": opm[i - 1] if i >= 1 else None, "y": opm[i - 4] if i >= 4 else None},
        "unit": "₹ cr", "source": co["source"] + "#quarters",
        "filing": (q["links"].get("Raw PDF") or [None] * (i + 1))[i] if q["links"] else None,
        "note": "EBITDA is operating profit before other income, as standardised by screener.in.",
    }


_PERSON = re.compile(
    r"(appointment|re-?appointment|resignation|cessation|retirement|elevation|demise|superannuation)"
    r"\s+of\s+((?:Mr|Ms|Mrs|Dr|Shri|Smt|Prof)\.?\s+[A-Z][\w.']*(?:\s+[A-Z][\w.']*){0,4}?)"
    r"\s*(?:\(DIN[^)]*\))?\s*(?:,\s*|\s+as\s+|\s+from\s+)(?:an?\s+|the\s+)?(?:post of\s+|position of\s+)?"
    r"([A-Z][A-Za-z&,\- ]{3,70}?)(?=\s+(?:of|w\.e\.f|with effect|effective|and|for)\b|[.;(]|$)", re.I)


def person(item: dict) -> dict | None:
    m = _PERSON.search(f"{item.get('text', '')} . {item.get('headline', '')}")
    if not m:
        return None
    action = m.group(1).lower().replace("-", "")
    leaving = action in ("resignation", "cessation", "retirement", "demise", "superannuation")
    return {"name": m.group(2).strip(), "role": m.group(3).strip(" ,"),
            "action": "Leaving" if leaving else "Joining", "verb": action}


def _profile_from_text(pages: list[str]) -> str:
    """Listed companies must attach a 'brief profile' to an appointment filing. Find it."""
    text = re.sub(r"[ \t]+", " ", "\n".join(pages[:8]))
    m = re.search(r"brief\s+profile[^\n:]*[:\n]", text, re.I)
    if not m:
        return ""
    body = text[m.end(): m.end() + 1400]
    cut = re.search(r"\n\s*(?:\d+[.)]\s+)?(disclosure of relationship|relationship between|information as required|"
                    r"declaration|yours (faithfully|sincerely|truly)|thanking you)", body, re.I)
    body = body[: cut.start()] if cut else body
    body = re.sub(r"\s+", " ", body).strip(" :-|")
    return body[:700]


def filing_detail(item: dict) -> dict:
    """Lazy enrichment: opens the filing PDF, so it runs only when a card asks for it."""
    out = {"id": item["id"]}
    who = person(item)
    # A CFO change usually arrives as two filings (exit + appointment) folded into one card.
    people = [who] if who else []
    for rel in item.get("related") or []:
        other = person({"text": rel.get("line") or "", "headline": rel.get("headline") or ""})
        if other and other["name"] not in [x["name"] for x in people]:
            people.append(other)
    pages = []
    if item.get("url", "").lower().split("?")[0].endswith(".pdf") or config.SAMPLE:
        try:
            pages = docs.pages(item["url"], max_pages=12)
        except Exception as e:  # noqa: BLE001
            out["doc_error"] = str(e)[:120]
    if item.get("cat") == "management_change":
        profile = _profile_from_text(pages) if pages else ""
        if llm.ready() and pages:
            got = llm.json_call("fast", "mgmt", (
                "From this stock-exchange filing, extract the management change. Use only the text.\n"
                'Return JSON: {"name": str, "role": str, "action": "Joining"|"Leaving", "effective": str|null, '
                '"reason": str|null, "background": [up to 3 short facts: previous employers and roles, years of '
                'experience, qualifications]}. If the filing gives no background, return an empty list.\n\n'
                + "\n".join(pages[:6])[:9000]), max_tokens=400)
            if isinstance(got, dict) and got.get("name"):
                who = {**(who or {}), **{k: got.get(k) for k in ("name", "role", "action", "effective", "reason")}}
                out["background"] = [b for b in got.get("background") or [] if isinstance(b, str)][:3]
        if who:
            people = [who] + [x for x in people if x["name"] != who["name"]]
        if people:
            who = next((x for x in people if x["action"] == "Joining"), people[0])
            out["people"] = people
            out["lookup"] = ("https://www.linkedin.com/search/results/people/?keywords="
                             + quote(f"{re.sub(r'^(Mr|Ms|Mrs|Dr|Shri|Smt|Prof)[.]? ', '', who['name'])} {item.get('company', '')}"))
        if profile and not out.get("background"):
            out["profile"] = profile
    elif pages and llm.ready() and item.get("tier") == "matters" and item.get("sub") != "numbers":
        text = llm.text_call("fast", "oneline", (
            "In one sentence of at most 28 words, state what this stock-exchange filing discloses and the "
            "key number if there is one. No preamble. Use only the text.\n\n" + "\n".join(pages[:4])[:7000]),
            max_tokens=90)
        if text:
            out["summary"] = text.strip()
    return out
