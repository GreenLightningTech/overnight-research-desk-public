"""Earnings dates come from a hand-filled CSV (by the decision maker, from company IR or the SEC 8-K). We never scrape Nasdaq.
Every 'reported' row is checked against SEC 8-K Item 2.02 filings within +/- N days.
Item 2.02 8-Ks that sec.classify_202() marked as production/deliveries releases are NOT earnings: they never confirm a
row and are shown as 'deliveries release' info flags. A fresh one (filed in the last few days) with no upcoming
'scheduled' row raises a medium flag: such releases usually announce the next earnings date."""
import csv, io
from datetime import date, timedelta
from .claims import Claim, Flag

FIELDS = ["ticker", "date", "status", "timing", "source_url", "entered_by", "entered_on"]


def load(path):
    with open(path, newline="") as f:
        lines = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    rows = []
    for r in csv.DictReader(io.StringIO("".join(lines))):
        r = {k: (r.get(k) or "").strip() for k in FIELDS}
        if r["ticker"] and r["date"]:
            rows.append(r)
    return rows


def check(rows, eightks_by_ticker, tickers, today, window, file_url, when, deliveries_new_days=7):
    """Returns (claims, flags)."""
    claims, flags = [], []
    for t in tickers:
        mine = [r for r in rows if r["ticker"].upper() == t]
        allks = eightks_by_ticker.get(t, [])
        ks = [k for k in allks if k.get("kind", "earnings") != "deliveries"]
        has_next = any(r["status"] == "scheduled" and r["date"] >= today.isoformat() for r in mine)
        for k in allks:
            if k.get("kind") != "deliveries":
                continue
            age = (today - date.fromisoformat(k["filingDate"])).days
            flags.append(Flag("info", "DELIVERIES_RELEASE", t, "%s 8-K Item 2.02 filed %s is a production/deliveries release, not earnings (%s)" % (
                t, k["filingDate"], k.get("exhibit_title") or "exhibit 99"), [k.get("exhibit_url") or k["url"], k["url"]]))
            if age <= deliveries_new_days and not has_next:
                flags.append(Flag("medium", "EARNINGS_DATE_TO_ADD", t, "%s deliveries release filed %s usually announces the next earnings date; read it and add the date to earnings-dates.csv" % (
                    t, k["filingDate"]), [k.get("exhibit_url") or k["url"], file_url]))
        for r in mine:
            try:
                rd = date.fromisoformat(r["date"])
            except ValueError:
                flags.append(Flag("medium", "EARNINGS_BAD_ROW", t, "earnings-dates.csv row has a bad date: %r" % r["date"], [file_url]))
                continue
            near = [k for k in ks if abs((date.fromisoformat(k["filingDate"]) - rd).days) <= window]
            if r["status"] == "reported":
                if near:
                    claims.append(Claim("earnings", t, "%s reported earnings %s (%s); confirmed by SEC 8-K Item 2.02 filed %s" % (
                        t, r["date"], r["timing"] or "timing n/a", near[0]["filingDate"]), near[0]["url"], when, "earnings_check",
                        {"date": r["date"], "verified": True, "accession": near[0]["accession"]}))
                else:
                    flags.append(Flag("high", "EARNINGS_UNVERIFIED", t, "%s 'reported' earnings date %s has no 8-K Item 2.02 within +/-%d days" % (
                        t, r["date"], window), [file_url, r["source_url"]]))
            elif r["status"] == "scheduled":
                days = (rd - today).days
                claims.append(Claim("earnings", t, "%s next earnings scheduled %s (%s), %d days away; source: entered by %s on %s" % (
                    t, r["date"], r["timing"] or "timing n/a", days, r["entered_by"] or "?", r["entered_on"] or "?"),
                    r["source_url"] or file_url, when, "earnings_input", {"date": r["date"], "days_away": days, "verified": False}))
                if rd < today:
                    flags.append(Flag("medium", "EARNINGS_PAST_SCHEDULED", t, "%s row %s is still 'scheduled' but the date has passed" % (t, r["date"]), [file_url]))
        if not has_next:
            flags.append(Flag("medium", "EARNINGS_NEXT_MISSING", t, "%s has no upcoming earnings date in earnings-dates.csv (fill it from company IR)" % t, [file_url]))
        listed = {r["date"] for r in mine}
        for k in ks:
            kd = date.fromisoformat(k["filingDate"])
            if not any(abs((date.fromisoformat(x) - kd).days) <= window for x in listed if _ok(x)):
                flags.append(Flag("info", "EARNINGS_8K_NOT_IN_FILE", t, "SEC 8-K Item 2.02 filed %s has no matching row in earnings-dates.csv. Item 2.02 also covers non-earnings results (e.g. Tesla delivery reports); please confirm" % k["filingDate"], [k["url"]]))
    return claims, flags


def _ok(s):
    try:
        date.fromisoformat(s); return True
    except ValueError:
        return False
