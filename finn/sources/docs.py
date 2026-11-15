"""Primary documents (filing PDFs, transcripts, annual reports) -> page texts, cached forever."""
import hashlib
import io

from .. import cache, http

MAX_PAGES = 400


def pages(url: str, max_pages: int = MAX_PAGES) -> list[str]:
    """Text of each page. Empty list if the document cannot be read (e.g. a scan)."""
    key = "doc:" + hashlib.sha1(url.encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return hit
    ref = "https://www.bseindia.com/" if "bseindia" in url else "https://www.nseindia.com/"
    raw = http.fetch(url, "bytes", headers={"Referer": ref}, timeout=45)
    if raw[:4] != b"%PDF":                      # some hosts serve text or html
        text = raw.decode("utf-8", "ignore")
        out = [p for p in text.split("\f") if p.strip()]
    else:
        from pypdf import PdfReader
        out = []
        for page in PdfReader(io.BytesIO(raw)).pages[:max_pages]:
            try:
                out.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page should not lose the document
                out.append("")
    cache.put(key, out)
    return out
