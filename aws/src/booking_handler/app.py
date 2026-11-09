"""
AI-Driven Hotel Booking Assistant - Bedrock Agent action group handler.

Implements three operations the agent can call:

  * checkAvailability(date, roomType)        -> read inventory
  * bookRoom(checkInDate, roomType, ...)      -> atomic decrement + booking record
  * updateInventory(date, roomType, count)    -> admin control

OVERBOOKING PREVENTION (the core business rule)
-----------------------------------------------
Booking uses a single atomic DynamoDB UpdateItem with a ConditionExpression
that the chosen room-type count is >= 1. DynamoDB serialises concurrent writes
to the same item, so if two guests try to book the last room simultaneously,
exactly one UpdateItem succeeds and the other raises ConditionalCheckFailedException.
The booking record is written only AFTER the decrement succeeds, so inventory
and bookings never drift apart.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
INVENTORY_TABLE = os.environ["INVENTORY_TABLE"]
BOOKINGS_TABLE = os.environ["BOOKINGS_TABLE"]
inventory_table = dynamodb.Table(INVENTORY_TABLE)
bookings_table = dynamodb.Table(BOOKINGS_TABLE)

# Map a guest-facing room type to its DynamoDB attribute name.
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
    """Return the DynamoDB attribute name for a guest-supplied room type, or None."""
    if not room_type:
        return None
    return ROOM_TYPE_ATTR.get(room_type.strip().lower())


def _to_int(value, default=0):
    if isinstance(value, Decimal):
        return int(value)
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
def check_availability(date, room_type=None):
    """Return availability for a date, optionally filtered to one room type."""
    if not _is_valid_date(date):
        return {"status": "error",
                "message": f"'{date}' is not a valid date. Use YYYY-MM-DD."}

    resp = inventory_table.get_item(Key={"date": date})
    item = resp.get("Item")
    if not item:
        return {"status": "unavailable",
                "message": f"No inventory is configured for {date}.",
                "date": date, "seaView": 0, "gardenView": 0}

    sea = _to_int(item.get("seaView"))
    garden = _to_int(item.get("gardenView"))
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


def book_room(check_in_date, room_type, guest_name, guest_email=None, nights=1):
    """
    Atomically decrement inventory for the check-in date and create a booking.

    NOTE (known limitation): inventory is decremented only for the check-in
    date, not for every night of a multi-night stay. See solution doc section 5.
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

    # --- ATOMIC, OVERBOOKING-SAFE DECREMENT -------------------------------- #
    # Only succeeds if the item exists AND the count is >= 1. Concurrent callers
    # racing for the last room: exactly one wins, the rest get the condition error.
    try:
        inventory_table.update_item(
            Key={"date": check_in_date},
            UpdateExpression="SET #rt = #rt - :one",
            ConditionExpression="attribute_exists(#rt) AND #rt >= :one",
            ExpressionAttributeNames={"#rt": attr},
            ExpressionAttributeValues={":one": 1},
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {
                "status": "unavailable",
                "message": (
                    f"Sorry, no {ROOM_TYPE_LABEL[attr]} rooms are available on "
                    f"{check_in_date}. The booking was not completed."
                ),
                "booked": False,
            }
        raise  # unexpected error -> surface to Bedrock as a failure

    # --- WRITE BOOKING RECORD ---------------------------------------------- #
    # Decrement already succeeded. If the booking write fails, roll inventory back
    # so the two stores stay consistent.
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

    try:
        bookings_table.put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(bookingId)",
        )
    except ClientError:
        # Compensating action: give the room back.
        inventory_table.update_item(
            Key={"date": check_in_date},
            UpdateExpression="SET #rt = #rt + :one",
            ExpressionAttributeNames={"#rt": attr},
            ExpressionAttributeValues={":one": 1},
        )
        return {"status": "error",
                "message": "Could not save the booking. No room was reserved. Please try again."}

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


def update_inventory(date, room_type, count):
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

    inventory_table.update_item(
        Key={"date": date},
        UpdateExpression="SET #rt = :c",
        ExpressionAttributeNames={"#rt": attr},
        ExpressionAttributeValues={":c": count_int},
    )
    return {"status": "ok",
            "message": f"Inventory updated: {ROOM_TYPE_LABEL[attr]} on {date} set to {count_int}.",
            "date": date, "roomType": ROOM_TYPE_LABEL[attr], "count": count_int}


# --------------------------------------------------------------------------- #
# Bedrock Agent plumbing
# --------------------------------------------------------------------------- #
def _params_to_dict(event):
    """Flatten the agent's parameter list and requestBody into a single dict."""
    params = {}
    for p in event.get("parameters", []) or []:
        params[p.get("name")] = p.get("value")

    request_body = event.get("requestBody", {}) or {}
    content = request_body.get("content", {}) or {}
    for _media_type, body in content.items():
        for prop in body.get("properties", []) or []:
            params[prop.get("name")] = prop.get("value")
    return params


def _agent_response(event, payload):
    """Wrap a result dict in the response envelope Bedrock Agents expect."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {"body": json.dumps(payload)}
            },
        },
        "sessionAttributes": event.get("sessionAttributes", {}) or {},
        "promptSessionAttributes": event.get("promptSessionAttributes", {}) or {},
    }


def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    api_path = event.get("apiPath", "")
    params = _params_to_dict(event)

    try:
        if api_path == "/checkAvailability":
            result = check_availability(params.get("date"), params.get("roomType"))
        elif api_path == "/bookRoom":
            result = book_room(
                check_in_date=params.get("checkInDate") or params.get("date"),
                room_type=params.get("roomType"),
                guest_name=params.get("guestName"),
                guest_email=params.get("guestEmail"),
                nights=params.get("nights", 1),
            )
        elif api_path == "/updateInventory":
            result = update_inventory(
                params.get("date"), params.get("roomType"), params.get("count")
            )
        else:
            result = {"status": "error", "message": f"Unknown operation: {api_path}"}
    except Exception as exc:  # noqa: BLE001 - surface as a clean agent message
        print("Handler error:", repr(exc))
        result = {"status": "error",
                  "message": "An internal error occurred. The booking was not completed."}

    return _agent_response(event, result)
