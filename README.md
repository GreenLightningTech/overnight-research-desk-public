# overnight-research-desk-public

An overnight stock research desk that runs on your own computer. A deterministic Python collector gathers facts from
free US sources behind a domain allow-list, every fact carries its source link and retrieval time, and a local LLM
reviewer checks the results before you read them in the morning. It makes no trading calls and has no broker access.

> **Research and education only. Not financial advice. This project does not trade.** See [DISCLAIMER.md](DISCLAIMER.md).

## Required software and applications

The collector uses only the Python standard library (no pip packages) and no paid cloud services. Versions are the
ones this was built and tested with; links were checked on 2026-10-28.

| Software | Tested version | Used for | Required? | Source |
|---|---|---|---|---|
| Python | 3.11 or newer | Runs the collector and tests (standard library only) | Yes | https://www.python.org/downloads/ |
| bash, git, curl | any recent | Run scripts, version control | Yes | https://www.gnu.org/software/bash/ · https://git-scm.com · https://curl.se |
| Docker (or another container runtime) | Docker 29 | Running the collector behind a network allow-list | Recommended | https://docs.docker.com/get-started/get-docker/ |
| dnsmasq | 2.90 | DNS allow-list (default deny), see `firewall/` | Recommended | https://thekelleys.org.uk/dnsmasq/doc.html |
| iptables / nftables (Linux) or pf (macOS) | iptables 1.8.10 | Drop traffic that bypasses the DNS allow-list | Recommended | https://www.netfilter.org/projects/iptables/ · https://www.netfilter.org/projects/nftables/ |
| Ollama | 0.40.8 | Local model server for the reviewer (localhost only) | For the review step | https://github.com/ollama/ollama |
| A local model, e.g. Qwen3.5 9B | Q4_K_M, 64k context | The reviewer's model | For the review step | https://ollama.com/library/qwen3.5 |
| A local LLM agent CLI with file tools | e.g. Hermes Agent 0.22.5 | Runs the review prompt (`REVIEW_CMD`) | For the review step | https://github.com/NousResearch/hermes-agent |
| Hammerspoon | 1.1.1 | Optional macOS scheduler example | Optional | https://github.com/Hammerspoon/hammerspoon/releases |

Data sources (all US, all free; keys go in `.env`, never in git):

| Source | What | Docs |
|---|---|---|
| Yahoo Finance chart API | Daily prices (primary; unofficial endpoint, check its terms) | https://finance.yahoo.com |
| Tiingo (free key) | Daily prices (cross-check) | https://www.tiingo.com/documentation/end-of-day |
| FRED, St. Louis Fed (free key) | VIX, HY and IG credit spreads, 2y/10y yields, fed funds | https://fred.stlouisfed.org/docs/api/fred/ |
| SEC EDGAR (submissions, Form 4, full-text search) | Filings, insider trades, earnings and material-event 8-Ks | https://www.sec.gov/edgar/sec-api-documentation · https://www.sec.gov/os/accessing-edgar-data |
| FINRA Query API (free credential) | Consolidated short interest | https://developer.finra.org/docs |
| BLS release calendar (ICS) | CPI, jobs and other release dates | https://www.bls.gov/schedule/news_release/bls.ics |
| BEA release calendar (ICS) | GDP, PCE and other release dates | https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics |
| Federal Reserve | FOMC calendar and monetary-policy statements | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm · https://www.federalreserve.gov/feeds/press_monetary.xml |

Not used, on purpose: Nasdaq (its terms ban automated collection), non-US data sources, brokers, paid cloud models.

## Quick start

    git clone https://github.com/GreenLightningTech/overnight-research-desk-public.git && cd overnight-research-desk-public
    cp .env.example .env                 # fill in SEC_USER_AGENT and the free keys; never commit .env
    $EDITOR config/desk.json             # your watchlist (ticker, SEC CIK, search terms)
    cp inputs/earnings-dates.example.csv inputs/earnings-dates.csv   # add confirmed earnings dates by hand
    python3 -m unittest discover -s tests                            # offline tests
    run/run-collector.sh                 # writes outputs/<today>/
    REVIEW_CMD="your-agent --oneshot --query-file" run/run-review.sh # optional local review

For real use, run the collector behind a network allow-list (see [firewall/README.md](firewall/README.md)) by setting
`DESK_WRAPPER` to a command that runs it inside your firewalled container.

## What runs, and when

| Step | Suggested time | What | Output |
|---|---|---|---|
| 1. Collector | ~1:00 AM | `run/run-collector.sh` runs `collector/collect.py` (deterministic, no LLM) | `outputs/<date>/` |
| 2. Review | ~4:30 AM | `run/run-review.sh` runs a local LLM agent with `reviewer/review-prompt.md` | `review.md` in the same folder |
| 3. Morning | before the open | The decision maker reads `brief-inputs.md`, `flags.md` and `review.md` | Their own notes |

## Output folder (one per date)

Times in the text are US Central (CT, the `CT` zone in `collector/desk/timeutil.py`); data.json keeps UTC.

| File | What |
|---|---|
| `brief-inputs.md` | Every fact as one line, each with its source link and retrieval time |
| `flags.md` | Flags (high / medium / info): sources that disagree, stale data, unverified or missing earnings dates, deliveries releases, material 8-Ks (Item 8.01) |
| `STATUS.md`, `status.json` | Per-source result and HTTP codes, overall ok / partial / failed, firewall canary |
| `sources.csv`, `requests.jsonl` | Every HTTP request: time, source, method, URL (keys redacted), HTTP code, bytes, seconds |
| `data.json` | All claims and flags as data |
| `run.log`, `run-meta.json` | Run log, exit code, memory samples |
| `review.md`, `review.log` | The review; its first line is the final verdict |

## Sources and checks

- **Watchlist** (`config/desk.json`): example tickers SPCX, TSLA, PLTR. `min_date` drops bars from before a symbol's
  current listing (SPCX was a different security before 2026-06-12).
- **Prices:** Yahoo and Tiingo, compared day by day: 1-day and 5-day change, 20-day range. Flags: closes differ by more
  than 0.5%, latest dates differ, data older than 4 days, no overlap. Today's bar is dropped before 4:15 PM ET.
- **Extension line:** close vs the prior 20-day high, vs a 20-day VWAP built from daily bars (an approximation), gap at
  the last open, the last two daily changes, and whether the last close is above the prior day's high. Facts only.
- **FRED:** VIXCLS, BAMLH0A0HYM2, BAMLC0A0CM, DGS10, DGS2, DFF. Stale after 5 days.
- **SEC:** recent filings per company (marks ones new since the last run), Form 4 details (owner, role, shares, price,
  10b5-1 flag), full-text search for other filers that name the company. Every 8-K Item 8.01 in the last 30 days is a
  MATERIAL_8K info flag with an excerpt. Item 2.02 8-Ks filed early in a quarter are opened; production/deliveries
  releases are DELIVERIES_RELEASE info flags, never earnings dates.
- **Earnings dates:** `inputs/earnings-dates.csv`, entered by hand. A "reported" date with no 8-K Item 2.02 within 3
  days is a high flag; a missing next date is a medium flag.
- **FINRA:** consolidated short interest. Stale after 35 days.
- **Calendars:** BLS and BEA ICS feeds (next 14 days), FOMC meetings, Fed monetary-policy statements.
- **Firewall canary:** the collector tries `example.com`, which must be blocked.

## Verdict rule

FAIL if the firewall canary was not blocked or the run failed; PASS WITH FLAGS if there is any high or medium flag or
any source is not OK; PASS otherwise. The final verdict is the stricter of this rule (computed by
`collector/desk/verdict.py`) and the reviewer's own verdict.

## Safety

- Network: in-code allow-list (`collector/desk/net.py`) plus a recommended network allow-list (`firewall/`).
- Memory: each run stops if free memory falls below `DESK_FLOOR` (default 10%). A watchdog samples every 5 seconds.
- Secrets: keys are read from the environment only and redacted from every URL in logs. `.gitignore` blocks env files;
  `scripts/check-secrets.sh` runs as a pre-commit hook (`git config core.hooksPath .githooks`) and in the tests.
- No broker access, no order code, no paid cloud keys; the reviewer's model runs on localhost.

## Scheduling (optional)

Use any scheduler. Example cron entries (local time, Mon-Fri):

    0 1 * * 1-5   /path/to/overnight-research-desk-public/run/run-collector.sh
    30 4 * * 1-5  /path/to/overnight-research-desk-public/run/run-review.sh

On macOS, `scheduler/research_desk.lua` is a Hammerspoon example (useful when launchd jobs can't read an external
volume). Turn it on with one line in your Hammerspoon `init.lua`, then reload:

    pcall(dofile, "/path/to/overnight-research-desk-public/scheduler/research_desk.lua")

Check it with `hs -c 'return researchDesk.status()'`. Turn it off by deleting the line and reloading. Timers don't fire
while the computer sleeps; this project never changes sleep settings.

## Tests

    python3 -m unittest discover -s tests              # offline; fixtures in tests/fixtures/ (public SEC/BLS/BEA/Fed pages)
    scripts/check-secrets.sh --all

## Layout

    collector/collect.py         entry point (steps, status, exit code)
    collector/desk/              net (allow-list, logging, redaction), prices, fred, sec, finra, calendars, earnings,
                                 crosscheck, report, claims, timeutil, verdict
    config/desk.json             example watchlist, thresholds, FRED series, SEC forms
    inputs/earnings-dates.example.csv   header for your hand-entered earnings dates
    reviewer/review-prompt.md    review prompt for the local LLM reviewer
    run/                         run-collector.sh, run-review.sh, common.sh
    firewall/                    allow-list, dnsmasq example, notes
    scheduler/research_desk.lua  optional Hammerspoon scheduler example
    scripts/check-secrets.sh     secrets check; .githooks/pre-commit
    docs/design.md               design notes
    .env.example                 settings template (empty keys)

## License

MIT, see [LICENSE](LICENSE). The collector has no third-party Python dependencies. The tools listed above are installed
separately under their own licenses (Hermes Agent, Hammerspoon and Ollama
are MIT; none of their code is included here). Test fixtures are excerpts of public US government web pages (SEC, BLS, BEA,
Federal Reserve).
