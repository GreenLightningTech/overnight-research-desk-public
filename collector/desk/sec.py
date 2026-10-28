"""SEC EDGAR: company submissions (10-K/10-Q/8-K), Form 4 insider trades, and full-text search (EFTS).
SEC fair access: declared User-Agent with contact, <= 10 requests/second (we sleep between calls)."""
import html as _html, re, time, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from .claims import Claim

ITEM_NAMES = {"1.01": "Material agreement", "2.02": "Results of operations", "5.02": "Officer/director change",
              "7.01": "Reg FD disclosure", "8.01": "Other events", "9.01": "Exhibits", "2.03": "New debt obligation",
              "3.02": "Unregistered equity sale", "5.07": "Shareholder vote"}
FORM4_CODES = {"P": "open-market buy", "S": "open-market sale", "A": "grant/award", "M": "option exercise",
               "F": "tax withholding", "G": "gift", "C": "conversion", "X": "option exercise", "D": "disposition to issuer"}


def filing_url(cik, accession, doc):
    return "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(cik), accession.replace("-", ""), doc)


def submissions(net, cik, sleep_s=0.25):
    url = "https://data.sec.gov/submissions/CIK%010d.json" % int(cik)
    j, when = net.get_json(url, source="sec_submissions")
    time.sleep(sleep_s)
    r = j["filings"]["recent"]
    rows = []
    for i in range(len(r["accessionNumber"])):
        rows.append({k: r[k][i] for k in ("accessionNumber", "filingDate", "form", "primaryDocument", "items", "reportDate")
                     if k in r})
    return {"name": j.get("name"), "tickers": j.get("tickers"), "rows": rows, "retrieved_at": when, "api_url": url}


def recent_filings(sub, cik, ticker, forms, since):
    out = []
    for r in sub["rows"]:
        if r["form"] in forms and r["filingDate"] >= since:
            items = [x for x in (r.get("items") or "").split(",") if x]
            names = ", ".join(("%s %s" % (x, ITEM_NAMES.get(x, ""))).strip() for x in items)
            url = filing_url(cik, r["accessionNumber"], r["primaryDocument"])
            txt = "%s filed %s on %s%s" % (ticker, r["form"], r["filingDate"], (" (items: %s)" % names) if names else "")
            out.append(Claim("sec_filing", ticker, txt, url, sub["retrieved_at"], "sec_submissions",
                             {"form": r["form"], "filingDate": r["filingDate"], "accession": r["accessionNumber"], "items": items}))
    return out


def parse_form4(xml_bytes):
    root = ET.fromstring(xml_bytes)
    g = lambda el, path: (el.findtext(path) or "").strip() if el is not None else ""
    owner = g(root, "reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        for tag, lab in (("isDirector", "director"), ("isOfficer", "officer"), ("isTenPercentOwner", "10% owner")):
            if g(rel, tag) in ("1", "true"):
                roles.append(lab)
        if g(rel, "officerTitle"):
            roles.append(g(rel, "officerTitle"))
    tx = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        tx.append({"date": g(t, "transactionDate/value"), "code": g(t, "transactionCoding/transactionCode"),
                   "shares": g(t, "transactionAmounts/transactionShares/value"),
                   "price": g(t, "transactionAmounts/transactionPricePerShare/value"),
                   "acq_disp": g(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                   "owned_after": g(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
                   "plan_10b5_1": None})
    plan = any("10b5-1" in (fn.text or "") for fn in root.iter("footnote")) or g(root, "aff10b5One") in ("1", "true")
    for x in tx:
        x["plan_10b5_1"] = plan
    return {"owner": owner, "roles": roles, "transactions": tx}


def form4s(net, sub, cik, ticker, since, max_n, sleep_s=0.25):
    claims, n = [], 0
    for r in sub["rows"]:
        if r["form"] != "4" or r["filingDate"] < since:
            continue
        if n >= max_n:
            break
        n += 1
        doc = r["primaryDocument"].split("/")[-1]           # strip the xslF345X0n/ rendering prefix -> raw XML
        raw_url = filing_url(cik, r["accessionNumber"], doc)
        human = filing_url(cik, r["accessionNumber"], r["primaryDocument"])
        st, body, when = net.request(raw_url, source="sec_form4")
        time.sleep(sleep_s)
        if st != 200:
            claims.append(Claim("form4", ticker, "%s Form 4 filed %s could not be read (HTTP %s)" % (ticker, r["filingDate"], st),
                                human, when, "sec_form4", {"error": st}))
            continue
        p = parse_form4(body)
        parts = []
        for t in p["transactions"]:
            parts.append("%s %s sh @ %s (%s%s)" % (t["date"], t["shares"], t["price"] or "n/a",
                                                     FORM4_CODES.get(t["code"], t["code"]), ", 10b5-1 plan" if t["plan_10b5_1"] else ""))
        txt = "%s Form 4 filed %s: %s (%s): %s" % (ticker, r["filingDate"], p["owner"], ", ".join(p["roles"]) or "role n/a",
                                                  "; ".join(parts) or "no non-derivative transactions")
        claims.append(Claim("form4", ticker, txt, human, when, "sec_form4", p))
    return claims


def efts(net, term, start, end, forms="8-K,10-Q,10-K", max_hits=10):
    q = urllib.parse.urlencode({"q": term, "forms": forms, "dateRange": "custom", "startdt": start, "enddt": end})
    url = "https://efts.sec.gov/LATEST/search-index?" + q
    j, when = net.get_json(url, source="sec_efts")
    hits = []
    for h in (j.get("hits", {}).get("hits") or [])[:max_hits]:
        s = h.get("_source", {})
        adsh = s.get("adsh", "")
        cik = (s.get("ciks") or ["0"])[0]
        doc = h.get("_id", ":").split(":", 1)[-1]
        hits.append({"form": s.get("form") or s.get("file_type"), "file_date": s.get("file_date"), "adsh": adsh,
                     "filer": " ".join((s.get("display_names") or ["?"])[0].split()), "cik": cik, "items": s.get("items") or [],
                     "url": filing_url(cik, adsh, doc) if adsh and doc else url})
    total = j.get("hits", {}).get("total", {}).get("value", len(hits))
    page = "https://efts.sec.gov/LATEST/search-index?" + q  # same query, public
    return {"term": term, "total": total, "hits": hits, "retrieved_at": when, "page_url": page}


def earnings_8ks(sub, cik, since):
    """8-K filings with Item 2.02 (results of operations) since a date. kind starts as "earnings"; classify_202()
    may change it to "deliveries" (production/deliveries releases are also filed under Item 2.02)."""
    out = []
    for r in sub["rows"]:
        if r["form"] in ("8-K", "8-K/A") and r["filingDate"] >= since and "2.02" in (r.get("items") or ""):
            out.append({"filingDate": r["filingDate"], "accession": r["accessionNumber"], "kind": "earnings",
                        "items": [x for x in (r.get("items") or "").split(",") if x],
                        "url": filing_url(cik, r["accessionNumber"], r["primaryDocument"])})
    return out


def index_url(cik, accession):
    return filing_url(cik, accession, accession + "-index.htm")


def html_text(raw):
    """Plain text from an EDGAR HTML document (tags, scripts and hidden XBRL headers stripped)."""
    t = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    t = re.sub(r"(?is)<(script|style|ix:header)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(_html.unescape(t).split())


def parse_index_exhibits(raw):
    """[(type, description, absolute_url)] for EX-99* documents listed on a filing's -index.htm page."""
    t = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    out = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)(?=<tr|</table>)", t):
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(cells) < 4:
            continue
        typ = html_text(cells[3]).upper()
        href = re.search(r'href="([^"]+)"', cells[2])
        if typ.startswith("EX-99") and href:
            u = href.group(1).replace("/ix?doc=", "")
            out.append((typ, html_text(cells[1]), "https://www.sec.gov" + u if u.startswith("/") else u))
    return out


DELIVERIES_RE = re.compile(r"\bproduction\b.{0,40}\bdeliver", re.I)


def is_deliveries_text(text, head=600):
    """True if the start of an exhibit reads like a production/deliveries release (title area only)."""
    return bool(DELIVERIES_RE.search(text[:head]))


def early_in_quarter(filing_date, days):
    d = filing_date  # YYYY-MM-DD
    return int(d[5:7]) in (1, 4, 7, 10) and int(d[8:10]) <= days


def exhibit_title(txt):
    """Short title around the production/deliveries phrase, without the 'Exhibit 99.1' prefix or the first sentence."""
    m = DELIVERIES_RE.search(txt[:600])
    if not m:
        return txt[:80].strip()
    seg = txt[max(0, m.start() - 60):m.end() + 40]
    seg = re.sub(r"^.*?Exhibit\s*99\.\d+\s*", "", seg, flags=re.I)
    d = seg.lower().find("deliver")
    seg = seg[:d] + re.split(r"\s(?:In|On|The|For|During)\s", seg[d:], maxsplit=1)[0]
    return seg.strip(" .,:;")


def classify_202(net, cik, k, early_days=10, sleep_s=0.25):
    """Item 2.02 8-Ks filed in the first `early_days` days of a quarter are checked: if their EX-99 exhibit is a
    production/deliveries release, kind becomes "deliveries" (not earnings). Adds exhibit_url / exhibit_title."""
    if not early_in_quarter(k["filingDate"], early_days):
        return k
    st, body, _ = net.request(index_url(cik, k["accession"]), source="sec_exhibits")
    time.sleep(sleep_s)
    if st != 200:
        k["classify_error"] = "index HTTP %s" % st; return k
    for typ, desc, url in parse_index_exhibits(body)[:2]:
        st, body, _ = net.request(url, source="sec_exhibits")
        time.sleep(sleep_s)
        if st != 200:
            k["classify_error"] = "exhibit HTTP %s" % st; continue
        txt = html_text(body)
        if is_deliveries_text(desc + " " + txt):
            k.update(kind="deliveries", exhibit_url=url, exhibit_title=exhibit_title(txt))
            return k
    return k


def item_text(raw, item="8.01", n=320):
    """First `n` characters of an 8-K's 'Item 8.01' section (plain text), or ''."""
    t = html_text(raw)
    m = re.search(r"Item\s*%s\.?\s*(Other Events\.?)?\s*" % re.escape(item), t, re.I)
    if not m:
        return ""
    s = t[m.end():m.end() + n]
    return (s[:s.rfind(" ")] + " ...") if len(t) > m.end() + n else s


def material_8ks(net, sub, cik, ticker, since, item="8.01", max_n=5, sleep_s=0.25):
    """8-K filings with Item 8.01 (Other Events; companies use it for material news) since a date.
    Reads each filing's main document for a short excerpt. Returns [dict]."""
    out = []
    for r in sub["rows"]:
        items = [x for x in (r.get("items") or "").split(",") if x]
        if r["form"] in ("8-K", "8-K/A") and r["filingDate"] >= since and item in items and len(out) < max_n:
            url = filing_url(cik, r["accessionNumber"], r["primaryDocument"])
            st, body, _ = net.request(url, source="sec_exhibits")
            time.sleep(sleep_s)
            out.append({"ticker": ticker, "filingDate": r["filingDate"], "accession": r["accessionNumber"], "items": items,
                        "url": url, "excerpt": item_text(body, item) if st == 200 else "", "http": st})
    return out
