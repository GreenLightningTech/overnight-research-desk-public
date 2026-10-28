# Design notes

## Principles
- Deterministic collector, no LLM. Every fact becomes a Claim with `source_url` and `retrieved_at` (UTC in data, local
  time in text).
- Facts are neutral (closes, changes, ranges, filings, dates). No signals, targets or trading calls.
- One request log (`requests.jsonl` / `sources.csv`) with HTTP code, bytes and seconds for every call; API keys redacted.
- Two layers of network control: `desk/net.py` refuses hosts outside its US allow-list, and a network firewall
  (see `firewall/`) refuses everything else. A canary (example.com) proves the firewall is on.
- A failed source never stops the run. Overall status: ok (all sources), partial (some failed), failed (no prices at all).
- The reviewer is a local LLM agent that reads only the results folder. It checks citations, values, freshness and
  contradictions; it does not add facts or give advice.
- Clear roles: the code collects and checks; a human decision maker owns the methods and every action.

## Decisions
- FINRA dataset: `otcMarket/consolidatedShortInterest`. `equityShortInterest` returns 204 for listed symbols.
  `sortFields` returns 400 unless the date filter is EQUAL, so rows are sorted client-side.
- Earnings dates: a hand-entered CSV, verified against SEC 8-K Item 2.02 (3-day window). No Nasdaq scraping (its terms
  ban automated collection), no estimates.
- Item 2.02 also covers production/deliveries releases (e.g. Tesla). Item 2.02 8-Ks filed early in a quarter are
  opened and classified by their exhibit 99 text; deliveries releases never confirm an earnings row and appear as
  DELIVERIES_RELEASE info flags. A fresh one with no upcoming date raises EARNINGS_DATE_TO_ADD, because such releases
  usually announce the next earnings date.
- Every 8-K Item 8.01 (Other Events) becomes a MATERIAL_8K info flag with a short excerpt (one extra request to
  www.sec.gov each; no new hosts).
- Yahoo returns an intraday bar for today during the session; bars dated today are dropped before 4:15 PM ET.
- Extension facts (close vs prior 20-day high, vs a 20-day VWAP built from daily bars, gap, last two daily changes,
  close above prior day's high) are derived from the same daily bars: no new data source.
- Review verdict: small local models sometimes say PASS when the rule says PASS WITH FLAGS. `run-review.sh` therefore
  computes the verdict from data.json/status.json (`collector/desk/verdict.py`) and records the stricter of that and
  the reviewer's verdict as the first line of `review.md`.
- Scheduling is optional and outside the code: cron, launchd, systemd or the Hammerspoon example in `scheduler/`.

## Known gaps
- No free US options-flow feed.
- Timers don't fire while the computer sleeps (the Hammerspoon example catches up once on wake before 7 AM).
- The 20-day VWAP is an approximation from daily bars, not intraday VWAP.
