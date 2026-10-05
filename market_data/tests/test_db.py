import sqlite3
from datetime import date

import pytest

import db
from common import day_hours
from helpers import auction, bid, result, store


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "market.db")
    yield conn
    conn.close()


def test_day_hours_follow_clock_changes():
    assert len(day_hours(date(2026, 9, 1))) == 24
    assert len(day_hours(date(2026, 3, 29))) == 23
    fall = day_hours(date(2026, 10, 25))
    assert len(fall) == 25
    assert [h["timetable"] for h in fall].count("02:00-03:00") == 2
    assert day_hours(date(2026, 9, 1))[0]["delivery_start_utc"] == "2026-08-31T22:00:00Z"
    assert day_hours(date(2026, 9, 1))[-1]["timetable"] == "23:00-24:00"


def test_save_auction_replaces_and_numbers_bids(conn):
    rows = (auction("JAO", "HU", "RS"), [result(1, 100, 5.0)], [bid(1, 10, 2.0), bid(1, 20, 9.0)])
    db.save_auction(conn, *rows)
    db.save_auction(conn, *rows)

    assert conn.execute("SELECT count(*) FROM auctions").fetchone()[0] == 1
    assert conn.execute("SELECT seq, price_eur_mwh FROM bids ORDER BY seq").fetchall() == [(1, 9.0), (2, 2.0)]
    assert db.has_auction(conn, "JAO", "JAO-HU-RS-2026-09-01")


def test_views_give_flat_rows(conn):
    store(conn, "SEECAO", "MK", "XK", capacity=200, price=3.0, bids=[(50, 4.0)])
    conn.execute("UPDATE results SET allocated_capacity_mw = 200")

    border, timetable, income = conn.execute(
        "SELECT border, timetable, congestion_income_eur FROM results_v").fetchone()
    assert (border, timetable, income) == ("MK-XK", "14:00-15:00", 600.0)
    assert conn.execute("SELECT border, timetable, quantity_mw FROM bids_v").fetchone() == ("MK-XK", "14:00-15:00", 50)


def test_old_schema_is_refused(tmp_path):
    path = tmp_path / "old.db"
    sqlite3.connect(path).execute("CREATE TABLE results (source TEXT)").connection.close()
    with pytest.raises(RuntimeError, match="schema version 0"):
        db.connect(path)


def test_missing_file_is_not_created_when_reading(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect(tmp_path / "none.db", create=False)
