#!/usr/bin/env python3
"""Overnight research desk collector. Meant to run behind a domain allow-list firewall (US sources only; see firewall/).

  python collect.py --date 2026-10-29 --out /outputs/research-desk/2026-10-29 \
      --config /inputs/research-desk/config/desk.json --earnings /inputs/research-desk/inputs/earnings-dates.csv

Deterministic Python, no LLM. Never prints or writes API keys (URLs are redacted, auth headers are not logged)."""
import argparse, glob, json, os, sys, time, traceback
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from desk import __version__, net as netmod, prices, fred, sec, finra, calendars, earnings, crosscheck, report
from desk.claims import Claim, Flag


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="run date (host local CT date), YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--earnings", required=True)
    ap.add_argument("--only", default="", help="comma list of steps to run (debug)")
    a = ap.parse_args(argv)
    cfg = json.load(open(a.config))
    today = date.fromisoformat(a.date)
    os.makedirs(a.out, exist_ok=True)
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        print("SEC_USER_AGENT not set (SEC/BLS need a contact User-Agent)", file=sys.stderr); return 2
    n = netmod.Net("overnight-research-desk-public/%s %s" % (__version__, ua), log_path=os.path.join(a.out, "requests.jsonl"))
    t0 = time.time()
    run = {"date": a.date, "started_at": netmod.utcnow().isoformat(timespec="seconds"), "collector_version": __version__,
           "tickers": {t: v["role"] for t, v in cfg["tickers"].items()}}
    claims, flags, status = [], [], {"sources": {}}
    only = set(x for x in a.only.split(",") if x)

    def step(name, fn):
        if only and name not in only:
            return None
        before = len(n.calls)
        try:
            r = fn(); err = None
        except Exception as e:  # noqa: BLE001 - a failed source must not stop the run
            r, err = None, "%s: %s" % (type(e).__name__, str(e)[:300])
            flags.append(Flag("high", "SOURCE_FAILED", "-", "%s failed: %s" % (name, err)))
            traceback.print_exc(file=sys.stderr)
        codes = [c["http"] for c in n.calls[before:]]
        ok = err is None and all(c in (200, 204) for c in codes)
        if err is None and not ok:
            err = "non-200 responses: %s" % sorted(set(codes))
        status["sources"][name] = {"ok": ok, "http": codes, "error": err}
        print("[%s] %s http=%s%s" % ("ok" if ok else "FAIL", name, sorted(set(codes)), (" err=" + err) if err else ""), flush=True)
        return r

    prior = _prior_accessions(a.out)
    sc = cfg["sec"]
    subs = {}

    # 1) SEC filings (company), new since the last run
    def s_filings():
        out = []
        for t, v in cfg["tickers"].items():
            subs[t] = sec.submissions(n, v["cik"], sc["sleep_s"])
            since = max((today - timedelta(days=sc["filings_lookback_days"])).isoformat(), v.get("min_date") or "")
            for c in sec.recent_filings(subs[t], v["cik"], t, sc["forms"], since):
                c.data["new_since_last_run"] = c.data["accession"] not in prior
                if c.data["new_since_last_run"] and prior:
                    c.text = "NEW: " + c.text
                out.append(c)
        claims.extend(out)
    step("sec_submissions", s_filings)

    # 2) Form 4 insider trades
    def s_form4():
        for t, v in cfg["tickers"].items():
            if t in subs:
                since = (today - timedelta(days=sc["form4_lookback_days"])).isoformat()
                claims.extend(sec.form4s(n, subs[t], v["cik"], t, since, sc["form4_max_per_ticker"], sc["sleep_s"]))
    step("sec_form4", s_form4)

    # 3) EDGAR full-text search: mentions by OTHER filers in the last few days
    def s_efts():
        start = (today - timedelta(days=sc["efts_lookback_days"])).isoformat()
        for t, v in cfg["tickers"].items():
            for term in v["name_terms"]:
                r = sec.efts(n, term, start, a.date, max_hits=sc["efts_max_hits"])
                time.sleep(sc["sleep_s"])
                others = [h for h in r["hits"] if str(h["cik"]).lstrip("0") != str(v["cik"])]
                for h in others:
                    claims.append(Claim("sec_mention", t, "%s mentioned in %s filed %s by %s" % (term, h["form"], h["file_date"], h["filer"]),
                                        h["url"], r["retrieved_at"], "sec_efts", h))
                claims.append(Claim("sec_mention", t, "EDGAR full-text search %s, %s to %s: %d hits total, %d from other filers listed" % (
                    term, start, a.date, r["total"], len(others)), r["page_url"], r["retrieved_at"], "sec_efts", {"total": r["total"]}))
    step("sec_efts", s_efts)

    # 3b) Material 8-Ks: every Item 8.01 (Other Events) filing in the filings window goes to flags.md with an excerpt
    def s_material():
        it = sc.get("material_item", "8.01")
        for t, v in cfg["tickers"].items():
            if t not in subs:
                continue
            since = max((today - timedelta(days=sc["filings_lookback_days"])).isoformat(), v.get("min_date") or "")
            for m in sec.material_8ks(n, subs[t], v["cik"], t, since, it, sc.get("material_max_per_ticker", 5), sc["sleep_s"]):
                new = m["accession"] not in prior
                txt = "%s%s material filing: 8-K Item %s (%s) filed %s: %s" % ("NEW: " if new and prior else "", t, it, sec.ITEM_NAMES.get(it, "?"), m["filingDate"],
                      m["excerpt"] or "(excerpt not available, HTTP %s)" % m["http"])
                flags.append(Flag("info", "MATERIAL_8K", t, txt, [m["url"]]))
    step("sec_material", s_material)

    # 4) Earnings: hand-entered dates checked against 8-K Item 2.02
    def s_earn():
        rows = earnings.load(a.earnings)
        since = (today - timedelta(days=cfg["earnings"]["lookback_8k_days"])).isoformat()
        ks = {t: sec.earnings_8ks(subs[t], v["cik"], max(since, v.get("min_date") or "")) for t, v in cfg["tickers"].items() if t in subs}
        for t, lst in ks.items():
            for k in lst:
                sec.classify_202(n, cfg["tickers"][t]["cik"], k, cfg["earnings"].get("deliveries_early_days", 10), sc["sleep_s"])
                if k.get("classify_error"):
                    flags.append(Flag("info", "EARNINGS_8K_UNCLASSIFIED", t, "8-K filed %s: could not read exhibits (%s); treated as earnings" % (
                        k["filingDate"], k["classify_error"]), [k["url"]]))
        if len(ks) < len(cfg["tickers"]):
            flags.append(Flag("high", "EARNINGS_UNCHECKED", "-", "SEC submissions missing for some tickers; earnings rows not verified"))
        c, f = earnings.check(rows, ks, list(cfg["tickers"]), today, cfg["earnings"]["verify_window_days"],
                              "inputs/earnings-dates.csv", netmod.utcnow().isoformat(timespec="seconds"),
                              cfg["earnings"].get("deliveries_new_days", 7))
        claims.extend(c); flags.extend(f)
        dl = {k["accession"] for lst in ks.values() for k in lst if k.get("kind") == "deliveries"}
        for cl in claims:                                   # label deliveries releases in the filings list too
            if cl.topic == "sec_filing" and cl.data.get("accession") in dl:
                cl.text += "; production/deliveries release, not earnings"
    step("earnings_check", s_earn)

    # 5) Prices: Yahoo + Tiingo, then cross-check
    px = {}
    def s_yahoo():
        for t, v in cfg["tickers"].items():
            px.setdefault(t, {})["yahoo"] = prices.yahoo(n, t, cfg["prices"]["lookback_days"], v.get("min_date"))
            claims.extend(prices.summarize(t, px[t]["yahoo"]))
            flags.extend(crosscheck.min_date(t, px[t]["yahoo"]["dropped_before_min_date"], v.get("min_date"), v.get("min_date_reason", ""), px[t]["yahoo"]["page_url"]))
    step("yahoo", s_yahoo)
    def s_tiingo():
        for t, v in cfg["tickers"].items():
            px.setdefault(t, {})["tiingo"] = prices.tiingo(n, t, cfg["prices"]["lookback_days"], v.get("min_date"))
            claims.extend(prices.summarize(t, px[t]["tiingo"])[:1])
    step("tiingo", s_tiingo)
    for t in cfg["tickers"]:
        if px.get(t, {}).get("yahoo") or px.get(t, {}).get("tiingo"):
            flags.extend(crosscheck.prices(t, px[t].get("yahoo"), px[t].get("tiingo"), today, cfg["prices"]))
        else:
            flags.append(Flag("high", "PRICE_MISSING", t, "%s: no price data from either source" % t))

    # 6) FRED macro gauges
    fs = {}
    def s_fred():
        for sid, meta in cfg["fred"]["series"].items():
            s, c = fred.series(n, sid, meta["label"], cfg["fred"]["lookback_days"])
            fs[sid] = s; claims.extend(c)
    step("fred", s_fred)
    flags.extend(crosscheck.fred(fs, today, cfg["fred"]))

    # 7) Calendars: BLS, BEA, FOMC, Fed statements
    hz = cfg["calendars"]["horizon_days"]
    def s_bls():
        txt, when = n.get_text(calendars.BLS_URL, source="bls")
        ev = calendars.parse_ics(txt)
        claims.extend(calendars.ics_claims(ev, "bls", calendars.BLS_URL, when, today, hz))
        if not calendars.upcoming(ev, today, 60):
            flags.append(Flag("medium", "STALE", "MACRO", "BLS calendar has no events in the next 60 days", [calendars.BLS_URL]))
    step("bls", s_bls)
    def s_bea():
        txt, when = n.get_text(calendars.BEA_URL, source="bea")
        ev = calendars.parse_ics(txt)
        claims.extend(calendars.ics_claims(ev, "bea", calendars.BEA_URL, when, today, hz))
        if not calendars.upcoming(ev, today, 60):
            flags.append(Flag("medium", "STALE", "MACRO", "BEA calendar has no events in the next 60 days", [calendars.BEA_URL]))
    step("bea", s_bea)
    def s_fomc():
        page, when = n.get_text(calendars.FOMC_URL, source="fed_fomc")
        ms = calendars.parse_fomc(page, today.year)
        if today.month >= 11:
            ms += calendars.parse_fomc(page, today.year + 1)
        if not ms:
            raise RuntimeError("could not parse FOMC calendar for %d" % today.year)
        c, nxt = calendars.fomc_claims(ms, when, today, hz)
        claims.extend(c)
    step("fed_fomc", s_fomc)
    def s_rss():
        txt, when = n.get_text(calendars.FED_RSS, source="fed_rss")
        claims.extend(calendars.rss_claims(calendars.parse_rss(txt), when, today))
    step("fed_rss", s_rss)

    # 8) FINRA short interest
    def s_finra():
        tok = finra.token(n)
        since = (today - timedelta(days=75)).isoformat()
        for t, v in cfg["tickers"].items():
            rows, when = finra.short_interest(n, tok, t, since, min_date=v.get("min_date"))
            claims.extend(finra.claims_for(t, rows[:1], when))
            flags.extend(crosscheck.finra(t, rows, today, cfg["finra"], finra.PUBLIC_URL))
    step("finra", s_finra)

    # 9) Firewall canary: a non-allow-listed name must NOT resolve
    blocked, detail = netmod.firewall_canary(cfg.get("firewall_canary", "example.com"))
    status["firewall"] = {"host": cfg.get("firewall_canary", "example.com"), "blocked": blocked, "detail": detail}
    if not blocked:
        flags.append(Flag("high", "FIREWALL_OPEN", "-", "Non-allow-listed host resolved: %s" % detail))

    nok = sum(1 for s in status["sources"].values() if not s["ok"])
    status["overall"] = "ok" if nok == 0 and blocked else ("failed" if nok > len(status["sources"]) / 2 else "partial")
    run["finished_at"] = netmod.utcnow().isoformat(timespec="seconds")
    run["elapsed_s"] = round(time.time() - t0, 1)
    status["counts"] = {"claims": len(claims), "flags": len(flags), "requests": len(n.calls)}
    report.write_all(a.out, run, claims, flags, n.calls, status)
    print("overall=%s claims=%d flags=%d requests=%d elapsed=%ss out=%s" % (status["overall"], len(claims), len(flags), len(n.calls), run["elapsed_s"], a.out))
    return 0 if status["overall"] in ("ok", "partial") else 1


def _prior_accessions(out):
    parent, me = os.path.dirname(os.path.abspath(out)), os.path.basename(os.path.abspath(out))
    prev = sorted(p for p in glob.glob(os.path.join(parent, "20??-??-??")) if os.path.basename(p) < me)
    for p in reversed(prev):
        f = os.path.join(p, "data.json")
        if os.path.exists(f):
            try:
                return {c["data"].get("accession") for c in json.load(open(f))["claims"] if c["topic"] == "sec_filing"}
            except Exception:
                return set()
    return set()


if __name__ == "__main__":
    sys.exit(main())
