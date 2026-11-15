"""Pull side, part 1: everything that can be computed, computed. No model involved.

Input is the company's standardised statements; output is a set of sections plus
`flags` - plain-language observations, each carrying the numbers that produced it.
"""
from .enrich import OPER, OPM, PAT, PBT, SALES, col_ym, quarter_label, row
from .sources import screener


def _last(series, n=1):
    vals = [v for v in series if v is not None]
    return vals[-n] if len(vals) >= n else None


def cagr(series, years):
    if len(series) <= years or series[-1] is None or series[-1 - years] in (None, 0):
        return None
    a, b = series[-1 - years], series[-1]
    if a <= 0 or b <= 0:
        return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)


def _annual(table):
    """Indices of fiscal-year columns (drops TTM and half-year balance-sheet columns)."""
    return [i for i, c in enumerate(table["cols"]) if (col_ym(c) or (0, 0))[1] == 3]


def _pick(series, idx):
    return [series[i] if i < len(series) else None for i in idx]


def build(symbol: str) -> dict:
    co = screener.company(symbol)
    pl, bs, cf, rt, q = co["profit-loss"], co["balance-sheet"], co["cash-flow"], co["ratios"], co["quarters"]
    financial = "Financing Profit" in pl["rows"] or "Deposits" in bs["rows"]
    ai = _annual(pl)[-10:]
    years = [f"FY{col_ym(pl['cols'][i])[0] % 100:02d}" for i in ai]
    sales, op, opm = _pick(row(pl, SALES), ai), _pick(row(pl, OPER), ai), _pick(row(pl, OPM), ai)
    pat, pbt = _pick(row(pl, PAT), ai), _pick(row(pl, PBT), ai)
    other = _pick(row(pl, ("Other Income",)), ai)
    ttm = pl["cols"].index("TTM") if "TTM" in pl["cols"] else None

    bi = _annual(bs)[-10:]
    byears = [f"FY{col_ym(bs['cols'][i])[0] % 100:02d}" for i in bi]
    debt = _pick(row(bs, ("Borrowings", "Borrowing")), bi)
    eq = [(a or 0) + (b or 0) if a is not None or b is not None else None
          for a, b in zip(_pick(row(bs, ("Equity Capital",)), bi), _pick(row(bs, ("Reserves",)), bi))]
    de = [round(d / e, 2) if d is not None and e else None for d, e in zip(debt, eq)]

    ci = _annual(cf)[-10:]
    cyears = [f"FY{col_ym(cf['cols'][i])[0] % 100:02d}" for i in ci]
    cfo = _pick(row(cf, ("Cash from Operating Activity",)), ci)
    fcf = _pick(row(cf, ("Free Cash Flow",)), ci)
    pat_by_year = dict(zip(years, pat))
    cpat = [pat_by_year.get(y) for y in cyears]
    conv = [round(c / p * 100) if c is not None and p and p > 0 else None for c, p in zip(cfo, cpat)]

    ri = _annual(rt)[-10:]
    ryears = [f"FY{col_ym(rt['cols'][i])[0] % 100:02d}" for i in ri]
    wc = {k: _pick(row(rt, (label,)), ri) for k, label in (
        ("debtor", "Debtor Days"), ("inventory", "Inventory Days"), ("payable", "Days Payable"),
        ("ccc", "Cash Conversion Cycle"), ("wc", "Working Capital Days"))}
    roce = _pick(row(rt, ("ROCE %",)), ri)

    qi = [i for i, c in enumerate(q["cols"]) if col_ym(c)][-9:]
    qs, qo, qm, qp = row(q, SALES), row(q, OPER), row(q, OPM), row(q, PAT)
    quarters = []
    for i in qi:
        yago = qs[i - 4] if i >= 4 else None
        quarters.append({"q": quarter_label(*col_ym(q["cols"][i])), "sales": qs[i], "op": qo[i], "opm": qm[i],
                         "pat": qp[i],
                         "yoy": round((qs[i] / yago - 1) * 100, 1) if qs[i] and yago else None})

    sh = co["shareholding"]
    promoter = row(sh, ("Promoters",)) if sh["cols"] else []

    out = {
        "symbol": co["symbol"], "name": co["name"], "basis": co["basis"], "about": co["about"],
        "source": co["source"], "financial": financial, "docs": co["docs"],
        "snapshot": {
            "mcap": co["topline"].get("Market Cap"), "price": co["topline"].get("Current Price"),
            "pe": co["topline"].get("Stock P/E"), "roce": co["topline"].get("ROCE"),
            "roe": co["topline"].get("ROE"), "yield": co["topline"].get("Dividend Yield"),
            "rev": row(pl, SALES)[ttm] if ttm is not None else _last(sales),
            "opm": row(pl, OPM)[ttm] if ttm is not None else _last(opm),
            "pat": row(pl, PAT)[ttm] if ttm is not None else _last(pat),
            "de": _last(de), "rev_label": "TTM" if ttm is not None else years[-1] if years else "",
        },
        "trajectory": {"years": years, "sales": sales, "op": op, "opm": opm, "pat": pat,
                       "cagr": {"sales3": cagr(sales, 3), "sales5": cagr(sales, 5),
                                "pat3": cagr(pat, 3), "pat5": cagr(pat, 5)}},
        "balance": {"years": byears, "debt": debt, "equity": eq, "de": de, "ryears": ryears, **wc, "roce": roce},
        "cash": {"years": cyears, "cfo": cfo, "pat": cpat, "conv": conv, "fcf": fcf},
        "quarters": quarters,
        "promoter": {"cols": sh["cols"][-5:], "pct": promoter[-5:]} if promoter else None,
    }
    out["flags"] = flags(out, other, pbt)
    return out


def flags(r: dict, other=None, pbt=None) -> list[dict]:
    """Observations a careful analyst would write down, each with its evidence."""
    f = []

    def add(tone, title, evidence):
        f.append({"tone": tone, "title": title, "evidence": evidence})

    t, c, b, cash, qs = r["trajectory"], r["trajectory"]["cagr"], r["balance"], r["cash"], r["quarters"]
    yrs = t["years"]
    if c["sales3"] is not None and c["sales5"] is not None:
        if c["sales3"] >= c["sales5"] + 3:
            add("good", "Growth is accelerating", f"Revenue grew {c['sales3']}% a year over 3 years vs {c['sales5']}% over 5.")
        elif c["sales3"] <= c["sales5"] - 3:
            add("bad", "Growth is slowing", f"Revenue grew {c['sales3']}% a year over 3 years vs {c['sales5']}% over 5.")
    opm = [v for v in t["opm"] if v is not None]
    if len(opm) >= 4:
        delta = opm[-1] - opm[-4]
        if delta <= -2:
            add("bad", "Margins are compressing", f"Operating margin {opm[-4]:.0f}% in {yrs[-4]} → {opm[-1]:.0f}% in {yrs[-1]}.")
        elif delta >= 2:
            add("good", "Margins are expanding", f"Operating margin {opm[-4]:.0f}% in {yrs[-4]} → {opm[-1]:.0f}% in {yrs[-1]}.")
    if c["sales5"] is not None and c["pat5"] is not None and abs(c["pat5"] - c["sales5"]) >= 4:
        if c["pat5"] > c["sales5"]:
            add("good", "Profit is outgrowing revenue", f"5-year profit growth {c['pat5']}% a year vs revenue {c['sales5']}%.")
        else:
            add("bad", "Profit is lagging revenue", f"5-year profit growth {c['pat5']}% a year vs revenue {c['sales5']}%.")
    if len(qs) >= 5 and qs[-1]["yoy"] is not None:
        prior = [x["yoy"] for x in qs[-5:-1] if x["yoy"] is not None]
        if prior:
            avg = sum(prior) / len(prior)
            if qs[-1]["yoy"] - avg >= 5:
                add("good", "Latest quarter stepped up", f"{qs[-1]['q']} revenue +{qs[-1]['yoy']}% YoY vs {avg:.0f}% average of the prior {len(prior)} quarters.")
            elif qs[-1]["yoy"] - avg <= -5:
                add("bad", "Latest quarter stepped down", f"{qs[-1]['q']} revenue {qs[-1]['yoy']:+}% YoY vs {avg:.0f}% average of the prior {len(prior)} quarters.")
        if qs[-1]["opm"] is not None and qs[-5]["opm"] is not None and abs(qs[-1]["opm"] - qs[-5]["opm"]) >= 2:
            d = qs[-1]["opm"] - qs[-5]["opm"]
            add("good" if d > 0 else "bad", f"Quarterly margin {'up' if d > 0 else 'down'} {abs(d):.0f} pts on a year ago",
                f"Operating margin {qs[-5]['opm']:.0f}% in {qs[-5]['q']} → {qs[-1]['opm']:.0f}% in {qs[-1]['q']}.")
    pairs = [(x, y) for x, y in zip(cash["cfo"][-5:], cash["pat"][-5:]) if x is not None and y is not None]
    if len(pairs) >= 3 and not r["financial"]:
        s_cfo, s_pat = sum(x for x, _ in pairs), sum(y for _, y in pairs)
        if s_pat > 0:
            ratio = s_cfo / s_pat * 100
            ev = f"Over {len(pairs)} years, ₹{s_cfo:,.0f} cr of operating cash against ₹{s_pat:,.0f} cr of reported profit ({ratio:.0f}%)."
            if ratio < 70:
                add("bad", "Profits are not turning into cash", ev)
            elif ratio >= 100:
                add("good", "Profits convert fully to cash", ev)
        neg = [y for y, v in zip(cash["years"][-5:], cash["fcf"][-5:]) if v is not None and v < 0]
        if len(neg) >= 3:
            add("watch", "Free cash flow is usually negative", f"Negative in {', '.join(neg)}: growth is being funded from outside.")
    de = [v for v in b["de"] if v is not None]
    if de and not r["financial"]:
        if de[-1] >= 1:
            add("bad" if de[-1] >= 2 else "watch", "Leverage is high", f"Debt is {de[-1]:.1f}× equity in {b['years'][-1]}.")
        elif de[-1] <= 0.1:
            add("good", "Almost debt-free", f"Debt is {de[-1]:.2f}× equity in {b['years'][-1]}.")
        if len(de) >= 4 and de[-1] - de[-4] >= 0.3:
            add("watch", "Debt is rising faster than equity", f"Debt/equity {de[-4]:.2f} in {b['years'][-4]} → {de[-1]:.2f} in {b['years'][-1]}.")
    if not r["financial"]:
        for key, name in (("debtor", "Customers are paying more slowly"), ("ccc", "Working-capital cycle is lengthening")):
            s = [v for v in b[key] if v is not None]
            if len(s) >= 4 and s[-1] - s[-4] >= 12 and s[-4] >= 0:
                unit = "Debtor days" if key == "debtor" else "Cash conversion cycle"
                add("watch", name, f"{unit} {s[-4]:.0f} → {s[-1]:.0f} days over three years.")
                break
    roce = [v for v in b["roce"] if v is not None]
    if roce:
        if roce[-1] >= 20:
            add("good", "High return on capital", f"ROCE {roce[-1]:.0f}% in {b['ryears'][-1]}" + (f", {min(roce[-5:]):.0f}%+ in each of the last {len(roce[-5:])} years." if min(roce[-5:]) >= 15 else "."))
        elif roce[-1] < 10 and not r["financial"]:
            add("bad", "Low return on capital", f"ROCE {roce[-1]:.0f}% in {b['ryears'][-1]}.")
    if other and pbt and other[-1] is not None and pbt[-1] and pbt[-1] > 0 and other[-1] / pbt[-1] >= 0.25:
        add("watch", "A large share of profit is non-operating", f"Other income is {other[-1] / pbt[-1] * 100:.0f}% of pre-tax profit in {yrs[-1]}.")
    p = r.get("promoter")
    if p and len([v for v in p["pct"] if v is not None]) >= 2:
        vals = [v for v in p["pct"] if v is not None]
        if vals[-1] - vals[0] <= -1:
            add("watch", "Promoter stake is falling", f"{vals[0]:.1f}% → {vals[-1]:.1f}% over the last {len(vals)} disclosures.")
        elif vals[-1] - vals[0] >= 1:
            add("good", "Promoter stake is rising", f"{vals[0]:.1f}% → {vals[-1]:.1f}% over the last {len(vals)} disclosures.")
    return f
