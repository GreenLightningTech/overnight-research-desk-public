"""FRED macro series (VIX, credit spreads, rates). Key is sent as a query param and redacted from all logs.
Uses the FRED(R) API but is not endorsed or certified by the Federal Reserve Bank of St. Louis."""
import os
from datetime import datetime, timedelta, timezone
from .claims import Claim


def series(net, sid, label, lookback_days):
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise RuntimeError("FRED_API_KEY not set")
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date().isoformat()
    url = ("https://api.stlouisfed.org/fred/series/observations?series_id=%s&api_key=%s&file_type=json"
           "&observation_start=%s" % (sid, key, start))
    j, when = net.get_json(url, source="fred")
    obs = [(o["date"], float(o["value"])) for o in j.get("observations", []) if o.get("value") not in (".", "", None)]
    page = "https://fred.stlouisfed.org/series/%s" % sid
    if not obs:
        return {"id": sid, "obs": [], "retrieved_at": when, "page_url": page}, []
    last_d, last_v = obs[-1]
    prev = obs[-6][1] if len(obs) >= 6 else None
    txt = "%s (%s) = %s on %s" % (label, sid, last_v, last_d)
    if prev is not None:
        txt += "; 5 obs earlier %s" % prev
    return ({"id": sid, "obs": obs, "retrieved_at": when, "page_url": page},
            [Claim("macro", "MACRO", txt, page, when, "fred", {"series": sid, "date": last_d, "value": last_v, "prev5": prev})])
