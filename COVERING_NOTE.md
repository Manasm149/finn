<!-- Draft for the covering email. Subject: IIT Delhi – AI Engineer - 2027 → assessment@enam.com
     Edit it into your own words, fill the three links, and check the "status" line is true
     for what you actually ran before sending. -->

**Links**
- Prototype (open on a phone): [deployed URL]
- Repository: [GitHub URL]
- AI build history: [export / share link of the coding-agent conversation]

**What I built**

FINN answers one question: what changed in my book, and what of it matters? The home
screen is a sentence ("42 filings in the last 24 hours. 6 are worth your time.") over a
strip of ticks, one per filing, with the few that matter standing tall. Below it: unusual
moves against thresholds I set, cards for what matters, one-liners for what is good to
know, and a collapsed count of everything buried. Each card has a Done button and the
screen ends at "You're caught up", because a tool I check through the day should have a
finish line.

On the pull side, any NSE ticker opens a research view led by "Said vs did": numeric
guidance from the last five earnings calls, each scored against reported numbers as met,
missed, running behind, or cut mid-year, with the quote and page it came from.

**Key decisions**

1. *The model reads; the code counts.* Classification, ranking, alerts and every number
   are deterministic. A model is used only to read filings and transcripts. Every quote
   is verified word for word against the transcript and every target is compared with
   reported figures in code, so a model can miss a promise but cannot invent one.
2. *Cheap by construction.* Rules handle all filings at zero cost. Transcripts are
   pre-filtered to about a fifth of their length before a fast model sees them, a
   stronger model is called once per company on about 1 KB of checked facts, and
   everything is cached forever because filings do not change. The app runs with no key.
3. *Rankings you can audit.* "Why ranked here" shows the arithmetic behind each card.
4. *Primary sources where they are better.* For a management change I use the profile
   the company must attach to the filing rather than scraping LinkedIn.
5. *One input.* A single bar takes a ticker, a question, or "what changed this week",
   typed or spoken; the brief can be read aloud.

6. *Open to read, gated to spend.* Anyone can open the link and use FINN as a guest.
   Signing in as an analyst unlocks model reading; admins see live operations (p95
   latency per route, errors, rate-limit hits, sign-in audit). Sessions are signed
   tokens and accounts live in configuration, because the free host wipes its disk.
   Token-bucket rate limits, request coalescing, a circuit breaker on each source, a
   daily model budget cap, a strict Content Security Policy and structured logs with
   request IDs are all in, and docs/SYSTEM_DESIGN.md says what each becomes at scale.
   Reviewer login: [username] / [password]  ← create with `python -m finn.users add`

**Trade-offs**

- The results first cut comes from screener.in's standardised quarterly table rather
  than the results PDF: exact and free, but it can lag a filing by hours, and the card
  says so when it does.
- EBITDA margin is measured as operating profit before other income, which can differ
  slightly from a company's own definition.
- Without a model, guidance extraction uses rules and will miss unusual phrasings.
- Exchanges block some cloud IPs, so the app keeps a saved copy and labels it.

**Left out on purpose**

Intraday data, accounts and server-side state, embeddings, capex tracking against
guidance (not broken out in the standardised statements), and news or broker research.

**Where I would take it next**

Parse results from the exchanges' XBRL feed for a same-minute first cut; add segment
and KPI guidance to the ledger; a per-management "say-do" score tracked over years;
true push through a small always-on worker; and a portfolio-level view of which
holdings' stories are diverging from their numbers.

**Status**: [say which of live data, hosted deploy and model calls you ran, and with which model]
