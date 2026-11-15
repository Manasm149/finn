"""The ask bar: one input that routes to the digest, a company, or a grounded answer."""
import math
import re
from collections import Counter

from . import llm
from .sources import docs, screener

STOP = set("a an the of on in for to is are was were what whats how why when did does do and or about tell me go up down at by "
           "show give company ltd limited please their its it this that with from has have had say said".split())


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9%]+", s.lower()) if w not in STOP and len(w) > 1]


def resolve(q: str, holdings: list[dict]):
    """Find the company a query is about -> (symbol, name) or None."""
    words = re.findall(r"[A-Za-z&]+", q)
    held = {h["symbol"].upper() for h in holdings}
    for w in words:
        if w.upper() in held:
            return w.upper(), None
    caps = [w for w in words if w[0].isupper() and w.lower() not in STOP]
    for cand in (" ".join(caps[:3]), " ".join(caps[:2]), caps[0] if caps else "", " ".join(_tokens(q)[:2])):
        if len(cand) >= 2:
            try:
                hits = screener.search(cand)
            except Exception:  # noqa: BLE001
                hits = []
            if hits:
                return hits[0]["symbol"], hits[0]["name"]
    return None


def route(q: str, holdings: list[dict]) -> dict:
    ql = q.lower().strip()
    m = re.search(r"(?:last|past)\s+(\d+)?\s*(hour|day|week|month)", ql)
    if m or re.search(r"what(?:'s| has| is)? (changed|new)|digest|brief me|anything (new|important)|catch me up", ql):
        hours = 24
        if m:
            hours = int(m.group(1) or 1) * {"hour": 1, "day": 24, "week": 168, "month": 720}[m.group(2)]
        return {"type": "digest", "hours": hours}
    hit = resolve(q, holdings)
    if not hit:
        return {"type": "none", "message": "I couldn't match that to a listed company. Try a ticker like TCS."}
    symbol, name = hit
    is_question = "?" in q or len(_tokens(q)) > 3 or re.match(r"(what|how|why|when|did|does|is|are|has)\b", ql)
    if is_question:
        return {"type": "answer", "symbol": symbol, **answer(symbol, q)}
    return {"type": "research", "symbol": symbol, "name": name}


def _chunks(symbol: str) -> list[dict]:
    co = screener.company(symbol)
    out = []
    for call in [c for c in co["docs"]["concalls"] if c.get("transcript")][:3]:
        try:
            pages = docs.pages(call["transcript"], max_pages=60)
        except Exception:  # noqa: BLE001
            continue
        for n, page in enumerate(pages, 1):
            text = re.sub(r"\s+", " ", page).strip()
            for i in range(0, len(text), 800):
                piece = text[i: i + 900]
                if len(piece) > 120:
                    out.append({"text": piece, "date": call["date"], "page": n, "url": call["transcript"]})
    return out


def _bm25(query: str, chunks: list[dict], k: int = 5) -> list[dict]:
    docs_tok = [_tokens(c["text"]) for c in chunks]
    df = Counter(t for d in docs_tok for t in set(d))
    n, avg = len(chunks), (sum(map(len, docs_tok)) / max(1, len(chunks)))
    scored = []
    for c, toks in zip(chunks, docs_tok):
        tf, score = Counter(toks), 0.0
        for t in set(_tokens(query)):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * len(toks) / avg))
        if score > 0:
            scored.append((score, c))
    return [c for _, c in sorted(scored, key=lambda x: -x[0])[:k]]


def answer(symbol: str, q: str) -> dict:
    """Answer from the company's own recent call transcripts, with the passages attached."""
    query = re.sub(rf"\b{re.escape(symbol)}\b", "", q, flags=re.I)
    top = _bm25(query, _chunks(symbol))
    if not top:
        return {"text": "Nothing in the last three call transcripts speaks to that.", "passages": []}
    text = None
    if llm.ready():
        body = "\n\n".join(f"[{i + 1}] ({c['date']} call, p.{c['page']}) {c['text']}" for i, c in enumerate(top))
        text = llm.text_call("fast", "ask", (
            f"Question about {symbol}: {q}\n\nAnswer in at most 70 words using only these excerpts from the "
            "company's earnings calls. Cite excerpts as [1], [2]. If they do not answer it, say that.\n\n" + body),
            max_tokens=220)
    terms = _tokens(query)
    shown, seen = [], set()
    for c in top:
        low = c["text"].lower()
        rare = next((t for t in sorted(terms, key=len, reverse=True) if t in low), None)   # longest ~ rarest
        at = low.find(rare) if rare else 0
        a = max(0, low.rfind(". ", 0, max(0, at - 60)) + 2) if at > 80 else 0
        piece = c["text"][a: a + 400]
        if piece[:80] not in seen:
            seen.add(piece[:80])
            shown.append({**c, "text": piece + ("…" if len(c["text"]) > a + 400 else "")})
    return {"text": text, "passages": shown[:3 if text else 4], "grounded_in": "earnings-call transcripts"}
