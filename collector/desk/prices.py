"""Daily prices from Yahoo (chart API) and Tiingo (daily EOD). Both allow-listed, both US."""
import os, urllib.parse
from datetime import datetime, timedelta, timezone
from .claims import Claim
from .timeutil import ET


def yahoo(net, ticker, lookback_days, min_date=None):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=3mo&interval=1d&includePrePost=false" % ticker
    j, when = net.get_json(url, source="yahoo")
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    bars, dropped = [], 0
    now_et = datetime.now(timezone.utc).astimezone(ET)
    # a bar for today is only a close after 4:15 PM ET; earlier it is a live intraday quote, so leave it out
    open_day = now_et.date().isoformat() if (now_et.hour, now_et.minute) < (16, 15) else None
    for i, ts in enumerate(r.get("timestamp") or []):
        day = datetime.fromtimestamp(ts, timezone.utc).astimezone(ET).date().isoformat()
        c = q["close"][i]
        if c is None:
            continue
        if min_date and day < min_date:
            dropped += 1; continue
        if day == open_day:
            continue
        bars.append({"date": day, "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": round(c, 4),
                     "volume": q["volume"][i]})
    page = "https://finance.yahoo.com/quote/%s/history/" % ticker
    return {"source": "yahoo", "bars": bars[-lookback_days:], "dropped_before_min_date": dropped,
            "retrieved_at": when, "api_url": url, "page_url": page}


def tiingo(net, ticker, lookback_days, min_date=None):
    key = os.environ.get("TIINGO_API_KEY", "")
    if not key:
        raise RuntimeError("TIINGO_API_KEY not set")
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days * 2)).date().isoformat()
    if min_date and start < min_date:
        start = min_date
    url = "https://api.tiingo.com/tiingo/daily/%s/prices?startDate=%s" % (ticker.lower(), start)
    j, when = net.get_json(url, source="tiingo", headers={"Authorization": "Token " + key, "Content-Type": "application/json"})
    bars = [{"date": b["date"][:10], "open": b.get("open"), "high": b.get("high"), "low": b.get("low"),
             "close": b.get("close"), "volume": b.get("volume")} for b in j]
    return {"source": "tiingo", "bars": bars[-lookback_days:], "dropped_before_min_date": 0, "retrieved_at": when,
            "api_url": url, "page_url": "https://www.tiingo.com/%s/overview" % ticker.lower()}


def summarize(ticker, series):
    """Neutral price facts (no signals): last close, 1d/5d change, 20-day high/low."""
    b = series["bars"]
    if not b:
        return []
    last = b[-1]
    out = [Claim("price", ticker, "%s last close %s: $%.2f (%s)" % (ticker, last["date"], last["close"], series["source"]),
                 series["page_url"], series["retrieved_at"], series["source"], {"date": last["date"], "close": last["close"]})]
    def chg(n):
        if len(b) > n and b[-1 - n]["close"]:
            return round((last["close"] / b[-1 - n]["close"] - 1) * 100, 2)
    c1, c5 = chg(1), chg(5)
    w = b[-20:]
    hi, lo = max(x["high"] or x["close"] for x in w), min(x["low"] or x["close"] for x in w)
    out.append(Claim("price", ticker, "%s change: 1-day %s%%, 5-day %s%%; 20-day range $%.2f-$%.2f (%s, %d bars)" % (
        ticker, c1, c5, lo, hi, series["source"], len(w)), series["page_url"], series["retrieved_at"], series["source"],
        {"chg_1d_pct": c1, "chg_5d_pct": c5, "hi_20d": hi, "lo_20d": lo}))
    ext = extension(b)
    if ext:
        out.append(Claim("price", ticker, "%s extension: close vs prior 20-day high $%s: %s%%; vs 20-day VWAP $%s: %s%%; "
                         "gap at last open %s%%; last two daily changes %s%% then %s%%; last close above prior day's high "
                         "$%s: %s (%s, daily bars)" % (
            ticker, ext["prior_hi_20d"], ext["pct_vs_prior_hi_20d"], ext["vwap_20d"], ext["pct_vs_vwap_20d"],
            ext["gap_pct"], ext["chg_1d_prev_pct"], c1, ext["prev_high"], "yes" if ext["close_above_prev_high"] else "no",
            series["source"]), series["page_url"], series["retrieved_at"], series["source"], ext))
    return out


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b else None


def extension(b):
    """Neutral extension facts from daily bars (no signals, no new hosts).
    prior_hi_20d: highest high of the 20 bars BEFORE the last one; vwap_20d: volume-weighted typical price
    ((H+L+C)/3) over the last 20 bars (a daily-bar approximation, not intraday VWAP); gap_pct: last open vs the
    previous close; chg_1d_prev_pct: the daily change one bar earlier; close_above_prev_high: last close > the
    previous bar's high."""
    if len(b) < 3:
        return None
    last, prev = b[-1], b[-2]
    prior = b[-21:-1]
    prior_hi = max(x["high"] or x["close"] for x in prior)
    w = [x for x in b[-20:] if x.get("volume")]
    vol = sum(x["volume"] for x in w)
    vwap = round(sum(((x["high"] or x["close"]) + (x["low"] or x["close"]) + x["close"]) / 3 * x["volume"] for x in w) / vol, 4) if vol else None
    prev_high = prev["high"] if prev["high"] is not None else prev["close"]
    return {"prior_hi_20d": round(prior_hi, 4), "pct_vs_prior_hi_20d": _pct(last["close"], prior_hi),
            "vwap_20d": vwap, "pct_vs_vwap_20d": _pct(last["close"], vwap),
            "gap_pct": _pct(last["open"], prev["close"]), "chg_1d_prev_pct": _pct(prev["close"], b[-3]["close"]),
            "prev_high": round(prev_high, 4), "close_above_prev_high": last["close"] > prev_high}
