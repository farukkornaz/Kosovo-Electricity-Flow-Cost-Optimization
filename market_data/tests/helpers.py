from datetime import date

import db
from common import day_hours

DAY = date(2026, 9, 1)


def auction(source, out_area, in_area, day=DAY):
    return {
        "source": source,
        "auction_id": f"{source}-{out_area}-{in_area}-{day}",
        "corridor": f"{out_area}-{in_area}",
        "out_area": out_area,
        "in_area": in_area,
        "delivery_date": day.isoformat(),
    }


def result(hour, capacity, price, day=DAY, **extra):
    return {
        **day_hours(day)[hour - 1],
        "offered_capacity_mw": capacity,
        "requested_capacity_mw": None,
        "allocated_capacity_mw": None,
        "clearing_price_eur_mwh": price,
        "participants": None,
        "awarded_participants": None,
        "comment": None,
        "cancelled": False,
        **extra,
    }


def bid(hour, quantity, price, awarded=None):
    return {"hour": hour, "quantity_mw": quantity, "price_eur_mwh": price, "awarded_quantity_mw": awarded}


def store(conn, source, out_area, in_area, hour=15, capacity=100, price=10.0, bids=()):
    """One auction with a single hour; hour 15 is '14:00-15:00'."""
    db.save_auction(conn, auction(source, out_area, in_area), [result(hour, capacity, price)],
                    [bid(hour, q, p) for q, p in bids])
