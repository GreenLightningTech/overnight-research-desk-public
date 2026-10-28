from datetime import datetime, date, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago"); ET = ZoneInfo("America/New_York")
except Exception:  # container without tzdata: fixed offsets (labelled honestly)
    CT = timezone(timedelta(hours=-5), "CT(fixed-5)"); ET = timezone(timedelta(hours=-4), "ET(fixed-4)")


def d(s):
    return date.fromisoformat(s[:10])


def ct_label(iso_utc):
    """'2026-10-29T06:01:02+00:00' -> '2026-10-29 01:01 CT'"""
    t = datetime.fromisoformat(iso_utc)
    return t.astimezone(CT).strftime("%Y-%m-%d %H:%M") + " CT"


def days_between(a, b):
    return (d(b) - d(a)).days
