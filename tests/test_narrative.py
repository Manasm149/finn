from finn import llm, narrative
from finn.sources import screener

CALL = ["""Moderator: Welcome. The first question is from the line of Rahul Shah from Axis Capital.
Rahul Shah: You had guided for 20% to 22% revenue growth this year. Is that intact?
Anil Rao: We maintain our guidance of 12% to 14% revenue growth for FY27. We expect EBITDA margin in the range of 18% to 19% for the full year.
Anil Rao: Last quarter our EBITDA margin was 17.2% and revenue grew 11%.
Meera Iyer: Net profit should grow at least 15% in FY27. Over the medium term we aspire to mid-teens growth in revenue.
Meera Iyer: We expect utilisation of 80% to 85% next year."""]


def test_extracts_management_targets_only():
    got = {(p["metric"], p["lo"], p["hi"], p["period"]) for p in narrative.heuristic_promises(CALL, "Jul 2026")}
    assert got == {("revenue_growth", 12.0, 14.0, "FY27"), ("margin", 18.0, 19.0, "FY27"),
                   ("pat_growth", 15.0, None, "FY27"), ("revenue_growth", 14, 16, "medium term")}


def test_ledger_scores_and_tracks_revisions():
    act = {"FY25": {"sales": 100, "op": 20, "pat": 10}, "FY26": {"sales": 110.8, "op": 21.7, "pat": 11}}
    c1 = {"date": "Oct 2025", "transcript": "u1"}
    c2 = {"date": "Jan 2026", "transcript": "u2"}
    p = lambda lo, hi: {"metric": "revenue_growth", "lo": lo, "hi": hi, "period": "FY26", "assumed_period": False,  # noqa: E731
                        "quote": "q", "speaker": "CEO", "page": 1}
    e = narrative.ledger([(c1, [p(16, 18)]), (c2, [p(11, 12)])], act)[0]
    assert e["status"] == "missed" and e["actual"] == 10.8 and e["target"] == "16–18%"
    assert e["revisions"][0]["move"] == "cut" and e["status_vs_latest"] == "met"
    assert narrative.scorecard([e]) == {"kept": 0, "missed": 1, "live": 0, "behind": 0, "cuts": 1, "total": 1}


def test_year_in_progress_is_tracked_not_judged():
    act = {("FY26", 1): {"sales": 100, "op": 20, "pat": 10}, ("FY26", 2): {"sales": 100, "op": 20, "pat": 10},
           ("FY27", 1): {"sales": 108, "op": 20, "pat": 10}, ("FY27", 2): {"sales": 109, "op": 20, "pat": 10}}
    call = {"date": "May 2026", "transcript": "u"}
    pr = {"metric": "revenue_growth", "lo": 14, "hi": 16, "period": "FY27", "assumed_period": False,
          "quote": "q", "speaker": "CEO", "page": 1}
    e = narrative.ledger([(call, [pr])], act)[0]
    assert e["status"] == "behind" and e["final"] is False and "2 of 4" in e["detail"] and e["actual"] == 8.5


def test_full_run_on_a_company():
    out = narrative.run("DHRUVTECH")
    by = {(e["label"], e["period"]): e for e in out["ledger"]}
    assert by[("Revenue growth", "FY26")]["status"] == "missed"
    assert by[("EBITDA margin", "FY27")]["status"] == "behind"
    assert out["score"]["kept"] == 0 and out["score"]["cuts"] == 2 and all(c["ok"] for c in out["calls"])
    steady = narrative.run("AARNA")["score"]
    assert steady["missed"] == 0 and steady["kept"] >= 2


def test_model_cannot_invent_a_quote(monkeypatch):
    """A promise whose quote is not in the transcript is thrown away, whatever the model says."""
    monkeypatch.setattr(llm, "ready", lambda: True)
    monkeypatch.setattr(llm, "json_call", lambda *a, **k: {"promises": [
        {"metric": "revenue_growth", "lo": 12, "hi": 14, "period": "FY27",
         "quote": "We maintain our guidance of 12% to 14% revenue growth for FY27."},
        {"metric": "margin", "lo": 30, "hi": 32, "period": "FY27",
         "quote": "We are very confident of 30% to 32% EBITDA margin next year."}]})
    got = narrative.model_promises(CALL, "Jul 2026")
    assert len(got) == 1 and got[0]["lo"] == 12 and got[0]["speaker"] == "Anil Rao" and got[0]["page"] == 1


def test_json_repair():
    assert llm.parse_json('Sure!\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert llm.parse_json("no json here") is None


def test_actuals_come_from_reported_tables():
    act = narrative.actuals(screener.company("AARNA"))
    fy = sorted(k for k in act if isinstance(k, str))
    assert len(fy) == 10 and any(isinstance(k, tuple) for k in act)
