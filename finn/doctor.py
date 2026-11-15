"""python -m finn.doctor [SYMBOL]  -  checks every live source and the model, and says what to fix.

Run this first on any new machine or host. Exchanges block some cloud IP ranges, and
this tells you in ten seconds which sources work from where you are.
"""
import sys
from datetime import timedelta

from . import config, digest, llm
from .sources import announcements, docs, prices, screener


def check(name, fn):
    try:
        print(f"  ok    {name}: {fn()}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {name}: {str(e)[:200]}")
        return False


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "TCS").upper()
    if config.SAMPLE:
        print("FINN_SAMPLE=1 is set: this would only test the generated fixtures. Unset it.")
        return 1
    print(f"Checking live sources with {sym}\n")
    end = digest.now()
    co = {}
    results = [
        check("prices (Yahoo chart)", lambda: f"{len(prices.history(sym))} daily bars, last close {prices.history(sym)[-1]['c']}"),
        check("fundamentals (screener.in)", lambda: (co.update(screener.company(sym)) or
              f"{co['name']}, {len(co['quarters']['cols'])} quarters, {len(co['docs']['concalls'])} calls ({sum('transcript' in c for c in co['docs']['concalls'])} with transcripts), {len(co['docs']['annual_reports'])} annual reports, BSE {co['bse_code']}")),
        check("filings (NSE, BSE fallback)", lambda: (lambda r: f"{len(r[0])} filings in 14 days"
              + (" (from saved copy)" if r[1] else "") + (f", via {r[0][0]['exch']}" if r[0] else ""))(
              announcements.fetch(sym, end - timedelta(days=14), end, bse_code=co.get("bse_code")))),
        check("company search", lambda: screener.search(sym)[:2]),
    ]
    calls = [c for c in (co.get("docs") or {}).get("concalls", []) if c.get("transcript")]
    if not calls:      # show the page's own markup so the parser can be fixed
        from . import cache
        html = next((v for v in (cache.get(f"http:{co.get('source', '')}", stale_ok=True),) if v), "")
        i = html.find("Concalls")
        print("  --    no transcripts parsed. Markup around 'Concalls':\n" + (html[max(0, i - 300): i + 1500] if i >= 0 else "  ('Concalls' does not appear in the page)"))
    if calls:
        results.append(check("transcript PDF", lambda: f"{calls[0]['date']}: {len(docs.pages(calls[0]['transcript'], 60))} pages, "
                             f"{sum(map(len, docs.pages(calls[0]['transcript'], 60))):,} characters"))
    if llm.ready():
        results.append(check(f"model, fast tier ({config.MODEL_FAST})",
                             lambda: llm.chat("fast", "doctor", "Reply with the single word: ready", 10) or (_ for _ in ()).throw(RuntimeError("no reply"))))
        if config.MODEL_SMART != config.MODEL_FAST:
            results.append(check(f"model, smart tier ({config.MODEL_SMART})",
                                 lambda: llm.chat("smart", "doctor", "Reply with the single word: ready", 10) or (_ for _ in ()).throw(RuntimeError("no reply"))))
    else:
        print("  --    model: not configured. FINN runs on rules alone; set FINN_LLM_* in .env to add reading.")
    bad = results.count(False)
    print(f"\n{len(results) - bad} of {len(results)} checks passed." + (
        "\nIf filings fail from a cloud host but work on your laptop, run `python -m finn.warm` locally and "
        "ship data/finn.db with the deploy: FINN serves the saved copy when an exchange refuses it." if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
