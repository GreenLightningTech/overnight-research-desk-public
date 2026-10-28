"""HTTP helper: every request is logged (URL with secrets redacted, HTTP code, bytes, time).
Secrets never reach logs or outputs: query params named in REDACT are masked and auth headers are not logged."""
import json, re, time, urllib.request, urllib.error, urllib.parse, socket
from datetime import datetime, timezone

REDACT = {"api_key", "token", "apikey", "access_token", "client_secret"}
ALLOWED_HOST_SUFFIXES = (
    "query1.finance.yahoo.com", "query2.finance.yahoo.com", "api.tiingo.com", "api.stlouisfed.org",
    "sec.gov", "api.finra.org", "ews.fip.finra.org", "www.bls.gov", "www.bea.gov", "www.federalreserve.gov",
)


def redact(url):
    p = urllib.parse.urlsplit(url)
    q = [(k, "REDACTED" if k.lower() in REDACT else v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q, safe=",:/\""), ""))


def host_allowed(url):
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(h == s or h.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def utcnow():
    return datetime.now(timezone.utc)


class Net:
    def __init__(self, ua, log_path=None, timeout=30):
        self.ua, self.timeout, self.log_path, self.calls = ua, timeout, log_path, []

    def _log(self, rec):
        self.calls.append(rec)
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    def request(self, url, method="GET", data=None, headers=None, source=""):
        """Returns (status, body_bytes, retrieved_at_iso). status 0 = network error (body = error text)."""
        if not host_allowed(url):
            raise ValueError("host not on the research-desk allow-list: %s" % urllib.parse.urlsplit(url).hostname)
        h = {"User-Agent": self.ua, "Accept-Encoding": "identity"}
        h.update(headers or {})
        t0, when = time.time(), utcnow().isoformat(timespec="seconds")
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            status, body = 0, str(getattr(e, "reason", e)).encode()
        self._log({"source": source, "method": method, "url": redact(url), "http": status, "bytes": len(body),
                   "elapsed_s": round(time.time() - t0, 2), "retrieved_at": when})
        return status, body, when

    def get_json(self, url, source="", headers=None):
        st, body, when = self.request(url, headers=headers, source=source)
        if st != 200:
            raise FetchError(source, url, st, body)
        return json.loads(body), when

    def get_text(self, url, source="", headers=None):
        st, body, when = self.request(url, headers=headers, source=source)
        if st != 200:
            raise FetchError(source, url, st, body)
        return body.decode("utf-8", errors="replace"), when


class FetchError(Exception):
    def __init__(self, source, url, status, body=b""):
        self.source, self.url, self.status = source, redact(url), status
        snippet = body[:120].decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)[:120]
        super().__init__("%s HTTP %s at %s (%s)" % (source, status, self.url, snippet.replace("\n", " ")))


def firewall_canary(host):
    """The allow-list firewall should make a non-listed name fail to resolve. Returns (blocked: bool, detail)."""
    try:
        addrs = socket.getaddrinfo(host, 443)
        return False, "resolved to %s" % addrs[0][4][0]
    except socket.gaierror as e:
        return True, "NXDOMAIN/blocked (%s)" % e
