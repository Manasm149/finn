import time

from finn.app import app

c = app.test_client()


def test_digest_filters_hard():
    d = c.get("/api/digest?hours=24").get_json()
    n = d["counts"]
    assert n["total"] > 30 and n["matters"] <= 8 and n["buried"] > n["matters"] * 3
    assert n["total"] == n["matters"] + n["know"] + n["buried"] + n["folded"]
    assert [p["rank"] for p in d["matters"]] == sorted((p["rank"] for p in d["matters"]), reverse=True)
    results = next(p for p in d["matters"] if p["cat"] == "results")
    assert results["first_cut"]["fresh"] and len(results["related"]) == 2 and "revenue up" in results["line"]
    assert {u["what"] for u in d["upcoming"]} == {"Results", "Record date"}
    assert not d["errors"]


def test_thresholds_change_what_fires():
    loose = c.get("/api/digest?hours=24&px=2&vol=1.5").get_json()["counts"]["movers"]
    tight = c.get("/api/digest?hours=24&px=9&vol=5").get_json()["counts"]["movers"]
    assert loose >= 4 and tight == 0


def test_management_card_carries_the_profile():
    d = c.get("/api/digest?hours=24").get_json()
    m = next(p for p in d["matters"] if p["cat"] == "management_change")
    det = c.get(f"/api/filing/{m['id']}").get_json()
    assert {x["action"] for x in det["people"]} == {"Joining", "Leaving"}
    assert "Chartered Accountant" in det["profile"] and "linkedin.com" in det["lookup"]


def test_research_generalises_beyond_the_book():
    r = c.get("/api/research/KAVERIAUTO").get_json()       # not a holding
    assert r["name"].startswith("Kaveri") and len(r["trajectory"]["years"]) == 10 and r["quarters"]
    assert c.get("/api/research/NOSUCHCO").status_code == 404
    bank = c.get("/api/research/CAUVERYBNK").get_json()
    assert bank["financial"] and not any("Leverage" in f["title"] for f in bank["flags"])


def test_flags_tell_the_story():
    titles = {f["title"] for f in c.get("/api/research/DHRUVTECH").get_json()["flags"]}
    assert {"Margins are compressing", "Profits are not turning into cash", "Customers are paying more slowly"} <= titles


def test_narrative_job_and_ask_routes():
    while (j := c.get("/api/narrative/AARNA").get_json())["state"] == "running":
        time.sleep(0.1)
    assert j["state"] == "done" and j["steps"][-1] == "Weighing the record"
    assert c.post("/api/ask", json={"q": "what changed in the last 3 days"}).get_json() == {"type": "digest", "hours": 72}
    assert c.post("/api/ask", json={"q": "Kaveri Auto"}).get_json()["symbol"] == "KAVERIAUTO"
    a = c.post("/api/ask", json={"q": "Why did receivable days move up at DHRUVTECH?"}).get_json()
    assert a["type"] == "answer" and "receivable" in a["passages"][0]["text"].lower()
