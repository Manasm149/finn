"""python -m finn.warm [EXTRA_SYMBOL ...]  -  fill the cache for the whole book.

Fetches prices, 30 days of filings, fundamentals and the promise ledger for every
holding (plus any extra tickers). Afterwards the app answers instantly, and a deploy
that ships data/finn.db keeps working when a source blocks the host.
"""
import sys
from datetime import timedelta

from . import config, digest, narrative, research


def main():
    extra = [s.upper() for s in sys.argv[1:]]
    book = config.portfolio()
    end = digest.now()
    d = digest.build(book, end - timedelta(days=30), end, dict(config.DEFAULT_RULES))
    print(f"digest: {d['counts']['total']} filings, {d['counts']['matters']} surfaced, {len(d['errors'])} source errors")
    for e in d["errors"]:
        print(f"   {e['symbol']} {e['what']}: {e['error']}")
    for sym in [h["symbol"] for h in book] + extra:
        try:
            r = research.build(sym)
            n = narrative.run(sym)
            print(f"{sym:12s} {len(r['flags'])} observations, {len(n['ledger'])} promises "
                  f"({sum(c['ok'] for c in n['calls'])}/{len(n['calls'])} transcripts read, {n['method']})")
        except Exception as e:  # noqa: BLE001
            print(f"{sym:12s} FAILED: {str(e)[:120]}")


if __name__ == "__main__":
    main()
