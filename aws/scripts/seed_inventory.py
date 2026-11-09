#!/usr/bin/env python3
"""
Seed the DynamoDB inventory table with the buildathon test data.

Usage:
    python aws/scripts/seed_inventory.py --table hotel-booking-assistant-inventory --region us-east-1

This is an alternative to running the PartiQL INSERTs by hand. It loads all 12
dates in one batch, including the deliberate edge cases:
    2026-12-25 -> Sea View sold out
    2026-12-29 -> only 1 Sea View left
    2026-12-31 -> fully sold out
"""
import argparse

import boto3

SEED = [
    {"date": "2026-12-20", "seaView": 10, "gardenView": 8},
    {"date": "2026-12-21", "seaView": 12, "gardenView": 9},
    {"date": "2026-12-22", "seaView": 10, "gardenView": 8},
    {"date": "2026-12-23", "seaView": 17, "gardenView": 21},
    {"date": "2026-12-24", "seaView": 8, "gardenView": 11},
    {"date": "2026-12-25", "seaView": 0, "gardenView": 2},
    {"date": "2026-12-26", "seaView": 7, "gardenView": 9},
    {"date": "2026-12-27", "seaView": 10, "gardenView": 4},
    {"date": "2026-12-28", "seaView": 7, "gardenView": 8},
    {"date": "2026-12-29", "seaView": 1, "gardenView": 0},
    {"date": "2026-12-30", "seaView": 7, "gardenView": 8},
    {"date": "2026-12-31", "seaView": 0, "gardenView": 0},
]


def main():
    parser = argparse.ArgumentParser(description="Seed the hotel inventory table.")
    parser.add_argument("--table", required=True, help="DynamoDB inventory table name.")
    parser.add_argument("--region", default="us-east-1", help="AWS region.")
    parser.add_argument("--profile", default=None, help="AWS named profile (optional).")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    table = session.resource("dynamodb").Table(args.table)

    with table.batch_writer() as batch:
        for row in SEED:
            batch.put_item(Item=row)

    print(f"Seeded {len(SEED)} dates into '{args.table}' ({args.region}).")


if __name__ == "__main__":
    main()
