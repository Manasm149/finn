"""python -m finn.watch  -  the push that reaches you when the app is closed.

Run it on a schedule (cron, or the GitHub Actions workflow in .github/). It builds the
last-24h digest, and sends anything new that matters to a Telegram chat. "New" is
tracked in the cache, so each item is pushed once.
"""
from datetime import timedelta

import requests

from . import cache, config, digest


def main():
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT):
        print("Set FINN_TELEGRAM_TOKEN and FINN_TELEGRAM_CHAT to enable pushes.")
        return
    end = digest.now()
    d = digest.build(config.portfolio(), end - timedelta(hours=24), end, dict(config.DEFAULT_RULES))
    sent = set(cache.get("watch:sent", stale_ok=True) or [])
    lines = []
    for a in d["movers"]:
        key = f"{a['symbol']}{a['date']}"
        if key not in sent:
            sent.add(key)
            lines.append(f"<b>{a['symbol']}</b> {a['pct']:+.1f}%, {a['volx']:.1f}x volume. {a['text'].capitalize()}.")
    for p in d["matters"]:
        if p["id"] not in sent:
            sent.add(p["id"])
            link = f' <a href="{p["url"]}">filing</a>' if p.get("url") else ""
            lines.append(f"<b>{p['symbol']}</b> {p['label']}: {p['line']}{link}")
    if lines:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage", timeout=20, json={
            "chat_id": config.TELEGRAM_CHAT, "parse_mode": "HTML", "disable_web_page_preview": True,
            "text": f"FINN: {len(lines)} new\n\n" + "\n\n".join(lines[:12])})
        r.raise_for_status()
    cache.put("watch:sent", sorted(sent)[-800:])
    print(f"{len(lines)} pushed, {d['counts']['buried']} buried")


if __name__ == "__main__":
    main()
