"""Time model.

* AEMO NEM data timestamps (SETTLEMENTDATE, INTERVAL_DATETIME, LOAD_DATE, report creation times,
  NEMWeb directory-listing times) are in *NEM market time*: Australian Eastern Standard Time, a fixed
  UTC+10:00 offset with no daylight saving. The evidence used for this project is recorded in
  ``data/source_selection.json`` (``market_time.evidence``) by ``scripts/source_probe.py``.
* Everything is stored in UTC. Display uses the region's IANA timezone, so daylight saving is applied
  for NSW1/VIC1/SA1/TAS1 and not for QLD1.
* AEMO interval timestamps are interval-*ending*: a 5-minute value stamped 02:35 covers (02:30, 02:35].
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NEM_TZ = timezone(timedelta(hours=10), name="NEM")

REGION_TZ: dict[str, str] = {
    "NSW1": "Australia/Sydney",
    "QLD1": "Australia/Brisbane",
    "SA1": "Australia/Adelaide",
    "TAS1": "Australia/Hobart",
    "VIC1": "Australia/Melbourne",
}
REGIONS = tuple(REGION_TZ)

_MARKET_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d%H%M")


def parse_market(value: str) -> datetime:
    """Parse an AEMO market-time string (e.g. ``2026/07/31 02:35:00``) into an aware UTC datetime."""
    s = value.strip().strip('"')
    for fmt in _MARKET_FORMATS:
        try:
            naive = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=NEM_TZ).astimezone(UTC)
    raise ValueError(f"unrecognised AEMO market timestamp: {value!r}")


def to_market(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(NEM_TZ)


def market_str(dt: datetime) -> str:
    return to_market(dt).strftime("%Y/%m/%d %H:%M:%S")


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; attach a timezone")
    return dt.astimezone(UTC)


def region_zone(region: str) -> ZoneInfo:
    try:
        return ZoneInfo(REGION_TZ[region])
    except KeyError as exc:
        raise ValueError(f"unknown NEM region {region!r}; expected one of {', '.join(REGIONS)}") from exc


def to_local(dt: datetime, region: str) -> datetime:
    return ensure_utc(dt).astimezone(region_zone(region))


def local_str(dt: datetime, region: str) -> str:
    loc = to_local(dt, region)
    return loc.strftime("%Y-%m-%d %H:%M %Z (UTC%z)")


def iso_utc(dt: datetime) -> str:
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp that must carry an offset (``Z`` or ``+hh:mm``)."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no timezone offset")
    return dt.astimezone(UTC)


def local_day_window(day: date, region: str) -> tuple[datetime, datetime]:
    """UTC bounds of a calendar day in the region's local time (DST-aware; 23/24/25 hours)."""
    tz = region_zone(region)
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def interval_start(end_utc: datetime, minutes: int) -> datetime:
    return ensure_utc(end_utc) - timedelta(minutes=minutes)


def half_hour_end_for(dt_utc: datetime) -> datetime:
    """The half-hour interval *ending* time that contains a 5-minute interval ending at ``dt_utc``.

    Policy (documented in docs/decisions.md): a 5-minute interval (t-5m, t] belongs to the half-hour
    (T-30m, T] where T is the smallest half-hour boundary >= t (boundaries aligned to NEM time, which
    coincides with UTC half-hour boundaries because the offset is a whole number of hours).
    """
    t = ensure_utc(dt_utc)
    base = t.replace(minute=0, second=0, microsecond=0)
    if t == base:
        return base
    if t <= base + timedelta(minutes=30):
        return base + timedelta(minutes=30)
    return base + timedelta(hours=1)
