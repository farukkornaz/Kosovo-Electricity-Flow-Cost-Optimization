"""SQLite storage for daily auction results and bids from JAO and SEECAO."""

import sqlite3
from pathlib import Path

KEY_COLUMNS = """
    source             TEXT    NOT NULL,  -- 'JAO' | 'SEECAO'
    auction_id         TEXT    NOT NULL,
    corridor           TEXT    NOT NULL,  -- platform's code, e.g. 'HU-RS', 'IF1-FR-GB', 'MK-XK'
    border             TEXT    NOT NULL,  -- '<out_area>-<in_area>'
    out_area           TEXT    NOT NULL,
    in_area            TEXT    NOT NULL,
    delivery_date      TEXT    NOT NULL,  -- CET/CEST delivery day, YYYY-MM-DD
    hour               INTEGER NOT NULL,  -- 1-based product hour within the delivery day
    timetable          TEXT    NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc TEXT    NOT NULL,"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS results ({KEY_COLUMNS}
    offered_capacity_mw    REAL,
    requested_capacity_mw  REAL,
    allocated_capacity_mw  REAL,
    clearing_price_eur_mwh REAL,
    congestion_income_eur  REAL,     -- SEECAO only
    participants           INTEGER,
    awarded_participants   INTEGER,
    bid_count              INTEGER,  -- SEECAO only
    comment                TEXT,     -- JAO only
    cancelled              INTEGER NOT NULL,
    PRIMARY KEY (source, auction_id, hour)
);
CREATE TABLE IF NOT EXISTS bids ({KEY_COLUMNS}
    quantity_mw         REAL NOT NULL,
    price_eur_mwh       REAL NOT NULL,
    awarded_quantity_mw REAL           -- JAO only
);
CREATE INDEX IF NOT EXISTS bids_auction_hour ON bids (source, auction_id, hour);
CREATE TABLE IF NOT EXISTS spot_prices (
    zone               TEXT    NOT NULL,  -- bidding zone, e.g. 'HU'
    delivery_date      TEXT    NOT NULL,  -- CET/CEST delivery day, YYYY-MM-DD
    hour               INTEGER NOT NULL,  -- 1-based product hour within the delivery day
    timetable          TEXT    NOT NULL,  -- CET/CEST, e.g. '00:00-01:00'
    delivery_start_utc TEXT    NOT NULL,
    price_eur_mwh      REAL    NOT NULL,  -- day-ahead price, hourly mean of the 15-min prices
    PRIMARY KEY (zone, delivery_start_utc)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def replace_auction(conn: sqlite3.Connection, source: str, auction_id: str, results: list, bids: list) -> None:
    """Overwrite everything stored for one auction, so re-crawling a day is idempotent."""
    with conn:
        for table in ("results", "bids"):
            conn.execute(f"DELETE FROM {table} WHERE source = ? AND auction_id = ?", (source, auction_id))
        _insert(conn, "results", results)
        _insert(conn, "bids", bids)


def save_spot_prices(conn: sqlite3.Connection, rows: list) -> None:
    """Upsert hourly spot prices; a re-fetched hour replaces the stored one."""
    with conn:
        _insert(conn, "spot_prices", rows, or_replace=True)


def _insert(conn: sqlite3.Connection, table: str, rows: list, or_replace: bool = False) -> None:
    if not rows:
        return
    columns = list(rows[0])
    verb = "INSERT OR REPLACE" if or_replace else "INSERT"
    conn.executemany(
        f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        [tuple(row[c] for c in columns) for row in rows],
    )
