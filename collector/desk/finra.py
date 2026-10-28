"""FINRA short interest (Query API, otcMarket/consolidatedShortInterest = exchange-listed + OTC, twice monthly).
Tested 2026-10-28 from the firewalled container:
  - otcMarket/equityShortInterest is OTC-only (HTTP 204 for SPCX/TSLA/PLTR/AAPL) -> not usable for listed stocks.
  - Server-side sortFields is rejected unless the partition key (settlementDate) is an EQUAL filter (HTTP 400).
  - Rows come back oldest-first, so we filter symbolCode EQUAL + settlementDate GTE <since> and sort newest-first here.
OAuth client-credentials token from ews.fip.finra.org; the secret is read from env and never logged."""
import base64, json, os
from datetime import date, timedelta
from .claims import Claim

TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
DATA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
PUBLIC_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data"


class FinraError(Exception):
    pass


def token(net):
    cid, sec = os.environ.get("FINRA_CLIENT_ID", ""), os.environ.get("FINRA_CLIENT_SECRET", "")
    if not (cid and sec):
        raise FinraError("FINRA_CLIENT_ID/FINRA_CLIENT_SECRET not set")
    basic = base64.b64encode(("%s:%s" % (cid, sec)).encode()).decode()
    st, body, _ = net.request(TOKEN_URL, method="POST", data=b"", headers={"Authorization": "Basic " + basic}, source="finra_token")
    if st != 200:
        raise FinraError("token HTTP %s" % st)              # body not echoed (could contain credential hints)
    return json.loads(body)["access_token"]


def query_body(symbol, since, limit):
    return {"limit": limit,
            "compareFilters": [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": symbol},
                               {"compareType": "GTE", "fieldName": "settlementDate", "fieldValue": since}]}


def short_interest(net, tok, symbol, since, limit=12, min_date=None):
    body = json.dumps(query_body(symbol, since, limit)).encode()
    st, raw, when = net.request(DATA_URL, method="POST", data=body, source="finra_si",
                                headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                                         "Accept": "application/json"})
    if st not in (200, 204):
        raise FinraError("data HTTP %s: %s" % (st, raw[:160].decode("utf-8", "replace")))
    rows = json.loads(raw) if (st == 200 and raw.strip()) else []   # 204 = no rows
    rows = [r for r in rows if r.get("symbolCode") == symbol and (not min_date or r.get("settlementDate", "") >= min_date)]
    rows.sort(key=lambda r: r.get("settlementDate", ""), reverse=True)
    return rows, when


def claims_for(symbol, rows, when):
    if not rows:
        return []
    r = rows[0]
    txt = "%s short interest (FINRA, settlement %s): %s shares short, days to cover %s" % (
        symbol, r.get("settlementDate"), "{:,}".format(int(r.get("currentShortPositionQuantity") or 0)), r.get("daysToCoverQuantity"))
    prev = r.get("previousShortPositionQuantity")
    if prev:
        txt += "; previous period %s (change %s%%)" % ("{:,}".format(int(prev)), r.get("changePercent"))
    if r.get("revisionFlag"):
        txt += "; FINRA revision flag %s" % r.get("revisionFlag")
    return [Claim("short_interest", symbol, txt, PUBLIC_URL, when, "finra_si", r)]
