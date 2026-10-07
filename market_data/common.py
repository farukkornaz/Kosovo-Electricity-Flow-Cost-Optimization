"""Helpers shared by the crawlers and importers."""

import http.client
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, time as day_time, timedelta, timezone
from zoneinfo import ZoneInfo

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
# Both platforms publish product hours in CET/CEST.
MARKET_TZ = ZoneInfo("Europe/Brussels")


def fetch_json(url: str, headers: dict, body: dict | None = None, retries: int = 3, timeout: float = 60):
    """GET (or POST when `body` is given) and decode JSON, retrying network and 5xx errors."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == retries - 1:
                raise
        except (OSError, http.client.HTTPException):  # URLError, timeouts, connection resets
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def delivery_day(period_start_utc: datetime) -> str:
    return period_start_utc.astimezone(MARKET_TZ).date().isoformat()


def auction_row(source, auction_id, corridor, out_area, in_area, period_start_utc) -> dict:
    """The `auctions` row identifying one auction."""
    return {
        "source": source,
        "auction_id": auction_id,
        "corridor": corridor,
        "out_area": out_area,
        "in_area": in_area,
        "delivery_date": delivery_day(period_start_utc),
    }


def hour_columns(period_start_utc: datetime, hour: int, timetable: str) -> dict:
    """Columns identifying the hourly product; `hour` is 1-based within the delivery day."""
    start = period_start_utc + timedelta(hours=hour - 1)
    return {
        "hour": hour,
        "timetable": timetable.replace(" ", ""),
        "delivery_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def day_hours(day: date) -> list[dict]:
    """`hour_columns` of every product hour of a CET/CEST delivery day (23, 24 or 25 of them).

    On the 25-hour day two hours share the timetable '02:00-03:00'; only `hour` and
    `delivery_start_utc` tell them apart.
    """
    start = datetime.combine(day, day_time(), MARKET_TZ).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), day_time(), MARKET_TZ).astimezone(timezone.utc)
    hours = []
    for hour in range(1, (end - start) // timedelta(hours=1) + 1):
        local = (start + timedelta(hours=hour - 1)).astimezone(MARKET_TZ).hour
        hours.append(hour_columns(start, hour, f"{local:02d}:00-{local + 1:02d}:00"))
    return hours
