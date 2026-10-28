"""Writes the results folder: brief-inputs.md, flags.md, data.json, sources.csv, status.json, STATUS.md."""
import csv, json, os
from .timeutil import ct_label

TOPIC_ORDER = [("calendar", "Calendar: macro releases, FOMC, Fed statements"), ("earnings", "Earnings dates (hand-entered, SEC-checked)"),
               ("sec_filing", "SEC filings (company)"), ("form4", "Insider trades (SEC Form 4)"), ("sec_mention", "SEC full-text mentions (other filers)"),
               ("price", "Prices (Yahoo + Tiingo)"), ("short_interest", "Short interest (FINRA)"), ("macro", "Macro and risk gauges (FRED)")]
def _w(path, text):
    with open(path, "w") as f:
        f.write(text)


SEV = {"high": 0, "medium": 1, "info": 2}


def write_all(out, run, claims, flags, calls, status):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "data.json"), "w") as f:
        json.dump({"run": run, "status": status, "claims": [c.to_dict() for c in claims], "flags": [x.to_dict() for x in flags]}, f, indent=1, default=str)
    with open(os.path.join(out, "sources.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["retrieved_at_utc", "source", "method", "http", "bytes", "elapsed_s", "url_redacted"])
        for c in calls:
            w.writerow([c["retrieved_at"], c["source"], c["method"], c["http"], c["bytes"], c["elapsed_s"], c["url"]])
    with open(os.path.join(out, "status.json"), "w") as f:
        json.dump(status, f, indent=1)
    _flags_md(out, run, flags)
    _brief_md(out, run, claims, flags, status)
    _status_md(out, run, status)


def _flags_md(out, run, flags):
    L = ["# Data-quality flags, %s" % run["date"], "", "Generated %s by the research-desk collector. Flags describe the data, not the market." % ct_label(run["finished_at"]), ""]
    if not flags:
        L.append("No flags.")
    for x in sorted(flags, key=lambda x: (SEV.get(x.severity, 9), x.ticker, x.code)):
        L.append("- **%s** `%s` %s: %s  " % (x.severity.upper(), x.code, x.ticker, x.text))
        if x.source_urls:
            L.append("  Sources: " + ", ".join(u for u in x.source_urls if u))
    _w(os.path.join(out, "flags.md"), "\n".join(L) + "\n")


def _brief_md(out, run, claims, flags, status):
    hi = [x for x in flags if x.severity == "high"]
    L = ["# Brief inputs, %s" % run["date"], "",
         "Overnight research-desk collection for the decision maker's morning brief. Facts only: every line below carries its source link and the time it was retrieved (CT).",
         "No trading calls. Research and education only; not financial advice.", "",
         "- Run: %s to %s (%ss); sources ok %d of %d; flags: %d high, %d medium, %d info (see flags.md)" % (
             ct_label(run["started_at"]), ct_label(run["finished_at"]), run["elapsed_s"],
             sum(1 for s in status["sources"].values() if s["ok"]), len(status["sources"]), len(hi),
             sum(1 for x in flags if x.severity == "medium"), sum(1 for x in flags if x.severity == "info")),
         "- Tickers: %s" % ", ".join("%s (%s)" % (t, r) for t, r in run["tickers"].items()), ""]
    if hi:
        L += ["## High flags first", ""] + ["- `%s` %s: %s" % (x.code, x.ticker, x.text) for x in hi] + [""]
    for topic, title in TOPIC_ORDER:
        cs = [c for c in claims if c.topic == topic]
        L += ["## " + title, ""]
        if not cs:
            L.append("- (nothing in range)")
        for c in cs:
            L.append("- %s. [source](%s), retrieved %s" % (c.text, c.source_url, ct_label(c.retrieved_at)))
        L.append("")
    failed = [k for k, s in status["sources"].items() if not s["ok"]]
    if failed:
        L += ["## Sources that failed", ""] + ["- %s: %s" % (k, status["sources"][k]["error"]) for k in failed] + [""]
    _w(os.path.join(out, "brief-inputs.md"), "\n".join(L))


def _status_md(out, run, status):
    L = ["# Run status, %s" % run["date"], "", "| Source | OK | HTTP codes | Calls | Note |", "|---|---|---|---|---|"]
    for k, s in status["sources"].items():
        L.append("| %s | %s | %s | %d | %s |" % (k, "yes" if s["ok"] else "NO", ",".join(str(c) for c in sorted(set(s["http"]))) or "-",
                                             len(s["http"]), (s.get("error") or s.get("note") or "").replace("|", "/")[:160]))
    L += ["", "Firewall canary (%s should NOT resolve): %s" % (status["firewall"]["host"], status["firewall"]["detail"]),
          "", "Overall: **%s**; elapsed %ss" % (status["overall"], run["elapsed_s"])]
    _w(os.path.join(out, "STATUS.md"), "\n".join(L) + "\n")
