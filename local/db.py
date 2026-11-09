"""
SQLite persistence for the local offline companion.

Mirrors the two DynamoDB tables used by the cloud app:
  * inventory(date PK, seaView, gardenView)
  * bookings(bookingId PK, guestName, checkInDate, nights, roomType, guestEmail, createdAt)

A single parameterizable path (DB_PATH default) lets tests point at a temp DB.
Connections use manual transaction control (isolation_level=None) and a
PRAGMA busy_timeout so concurrent writers wait rather than erroring.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "hotel.db"

# The 12 canonical seed rows: (date, seaView, gardenView).
SEED = [
    ("2026-12-20", 10, 8),
    ("2026-12-21", 12, 9),
    ("2026-12-22", 10, 8),
    ("2026-12-23", 17, 21),
    ("2026-12-24", 8, 11),
    ("2026-12-25", 0, 2),
    ("2026-12-26", 7, 9),
    ("2026-12-27", 10, 4),
    ("2026-12-28", 7, 8),
    ("2026-12-29", 1, 0),
    ("2026-12-30", 7, 8),
    ("2026-12-31", 0, 0),
]


def connect(path=DB_PATH):
    """Return a sqlite3.Connection with manual transactions and a busy timeout."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # manual transaction control (BEGIN/COMMIT/ROLLBACK)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(reset=False, path=DB_PATH):
    """Create the tables if absent. When reset=True, drop both first."""
    conn = connect(path)
    try:
        if reset:
            conn.execute("DROP TABLE IF EXISTS bookings")
            conn.execute("DROP TABLE IF EXISTS inventory")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS inventory ("
            "date TEXT PRIMARY KEY, "
            "seaView INTEGER NOT NULL, "
            "gardenView INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bookings ("
            "bookingId TEXT PRIMARY KEY, "
            "guestName TEXT, "
            "checkInDate TEXT, "
            "nights INTEGER, "
            "roomType TEXT, "
            "guestEmail TEXT, "
            "createdAt TEXT)"
        )
    finally:
        conn.close()


def seed(path=DB_PATH):
    """INSERT OR REPLACE each of the 12 canonical inventory rows."""
    conn = connect(path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO inventory (date, seaView, gardenView) "
            "VALUES (?, ?, ?)",
            SEED,
        )
    finally:
        conn.close()
