"""Sample mode (FINN_SAMPLE=1): fictional companies, generated in the *source* formats.

Nothing here is real. The companies, people, filings and numbers are invented so the
full pipeline - parsers, classifier, alerts, research, promise ledger - can run and be
tested with no network. Responses mimic what Yahoo, NSE and screener.in return, so the
same parsing code is exercised as in live mode.
"""
import json
import random
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

IST = timezone(timedelta(hours=5, minutes=30))
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

# g: revenue growth % for each of the last 9 fiscal years; opm: operating margin for 10 years.
# cur / cur_opm: growth and margin in the fiscal year now in progress.
CO = {
    "AARNA": dict(name="Aarna Foods Ltd", bse="590101", weight=14, price=1840, base=2100,
                  g=[11, 12, 9, 6, 14, 15, 13, 12, 13.2], opm=[15, 15.5, 16, 16, 15.5, 16.5, 17, 17.2, 17.4, 17.6],
                  cur=14.8, cur_opm=18.1, de=0.05, conv=1.08, dd=[22, 22, 21, 23, 22, 21], promoter=[54.2, 54.2, 54.2, 54.3, 54.3],
                  about="Aarna Foods makes packaged staples, snacks and ready-to-cook mixes sold under the Aarna and Kitchen Bell brands across India. (Sample company - not real.)"),
    "BRIJSTEEL": dict(name="Brij Steel & Alloys Ltd", bse="590102", weight=8, price=412, base=9800,
                      g=[8, 14, -6, 4, 31, 12, -3, 5, 6.5], opm=[14, 15, 17, 12, 13, 21, 15, 11, 12, 12.5],
                      cur=4.0, cur_opm=11.8, de=1.35, conv=0.92, dd=[28, 30, 31, 33, 36, 38], promoter=[61.0, 61.0, 60.4, 59.8, 59.1],
                      about="Brij Steel & Alloys is an integrated producer of long steel products and ferro alloys with plants in Odisha and Chhattisgarh. (Sample company - not real.)"),
    "CAUVERYBNK": dict(name="Cauvery Bank Ltd", bse="590103", weight=13, price=268, base=6400, bank=True,
                       g=[10, 12, 13, 8, 7, 16, 21, 15, 12.4], opm=[58, 58, 59, 57, 55, 56, 58, 60, 60, 61],
                       cur=11.0, cur_opm=60.5, de=0, conv=1.0, dd=[0] * 6, promoter=[0, 0, 0, 0, 0],
                       about="Cauvery Bank is a mid-sized private sector bank with about 900 branches, concentrated in southern India. (Sample company - not real.)"),
    "DHRUVTECH": dict(name="Dhruv Technologies Ltd", bse="590104", weight=12, price=2960, base=1500,
                      g=[18, 21, 16, 9, 24, 26, 19, 17, 10.8], opm=[24, 24.5, 25, 25, 26, 25.5, 24, 22.5, 21, 19.6],
                      cur=8.5, cur_opm=18.4, de=0.02, conv=0.61, dd=[62, 64, 68, 74, 83, 96], promoter=[48.6, 48.6, 47.9, 46.8, 45.2],
                      about="Dhruv Technologies provides engineering R&D and embedded software services to automotive and industrial customers in Europe and North America. (Sample company - not real.)"),
    "ELARAPH": dict(name="Elara Pharma Ltd", bse="590105", weight=10, price=1215, base=3300,
                    g=[9, 11, 12, 15, 10, 8, 12, 14, 11.0], opm=[21, 21, 22, 23, 25, 24, 22, 23, 24, 24.5],
                    cur=10.2, cur_opm=24.0, de=0.18, conv=0.95, dd=[70, 72, 71, 73, 72, 74], promoter=[51.5, 51.5, 51.5, 51.5, 51.5],
                    about="Elara Pharma develops and manufactures generic formulations for the US and India, with a growing injectables portfolio. (Sample company - not real.)"),
    "FALCONINF": dict(name="Falcon Infra Projects Ltd", bse="590106", weight=9, price=684, base=5200,
                      g=[12, 15, 10, -4, 18, 22, 17, 19, 20.5], opm=[11, 11, 11.5, 11, 10, 10.5, 11, 11, 11.2, 11.4],
                      cur=23.0, cur_opm=11.6, de=0.82, conv=0.74, dd=[84, 88, 90, 95, 98, 104], promoter=[56.9, 56.9, 56.9, 56.9, 56.9],
                      about="Falcon Infra Projects builds highways, metro viaducts and water pipelines on an EPC basis for central and state agencies. (Sample company - not real.)"),
    "GIRNARCEM": dict(name="Girnar Cement Ltd", bse="590107", weight=10, price=2385, base=7600,
                      g=[7, 13, 9, 1, 16, 14, 6, 4, 7.9], opm=[19, 20, 21, 22, 24, 20, 16, 17, 16, 16.8],
                      cur=9.0, cur_opm=18.0, de=0.44, conv=1.12, dd=[14, 15, 14, 16, 15, 15], promoter=[63.4, 63.4, 63.4, 63.4, 63.4],
                      about="Girnar Cement sells grey cement and ready-mix concrete in western and central India from five integrated plants. (Sample company - not real.)"),
    "HIMADRIEL": dict(name="Himadri Electricals Ltd", bse="590108", weight=9, price=1492, base=2800,
                      g=[10, 13, 8, 5, 22, 25, 20, 18, 19.4], opm=[10, 10, 10.5, 11, 11, 11.5, 12, 12.6, 13, 13.5],
                      cur=21.0, cur_opm=14.0, de=0.09, conv=0.88, dd=[48, 47, 49, 50, 48, 47], promoter=[66.0, 66.0, 66.0, 66.2, 66.4],
                      about="Himadri Electricals makes wires, cables, switchgear and fans for housing and industrial customers. (Sample company - not real.)"),
    "INDUSLOG": dict(name="Indus Logistics Ltd", bse="590109", weight=7, price=356, base=1900,
                     g=[14, 16, 11, -2, 19, 13, 8, 9, 8.0], opm=[9, 9, 9.5, 9, 8, 9.5, 9, 8.5, 8.6, 8.4],
                     cur=6.5, cur_opm=8.0, de=0.66, conv=1.02, dd=[55, 56, 58, 57, 59, 60], promoter=[42.0, 42.0, 41.6, 41.2, 40.9],
                     about="Indus Logistics runs contract logistics, express freight and warehousing for consumer and auto companies. (Sample company - not real.)"),
    "JALDHARA": dict(name="Jaldhara Renewables Ltd", bse="590110", weight=8, price=527, base=900,
                     g=[22, 28, 31, 18, 26, 34, 29, 33, 36.0], opm=[72, 73, 74, 75, 76, 77, 78, 78, 79, 79.5],
                     cur=31.0, cur_opm=80.0, de=2.9, conv=1.25, dd=[66, 70, 75, 81, 86, 92], promoter=[71.2, 71.2, 69.5, 69.5, 68.0],
                     about="Jaldhara Renewables owns and operates wind and solar farms selling power under long-term contracts to state utilities. (Sample company - not real.)"),
    "KAVERIAUTO": dict(name="Kaveri Auto Components Ltd", bse="590111", weight=0, price=978, base=2400,
                       g=[9, 12, 4, -9, 20, 18, 14, 11, 12.6], opm=[12, 12.5, 13, 12, 11, 12.5, 13, 13.5, 14, 14.4],
                       cur=13.0, cur_opm=14.8, de=0.31, conv=0.97, dd=[52, 51, 53, 52, 50, 51], promoter=[58.3, 58.3, 58.3, 58.3, 58.3],
                       about="Kaveri Auto Components supplies braking and suspension parts to two-wheeler and passenger-vehicle makers. (Sample company - not real.)"),
}
PORTFOLIO = [{"symbol": s, "weight": c["weight"]} for s, c in CO.items() if c["weight"]]


def _now():
    return datetime.now(IST).replace(tzinfo=None)


def _periods():
    """(fiscal years FYxx..., quarter-end (y, m) list) relative to today."""
    n = _now()
    last_fy = n.year if n.month >= 6 else n.year - 1
    q = []
    y, m = n.year, n.month
    while len(q) < 13:
        if m in (3, 6, 9, 12) and (n - datetime(y, m, 28)).days >= 20:
            q.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(range(last_fy - 9, last_fy + 1)), q[::-1]


def model(sym: str) -> dict:
    """Ten fiscal years and thirteen quarters of statements from a company's spec."""
    c = CO[sym]
    fys, qs = _periods()
    sales = [c["base"]]
    for g in c["g"]:
        sales.append(sales[-1] * (1 + g / 100))
    bank = c.get("bank")
    A = {"fy": fys, "sales": sales, "opm": c["opm"]}
    A["op"] = [s * m / 100 for s, m in zip(sales, c["opm"])]
    eq_cap = round(c["base"] * 0.01) + 20
    reserves, debt, pat, pbt, other, intr, dep = [], [], [], [], [], [], []
    res = c["base"] * 0.5
    for i, (s, o) in enumerate(zip(sales, A["op"])):
        de_i = c["de"] * (0.75 + 0.25 * i / 9)
        d = de_i * (eq_cap + res)
        oi = s * (0.012 if not bank else 0.14)
        it = d * 0.085 if not bank else 0
        dp = s * (0.035 if not bank else 0.02)
        if sym == "JALDHARA":
            dp = s * 0.22
        b = o + oi - it - dp
        p = b * 0.75
        res += max(p, 0) * 0.72
        for arr, v in ((reserves, res), (debt, d), (pat, p), (pbt, b), (other, oi), (intr, it), (dep, dp)):
            arr.append(v)
    A.update(reserves=reserves, debt=debt, pat=pat, pbt=pbt, other=other, interest=intr, dep=dep, eq_cap=eq_cap)
    drift = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.96, 0.9, 0.84] if c["conv"] < 0.7 else [1.0] * 10
    A["cfo"] = [p * c["conv"] * k for p, k in zip(pat, drift)]
    capex = [s * (0.05 if sym != "JALDHARA" else 0.9) for s in sales]
    A["fcf"] = [a - b for a, b in zip(A["cfo"], capex)]
    A["capex"] = capex
    # quarters: fiscal-year sales split by season; the year in progress grows at `cur`
    season = {6: 0.235, 9: 0.245, 12: 0.255, 3: 0.265}
    Q = {"ym": qs, "sales": [], "opm": []}
    fy_sales = dict(zip(fys, sales))
    fy_opm = dict(zip(fys, c["opm"]))
    rnd = random.Random(sym)
    hist = {}
    for (y, m) in [(yy, mm) for yy in range(fys[0], fys[-1] + 2) for mm in (6, 9, 12, 3)]:
        fy = y + 1 if m > 3 else y
        yy = y if m > 3 else y            # calendar year of the quarter-end
        if m == 3:
            yy = fy
        else:
            yy = fy - 1
        if fy in fy_sales:
            hist[(yy, m)] = (fy_sales[fy] * season[m], fy_opm[fy] + rnd.uniform(-0.5, 0.5))
        elif (yy - 1, m) in hist:
            hist[(yy, m)] = (hist[(yy - 1, m)][0] * (1 + c["cur"] / 100), c["cur_opm"] + rnd.uniform(-0.4, 0.4))
    for ym in qs:
        s, o = hist.get(ym, (None, None))
        Q["sales"].append(s)
        Q["opm"].append(o)
    A["dd"] = c["dd"]
    return {"A": A, "Q": Q, "c": c}


def _fmt(v, pct=False, dec=0):
    if v is None:
        return ""
    return f"{v:.0f}%" if pct else f"{v:,.{dec}f}"


def _table(sec_id, title, cols, rows):
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for label, vals in rows:
        plus = '&nbsp;<span class="blue-icon">+</span>' if label in ("Sales", "Revenue", "Expenses", "Other Income", "Net Profit", "Borrowings", "Borrowing") else ""
        cells = "".join(f"<td>{v}</td>" for v in vals)
        body += f'<tr><td class="text">{label}{plus}</td>{cells}</tr>'
    return (f'<section id="{sec_id}" class="card card-large"><h2>{title}</h2>'
            f'<table class="data-table"><thead><tr><th class="text"></th>{head}</tr></thead><tbody>{body}</tbody></table></section>')


def _calls(sym):
    """Last five results calls: (label 'Oct 2026', url)."""
    _, qs = _periods()
    out = []
    for i, (y, m) in enumerate(reversed(qs[-5:])):
        cm = m + 1 if m < 12 else 1
        cy = y if m < 12 else y + 1
        if m == 3:
            cm = 5
        out.append({"date": f"{MON[cm - 1]} {cy}", "q": (y, m), "url": f"https://sample.finn/doc/{sym}/call/{y}-{m:02d}.pdf"})
    return out


def screener_html(sym: str) -> str:
    M = model(sym)
    A, Q, c = M["A"], M["Q"], M["c"]
    bank = c.get("bank")
    S, OP, OPM = ("Revenue", "Financing Profit", "Financing Margin %") if bank else ("Sales", "Operating Profit", "OPM %")
    qcols = [f"{MON[m - 1]} {y}" for y, m in Q["ym"]]
    qop = [s * o / 100 if s else None for s, o in zip(Q["sales"], Q["opm"])]
    qpbt = [o * 0.93 if o else None for o in qop]
    qpat = [b * 0.75 if b else None for b in qpbt]
    quarters = _table("quarters", "Quarterly Results", qcols, [
        (S, [_fmt(v) for v in Q["sales"]]),
        ("Expenses", [_fmt(s - o) if s else "" for s, o in zip(Q["sales"], qop)]),
        (OP, [_fmt(v) for v in qop]), (OPM, [_fmt(v, True) for v in Q["opm"]]),
        ("Profit before tax", [_fmt(v) for v in qpbt]), ("Net Profit", [_fmt(v) for v in qpat]),
        ("Raw PDF", [f'<a href="/company/source/quarter/1/{m}/{y}/">PDF</a>' for y, m in Q["ym"]]),
    ])
    ycols = [f"Mar {y}" for y in A["fy"]]
    ttm_s = sum(v for v in Q["sales"][-4:] if v)
    ttm_op = sum(v for v in qop[-4:] if v)
    pl = _table("profit-loss", "Profit &amp; Loss", ycols + ["TTM"], [
        (S, [_fmt(v) for v in A["sales"]] + [_fmt(ttm_s)]),
        ("Expenses", [_fmt(s - o) for s, o in zip(A["sales"], A["op"])] + [_fmt(ttm_s - ttm_op)]),
        (OP, [_fmt(v) for v in A["op"]] + [_fmt(ttm_op)]),
        (OPM, [_fmt(v, True) for v in A["opm"]] + [_fmt(ttm_op / ttm_s * 100, True)]),
        ("Other Income", [_fmt(v) for v in A["other"]] + [""]),
        ("Interest", [_fmt(v) for v in A["interest"]] + [""]),
        ("Depreciation", [_fmt(v) for v in A["dep"]] + [""]),
        ("Profit before tax", [_fmt(v) for v in A["pbt"]] + [_fmt(sum(v for v in qpbt[-4:] if v))]),
        ("Net Profit", [_fmt(v) for v in A["pat"]] + [_fmt(sum(v for v in qpat[-4:] if v))]),
    ])
    eq = [A["eq_cap"] + r for r in A["reserves"]]
    tot = [e + d + s * 0.2 for e, d, s in zip(eq, A["debt"], A["sales"])]
    bs = _table("balance-sheet", "Balance Sheet", ycols, [
        ("Equity Capital", [_fmt(A["eq_cap"])] * 10), ("Reserves", [_fmt(v) for v in A["reserves"]]),
        ("Deposits" if bank else "Borrowings", [_fmt(s * 6) for s in A["sales"]] if bank else [_fmt(v) for v in A["debt"]]),
        ("Other Liabilities", [_fmt(s * 0.2) for s in A["sales"]]), ("Total Liabilities", [_fmt(v) for v in tot]),
        ("Total Assets", [_fmt(v) for v in tot]),
    ])
    cfl = _table("cash-flow", "Cash Flows", ycols, [
        ("Cash from Operating Activity", [_fmt(v) for v in A["cfo"]]),
        ("Cash from Investing Activity", [_fmt(-v) for v in A["capex"]]),
        ("Free Cash Flow", [_fmt(v) for v in A["fcf"]]),
    ])
    dd = [c["dd"][0]] * 4 + c["dd"]
    roce = [(o - d) / (e + b) * 100 for o, d, e, b in zip(A["op"], A["dep"], eq, A["debt"])]
    rt = _table("ratios", "Ratios", ycols, [
        ("Debtor Days", [_fmt(v) for v in dd]), ("Inventory Days", [_fmt(v * 0.6) for v in dd]),
        ("Days Payable", [_fmt(v * 0.5) for v in dd]), ("Cash Conversion Cycle", [_fmt(v * 1.1) for v in dd]),
        ("Working Capital Days", [_fmt(v * 0.7) for v in dd]), ("ROCE %", [_fmt(v, True) for v in roce]),
    ])
    sh = _table("shareholding", "Shareholding Pattern", qcols[-5:], [
        ("Promoters", [f"{v:.2f}%" for v in c["promoter"]]),
        ("Public", [f"{100 - v:.2f}%" for v in c["promoter"]]),
    ]) if any(c["promoter"]) else ""
    pat_ttm = sum(v for v in qpat[-4:] if v)
    shares = c["base"] / 40
    mcap = c["price"] * shares / 10
    top = [("Market Cap", f"₹ <span class=\"number\">{mcap:,.0f}</span> Cr."),
           ("Current Price", f"₹ <span class=\"number\">{c['price']:,}</span>"),
           ("High / Low", f"₹ <span class=\"number\">{c['price'] * 1.22:,.0f}</span> / <span class=\"number\">{c['price'] * 0.74:,.0f}</span>"),
           ("Stock P/E", f"<span class=\"number\">{mcap / pat_ttm:.1f}</span>"),
           ("ROCE", f"<span class=\"number\">{roce[-1]:.1f}</span> %"),
           ("ROE", f"<span class=\"number\">{A['pat'][-1] / eq[-1] * 100:.1f}</span> %"),
           ("Dividend Yield", "<span class=\"number\">0.90</span> %")]
    lis = "".join(f'<li class="flex flex-space-between"><span class="name">{k}</span>'
                  f'<span class="nowrap value">{v}</span></li>' for k, v in top)
    ars = "".join(f'<li><a href="https://sample.finn/doc/{sym}/ar/{y}.pdf">Financial Year {y}'
                  f'<div class="ink-600 smaller">from bse</div></a></li>' for y in reversed(A["fy"][-3:]))
    calls = "".join(f'<li class="flex flex-gap-8"><div class="ink-600 font-size-15 nowrap">{k["date"]}</div>'
                    f'<a class="concall-link" href="{k["url"]}" title="Raw Transcript">Transcript</a>'
                    f'<a class="concall-link" href="https://sample.finn/doc/{sym}/ppt.pdf">PPT</a></li>' for k in _calls(sym))
    return f"""<html><body><h1 class="margin-0">{c['name']}</h1>
<div class="company-links"><a href="#"><span class="ink-700 upper">BSE: {c['bse']}</span></a>
<a href="#"><span class="ink-700 upper">NSE: {sym}</span></a></div>
<ul id="top-ratios">{lis}</ul>
<div class="company-profile"><div class="sub show-more-box about"><p>{c['about']}</p></div></div>
{quarters}{pl}{bs}{cfl}{rt}{sh}
<section id="documents"><h2>Documents</h2>
<div class="documents annual-reports flex-column"><h3>Annual reports</h3><ul class="list-links">{ars}</ul></div>
<div class="documents concalls flex-column"><h3>Concalls</h3><ul class="list-links">{calls}</ul></div>
</section></body></html>"""


# ---- documents ---------------------------------------------------------------------------

PEOPLE = {s: (f"{a} {b}", f"{x} {y}") for s, (a, b, x, y) in {
    "AARNA": ("Sunita", "Kelkar", "Rohit", "Bansal"), "BRIJSTEEL": ("Harish", "Tiwari", "Neha", "Saxena"),
    "CAUVERYBNK": ("R.", "Venkataraman", "Lakshmi", "Pillai"), "DHRUVTECH": ("Nikhil", "Deshpande", "Arvind", "Kothari"),
    "ELARAPH": ("Farah", "Qureshi", "Sanjay", "Mathur"), "FALCONINF": ("Gurpreet", "Sandhu", "Anita", "Rao"),
    "GIRNARCEM": ("Jignesh", "Vora", "Pooja", "Trivedi"), "HIMADRIEL": ("Tarun", "Bisht", "Mala", "Negi"),
    "INDUSLOG": ("Imran", "Sheikh", "Deepa", "Kulkarni"), "JALDHARA": ("Aditi", "Rathore", "Karan", "Mehra"),
    "KAVERIAUTO": ("Suresh", "Gowda", "Rekha", "Hegde")}.items()}


def _band(v, w=1.0):
    lo = round(v - w)
    return lo, lo + round(2 * w)


def transcript(sym: str, y: int, m: int) -> str:
    """An invented call transcript whose guidance is tied to the generated numbers."""
    M = model(sym)
    c, A = M["c"], M["A"]
    ceo, cfo = PEOPLE[sym]
    analyst = random.Random(f"{sym}{y}{m}").choice(["Rahul Shah", "Priya Menon", "Vikram Joshi", "Sneha Agarwal"])
    fy = y + 1 if m > 3 else y                      # fiscal year of the quarter discussed
    call_fy = fy + 1 if m == 3 else fy              # after Q4, talk turns to the new year
    last_fy = A["fy"][-1]
    qn = {6: 1, 9: 2, 12: 3, 3: 4}[m]
    g_done, g_cur = c["g"][-1], c["cur"]
    lines = [f"Moderator: Ladies and gentlemen, welcome to the Q{qn} FY{fy % 100} earnings conference call of {c['name']}. "
             f"This is a sample transcript generated for testing; the company is fictional. I now hand over to {ceo}.",
             f"{ceo}: Thank you, and good evening everyone. Let me begin with the quarter and then our outlook."]
    over = sym == "DHRUVTECH"
    if call_fy == last_fy:                           # calls during the last completed year
        if over and qn <= 2:
            lines.append(f"{ceo}: Demand remains strong and we maintain our guidance of 16% to 18% revenue growth for FY{call_fy % 100}. "
                         f"We expect EBITDA margin in the range of 23% to 24% for the full year.")
        elif over:
            lines.append(f"{ceo}: Given the deferral of two large programmes, we now expect revenue growth of 11% to 12% for FY{call_fy % 100}. "
                         f"We expect EBITDA margin of around 20% for the full year.")
        else:
            lo, hi = _band(g_done)
            mlo, mhi = _band(c["opm"][-1], 0.5)
            lines.append(f"{ceo}: We maintain our guidance of {lo}% to {hi}% revenue growth for FY{call_fy % 100}. "
                         f"On profitability, we expect EBITDA margin in the range of {mlo}% to {mhi + 0}% for the full year.")
    else:                                            # calls in the year now in progress
        if over:
            lines.append(f"{ceo}: For FY{call_fy % 100}, we are guiding for revenue growth of 14% to 16%, with a strong second half. "
                         f"We expect EBITDA margin of 21% to 22% for FY{call_fy % 100} as utilisation improves.")
        elif sym == "AARNA":
            lines.append(f"{ceo}: For FY{call_fy % 100} we expect revenue growth of 12% to 14%. "
                         f"We are confident of EBITDA margin of at least 17% for the full year. "
                         f"Net profit should grow in double digits in FY{call_fy % 100}.")
        else:
            lo, hi = _band(g_cur + (2 if sym in ("BRIJSTEEL", "INDUSLOG") else 0))
            lines.append(f"{ceo}: For FY{call_fy % 100} we expect revenue growth of {lo}% to {hi}%. "
                         f"We expect EBITDA margin of around {round(c['cur_opm'])}% for the full year.")
    lines += [
        f"{cfo}: On the balance sheet, receivables stood at {c['dd'][-1]} days. We plan a capex of Rs. {round(A['capex'][-1] / 10) * 10:,} crore this year, funded largely from internal accruals.",
        f"{ceo}: Over the medium term we aspire to mid-teens growth in revenue, and we will keep investing in capacity and people.",
        f"Moderator: Thank you. We will now begin the question and answer session. The first question is from the line of {analyst} from Meridian Securities.",
        f"{analyst}: Thanks for the opportunity. You had earlier spoken about 20% growth; is that still achievable, and how should we think about margins?",
        f"{ceo}: I would not want to add to what we have said in the opening remarks. Pricing has been stable and input costs are behaving, so margins should hold near current levels.",
        f"{analyst}: And on working capital, receivable days have moved up. Is that structural?",
        f"{cfo}: Part of it is mix. A few large customers have longer credit terms, and collections in the last week of the quarter slipped into the next month. We are watching it closely.",
        "Moderator: Thank you. That was the last question. I now hand the conference back to the management for closing comments.",
        f"{ceo}: Thank you all for joining us.",
    ]
    return "\n".join(lines)


def _docs(path: str) -> str:
    parts = path.strip("/").split("/")
    sym = parts[1]
    if parts[2] == "call":
        y, m = parts[3].replace(".pdf", "").split("-")
        return transcript(sym, int(y), int(m))
    if parts[2] == "cfo.pdf":
        return (f"To, National Stock Exchange of India Ltd. Sub: Change in Key Managerial Personnel.\n"
                f"This is a sample filing; the company and people are fictional.\n"
                f"Pursuant to Regulation 30, we inform you that Mr. Arvind Kothari has tendered his resignation as Chief Financial Officer "
                f"of the Company with effect from close of business on the last day of this month, to pursue opportunities outside the Company.\n"
                f"The Board has approved the appointment of Ms. Kavita Rangan as Chief Financial Officer and Key Managerial Personnel with effect from the first day of next month.\n"
                f"Brief Profile: Ms. Kavita Rangan is a Chartered Accountant with over 22 years of experience in corporate finance, treasury and investor relations. "
                f"She was most recently Finance Controller at Northwind Components, and earlier spent eleven years at Saffron Motors in business finance roles. "
                f"She holds a B.Com from Pune and is a member of the ICAI.\n"
                f"Disclosure of relationship between directors: Not applicable.\nYours faithfully, Company Secretary")
    return f"Sample document for {sym}. This company is fictional and this text is generated for testing."


# ---- filings and prices ---------------------------------------------------------------------

def _filings() -> list[dict]:
    n = _now()
    nxt = (n + timedelta(days=6)).strftime("%B %d, %Y")
    rec = (n + timedelta(days=11)).strftime("%B %d, %Y")
    F = [  # (symbol, hours ago, exchange subject, text, attachment)
        ("DHRUVTECH", 3.2, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
         "Dhruv Technologies Limited has informed the Exchange regarding Resignation of Mr. Arvind Kothari as Chief Financial Officer of the company w.e.f. month end.", "cfo.pdf"),
        ("DHRUVTECH", 3.1, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
         "Dhruv Technologies Limited has informed the Exchange regarding Appointment of Ms. Kavita Rangan as Chief Financial Officer of the company w.e.f. next month.", "cfo.pdf"),
        ("AARNA", 5.5, "Outcome of Board Meeting", "Aarna Foods Limited has informed the Exchange regarding Outcome of Board Meeting: the Board approved the unaudited financial results for the quarter and half year.", "results.pdf"),
        ("AARNA", 5.3, "Press Release", "Aarna Foods Limited has informed the Exchange regarding a press release on the financial results for the quarter.", "pr.pdf"),
        ("AARNA", 5.0, "Investor Presentation", "Aarna Foods Limited has informed the Exchange about Investor Presentation", "deck.pdf"),
        ("AARNA", 1.4, "Copy of Newspaper Publication", "Aarna Foods Limited has informed the Exchange about Copy of Newspaper Publication of financial results", "np.pdf"),
        ("AARNA", 30, "Analysts/Institutional Investor Meet/Con. Call Updates", "Aarna Foods Limited has informed the Exchange about earnings call schedule", "call.pdf"),
        ("FALCONINF", 7.8, "Bagging/Receiving of orders/contracts", "Falcon Infra Projects Limited has informed the Exchange regarding receipt of Letter of Award for an elevated corridor project worth Rs. 1,840 crore from a state road agency.", "loa.pdf"),
        ("ELARAPH", 9.0, "Action(s) initiated or orders passed", "Elara Pharma Limited has informed the Exchange regarding a warning letter received from the US FDA for its injectables facility following the recent inspection.", "fda.pdf"),
        ("GIRNARCEM", 11.5, "Acquisition", "Girnar Cement Limited has informed the Exchange regarding acquisition of 51% stake in a 2 MTPA grinding unit for Rs. 620 crore.", "acq.pdf"),
        ("BRIJSTEEL", 14.0, "Disclosure under SEBI Takeover Regulations", "Brij Steel & Alloys Limited has informed the Exchange regarding creation of pledge on 1.9% of equity by a promoter group entity.", "sast.pdf"),
        ("HIMADRIEL", 16.0, "Dividend", f"Himadri Electricals Limited has informed the Exchange that the Board has declared an interim dividend of Rs. 6 per share. Record date is {rec}.", "div.pdf"),
        ("CAUVERYBNK", 18.0, "Board Meeting Intimation", f"Cauvery Bank Limited has informed the Exchange about Board Meeting to be held on {nxt} to consider financial results for the quarter.", "bm.pdf"),
        ("JALDHARA", 20.0, "Credit Rating", "Jaldhara Renewables Limited has informed the Exchange regarding credit rating: CRISIL has reaffirmed its rating on the bank facilities.", "cr.pdf"),
        ("INDUSLOG", 21.0, "Analysts/Institutional Investor Meet/Con. Call Updates", "Indus Logistics Limited has informed the Exchange about Schedule of meet with institutional investors.", "meet.pdf"),
        ("HIMADRIEL", 22.5, "Press Release", "Himadri Electricals Limited has informed the Exchange regarding launch of a new range of energy-efficient fans.", "launch.pdf"),
        ("GIRNARCEM", 46, "Analysts/Institutional Investor Meet/Con. Call Updates", "Girnar Cement Limited has informed the Exchange about Transcript of the earnings call.", "tr.pdf"),
        ("JALDHARA", 52, "Raising of Funds", "Jaldhara Renewables Limited has informed the Exchange that the Board approved raising of funds up to Rs. 2,500 crore through a qualified institutions placement.", "qip.pdf"),
        ("INDUSLOG", 75, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent", "Indus Logistics Limited has informed the Exchange regarding Appointment of Ms. Shalini Bose as Independent Director.", "id.pdf"),
        ("FALCONINF", 98, "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company", "Falcon Infra Projects Limited has informed the Exchange regarding an arbitration award of Rs. 212 crore in its favour.", "arb.pdf"),
        ("CAUVERYBNK", 120, "Credit Rating", "Cauvery Bank Limited has informed the Exchange that ICRA has upgraded the rating of its tier II bonds.", "up.pdf"),
        ("ELARAPH", 140, "Press Release", "Elara Pharma Limited has informed the Exchange regarding USFDA approval for a generic injectable.", "anda.pdf"),
    ]
    routine = [("Trading Window", "closure of trading window"), ("ESOP/ESOS/ESPS", "allotment of equity shares under ESOP"),
               ("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "certificate under Regulation 74(5)"),
               ("Loss/Duplicate-Share Certificate-XBRL", "issue of duplicate share certificate"),
               ("Copy of Newspaper Publication", "Copy of Newspaper Publication"), ("Shareholders meeting", "voting results of postal ballot"),
               ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meet"), ("General Updates", "General Updates"),
               ("Business Responsibility and Sustainability Reporting (BRSR)", "BRSR report"), ("Updates", "investor grievance report")]
    rnd = random.Random(7)
    for sym in PORTFOLIO:
        s = sym["symbol"]
        for _ in range(rnd.randint(4, 8)):
            subj, txt = rnd.choice(routine)
            F.append((s, rnd.choice([rnd.uniform(0.5, 23), rnd.uniform(24, 400)]), subj,
                      f"{CO[s]['name'].replace('Ltd', 'Limited')} has informed the Exchange about {txt}", "misc.pdf"))
    out = []
    for i, (s, h, subj, txt, att) in enumerate(F):
        t = n - timedelta(hours=h)
        out.append({"symbol": s, "desc": subj, "attchmntText": txt, "sm_name": CO[s]["name"].replace("Ltd", "Limited"),
                    "attchmntFile": f"https://sample.finn/doc/{s}/{att}", "seq_id": 100000 + i,
                    "an_dt": t.strftime("%d-%b-%Y %H:%M:%S"), "sort_date": t.strftime("%Y-%m-%d %H:%M:%S")})
    return out


PLANT = {"DHRUVTECH": (-6.8, 3.4), "FALCONINF": (5.2, 2.7), "GIRNARCEM": (2.1, 2.6), "ELARAPH": (-4.4, 1.9)}


def chart(sym: str) -> dict:
    c = CO[sym]
    rnd = random.Random(sym + "px")
    n = _now()
    day = n if n.hour >= 16 else n - timedelta(days=1)
    days = []
    while len(days) < 260:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    rets = [rnd.gauss(0.0004, 0.012) for _ in days]
    vols = [max(0.4, rnd.gauss(1, 0.22)) for _ in days]
    if sym in PLANT:
        rets[-1], vols[-1] = PLANT[sym][0] / 100, PLANT[sym][1]
    px = [1.0]
    for r in rets[1:]:
        px.append(px[-1] * (1 + r))
    k = c["price"] / px[-1]
    close = [round(p * k, 2) for p in px]
    base_vol = 40_000_000 / c["price"] * 10
    ts = [int(d.replace(hour=15, minute=30, second=0, microsecond=0, tzinfo=IST).timestamp()) for d in days]
    return {"chart": {"result": [{"meta": {"symbol": sym + ".NS", "currency": "INR"}, "timestamp": ts,
            "indicators": {"quote": [{"open": close, "high": [x * 1.008 for x in close], "low": [x * 0.992 for x in close],
                                      "close": close, "volume": [int(base_vol * v) for v in vols]}]}}], "error": None}}


def respond(url: str, kind: str):
    u = urlparse(url)
    qs = parse_qs(u.query)
    if "finance.yahoo.com" in u.netloc:
        sym = u.path.rsplit("/", 1)[-1].split(".")[0]
        if sym not in CO:
            raise RuntimeError("404 unknown symbol")
        return chart(sym)
    if "nseindia.com" in u.netloc:
        sym = unquote(qs["symbol"][0])
        return [f for f in _filings() if f["symbol"] == sym]
    if "screener.in" in u.netloc and "/api/company/search" in u.path:
        q = qs.get("q", [""])[0].lower()
        return [{"id": i, "name": c["name"], "url": f"/company/{s}/consolidated/"}
                for i, (s, c) in enumerate(CO.items()) if q in c["name"].lower() or q in s.lower()]
    if "screener.in" in u.netloc:
        m = re.match(r"/company/([^/]+)/", u.path)
        sym = unquote(m.group(1)).upper() if m else ""
        if sym not in CO:
            raise RuntimeError("404 not found")
        return screener_html(sym)
    if u.netloc == "sample.finn":
        return _docs(u.path).encode()
    raise RuntimeError(f"sample mode has no fixture for {u.netloc}")
