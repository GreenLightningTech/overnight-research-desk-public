"""US release calendars: BLS (.ics), BEA (.ics), Fed FOMC meetings (HTML) and Fed monetary press releases (RSS)."""
import re, html, xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
from .claims import Claim
from .timeutil import ET as EASTERN, CT

BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


def parse_ics(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n[ \t]", "", text)                 # unfold continuation lines
    events = []
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)END:VEVENT", text, re.S):
        ev = {}
        for line in block.split("\n"):
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            name = k.split(";")[0]
            if name == "SUMMARY":
                ev["summary"] = v.replace("\\,", ",").replace("\\;", ";").strip()
            elif name == "DTSTART":
                if v.endswith("Z"):
                    ev["start"] = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                elif "T" in v:
                    ev["start"] = datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=EASTERN)  # BLS TZID=US-Eastern
                else:
                    ev["start"] = datetime.strptime(v, "%Y%m%d").replace(tzinfo=EASTERN)
        if "start" in ev and "summary" in ev:
            events.append(ev)
    return events


def upcoming(events, today, horizon_days):
    end = today + timedelta(days=horizon_days)
    return sorted([e for e in events if today <= e["start"].astimezone(CT).date() <= end], key=lambda e: e["start"])


def ics_claims(events, src, url, when, today, horizon):
    out = []
    for e in upcoming(events, today, horizon):
        t = e["start"].astimezone(CT)
        out.append(Claim("calendar", "MACRO", "%s release: %s on %s" % (src.upper(), e["summary"], t.strftime("%a %b %d %I:%M %p CT")),
                         url, when, src, {"date": t.date().isoformat(), "time_ct": t.strftime("%H:%M"), "title": e["summary"]}))
    return out


def parse_fomc(page, year):
    i = page.find("%d FOMC Meetings" % year)
    if i < 0:
        return []
    j = page.find("FOMC Meetings", i + 20)
    seg = page[i:j if j > 0 else None]
    meetings = []
    for block in re.split(r'<div class="[^"]*row fomc-meeting"', seg)[1:]:
        m = re.search(r"fomc-meeting__month[^>]*><strong>([A-Za-z/]+)</strong>", block)
        dd = re.search(r'fomc-meeting__date[^>]*>([^<]+)<', block)
        if not (m and dd):
            continue
        month_txt, day_txt = m.group(1), html.unescape(dd.group(1)).strip()
        sep = "*" in day_txt                                 # * = Summary of Economic Projections meeting
        days = re.findall(r"\d+", day_txt)
        months = month_txt.split("/")
        last_month = MONTHS.get(months[-1])
        if not (days and last_month):
            continue
        end = date(year, last_month, int(days[-1]))
        stmt = re.search(r'href="(/newsevents/pressreleases/monetary\d{8}a\.htm)"', block)
        meetings.append({"label": "%s %s" % (month_txt, day_txt), "end_date": end.isoformat(), "sep": sep,
                         "statement_url": ("https://www.federalreserve.gov" + stmt.group(1)) if stmt else None})
    return meetings


def fomc_claims(meetings, when, today, horizon):
    out, nxt = [], None
    for m in meetings:
        d = date.fromisoformat(m["end_date"])
        if d >= today and nxt is None:
            nxt = m
        if today - timedelta(days=7) <= d < today and m["statement_url"]:
            out.append(Claim("calendar", "MACRO", "FOMC statement released %s (meeting %s)" % (m["end_date"], m["label"]),
                             m["statement_url"], when, "fed_fomc", m))
    if nxt:
        days = (date.fromisoformat(nxt["end_date"]) - today).days
        out.append(Claim("calendar", "MACRO", "Next FOMC decision: %s (meeting %s%s), %d days away; statement usually 1:00 PM CT" % (
            nxt["end_date"], nxt["label"], ", with projections" if nxt["sep"] else "", days), FOMC_URL, when, "fed_fomc",
            dict(nxt, days_away=days)))
    return out, nxt


def parse_rss(text):
    root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    items = []
    for it in root.iter("item"):
        pub = (it.findtext("pubDate") or "").strip()
        try:
            t = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
        except ValueError:
            t = None
        items.append({"title": html.unescape((it.findtext("title") or "").strip()), "link": (it.findtext("link") or "").strip(),
                      "published": t.isoformat() if t else pub})
    return items


def rss_claims(items, when, today, days=3):
    out = []
    for it in items:
        try:
            t = datetime.fromisoformat(it["published"]).astimezone(CT)
        except ValueError:
            continue
        if (today - t.date()).days <= days:
            out.append(Claim("calendar", "MACRO", "Fed monetary press release %s: %s" % (t.strftime("%b %d %I:%M %p CT"), it["title"]),
                             it["link"], when, "fed_rss", it))
    return out
