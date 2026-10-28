"""Rule-based review verdict (the same rule the reviewer prompt states), computed from the collector's own files so a
small local model can't soften it. The final verdict is the stricter of this and the reviewer's verdict.
  FAIL             firewall canary not blocked, or the collector run failed
  PASS WITH FLAGS  any HIGH or MEDIUM flag, or any source not OK
  PASS             otherwise"""
import json, os, re, sys

ORDER = {"PASS": 0, "PASS WITH FLAGS": 1, "FAIL": 2}


def rule_verdict(status, flags):
    sev = [f.get("severity") for f in flags]
    bad = sorted(k for k, s in status.get("sources", {}).items() if not s.get("ok"))
    why = []
    if not status.get("firewall", {}).get("blocked"):
        why.append("firewall canary not blocked")
    if status.get("overall") == "failed":
        why.append("collector run failed")
    if why:
        return "FAIL", why
    nh, nm = sev.count("high"), sev.count("medium")
    if nh or nm:
        why.append("%d high / %d medium flags" % (nh, nm))
    if bad:
        why.append("sources not OK: " + ", ".join(bad))
    return ("PASS WITH FLAGS" if why else "PASS"), (why or ["no high/medium flags, all sources OK, canary blocked"])


def reviewer_verdict(md):
    m = re.search(r"##\s*Verdict\s*\n+\s*\**\s*(PASS WITH FLAGS|PASS|FAIL)\b", md or "", re.I)
    return m.group(1).upper() if m else None


def final(rule, reviewer):
    if reviewer is None:
        return rule
    return max(rule, reviewer, key=lambda v: ORDER.get(v, 0))


def main(results_dir, review_md):
    data = json.load(open(os.path.join(results_dir, "data.json")))
    status = data.get("status") or json.load(open(os.path.join(results_dir, "status.json")))
    rule, why = rule_verdict(status, data.get("flags", []))
    rv = reviewer_verdict(open(review_md).read() if os.path.exists(review_md) else "")
    fin = final(rule, rv)
    note = "agrees" if rv == fin else ("reviewer said %s; rule-based verdict is stricter, so it wins" % rv if rv else "reviewer verdict not found")
    print("Final verdict: **%s** (rule-based: %s, because %s; reviewer: %s; %s)" % (fin, rule, "; ".join(why), rv or "n/a", note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
