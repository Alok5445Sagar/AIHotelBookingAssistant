"""
Local self-test of the booking logic WITHOUT AWS.

Replaces boto3's DynamoDB Table with an in-memory fake that honours the two
behaviours the handler relies on:
  * ConditionExpression "attribute_exists(#rt) AND #rt >= :one" on UpdateItem
  * ConditionExpression "attribute_not_exists(bookingId)" on PutItem
and verifies:
  1. booking an available room decrements the count and creates a record
  2. booking a sold-out room is refused and does NOT create a record
  3. booking the last room succeeds, and a second attempt is refused
  4. a clarifying/validation path (missing room type) returns an error
  5. concurrency: two racing bookings for the last room -> exactly one wins

Run:  python aws/scripts/local_test.py
"""
import os
import sys
import threading

# Point the handler at fake table names before importing it.
os.environ["INVENTORY_TABLE"] = "inv"
os.environ["BOOKINGS_TABLE"] = "book"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "booking_handler"))


# --------------------------------------------------------------------------- #
# Minimal fakes
# --------------------------------------------------------------------------- #
class _ConditionalCheckFailed(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self):
        self.items = {}
        self._lock = threading.Lock()

    # inventory keyed by date, bookings keyed by bookingId
    def _key_name(self):
        return "date" if any("seaView" in v or "gardenView" in v
                             for v in self.items.values()) else "bookingId"

    def put_item(self, Item, ConditionExpression=None):
        with self._lock:
            key_name = "bookingId" if "bookingId" in Item else "date"
            key = Item[key_name]
            if ConditionExpression and "attribute_not_exists(bookingId)" in ConditionExpression:
                if key in self.items:
                    raise _ConditionalCheckFailed()
            self.items[key] = dict(Item)

    def get_item(self, Key):
        key = list(Key.values())[0]
        item = self.items.get(key)
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, ConditionExpression=None):
        with self._lock:
            key = list(Key.values())[0]
            item = self.items.get(key)
            attr = list(ExpressionAttributeNames.values())[0] if ExpressionAttributeNames else None

            if ConditionExpression:
                # attribute_exists(#rt) AND #rt >= :one
                if item is None:
                    raise _ConditionalCheckFailed()
                if "attribute_exists" in ConditionExpression and attr not in item:
                    raise _ConditionalCheckFailed()
                if ">= :one" in ConditionExpression and item.get(attr, 0) < 1:
                    raise _ConditionalCheckFailed()

            if item is None:
                item = {"date": key}
                self.items[key] = item

            one = (ExpressionAttributeValues or {}).get(":one")
            # UpdateExpression uses the "#rt" placeholder, not the resolved name.
            if ":c" in (ExpressionAttributeValues or {}):
                item[attr] = ExpressionAttributeValues[":c"]
            elif "#rt - :one" in UpdateExpression:
                item[attr] = item.get(attr, 0) - one
            elif "#rt + :one" in UpdateExpression:
                item[attr] = item.get(attr, 0) + one


class FakeClientError(Exception):
    pass


# Patch boto3 BEFORE importing app
import boto3  # noqa: E402

inv = FakeTable()
book = FakeTable()


class _FakeResource:
    def Table(self, name):
        return inv if name == "inv" else book


boto3.resource = lambda *a, **k: _FakeResource()

# Patch the ClientError the handler catches to our fake's type.
import botocore.exceptions  # noqa: E402
botocore.exceptions.ClientError = _ConditionalCheckFailed

import app  # noqa: E402
app.ClientError = _ConditionalCheckFailed
app.inventory_table = inv
app.bookings_table = book


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def reset():
    inv.items.clear()
    book.items.clear()


def check(name, condition):
    print(("PASS" if condition else "FAIL"), "-", name)
    if not condition:
        raise SystemExit(1)


def test_available_booking():
    reset()
    inv.items["2026-12-22"] = {"date": "2026-12-22", "seaView": 10, "gardenView": 8}
    r = app.book_room("2026-12-22", "Sea View", "Jane Doe", "jane@example.com")
    check("available booking confirmed", r["status"] == "confirmed")
    check("count decremented 10 -> 9", inv.items["2026-12-22"]["seaView"] == 9)
    check("booking record created", len(book.items) == 1)
    check("booking id returned", bool(r.get("bookingId")))


def test_soldout_booking():
    reset()
    inv.items["2026-12-25"] = {"date": "2026-12-25", "seaView": 0, "gardenView": 2}
    r = app.book_room("2026-12-25", "Sea View", "John Smith")
    check("sold-out booking refused", r["status"] == "unavailable")
    check("count stays 0", inv.items["2026-12-25"]["seaView"] == 0)
    check("no booking record", len(book.items) == 0)


def test_last_room():
    reset()
    inv.items["2026-12-29"] = {"date": "2026-12-29", "seaView": 1, "gardenView": 0}
    r1 = app.book_room("2026-12-29", "Sea View", "Priya Patel")
    r2 = app.book_room("2026-12-29", "Sea View", "Second Guest")
    check("last room booked", r1["status"] == "confirmed")
    check("second attempt refused", r2["status"] == "unavailable")
    check("count is 0", inv.items["2026-12-29"]["seaView"] == 0)
    check("exactly one booking record", len(book.items) == 1)


def test_missing_room_type():
    reset()
    r = app.book_room("2026-12-27", None, "Alex")
    check("missing room type -> error", r["status"] == "error")


def test_concurrency():
    reset()
    inv.items["2026-12-29"] = {"date": "2026-12-29", "seaView": 1, "gardenView": 0}
    results = []

    def worker(name):
        results.append(app.book_room("2026-12-29", "Sea View", name)["status"])

    threads = [threading.Thread(target=worker, args=(f"G{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    confirmed = results.count("confirmed")
    unavailable = results.count("unavailable")
    check("concurrency: exactly one confirmed", confirmed == 1)
    check("concurrency: exactly one refused", unavailable == 1)
    check("concurrency: count is 0", inv.items["2026-12-29"]["seaView"] == 0)
    check("concurrency: one booking record", len(book.items) == 1)


def test_check_availability():
    reset()
    inv.items["2026-12-22"] = {"date": "2026-12-22", "seaView": 10, "gardenView": 8}
    r = app.check_availability("2026-12-22")
    check("availability reports sea=10", r["seaView"] == 10)
    check("availability reports garden=8", r["gardenView"] == 8)


if __name__ == "__main__":
    test_check_availability()
    test_available_booking()
    test_soldout_booking()
    test_last_room()
    test_missing_room_type()
    test_concurrency()
    print("\nAll local logic tests passed.")
