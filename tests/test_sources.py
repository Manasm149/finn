"""Parsers against records in the shape each source really returns."""
from finn import alerts, enrich
from finn.sources import announcements, prices, screener

NSE = [{"symbol": "LMW", "desc": "Press Release", "dt": "19072025101809",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/LAXMIMACH_19072025101722_X.pdf",
        "sm_name": "LMW Limited", "sm_isin": "INE269B01029", "an_dt": "19-Jul-2025 10:18:09",
        "sort_date": "2025-07-19 10:18:09", "seq_id": "105312", "attchmntText": "LMW Limited has informed the Exchange regarding a press release.",
        "exchdisstime": "19-Jul-2025 10:18:10", "difference": "00:00:01", "fileSize": "208 KB"}]
BSE = {"Table": [{"NEWSID": "abc-1", "SCRIP_CD": 500325, "NEWSSUB": "Reliance Industries Ltd - 500325 - Announcement under Regulation 30 (LODR)-Acquisition",
                  "DT_TM": "2025-07-19T10:18:09.52", "NEWS_DT": "2025-07-19T10:18:09.52", "ATTACHMENTNAME": "f1.pdf",
                  "HEADLINE": "Acquisition of stake in X", "CATEGORYNAME": "Company Update", "SUBCATNAME": "Acquisition",
                  "SLONGNAME": "Reliance Industries Ltd"}], "Table1": [{"ROWCNT": 1}]}
YAHOO = {"chart": {"result": [{"meta": {"symbol": "X.NS"}, "timestamp": [1752810300, 1752896700, 1752983100],
         "indicators": {"quote": [{"open": [10, 11, None], "high": [11, 12, None], "low": [9, 10, None],
                                   "close": [10.5, 11.25, None], "volume": [1000, 2000, None]}]}}], "error": None}}


def test_nse_record():
    it = announcements.parse_nse(NSE, "LMW")[0]
    assert it["ts"] == "2025-07-19T10:18:09+05:30" and it["exch"] == "NSE"
    assert it["headline"] == "Press Release" and it["url"].endswith(".pdf") and it["company"] == "LMW Limited"


def test_bse_record():
    it = announcements.parse_bse(BSE, "RELIANCE")[0]
    assert it["headline"].endswith("Acquisition") and "500325" not in it["headline"]
    assert it["url"].endswith("/AttachLive/f1.pdf") and it["ts"].startswith("2025-07-19T10:18:09")


def test_yahoo_chart_drops_unfinished_bar():
    bars = prices._parse(YAHOO)
    assert [b["c"] for b in bars] == [10.5, 11.25] and bars[0]["d"] == "2025-07-18"


def test_screener_page():
    co = screener.company("DHRUVTECH")
    assert co["name"] == "Dhruv Technologies Ltd" and co["bse_code"] == "590104" and co["basis"] == "consolidated"
    assert co["quarters"]["cols"][-1][:3] in ("Mar", "Jun", "Sep", "Dec")
    assert set(["Sales", "Operating Profit", "OPM %", "Net Profit"]) <= set(co["quarters"]["rows"])
    assert co["profit-loss"]["cols"][-1] == "TTM" and len(co["docs"]["concalls"]) == 5
    assert co["docs"]["concalls"][0]["transcript"].endswith(".pdf") and co["docs"]["annual_reports"][0]["fy"] >= 2025
    assert co["topline"]["Current Price"] == 2960


def test_bank_labels_are_handled():
    cut = enrich.first_cut("CAUVERYBNK")
    assert cut["rows"][0]["k"] == "Revenue" and cut["rows"][0]["v"] and cut["rows"][1]["v"]


def test_first_cut_maths_and_staleness():
    cut = enrich.first_cut("AARNA")
    rev = cut["rows"][0]
    assert cut["period"].startswith("Q") and 14 <= rev["yoy"] <= 16      # the sample grows 14.8% this year
    assert enrich.first_cut("AARNA", "2031-02-10T10:00:00+05:30")["fresh"] is False


def test_quarter_labels():
    assert enrich.quarter_label(2026, 9) == "Q2 FY27" and enrich.quarter_label(2026, 3) == "Q4 FY26"


def _bars(closes, vols):
    return [{"d": f"2026-01-{i + 1:02d}", "c": c, "v": v, "o": c, "h": c, "l": c} for i, (c, v) in enumerate(zip(closes, vols))]


def test_alert_thresholds_are_the_users():
    bars = _bars([100] * 25 + [103], [1000] * 25 + [2500])
    a = alerts.scan("X", bars, vol_x=2.0, px_pct=4.0)
    assert a["fired"] == ["volume"] and a["volx"] == 2.5 and a["pct"] == 3.0
    assert alerts.scan("X", bars, vol_x=3.0, px_pct=2.5)["fired"] == ["price"]
    assert alerts.scan("X", bars, vol_x=3.0, px_pct=5.0)["fired"] == []
