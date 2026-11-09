# Test scenarios (required by the submission guide, section 8)

Run each in the Bedrock Agent **Test** panel. Capture a screenshot of the agent
conversation AND of the affected DynamoDB table(s) before/after. Write a caption
for every screenshot stating the actual numbers.

| # | Scenario | What to type to the agent | Expected result |
|---|----------|---------------------------|-----------------|
| 1 | General hotel question | "What time is check-out?" | Answered from the knowledge base: 11:00 AM. No action group called. |
| 2 | Availability on a date with rooms | "How many rooms are available on 2026-12-22?" | 10 Sea View and 8 Garden View. |
| 3 | Book a room on an available date | "Book a Sea View room for 2026-12-22 for Jane Doe, jane@example.com" | Booking ID returned; a new record in the bookings table; Sea View count for 2026-12-22 drops 10 → 9. |
| 4 | Book on a sold-out date | "Book a Sea View room for 2026-12-25 for John Smith" | Booking refused, guest told no Sea View rooms are available; NO booking record created; Sea View count for 2026-12-25 stays 0. |
| 5 | Missing detail | "I'd like to book a room for 2026-12-27" | Agent asks a clarifying question (room type and/or name) before booking. |
| 6 | Edge case – book the last room | "Book a Sea View room for 2026-12-29 for Priya Patel" | Booking confirmed; Sea View count 1 → 0. A second identical request afterwards is refused (now sold out). |
| 7 | Edge case – fully sold-out date | "Book a Sea View room for 2026-12-31 for Sam Lee", then "Book a Garden View room for 2026-12-31 for Sam Lee" | Both requests refused, guest told no rooms of that type are available; NO booking record created; counts for 2026-12-31 stay 0 Sea View / 0 Garden View (0 / 0 before and after). |

## Verifying scenarios 3, 4 and 7 in DynamoDB
1. Before booking: DynamoDB console → `hotel-booking-assistant-inventory` → Explore items → note the count for the date.
2. Run the booking in the agent test panel.
3. After booking: refresh the item and confirm the count changed (3) or did not (4, 7).
4. Check `hotel-booking-assistant-bookings` → confirm a record exists (3) or does not (4, 7).

## Overbooking (concurrency) check — optional but strong evidence
To demonstrate the atomic guarantee directly against the Lambda, invoke two
bookRoom calls for the last room (2026-12-29 Sea View) nearly simultaneously.
Exactly one returns status "confirmed"; the other returns status "unavailable".
You can do this from two terminals with the AWS CLI `lambda invoke`, or by
setting the count to 1 and firing two quick requests.
