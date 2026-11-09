"""
Stdlib-unittest proof for the offline booking core.

Each test runs against a fresh temp SQLite DB seeded with the 12 canonical
rows, pointing booking_core at that temp path. No network, no Ollama.
"""

import os
import tempfile
import threading
import unittest

from local import booking_core, db


class BookingCoreTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init(reset=True, path=self.path)
        db.seed(path=self.path)

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    # Helpers ------------------------------------------------------------- #
    def _count(self, date, col):
        conn = db.connect(self.path)
        try:
            row = conn.execute(
                f"SELECT {col} FROM inventory WHERE date = ?", (date,)
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else row[col]

    def _booking_rows(self, date):
        conn = db.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE checkInDate = ?", (date,)
            ).fetchall()
        finally:
            conn.close()
        return rows

    # (a) Concurrency / overbooking proof --------------------------------- #
    def test_concurrent_last_sea_view_room(self):
        date = "2026-12-29"  # seeded seaView=1
        self.assertEqual(self._count(date, "seaView"), 1)

        results = []
        lock = threading.Lock()

        def book(name):
            res = booking_core.book_room(
                check_in_date=date, room_type="Sea View",
                guest_name=name, path=self.path,
            )
            with lock:
                results.append(res)

        t1 = threading.Thread(target=book, args=("Alice",))
        t2 = threading.Thread(target=book, args=("Bob",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        statuses = sorted(r["status"] for r in results)
        self.assertEqual(statuses, ["confirmed", "unavailable"])
        self.assertEqual(self._count(date, "seaView"), 0)
        self.assertEqual(len(self._booking_rows(date)), 1)

    # (b) Available date decrements by one and writes one record ---------- #
    def test_available_date_decrements_once(self):
        date = "2026-12-22"  # seaView=10
        self.assertEqual(self._count(date, "seaView"), 10)
        res = booking_core.book_room(
            check_in_date=date, room_type="Sea View",
            guest_name="Carol", path=self.path,
        )
        self.assertEqual(res["status"], "confirmed")
        self.assertTrue(res["booked"])
        self.assertEqual(self._count(date, "seaView"), 9)
        self.assertEqual(len(self._booking_rows(date)), 1)

    # (c) Sold-out date refuses, no record, count stays 0 ----------------- #
    def test_sold_out_sea_view(self):
        date = "2026-12-25"  # seaView=0
        self.assertEqual(self._count(date, "seaView"), 0)
        res = booking_core.book_room(
            check_in_date=date, room_type="Sea View",
            guest_name="Dave", path=self.path,
        )
        self.assertEqual(res["status"], "unavailable")
        self.assertFalse(res["booked"])
        self.assertEqual(self._count(date, "seaView"), 0)
        self.assertEqual(len(self._booking_rows(date)), 0)

    # (d) Missing room type -> error, no record --------------------------- #
    def test_missing_room_type(self):
        date = "2026-12-22"
        res = booking_core.book_room(
            check_in_date=date, room_type=None,
            guest_name="Eve", path=self.path,
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(
            res["message"],
            "Please specify a valid room type: 'Sea View' or 'Garden View'.",
        )
        self.assertEqual(len(self._booking_rows(date)), 0)

    # (e) check_availability message strings match the contract ----------- #
    def test_check_availability_messages(self):
        plain = booking_core.check_availability("2026-12-22", path=self.path)
        self.assertEqual(plain["status"], "ok")
        self.assertEqual(plain["seaView"], 10)
        self.assertEqual(plain["gardenView"], 8)
        self.assertEqual(
            plain["message"],
            "On 2026-12-22: 10 Sea View and 8 Garden View room(s) available.",
        )

        filtered = booking_core.check_availability(
            "2026-12-22", room_type="Sea View", path=self.path
        )
        self.assertEqual(filtered["requestedRoomType"], "Sea View")
        self.assertEqual(filtered["requestedRoomAvailable"], 10)
        self.assertEqual(
            filtered["message"],
            "10 Sea View room(s) available on 2026-12-22.",
        )

        sold_out = booking_core.check_availability(
            "2026-12-25", room_type="Sea View", path=self.path
        )
        self.assertEqual(
            sold_out["message"],
            "No Sea View rooms available on 2026-12-25.",
        )

    # (f) update_inventory sets absolute count and rejects negative ------- #
    def test_update_inventory(self):
        date = "2026-12-22"
        res = booking_core.update_inventory(
            date, "Sea View", 3, path=self.path
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["count"], 3)
        self.assertEqual(res["roomType"], "Sea View")
        self.assertEqual(
            res["message"],
            "Inventory updated: Sea View on 2026-12-22 set to 3.",
        )
        self.assertEqual(self._count(date, "seaView"), 3)

        neg = booking_core.update_inventory(
            date, "Sea View", -1, path=self.path
        )
        self.assertEqual(neg["status"], "error")
        self.assertEqual(neg["message"], "Count cannot be negative.")
        self.assertEqual(self._count(date, "seaView"), 3)


if __name__ == "__main__":
    unittest.main()
