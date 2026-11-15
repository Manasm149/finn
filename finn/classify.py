"""Filing -> category, sub-type and a priority score. Rules only: no tokens spent.

Categories follow the brief's reference list. The sub-type is our addition, because
priority lives there: "results" covers both the numbers themselves and the newspaper
ad saying they were printed, and those deserve very different treatment.
"""
import re

# (category, sub-type, base score, pattern). First match wins, so order is the logic:
# noise that borrows important words goes first, then the specific, then the general.
RULES = [
    # --- paperwork that mentions important things -------------------------------------
    ("results", "newspaper_ad", 4, r"newspaper|published in the|advertisement"),
    ("unclassified", "trading_window", 3, r"trading window"),
    ("unclassified", "share_certificate", 2, r"duplicate|loss of share|share certificate|regulation 74\(5\)|depositories and participants"),
    ("unclassified", "esop", 3, r"\besop|\besos|\besps|employee stock|stock option|allotment of (equity )?shares (under|pursuant)"),
    ("unclassified", "compliance", 3, r"compliance certificate|brsr|business responsibility|sustainability report|esg|structural digital database|regulation 7\(3\)|regulation 40\(|secretarial compliance|investor grievance|reconciliation of share capital|monitoring agency|statement of deviation"),
    ("earnings_call", "transcript", 40, r"transcript"),
    ("earnings_call", "recording", 10, r"audio|video recording|recording of|link (to|of) the (call|recording)"),
    # --- results ------------------------------------------------------------------------
    ("results", "clarification", 70, r"clarification.{0,30}financial results|reply to clarification"),
    ("results", "date_notice", 34, r"board meeting intimation|intimation of (the )?board meeting|notice of board meeting|to consider.{0,60}(financial results|dividend)|prior intimation"),
    ("results", "investor_deck", 46, r"investor presentation|earnings presentation|results presentation|shareholder letter"),
    ("results", "numbers", 92, r"financial results?|quarterly results|audited results|unaudited|results for the (quarter|half|year)|integrated filing.{0,12}financial"),
    # --- people -------------------------------------------------------------------------
    ("management_change", "auditor_exit", 76, r"resignation of (statutory )?auditor|auditor.{0,40}resign"),
    ("management_change", "kmp_exit", 90, r"(resign|step(ped|s)? down|cessation|demise|retire).{0,160}(chief executive|ceo\b|managing director|\bmd\b|chief financial|cfo\b|chairman|chairperson|whole[- ]?time director|executive director|chief operating|coo\b)|(chief executive|ceo\b|managing director|chief financial|cfo\b|chairman|chairperson|whole[- ]?time director|chief operating).{0,160}(resign|step(ped|s)? down|cessation|demise|retire)"),
    ("management_change", "kmp_join", 84, r"(appoint|elevat|re-?designat|succeed).{0,160}(chief executive|ceo\b|managing director|\bmd\b|chief financial|cfo\b|chairman|chairperson|whole[- ]?time director|executive director|chief operating|coo\b)"),
    ("unclassified", "auditor_appointment", 6, r"appointment of.{0,40}auditor|secretarial auditor|cost auditor|internal auditor"),
    ("management_change", "officer", 28, r"company secretary|compliance officer|share transfer agent|registrar"),
    ("management_change", "board", 42, r"change in director|appointment|resignation|cessation|independent director|key managerial|re-?appoint"),
    # --- deals and money ----------------------------------------------------------------
    ("M&A", "deal", 88, r"acqui|merger|amalgamat|demerger|scheme of arrangement|joint venture|slump sale|sale or disposal|divest|stake (sale|purchase)|incorporation of.{0,40}subsidiar|investment in.{0,40}subsidiar|wholly[- ]owned subsidiary"),
    ("fund_raise", "buyback", 72, r"buy-?back"),
    ("fund_raise", "equity", 78, r"qualified institution|\bqip\b|rights issue|preferential (issue|allotment)|raising of funds|fund ?rais|further public offer"),
    ("fund_raise", "debt", 38, r"commercial paper|non-?convertible debenture|\bncds?\b|issue of (debt )?securities|bonds"),
    ("litigation", "order", 78, r"litigation|dispute|penalt|\bfine\b|show cause|order(s)? passed|action\(s\) (taken|initiated)|sebi order|nclt|insolvency|arbitrat|tax demand|gst (demand|order)|income tax (order|demand)|search (and|&) seizure|warning letter|\bfda\b.{0,40}(observation|warning|form 483)"),
    ("credit_rating", "downgrade", 86, r"(rating|outlook).{0,80}(downgrad|revised to negative|placed on watch)|downgrad.{0,60}rating"),
    ("credit_rating", "upgrade", 64, r"(rating|outlook).{0,80}(upgrad|revised to positive)|upgrad.{0,60}rating"),
    ("credit_rating", "reaffirm", 24, r"credit rating|rating.{0,40}(reaffirm|assign)|\bcrisil\b|\bicra\b|care ratings|india ratings"),
    ("pledging", "pledge", 74, r"pledg|encumbr|invocation"),
    ("insider_trading", "disclosure", 50, r"takeover regulations|\bsast\b|regulation 29|insider trading|\bpit\b regulations|regulation 7\(2\)|promoter.{0,40}(acqui|sold|sale|purchase|bought)"),
    ("bonus_split", "action", 62, r"bonus (issue|shares)|stock split|sub-?division|split of"),
    ("dividend", "declared", 52, r"dividend"),
    ("capex", "expansion", 66, r"capex|capital expenditure|capacity (expansion|addition)|new (plant|facility|unit)|greenfield|brownfield|commissioning|commercial production"),
    # --- meetings -----------------------------------------------------------------------
    ("earnings_call", "notice", 14, r"earnings call|conference call|con\. ?call|concall"),
    ("investor_meetings", "meet", 8, r"analyst|institutional investor|investor (meet|conference)|non-?deal roadshow|one-on-one"),
    ("postal_ballot", "ballot", 10, r"postal ballot"),
    ("agm_egm", "meeting", 12, r"annual general meeting|\bagm\b|\begm\b|extra-?ordinary general|shareholders? meeting|voting results|scrutini[sz]er|book closure"),
    ("dividend", "record_date", 30, r"record date"),
    # --- news ---------------------------------------------------------------------------
    ("press_release", "rumour", 68, r"rumour|clarification on (news|media)|media report|spurt in (volume|price)|price movement"),
    ("press_release", "order_win", 58, r"(bagging|receiv|award|secur|win|won).{0,40}(order|contract|letter of (award|intent))|order (win|inflow|book)|\bloa\b"),
    ("press_release", "launch", 40, r"launch|partnership|collaborat|tie-?up|agreement|\bmou\b|memorandum of understanding|approval from|usfda approval|patent"),
    ("press_release", "general", 34, r"press release|media release|general updates?|\bupdates?\b|outcome of board meeting"),
]
_COMPILED = [(c, s, b, re.compile(p)) for c, s, b, p in RULES]

LABELS = {
    "results": "Results", "M&A": "M&A", "fund_raise": "Fund raise", "management_change": "Management",
    "litigation": "Legal", "insider_trading": "Insider", "earnings_call": "Earnings call",
    "investor_meetings": "Investor meet", "credit_rating": "Credit rating", "dividend": "Dividend",
    "bonus_split": "Bonus / split", "capex": "Capex", "press_release": "News", "postal_ballot": "Postal ballot",
    "agm_egm": "AGM / EGM", "pledging": "Pledge", "unclassified": "Routine",
}
MATTERS, KNOW = 60, 30      # score >= 60 is surfaced, 30-59 is a one-liner, below is buried

_GENERIC_HEADS = {
    "change in directors/ key managerial pers": "change in director",
    "change in director(s)": "change in director",
    "analysts/institutional investor meet/con": "institutional investor meet",
}
_BOILER = re.compile(
    r"^.{0,80}?\b(has|have) (informed|submitted to|intimated) (to )?the exchange(s)? "
    r"(regarding|about|that|a copy of|with respect to)?\s*", re.I)
_AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn)", re.I)


def amount_cr(text: str):
    """Largest rupee amount mentioned, in crore. Used to size order wins, deals, fund raises."""
    best = None
    for num, unit in _AMOUNT.findall(text or ""):
        v = float(num.replace(",", ""))
        u = unit.lower()
        cr = v if u.startswith("cr") else v / 100 if u.startswith("la") else v / 10 if u[0] == "m" else v * 100
        best = cr if best is None or cr > best else best
    return best


def one_line(item: dict) -> str:
    """The exchange's own summary text with the legal throat-clearing removed."""
    t = re.sub(r"\s+", " ", item.get("text") or "").strip()
    t = _BOILER.sub("", t).strip(" .:-")
    if not t or t.lower() == (item.get("headline") or "").lower():
        return item.get("headline") or ""
    t = t[0].upper() + t[1:]
    return t if len(t) <= 220 else t[:217].rsplit(" ", 1)[0] + "…"


def classify(item: dict) -> dict:
    head = (item.get("headline") or "").lower()
    # Two exchange subject lines name several unrelated things at once; neutralise them
    # so the filing's own text decides.
    head = _GENERIC_HEADS.get(head[:40], head)
    cat_text = "" if item.get("exch") == "NSE" else (item.get("exch_cat") or "").lower()
    hay = f"{head} || {cat_text} || {item.get('text', '')}".lower()
    for cat, sub, base, rx in _COMPILED:
        if rx.search(hay):
            if sub == "general" and one_line(item).lower() == (item.get("headline") or "").lower():
                base = 20            # an "update" that says nothing about what was updated
            return {"cat": cat, "sub": sub, "base": base}
    return {"cat": "unclassified", "sub": "other", "base": 8}


def prioritise(item: dict, weight: float = 0, move: dict | None = None, rules: dict | None = None) -> dict:
    """Attach cat/sub/score/tier/why to a filing. `why` is shown to the user verbatim:
    a ranking they cannot inspect is a ranking they will not trust."""
    rules = rules or {}
    c = classify(item)
    score = c["base"]
    why = [f"{LABELS[c['cat']]}: {c['sub'].replace('_', ' ')} ({c['base']})"]
    amt = amount_cr(f"{item.get('headline', '')} {item.get('text', '')}")
    if amt and c["cat"] in ("press_release", "M&A", "fund_raise", "capex", "litigation"):
        bump = 14 if amt >= 1000 else 8 if amt >= 100 else 0
        if bump:
            score += bump
            why.append(f"₹{amt:,.0f} cr involved (+{bump})")
    if weight and score >= KNOW:
        bump = min(8, round(weight * 0.6))
        score += bump
        why.append(f"{weight:g}% of your book (+{bump})")
    if move and score >= KNOW:
        score += 10
        why.append(f"stock moved {move['pct']:+.1f}% on {move['volx']:.1f}× volume around it (+10)")
    if c["cat"] in (rules.get("watch") or []):
        score = max(score + 15, MATTERS)
        why.append("a type you asked to be alerted on")
    if c["cat"] in (rules.get("mute") or []):
        score = 0
        why = [f"{LABELS[c['cat']]}: muted in your rules"]
    rank = max(0, score)                 # uncapped, so two "100s" still sort apart
    score = min(100, rank)
    tier = "matters" if score >= MATTERS else "know" if score >= KNOW else "buried"
    return {**item, **c, "label": LABELS[c["cat"]], "score": score, "rank": rank, "tier": tier, "why": why,
            "line": one_line(item), "amount_cr": amt}
