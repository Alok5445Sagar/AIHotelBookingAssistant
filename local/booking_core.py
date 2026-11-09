"""
Offline port of aws/src/booking_handler/app.py business operations over SQLite.

The return dicts and status strings are byte-for-byte identical to the Lambda
handler. Overbooking prevention replaces the DynamoDB conditional UpdateItem
with a single SQLite transaction:

    BEGIN IMMEDIATE
    UPDATE inventory SET <col> = <col> - 1 WHERE date = ? AND <col> >= 1
    if rowcount != 1 -> ROLLBACK -> unavailable
    INSERT booking row in the SAME transaction
    if insert fails -> ROLLBACK (compensating restore) -> error
    COMMIT -> confirmed

<col> is chosen only from the {seaView, gardenView} whitelist, never
interpolated from user text.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

from . import db

# Map a guest-facing room type to its column name.
ROOM_TYPE_ATTR = {
    "sea view": "seaView",
    "seaview": "seaView",
    "sea": "seaView",
    "garden view": "gardenView",
    "gardenview": "gardenView",
    "garden": "gardenView",
}
ROOM_TYPE_LABEL = {"seaView": "Sea View", "gardenView": "Garden View"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _normalise_room_type(room_type):
    """Return the column name for a guest-supplied room type, or None."""
    if not room_type:
        return None
    return ROOM_TYPE_ATTR.get(room_type.strip().lower())


def _to_int(value, default=0):
    if value is None:
        return default
    return int(value)


def _is_valid_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Business operations
# --------------------------------------------------------------------------- #
def check_availability(date, room_type=None, path=db.DB_PATH):
    """Return availability for a date, optionally filtered to one room type."""
    if not _is_valid_date(date):
        return {"status": "error",
                "message": f"'{date}' is not a valid date. Use YYYY-MM-DD."}

    conn = db.connect(path)
    try:
        row = conn.execute(
            "SELECT seaView, gardenView FROM inventory WHERE date = ?", (date,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"status": "unavailable",
                "message": f"No inventory is configured for {date}.",
                "date": date, "seaView": 0, "gardenView": 0}

    sea = _to_int(row["seaView"])
    garden = _to_int(row["gardenView"])
    result = {"status": "ok", "date": date, "seaView": sea, "gardenView": garden}

    attr = _normalise_room_type(room_type)
    if attr:
        count = sea if attr == "seaView" else garden
        result["requestedRoomType"] = ROOM_TYPE_LABEL[attr]
        result["requestedRoomAvailable"] = count
        result["message"] = (
            f"{count} {ROOM_TYPE_LABEL[attr]} room(s) available on {date}."
            if count > 0 else
            f"No {ROOM_TYPE_LABEL[attr]} rooms available on {date}."
        )
    else:
        result["message"] = (
            f"On {date}: {sea} Sea View and {garden} Garden View room(s) available."
        )
    return result


def book_room(check_in_date, room_type, guest_name, guest_email=None, nights=1,
              path=db.DB_PATH):
    """
    Atomically decrement inventory for the check-in date and create a booking.

    NOTE (known limitation): inventory is decremented only for the check-in
    date, not for every night of a multi-night stay.
    """
    if not _is_valid_date(check_in_date):
        return {"status": "error",
                "message": f"'{check_in_date}' is not a valid date. Use YYYY-MM-DD."}

    attr = _normalise_room_type(room_type)
    if not attr:
        return {"status": "error",
                "message": "Please specify a valid room type: 'Sea View' or 'Garden View'."}

    if not guest_name:
        return {"status": "error",
                "message": "A guest name is required to complete the booking."}

    # Column name is chosen from a fixed whitelist, never interpolated from text.
    col = attr  # attr is guaranteed to be "seaView" or "gardenView"

    booking_id = str(uuid.uuid4())
    record = {
        "bookingId": booking_id,
        "guestName": guest_name,
        "checkInDate": check_in_date,
        "nights": _to_int(nights, 1),
        "roomType": ROOM_TYPE_LABEL[attr],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if guest_email:
        record["guestEmail"] = guest_email

    conn = db.connect(path)
    try:
        # --- ATOMIC, OVERBOOKING-SAFE DECREMENT --------------------------- #
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"UPDATE inventory SET {col} = {col} - 1 "
            f"WHERE date = ? AND {col} >= 1",
            (check_in_date,),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return {
                "status": "unavailable",
                "message": (
                    f"Sorry, no {ROOM_TYPE_LABEL[attr]} rooms are available on "
                    f"{check_in_date}. The booking was not completed."
                ),
                "booked": False,
            }

        # --- WRITE BOOKING RECORD IN THE SAME TRANSACTION ----------------- #
        try:
            conn.execute(
                "INSERT INTO bookings "
                "(bookingId, guestName, checkInDate, nights, roomType, "
                "guestEmail, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["bookingId"],
                    record["guestName"],
                    record["checkInDate"],
                    record["nights"],
                    record["roomType"],
                    record.get("guestEmail"),
                    record["createdAt"],
                ),
            )
        except sqlite3.Error:
            # Compensating action: ROLLBACK undoes the decrement too.
            conn.execute("ROLLBACK")
            return {"status": "error",
                    "message": "Could not save the booking. No room was reserved. Please try again."}

        conn.execute("COMMIT")
    finally:
        conn.close()

    return {
        "status": "confirmed",
        "booked": True,
        "bookingId": booking_id,
        "message": (
            f"Booking confirmed. Confirmation ID {booking_id} for {guest_name}: "
            f"{ROOM_TYPE_LABEL[attr]} room, check-in {check_in_date} "
            f"({record['nights']} night(s))."
        ),
        "booking": record,
    }


def update_inventory(date, room_type, count, path=db.DB_PATH):
    """Admin: set the absolute available count for a room type on a date."""
    if not _is_valid_date(date):
        return {"status": "error",
                "message": f"'{date}' is not a valid date. Use YYYY-MM-DD."}
    attr = _normalise_room_type(room_type)
    if not attr:
        return {"status": "error",
                "message": "Please specify a valid room type: 'Sea View' or 'Garden View'."}
    try:
        count_int = int(count)
    except (TypeError, ValueError):
        return {"status": "error", "message": "Count must be a whole number."}
    if count_int < 0:
        return {"status": "error", "message": "Count cannot be negative."}

    col = attr  # whitelist-derived column name
    conn = db.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE inventory SET {col} = ? WHERE date = ?",
            (count_int, date),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    return {"status": "ok",
            "message": f"Inventory updated: {ROOM_TYPE_LABEL[attr]} on {date} set to {count_int}.",
            "date": date, "roomType": ROOM_TYPE_LABEL[attr], "count": count_int}
