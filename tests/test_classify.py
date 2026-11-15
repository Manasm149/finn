import pytest

from finn.classify import amount_cr, one_line, prioritise

KMP = "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent"
MEET = "Analysts/Institutional Investor Meet/Con. Call Updates"
CASES = [
    # headline, text, category, sub-type, tier
    ("Outcome of Board Meeting", "approved the unaudited financial results for the quarter", "results", "numbers", "matters"),
    ("Copy of Newspaper Publication", "newspaper publication of financial results", "results", "newspaper_ad", "buried"),
    ("Board Meeting Intimation", "to consider financial results on November 20, 2026", "results", "date_notice", "know"),
    (KMP, "Resignation of Mr. A B as Chief Financial Officer of the company", "management_change", "kmp_exit", "matters"),
    (KMP, "Appointment of Ms. C D as Managing Director and CEO", "management_change", "kmp_join", "matters"),
    (KMP, "Appointment of Ms. C D as Independent Director", "management_change", "board", "know"),
    (KMP, "Appointment of M/s XYZ as Secretarial Auditor", "unclassified", "auditor_appointment", "buried"),
    (KMP, "Resignation of statutory auditor M/s XYZ & Co", "management_change", "auditor_exit", "matters"),
    ("Acquisition", "acquisition of 51% stake in Y Ltd for Rs. 320 crore", "M&A", "deal", "matters"),
    ("Raising of Funds", "raising of funds through a qualified institutions placement", "fund_raise", "equity", "matters"),
    ("Credit Rating", "CRISIL has reaffirmed the rating", "credit_rating", "reaffirm", "buried"),
    ("Credit Rating", "ICRA has downgraded the long-term rating", "credit_rating", "downgrade", "matters"),
    ("Disclosure under SEBI Takeover Regulations", "creation of pledge on 1.9% of equity by promoter", "pledging", "pledge", "matters"),
    ("Bagging/Receiving of orders/contracts", "receipt of order worth Rs. 1,450 crore", "press_release", "order_win", "matters"),
    ("Action(s) initiated or orders passed", "GST demand order of Rs. 12 crore", "litigation", "order", "matters"),
    ("Dividend", "interim dividend of Rs. 6 per share", "dividend", "declared", "know"),
    (MEET, "Schedule of meet with institutional investors", "investor_meetings", "meet", "buried"),
    (MEET, "Transcript of the earnings call", "earnings_call", "transcript", "know"),
    ("Trading Window", "closure of trading window", "unclassified", "trading_window", "buried"),
    ("ESOP/ESOS/ESPS", "allotment of equity shares under ESOP", "unclassified", "esop", "buried"),
    ("General Updates", "X Limited has informed the Exchange about General Updates", "press_release", "general", "buried"),
]


@pytest.mark.parametrize("head,text,cat,sub,tier", CASES)
def test_rules(head, text, cat, sub, tier):
    p = prioritise({"headline": head, "text": text, "ts": "2026-11-14T10:00:00+05:30", "exch": "NSE"}, weight=5)
    assert (p["cat"], p["sub"], p["tier"]) == (cat, sub, tier), p["why"]


def test_amounts_and_boilerplate():
    assert amount_cr("order worth Rs. 1,450 crore and ₹ 25 lakh") == 1450
    assert amount_cr("USD nothing") is None
    line = one_line({"headline": "Acquisition", "text": "X Limited has informed the Exchange regarding acquisition of Y."})
    assert line == "Acquisition of Y"


def test_user_rules_override_ranking():
    item = {"headline": "Credit Rating", "text": "CRISIL has reaffirmed the rating", "ts": "2026-11-14T10:00:00+05:30"}
    assert prioritise(item, rules={"watch": ["credit_rating"]})["tier"] == "matters"
    big = {"headline": "Acquisition", "text": "acquisition of Y", "ts": "2026-11-14T10:00:00+05:30"}
    assert prioritise(big, rules={"mute": ["M&A"]})["tier"] == "buried"


def test_size_and_confluence_raise_rank():
    base = {"headline": "Bagging/Receiving of orders/contracts", "ts": "2026-11-14T10:00:00+05:30"}
    small = prioritise({**base, "text": "receipt of order worth Rs. 40 crore"})
    large = prioritise({**base, "text": "receipt of order worth Rs. 4,000 crore"})
    moved = prioritise({**base, "text": "receipt of order worth Rs. 40 crore"}, move={"pct": 6.0, "volx": 3.0, "date": "2026-11-14"})
    assert large["rank"] > small["rank"] and moved["rank"] > small["rank"]
