-- =====================================================================
-- AI-Driven Hotel Booking Assistant - Inventory seed data (DynamoDB PartiQL)
-- =====================================================================
-- Table name used below: hotel-booking-assistant-inventory
--   (this is what aws/template.yaml creates with the default ProjectName).
--   If you changed ProjectName, Find & Replace the table name to match.
--
-- HOW TO USE
--   1. Deploy the stack (sam deploy) so the table exists.
--   2. Open DynamoDB console > PartiQL editor.
--   3. Run ONE INSERT statement at a time.
--   4. Click Explore items to confirm all rows loaded.
--   (Alternative: run aws/scripts/seed_inventory.py to load everything at once.)
--
-- EDGE-CASE TEST DATES (included on purpose)
--   2026-12-25  -> Sea View sold out        (test a refused Sea View booking)
--   2026-12-29  -> only 1 Sea View left     (test booking the last room)
--   2026-12-31  -> fully sold out           (test 'no rooms available')
-- =====================================================================

INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-20', 'seaView': 10, 'gardenView': 8};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-21', 'seaView': 12, 'gardenView': 9};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-22', 'seaView': 10, 'gardenView': 8};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-23', 'seaView': 17, 'gardenView': 21};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-24', 'seaView': 8,  'gardenView': 11};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-25', 'seaView': 0,  'gardenView': 2};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-26', 'seaView': 7,  'gardenView': 9};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-27', 'seaView': 10, 'gardenView': 4};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-28', 'seaView': 7,  'gardenView': 8};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-29', 'seaView': 1,  'gardenView': 0};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-30', 'seaView': 7,  'gardenView': 8};
INSERT INTO "hotel-booking-assistant-inventory" VALUE {'date': '2026-12-31', 'seaView': 0,  'gardenView': 0};
