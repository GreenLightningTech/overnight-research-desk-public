"""Offline unit tests (stdlib unittest; no network). Run: python3 -m unittest discover -s tests -v"""
import json, os, sys, tempfile, unittest
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "collector"))
from desk import net, calendars, sec, earnings, crosscheck, finra, report, prices
from desk.claims import Claim, Flag
FX = os.path.join(HERE, "fixtures")
rd = lambda f: open(os.path.join(FX, f)).read()


class TestNet(unittest.TestCase):
    def test_redacts_keys(self):
        u = net.redact("https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&api_key=FAKE99&file_type=json")
        self.assertNotIn("FAKE99", u); self.assertIn("api_key=REDACTED", u); self.assertIn("VIXCLS", u)

    def test_allow_list(self):
        self.assertTrue(net.host_allowed("https://data.sec.gov/x")); self.assertTrue(net.host_allowed("https://efts.sec.gov/x"))
        self.assertTrue(net.host_allowed("https://api.finra.org/x")); self.assertFalse(net.host_allowed("https://api.nasdaq.com/x"))
        self.assertFalse(net.host_allowed("https://evilsec.gov.example.cn/x")); self.assertFalse(net.host_allowed("https://notsec.gov/x"))

    def test_request_refuses_unlisted_host(self):
        with self.assertRaises(ValueError):
            net.Net("t").request("https://www.nasdaq.com/")


class TestCalendars(unittest.TestCase):
    def test_bls_ics(self):
        ev = calendars.parse_ics(rd("bls_sample.ics"))
        self.assertEqual(len(ev), 12)
        self.assertTrue(all(e["start"].tzinfo for e in ev))

    def test_bea_ics_utc_and_unfold(self):
        ev = calendars.parse_ics(rd("bea_sample.ics"))
        self.assertEqual(len(ev), 12)
        self.assertFalse(any("\n" in e["summary"] for e in ev))

    def test_fomc(self):
        ms = calendars.parse_fomc(rd("fomc_2026.htm"), 2026)
        self.assertEqual(len(ms), 8)
        self.assertEqual(ms[0]["end_date"], "2026-01-28")
        self.assertTrue(ms[1]["sep"])
        self.assertTrue(ms[0]["statement_url"].startswith("https://www.federalreserve.gov/newsevents/pressreleases/monetary2026"))
        c, nxt = calendars.fomc_claims(ms, "2026-10-28T06:00:00+00:00", date(2026, 10, 20), 14)
        self.assertEqual(nxt["end_date"], "2026-10-28")

    def test_rss(self):
        items = calendars.parse_rss(rd("press_monetary.xml"))
        self.assertGreater(len(items), 3)
        self.assertTrue(items[0]["link"].startswith("https://www.federalreserve.gov/"))


class TestSec(unittest.TestCase):
    def test_form4(self):
        p = sec.parse_form4(open(os.path.join(FX, "form4_pltr.xml"), "rb").read())
        self.assertIn("Woersching", p["owner"]); self.assertIn("director", p["roles"])
        self.assertEqual(p["transactions"][0]["code"], "S"); self.assertTrue(p["transactions"][0]["plan_10b5_1"])

    def test_filing_url(self):
        self.assertEqual(sec.filing_url(1181412, "0001628280-26-066482", "spcx-20261020.htm"),
                         "https://www.sec.gov/Archives/edgar/data/1181412/000162828026066482/spcx-20261020.htm")

    def test_recent_filings_and_8ks(self):
        sub = {"retrieved_at": "2026-10-28T06:00:00+00:00", "rows": [
            {"accessionNumber": "0001-26-1", "filingDate": "2026-10-20", "form": "8-K", "primaryDocument": "a.htm", "items": "2.02,9.01"},
            {"accessionNumber": "0001-26-2", "filingDate": "2026-09-01", "form": "4", "primaryDocument": "x/b.xml", "items": ""}]}
        c = sec.recent_filings(sub, 1, "SPCX", ["8-K"], "2026-10-01")
        self.assertEqual(len(c), 1); self.assertIn("2.02 Results", c[0].text)
        self.assertEqual(len(sec.earnings_8ks(sub, 1, "2026-10-01")), 1)


class TestEarnings(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        self.f.write("# comment\nticker,date,status,timing,source_url,entered_by,entered_on\n"
                     "SPCX,2026-10-20,reported,amc,u,analyst,2026-10-28\nSPCX,2026-11-30,scheduled,amc,u,analyst,2026-10-28\n"
                     "TSLA,2026-10-10,reported,amc,u,analyst,2026-10-28\n")
        self.f.close()

    def test_check(self):
        rows = earnings.load(self.f.name)
        ks = {"SPCX": [{"filingDate": "2026-10-20", "accession": "a", "url": "u1"}], "TSLA": [], "PLTR": []}
        c, f = earnings.check(rows, ks, ["SPCX", "TSLA", "PLTR"], date(2026, 10, 28), 3, "file", "2026-10-28T06:00:00+00:00")
        codes = {(x.ticker, x.code) for x in f}
        self.assertIn(("TSLA", "EARNINGS_UNVERIFIED"), codes)
        self.assertIn(("PLTR", "EARNINGS_NEXT_MISSING"), codes)
        self.assertNotIn(("SPCX", "EARNINGS_NEXT_MISSING"), codes)
        self.assertTrue(any(x.data.get("verified") for x in c))

    def tearDown(self):
        os.unlink(self.f.name)


class FakeNet:
    """Serves fixture files by URL suffix; records requests."""
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def request(self, url, source=""):
        self.urls.append(url)
        for suffix, path in self.routes.items():
            if url.endswith(suffix):
                return 200, open(os.path.join(FX, path), "rb").read(), "2026-10-28T06:00:00+00:00"
        return 404, b"", "2026-10-28T06:00:00+00:00"


class TestEarnings8K(unittest.TestCase):
    """Hand-entered rows, Tesla deliveries releases under Item 2.02, and Item 8.01 material filings."""
    CSV = ("ticker,date,status,timing,source_url,entered_by,entered_on\n"
           "SPCX,2026-10-20,reported,amc,https://www.sec.gov/a,analyst,2026-10-28\n"
           "TSLA,2026-10-21,reported,amc,https://www.sec.gov/b,analyst,2026-10-28\n"
           "PLTR,2026-11-02,scheduled,amc,https://investors.palantir.com/x,analyst,2026-10-28\n"
           "SPCX,,unknown/not announced,unknown,,analyst,2026-10-28\n")

    def rows(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False); f.write(self.CSV); f.close()
        try:
            return earnings.load(f.name)
        finally:
            os.unlink(f.name)

    def sub(self):
        return {"retrieved_at": "t", "rows": [
            {"accessionNumber": "0001628280-26-066738", "filingDate": "2026-10-21", "form": "8-K", "items": "2.02,9.01", "primaryDocument": "tsla-20261021.htm"},
            {"accessionNumber": "0001628280-26-064366", "filingDate": "2026-10-02", "form": "8-K", "items": "2.02,9.01", "primaryDocument": "tsla-20261002.htm"},
            {"accessionNumber": "0001104659-26-118614", "filingDate": "2026-10-26", "form": "8-K", "items": "8.01", "primaryDocument": "tm2628247d1_8k.htm"},
            {"accessionNumber": "x", "filingDate": "2026-10-22", "form": "10-Q", "items": "", "primaryDocument": "q.htm"}]}

    def net(self):
        return FakeNet({"0001628280-26-064366-index.htm": "sec_index_tsla_pd.htm", "exhibit991111111.htm": "sec_ex99_tsla_pd.htm",
                        "tm2628247d1_8k.htm": "sec_8k_801_spcx.htm"})

    def test_rows_without_date_are_skipped(self):
        r = self.rows()
        self.assertEqual([(x["ticker"], x["status"]) for x in r], [("SPCX", "reported"), ("TSLA", "reported"), ("PLTR", "scheduled")])

    def test_helpers(self):
        self.assertTrue(sec.early_in_quarter("2026-10-02", 10)); self.assertTrue(sec.early_in_quarter("2027-01-02", 10))
        self.assertFalse(sec.early_in_quarter("2026-10-21", 10)); self.assertFalse(sec.early_in_quarter("2026-11-02", 10))
        ex = sec.parse_index_exhibits(open(os.path.join(FX, "sec_index_tsla_pd.htm")).read())
        self.assertEqual(ex[0][0], "EX-99.1"); self.assertTrue(ex[0][2].startswith("https://www.sec.gov/Archives/"))
        self.assertTrue(sec.is_deliveries_text(sec.html_text(open(os.path.join(FX, "sec_ex99_tsla_pd.htm")).read())))
        self.assertFalse(sec.is_deliveries_text("Tesla Q3 2026 Update. Highlights: revenue, operating income, production ramp"))

    def classified(self):
        n = self.net()
        ks = sec.earnings_8ks(self.sub(), 1318605, "2026-09-01")
        for k in ks:
            sec.classify_202(n, 1318605, k, 10, 0)
        return ks, n

    def test_deliveries_release_is_not_earnings(self):
        ks, n = self.classified()
        kinds = {k["filingDate"]: k["kind"] for k in ks}
        self.assertEqual(kinds, {"2026-10-21": "earnings", "2026-10-02": "deliveries"})
        self.assertEqual(len(n.urls), 2)                 # only the early-quarter filing was opened (index + exhibit)
        c, f = earnings.check(self.rows(), {"SPCX": [{"filingDate": "2026-10-20", "accession": "a", "url": "u", "kind": "earnings"}],
                                            "TSLA": ks, "PLTR": []}, ["SPCX", "TSLA", "PLTR"], date(2026, 10, 28), 3, "file", "t")
        codes = [(x.ticker, x.code, x.severity) for x in f]
        self.assertIn(("TSLA", "DELIVERIES_RELEASE", "info"), codes)
        self.assertNotIn(("TSLA", "EARNINGS_8K_NOT_IN_FILE", "info"), codes)
        self.assertNotIn(("TSLA", "EARNINGS_DATE_TO_ADD", "medium"), codes)      # 26 days old
        self.assertIn(("SPCX", "EARNINGS_NEXT_MISSING", "medium"), codes)
        self.assertIn(("TSLA", "EARNINGS_NEXT_MISSING", "medium"), codes)
        self.assertNotIn(("PLTR", "EARNINGS_NEXT_MISSING", "medium"), codes)
        self.assertEqual(sum(1 for x in c if x.data.get("verified")), 2)       # SPCX + TSLA confirmed by real earnings 8-Ks
        self.assertTrue(any("PLTR next earnings scheduled 2026-11-02" in x.text for x in c))
        d = [x for x in f if x.code == "DELIVERIES_RELEASE"][0]
        self.assertIn("Production, Deliveries", d.text)

    def test_fresh_q4_deliveries_release_asks_for_date(self):
        k = {"filingDate": "2027-01-02", "accession": "z", "url": "u", "kind": "deliveries", "exhibit_url": "e"}
        _, f = earnings.check(self.rows(), {"TSLA": [k]}, ["TSLA"], date(2027, 1, 4), 3, "file", "t")
        self.assertIn(("TSLA", "EARNINGS_DATE_TO_ADD", "medium"), [(x.ticker, x.code, x.severity) for x in f])

    def test_material_801(self):
        m = sec.material_8ks(self.net(), self.sub(), 1181412, "SPCX", "2026-09-28", "8.01", 5, 0)
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["filingDate"], "2026-10-26")
        self.assertIn("Apollo", m[0]["excerpt"]); self.assertIn("finance lease", m[0]["excerpt"])
        self.assertEqual(sec.material_8ks(self.net(), self.sub(), 1181412, "SPCX", "2026-10-27", "8.01", 5, 0), [])


class TestExhibitTitle(unittest.TestCase):
    def test_title(self):
        from desk import sec
        t = sec.html_text(open(os.path.join(FX, "sec_ex99_tsla_pd.htm"), "rb").read())
        self.assertEqual(sec.exhibit_title(t), "Tesla Third Quarter 2026 Production, Deliveries & Deployments")


class TestVerdict(unittest.TestCase):
    def test_rule_and_final(self):
        from desk import verdict
        ok = {"sources": {"a": {"ok": True}}, "firewall": {"blocked": True}, "overall": "ok"}
        self.assertEqual(verdict.rule_verdict(ok, [{"severity": "info"}])[0], "PASS")
        self.assertEqual(verdict.rule_verdict(ok, [{"severity": "medium"}])[0], "PASS WITH FLAGS")
        bad = dict(ok, sources={"a": {"ok": False}})
        self.assertEqual(verdict.rule_verdict(bad, [])[0], "PASS WITH FLAGS")
        self.assertEqual(verdict.rule_verdict(dict(ok, firewall={"blocked": False}), [])[0], "FAIL")
        self.assertEqual(verdict.reviewer_verdict("<!-- x -->\n## Verdict\n**PASS** - fine"), "PASS")
        self.assertEqual(verdict.reviewer_verdict("## Verdict\nPASS WITH FLAGS: x"), "PASS WITH FLAGS")
        self.assertEqual(verdict.final("PASS WITH FLAGS", "PASS"), "PASS WITH FLAGS")
        self.assertEqual(verdict.final("PASS", "FAIL"), "FAIL")
        self.assertEqual(verdict.final("PASS", None), "PASS")


class TestPrices(unittest.TestCase):
    def bars(self):
        b = []
        for i in range(22):   # flat 100 closes, high 101, low 99, volume 1000
            b.append({"date": "2026-09-%02d" % (i + 1), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000})
        b[-2].update(close=97.0, high=98.0)                 # prior day -3%
        b[-1].update(open=99.0, close=99.5, high=100.0)     # last bar: gap +2.06%, close above prior high 98
        return b

    def test_extension_facts(self):
        e = prices.extension(self.bars())
        self.assertEqual(e["prior_hi_20d"], 101.0)
        self.assertEqual(e["pct_vs_prior_hi_20d"], -1.49)
        self.assertEqual(e["gap_pct"], 2.06)
        self.assertEqual(e["chg_1d_prev_pct"], -3.0)
        self.assertEqual(e["prev_high"], 98.0)
        self.assertTrue(e["close_above_prev_high"])
        self.assertAlmostEqual(e["vwap_20d"], (18 * 100.0 + (98 + 99 + 97) / 3 + (100 + 99 + 99.5) / 3) / 20, places=3)

    def test_summarize_has_change_range_and_extension(self):
        s = {"source": "yahoo", "bars": self.bars(), "page_url": "https://finance.yahoo.com/quote/X/history/",
             "retrieved_at": "2026-10-28T06:00:00Z"}
        c = prices.summarize("X", s)
        self.assertEqual(len(c), 3)
        self.assertEqual(c[1].data["chg_1d_pct"], 2.58)
        self.assertEqual((c[1].data["lo_20d"], c[1].data["hi_20d"]), (99.0, 101.0))
        self.assertIn("extension", c[2].text)
        self.assertFalse(prices.extension(self.bars()[:2]))


class TestCrossCheck(unittest.TestCase):
    def s(self, src, closes):
        return {"source": src, "page_url": src, "bars": [{"date": d, "close": c, "high": c, "low": c} for d, c in closes]}

    def test_mismatch_and_stale(self):
        y = self.s("yahoo", [("2026-10-20", 100.0), ("2026-10-21", 101.0)])
        t = self.s("tiingo", [("2026-10-20", 100.1), ("2026-10-21", 103.0)])
        f = crosscheck.prices("SPCX", y, t, date(2026, 10, 28), {"mismatch_pct": 0.5, "stale_days": 4})
        codes = [x.code for x in f]
        self.assertEqual(codes.count("PRICE_MISMATCH"), 1); self.assertIn("STALE", codes)

    def test_clean(self):
        y = self.s("yahoo", [("2026-10-27", 100.0)]); t = self.s("tiingo", [("2026-10-27", 100.2)])
        self.assertEqual(crosscheck.prices("SPCX", y, t, date(2026, 10, 28), {"mismatch_pct": 0.5, "stale_days": 4}), [])

    def test_finra_stale(self):
        f = crosscheck.finra("SPCX", [{"settlementDate": "2026-08-01"}], date(2026, 10, 28), {"stale_days": 35}, "u")
        self.assertEqual(f[0].code, "STALE")


class TestFinra(unittest.TestCase):
    def test_body_has_no_server_sort(self):
        b = finra.query_body("SPCX", "2026-08-01", 12)
        self.assertNotIn("sortFields", b)                        # rejected by FINRA unless settlementDate EQUAL
        self.assertEqual(b["compareFilters"][0]["fieldName"], "symbolCode")

    def test_claim(self):
        rows = [{"settlementDate": "2026-10-15", "currentShortPositionQuantity": 167294863, "daysToCoverQuantity": 1.9,
                 "previousShortPositionQuantity": 180996777, "changePercent": -7.57}]
        c = finra.claims_for("SPCX", rows, "2026-10-28T06:00:00+00:00")
        self.assertIn("167,294,863", c[0].text); self.assertTrue(c[0].source_url.startswith("https://www.finra.org/"))


class TestReport(unittest.TestCase):
    def test_every_claim_has_link_and_time(self):
        d = tempfile.mkdtemp()
        run = {"date": "2026-10-28", "started_at": "2026-10-28T06:00:00+00:00", "finished_at": "2026-10-28T06:01:00+00:00",
               "elapsed_s": 60, "tickers": {"SPCX": "core"}}
        c = [Claim("price", "SPCX", "SPCX last close", "https://finance.yahoo.com/quote/SPCX/history/", "2026-10-28T06:00:10+00:00", "yahoo")]
        st = {"sources": {"yahoo": {"ok": True, "http": [200], "error": None}}, "firewall": {"host": "example.com", "detail": "blocked"}, "overall": "ok"}
        report.write_all(d, run, c, [Flag("info", "X", "SPCX", "t")], [], st)
        b = open(os.path.join(d, "brief-inputs.md")).read()
        line = [l for l in b.splitlines() if "SPCX last close" in l][0]
        self.assertIn("[source](https://", line); self.assertIn("retrieved 2026-10-28 01:00 CT", line)
        for f in ("flags.md", "data.json", "sources.csv", "status.json", "STATUS.md"):
            self.assertTrue(os.path.exists(os.path.join(d, f)), f)


class TestConfig(unittest.TestCase):
    def test_config(self):
        cfg = json.load(open(os.path.join(HERE, "..", "config", "desk.json")))
        self.assertEqual(cfg["tickers"]["SPCX"]["min_date"], "2026-06-12")
        self.assertEqual(set(cfg["tickers"]), {"SPCX", "TSLA", "PLTR"})
        self.assertNotIn("key", json.dumps(cfg).lower().replace("keys", ""))


if __name__ == "__main__":
    unittest.main()


class TestSecretsCheck(unittest.TestCase):
    def test_catches_planted_key(self):
        import subprocess, shutil
        d = tempfile.mkdtemp()
        sh = os.path.join(HERE, "..", "scripts", "check-secrets.sh")
        subprocess.run(["git", "init", "-q", d], check=True)
        os.makedirs(os.path.join(d, "scripts")); shutil.copy(sh, os.path.join(d, "scripts", "check-secrets.sh"))
        with open(os.path.join(d, "ok.md"), "w") as f:
            f.write("SEC User-Agent: Your Name you@example.com\n")
        with open(os.path.join(d, "bad.py"), "w") as f:
            f.write('TIINGO_API_KEY = "' + "ab12" * 10 + '"\n')
        subprocess.run(["git", "-C", d, "add", "."], check=True)
        r = subprocess.run(["bash", os.path.join(d, "scripts", "check-secrets.sh")], cwd=d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1); self.assertIn("bad.py", r.stdout); self.assertNotIn("ok.md", r.stdout)
        self.assertNotIn("ab12ab12", r.stdout)                  # never echoes the secret
