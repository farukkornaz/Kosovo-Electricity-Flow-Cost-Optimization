"""Hourly day-ahead spot prices from the local price API (ENTSO-E backed).

The API is a separate project (~/lab/south-europe-energy-prices); start it there with
`.venv/bin/python api.py`. Its address can be changed with PRICE_API_URL.
"""

import os
import urllib.error
import urllib.parse
from datetime import date, timedelta

from common import day_hours, fetch_json, parse_utc

SOURCE = "ENTSOE"
API_URL = os.environ.get("PRICE_API_URL", "http://127.0.0.1:8000")
# Modeled zones the API serves (it has no BA or TR).
ZONES = ["AL", "BG", "GR", "HR", "HU", "ME", "MK", "RO", "RS", "XK"]
# The API refuses longer ranges; a month per request keeps responses small.
MAX_DAYS_PER_REQUEST = 31
# The API queries ENTSO-E zone by zone on a cache miss: a month of 10 zones took 76 s.
REQUEST_TIMEOUT = 600


def is_up(api_url: str = API_URL) -> bool:
    try:
        return fetch_json(f"{api_url}/health", {"Accept": "application/json"}, retries=1)["status"] == "ok"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def fetch_hourly(start: date, end: date, zones: list[str] = ZONES, api_url: str = API_URL) -> list[dict]:
    """`spot_prices` rows for the delivery days `start`..`end`; hourly price = mean of the four quarter-hours."""
    rows = []
    while start <= end:
        chunk_end = min(end, start + timedelta(days=MAX_DAYS_PER_REQUEST - 1))
        rows += _fetch_range(start, chunk_end, zones, api_url)
        start = chunk_end + timedelta(days=1)
    return rows


def _fetch_range(start: date, end: date, zones: list[str], api_url: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "zones": ",".join(zones), "start": start.isoformat(), "end": end.isoformat(), "resolution": "hourly",
    })
    try:
        response = fetch_json(f"{api_url}/prices?{query}", {"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # nothing published for the period
            return []
        raise

    hours = {}
    day = start
    while day <= end:
        hours |= {h["delivery_start_utc"]: {"delivery_date": day.isoformat(), **h} for h in day_hours(day)}
        day += timedelta(days=1)

    rows = []
    for point in response["data"]:
        hour = hours[parse_utc(point["timestamp"]).strftime("%Y-%m-%dT%H:%M:%SZ")]
        for zone in zones:
            if point.get(zone) is not None:
                rows.append({"source": SOURCE, "zone": zone, **hour, "price_eur_mwh": point[zone]})
    return rows
