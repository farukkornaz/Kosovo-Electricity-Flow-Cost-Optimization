"""Hourly day-ahead spot prices from the local price API (ENTSO-E backed)."""

import urllib.parse
from datetime import date, datetime, time, timedelta, timezone

from common import MARKET_TZ, fetch_json, hour_columns, parse_utc

API_URL = "http://127.0.0.1:8000"
# Balkan zones the API serves (it has no BA or TR), plus HU, which the Kosovo scenario uses.
ZONES = ["AL", "BG", "GR", "HR", "HU", "ME", "MK", "RO", "RS", "SI", "XK"]


def fetch_hourly(day: date, zones: list[str] = ZONES) -> list[dict]:
    """`spot_prices` rows for `day`; the API's hourly price is the mean of the four quarter-hours."""
    query = urllib.parse.urlencode({"zones": ",".join(zones), "start": day.isoformat(), "resolution": "hourly"})
    response = fetch_json(f"{API_URL}/prices?{query}", {"Accept": "application/json"})

    day_start = datetime.combine(day, time(), MARKET_TZ).astimezone(timezone.utc)
    rows = []
    for point in response["data"]:
        start = parse_utc(point["timestamp"])
        hour = int((start - day_start) / timedelta(hours=1)) + 1
        local_hour = start.astimezone(MARKET_TZ).hour
        timetable = f"{local_hour:02d}:00-{local_hour + 1:02d}:00"
        for zone in zones:
            if point.get(zone) is None:
                continue
            rows.append({
                "zone": zone,
                "delivery_date": day.isoformat(),
                **hour_columns(day_start, hour, timetable),
                "price_eur_mwh": point[zone],
            })
    return rows
