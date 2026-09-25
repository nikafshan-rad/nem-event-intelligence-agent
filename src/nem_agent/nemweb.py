"""NEMWeb directory listings and AEMO file-name conventions.

Every URL used by the project is *discovered* from a NEMWeb directory listing (or validated by a
successful response); no archive URL is constructed and trusted without a response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urljoin

from .http import HttpResult, fetch
from .timeutil import NEM_TZ, UTC, parse_market

NEMWEB = "https://nemweb.com.au"

# Logical dataset -> (Current directory, Archive directory)
DATASET_DIRS: dict[str, tuple[str, str | None]] = {
    "DISPATCHIS": ("/Reports/Current/DispatchIS_Reports/", "/Reports/Archive/DispatchIS_Reports/"),
    "DISPATCH_SCADA": ("/Reports/Current/Dispatch_SCADA/", "/Reports/Archive/Dispatch_SCADA/"),
    "PUBLIC_PRICES": ("/Reports/Current/Public_Prices/", "/Reports/Archive/Public_Prices/"),
    "OPDEM_FORECAST_HH": (
        "/Reports/Current/Operational_Demand/FORECAST_HH/",
        "/Reports/Archive/Operational_Demand/FORECAST_HH/",
    ),
    "OPDEM_ACTUAL_HH": (
        "/Reports/Current/Operational_Demand/ACTUAL_HH/",
        "/Reports/Archive/Operational_Demand/ACTUAL_HH/",
    ),
    "OPDEM_ACTUAL_DAILY": (
        "/Reports/Current/Operational_Demand/ACTUAL_DAILY/",
        "/Reports/Archive/Operational_Demand/ACTUAL_DAILY/",
    ),
    "MARKET_NOTICE": ("/Reports/Current/Market_Notice/", None),
}

_LISTING_RE = re.compile(
    r"(?P<ts>[A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\s+"
    r"(?P<size>&lt;dir&gt;|<dir>|\d+)\s+<A HREF=\"(?P<href>[^\"]+)\">(?P<name>[^<]+)</A>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ListingEntry:
    name: str
    url: str
    listed_at_market: str | None  # as shown by NEMWeb (market time, minute precision)
    listed_at_utc: datetime | None
    size: int | None
    is_dir: bool


def parse_listing(html_text: str, base_url: str) -> list[ListingEntry]:
    entries: list[ListingEntry] = []
    for m in _LISTING_RE.finditer(html_text):
        size_raw = m.group("size")
        is_dir = not size_raw.isdigit()
        ts_raw = " ".join(m.group("ts").split())
        listed = datetime.strptime(ts_raw, "%A, %B %d, %Y %I:%M %p").replace(tzinfo=NEM_TZ)
        href = m.group("href")
        url = urljoin(base_url, href)
        entries.append(
            ListingEntry(
                name=unquote(m.group("name")).strip(),
                url=url,
                listed_at_market=listed.strftime("%Y/%m/%d %H:%M"),
                listed_at_utc=listed.astimezone(UTC),
                size=None if is_dir else int(size_raw),
                is_dir=is_dir,
            )
        )
    return entries


def list_dir(path_or_url: str) -> tuple[HttpResult, list[ListingEntry]]:
    url = path_or_url if path_or_url.startswith("http") else NEMWEB + path_or_url
    res = fetch(url, timeout=60, max_bytes=20 * 1024 * 1024)
    if not res.ok or res.body is None:
        return res, []
    return res, parse_listing(res.body.decode("utf-8", "replace"), url)


# ---------------------------------------------------------------- file-name conventions
_TS12 = r"(\d{12})"
_TS14 = r"(\d{14})"
NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    # Current (individual) files
    "OPDEM_FORECAST_HH": re.compile(rf"^PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_{_TS12}_{_TS14}\.zip$", re.I),
    "OPDEM_ACTUAL_HH": re.compile(rf"^PUBLIC_ACTUAL_OPERATIONAL_DEMAND_HH_{_TS12}_{_TS14}\.zip$", re.I),
    "OPDEM_ACTUAL_DAILY": re.compile(r"^PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_(\d{8})_(\d{14})\.zip$", re.I),
    "DISPATCHIS": re.compile(rf"^PUBLIC_DISPATCHIS_{_TS12}_(\d+)\.zip$", re.I),
    "DISPATCH_SCADA": re.compile(rf"^PUBLIC_DISPATCHSCADA_{_TS12}_(\d+)\.zip$", re.I),
    "PUBLIC_PRICES": re.compile(rf"^PUBLIC_PRICES_{_TS12}_{_TS14}\.zip$", re.I),
}
ARCHIVE_PATTERNS: dict[str, re.Pattern[str]] = {
    "OPDEM_FORECAST_HH": re.compile(r"^PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_(\d{8})\.zip$", re.I),
    "OPDEM_ACTUAL_HH": re.compile(r"^PUBLIC_ACTUAL_OPERATIONAL_DEMAND_HH_(\d{8})\.zip$", re.I),
    "OPDEM_ACTUAL_DAILY": re.compile(r"^PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_(\d{8})\.zip$", re.I),
    "DISPATCHIS": re.compile(r"^PUBLIC_DISPATCHIS_(\d{8})\.zip$", re.I),
    "DISPATCH_SCADA": re.compile(r"^PUBLIC_DISPATCHSCADA_(\d{8})\.zip$", re.I),
    "PUBLIC_PRICES": re.compile(r"^PUBLIC_PRICES_(\d{8})\.zip$", re.I),
}


def creation_time_from_name(name: str) -> datetime | None:
    """File-creation timestamp embedded in operational-demand / price file names (market time)."""
    for key in ("OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH", "PUBLIC_PRICES"):
        m = NAME_PATTERNS[key].match(name)
        if m:
            return parse_market(m.group(2))
    m = NAME_PATTERNS["OPDEM_ACTUAL_DAILY"].match(name)
    if m:
        return parse_market(m.group(2))
    return None


def archive_start(dataset: str, name: str) -> datetime | None:
    pat = ARCHIVE_PATTERNS.get(dataset)
    if not pat:
        return None
    m = pat.match(name)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=NEM_TZ)


MARKET_NOTICE_RE = re.compile(r"^NEMITWEB1_MKTNOTICE_(\d{8})\.R(\d+)$", re.I)
