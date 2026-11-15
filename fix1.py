import re, pathlib
p = pathlib.Path("finn/sources/screener.py"); s = p.read_text()
a, b = s.index("def _documents(soup)"), s.index("def parse(html")
s = s[:a] + '''def _doc_box(root, css: str, heading: str):
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
        text = re.sub(r"\\s+", " ", a.get_text(" ", strip=True))
        m = re.search(r"(20\\d\\d)", text)
        if m:
            docs["annual_reports"].append({"title": f"Annual Report FY{m.group(1)[2:]}",
                                           "fy": int(m.group(1)), "url": urljoin(BASE, a["href"])})
    box = _doc_box(root, ".documents.concalls", "concall")
    for li in (box.find_all("li") if box else []):
        m = re.search(r"([A-Z][a-z]{2})\\w*\\s+(20\\d\\d)", li.get_text(" ", strip=True))
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


''' + s[b:]
p.write_text(s)

p = pathlib.Path("finn/doctor.py"); s = p.read_text()
old = """{len(co['docs']['concalls'])} calls, BSE {co['bse_code']}\""""
new = """{len(co['docs']['concalls'])} calls ({sum('transcript' in c for c in co['docs']['concalls'])} with transcripts), {len(co['docs']['annual_reports'])} annual reports, BSE {co['bse_code']}\""""
if old in s:
    s = s.replace(old, new)
    s = s.replace('''    calls = [c for c in (co.get("docs") or {}).get("concalls", []) if c.get("transcript")]''', '''    calls = [c for c in (co.get("docs") or {}).get("concalls", []) if c.get("transcript")]
    if not calls:      # show the page's own markup so the parser can be fixed
        from . import cache
        html = next((v for v in (cache.get(f"http:{co.get('source', '')}", stale_ok=True),) if v), "")
        i = html.find("Concalls")
        print("  --    no transcripts parsed. Markup around 'Concalls':\\n" + (html[max(0, i - 300): i + 1500] if i >= 0 else "  ('Concalls' does not appear in the page)"))''')
    p.write_text(s)
print("patched")
