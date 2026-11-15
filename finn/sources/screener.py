"""Fundamentals from screener.in: standardised multi-year tables plus links to the
primary documents (annual reports, concall transcripts). Works for any listed symbol.

The parser anchors on section ids first and visible headings second, so a markup
change degrades one field instead of breaking the page.
"""
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .. import http

BASE = "https://www.screener.in"
SECTIONS = {"quarters": "Quarterly Results", "profit-loss": "Profit & Loss",
            "balance-sheet": "Balance Sheet", "cash-flow": "Cash Flows", "ratios": "Ratios",
            "shareholding": "Shareholding Pattern"}


def _num(text: str):
    t = text.replace(",", "").replace("%", "").replace("₹", "").strip()
    if t in ("", "-", "--"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _label(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("+", "")).strip()


def _find_section(soup, sec_id: str, heading: str):
    sec = soup.find(id=sec_id)
    if sec:
        return sec
    for h in soup.find_all(["h2", "h3"]):
        if h.get_text(strip=True).lower() == heading.lower():
            return h.find_parent("section") or h.parent
    return None


def _table(sec) -> dict:
    out = {"cols": [], "rows": {}, "links": {}}
    tbl = sec.find("table") if sec else None
    if not tbl:
        return out
    head = tbl.find("thead")
    cells = (head or tbl).find_all("th")
    out["cols"] = [c.get_text(strip=True) for c in cells][1:]
    for tr in tbl.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = _label(tds[0].get_text(" ", strip=True))
        if not label:
            continue
        hrefs = [(td.find("a") or {}).get("href") if td.find("a") else None for td in tds[1:]]
        if any(hrefs):
            out["links"][label] = [urljoin(BASE, h) if h else None for h in hrefs]
        out["rows"][label] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return out


def _doc_box(root, css: str, heading: str):
    """The block holding one document list: by class, else by climbing up from its heading."""
    box = root.select_one(css)
    if box and box.find("li"):
        return box
    for h in root.find_all(["h2", "h3", "h4"]):
        if h.get_text(strip=True).lower().startswith(heading):
            node = h
            for _ in range(4):                 # the heading is often wrapped in its own header div
                node = node.parent
                if node is None or node.find("li"):
                    return node
    return None


def _documents(soup) -> dict:
    docs = {"annual_reports": [], "concalls": []}
    root = soup.find(id="documents") or soup
    box = _doc_box(root, ".documents.annual-reports", "annual report")
    for a in (box.find_all("a", href=True) if box else []):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        m = re.search(r"(20\d\d)", text)
        if m:
            docs["annual_reports"].append({"title": f"Annual Report FY{m.group(1)[2:]}",
                                           "fy": int(m.group(1)), "url": urljoin(BASE, a["href"])})
    box = _doc_box(root, ".documents.concalls", "concall")
    for li in (box.find_all("li") if box else []):
        m = re.search(r"([A-Z][a-z]{2})\w*\s+(20\d\d)", li.get_text(" ", strip=True))
        if not m:
            continue
        entry = {"date": f"{m.group(1)} {m.group(2)}"}
        for a in li.find_all("a", href=True):
            kind = (a.get_text(strip=True) or a.get("title") or "").lower()
            for name in ("transcript", "ppt", "notes"):
                if name in kind and name not in entry:
                    entry[name] = urljoin(BASE, a["href"])
        docs["concalls"].append(entry)
    return docs


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    h1 = soup.find("h1")
    nse = re.search(r"NSE\s*:\s*([A-Z0-9&\-]+)", text)
    bse = re.search(r"BSE\s*:\s*(\d{6})", text)
    ratios = {}
    for li in soup.select("#top-ratios li") or soup.select("li.flex.flex-space-between"):
        name = li.find(class_="name")
        nums = li.select(".number")
        if name and nums:
            vals = [_num(n.get_text()) for n in nums]
            ratios[_label(name.get_text())] = vals[0] if len(vals) == 1 else vals
    about = soup.select_one(".company-profile .about") or soup.select_one(".about")
    out = {
        "name": h1.get_text(strip=True) if h1 else "",
        "symbol": nse.group(1) if nse else None,
        "bse_code": bse.group(1) if bse else None,
        "about": re.sub(r"\s*\[\d+\]", "", about.get_text(" ", strip=True)) if about else "",
        "topline": ratios,
        "docs": _documents(soup),
    }
    for sec_id, heading in SECTIONS.items():
        out[sec_id] = _table(_find_section(soup, sec_id, heading))
    return out


def company(symbol: str) -> dict:
    """Consolidated numbers when the company reports them, standalone otherwise. 12h cache."""
    symbol = symbol.upper().strip()
    last = None
    for path, basis in ((f"/company/{quote(symbol)}/consolidated/", "consolidated"),
                        (f"/company/{quote(symbol)}/", "standalone")):
        try:
            data = parse(http.fetch(BASE + path, "text", ttl=12 * 3600))
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        if data["quarters"]["cols"] and any(v is not None for row in data["quarters"]["rows"].values() for v in row):
            data.update(basis=basis, source=BASE + path)
            data["symbol"] = data["symbol"] or symbol
            return data
    if last is not None and "404" not in str(last):
        raise RuntimeError("screener.in could not be reached")
    raise LookupError(f"No listed company found for '{symbol}'. Check the ticker, or search by name.")


def search(q: str) -> list[dict]:
    """Company search across everything listed -> [{name, symbol}]."""
    rows = http.fetch(f"{BASE}/api/company/search/?q={quote(q)}", "json", ttl=24 * 3600)
    out = []
    for r in rows or []:
        m = re.search(r"/company/([^/]+)/", r.get("url") or "")
        if m and r.get("name"):
            out.append({"name": r["name"], "symbol": m.group(1)})
    return out[:8]
