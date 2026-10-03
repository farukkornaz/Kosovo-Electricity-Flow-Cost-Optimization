"""Helpers shared by the JAO and SEECAO crawlers."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
# Both platforms publish product hours in CET/CEST.
MARKET_TZ = ZoneInfo("Europe/Brussels")


def fetch_json(url: str, headers: dict, body: dict | None = None, retries: int = 3):
    """GET (or POST when `body` is given) and decode JSON, retrying network and 5xx errors."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    for attempt in range(retries):
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def delivery_day(period_start_utc: datetime) -> str:
    return period_start_utc.astimezone(MARKET_TZ).date().isoformat()


def auction_columns(source, auction_id, corridor, out_area, in_area, period_start_utc) -> dict:
    """Columns identifying an auction, shared by its `results` and `bids` rows."""
    return {
        "source": source,
        "auction_id": auction_id,
        "corridor": corridor,
        "border": f"{out_area}-{in_area}",
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
