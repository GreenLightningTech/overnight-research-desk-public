"""Cross-check: flags disagreement between sources and stale data. Flags are facts about data quality, not trading signals."""
from datetime import date
from .claims import Flag


def prices(ticker, yahoo, tiingo, today, cfg):
    flags = []
    yb = {b["date"]: b["close"] for b in (yahoo or {}).get("bars", [])}
    tb = {b["date"]: b["close"] for b in (tiingo or {}).get("bars", [])}
    urls = [s["page_url"] for s in (yahoo, tiingo) if s]
    common = sorted(set(yb) & set(tb))
    for d in common[-5:]:
        a, b = yb[d], tb[d]
        if a and b:
            diff = abs(a - b) / b * 100
            if diff > cfg["mismatch_pct"]:
                flags.append(Flag("high", "PRICE_MISMATCH", ticker, "%s close %s: Yahoo $%.2f vs Tiingo $%.2f (%.2f%% apart, limit %.2f%%)" % (
                    ticker, d, a, b, diff, cfg["mismatch_pct"]), urls))
    ly, lt = (max(yb) if yb else None), (max(tb) if tb else None)
    if ly and lt and ly != lt:
        flags.append(Flag("medium", "PRICE_DATE_MISMATCH", ticker, "%s latest bar: Yahoo %s vs Tiingo %s" % (ticker, ly, lt), urls))
    for name, last in (("Yahoo", ly), ("Tiingo", lt)):
        if last and (today - date.fromisoformat(last)).days > cfg["stale_days"]:
            flags.append(Flag("high", "STALE", ticker, "%s %s latest price is %s (%d days old, limit %d)" % (
                ticker, name, last, (today - date.fromisoformat(last)).days, cfg["stale_days"]), urls))
    if yb and tb and not common:
        flags.append(Flag("high", "PRICE_NO_OVERLAP", ticker, "%s: Yahoo and Tiingo share no dates" % ticker, urls))
    return flags


def fred(series, today, cfg):
    flags = []
    for sid, meta in cfg["series"].items():
        s = series.get(sid)
        if not s or not s["obs"]:
            continue
        last = s["obs"][-1][0]
        age = (today - date.fromisoformat(last)).days
        if age > meta["stale_days"]:
            flags.append(Flag("medium", "STALE", "MACRO", "FRED %s latest observation %s (%d days old, limit %d)" % (sid, last, age, meta["stale_days"]), [s["page_url"]]))
    return flags


def finra(ticker, rows, today, cfg, url):
    if not rows:
        return [Flag("medium", "FINRA_NO_ROWS", ticker, "FINRA returned no short-interest rows for %s" % ticker, [url])]
    last = rows[0]["settlementDate"]
    age = (today - date.fromisoformat(last)).days
    if age > cfg["stale_days"]:
        return [Flag("medium", "STALE", ticker, "FINRA short interest for %s is from %s (%d days old, limit %d)" % (ticker, last, age, cfg["stale_days"]), [url])]
    return []


def min_date(ticker, dropped, min_d, reason, url):
    if dropped:
        return [Flag("info", "PRE_LISTING_DROPPED", ticker, "%s: dropped %d rows dated before %s (%s)" % (ticker, dropped, min_d, reason), [url])]
    return []
