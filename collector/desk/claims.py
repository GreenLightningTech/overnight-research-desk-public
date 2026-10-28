"""A claim is one fact with its source URL and retrieval time. Everything in brief-inputs.md is a claim."""
from dataclasses import dataclass, field, asdict


@dataclass
class Claim:
    topic: str          # e.g. "price", "sec_filing", "form4", "macro", "short_interest", "calendar", "earnings"
    ticker: str         # ticker or "MACRO"
    text: str           # one-line human statement
    source_url: str     # public URL a human can open (never contains a key)
    retrieved_at: str   # ISO-8601 UTC
    source: str         # source id, e.g. "yahoo", "sec_submissions"
    data: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Flag:
    severity: str       # "high" | "medium" | "info"
    code: str           # e.g. PRICE_MISMATCH, STALE, SOURCE_FAILED, EARNINGS_UNVERIFIED
    ticker: str
    text: str
    source_urls: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
