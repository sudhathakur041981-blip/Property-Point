"""Copy existing Property Point SQLite records into Firebase Realtime Database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from firebase_rtdb import initialize_store
from server import DATABASE_PATH, FIREBASE_ENQUIRY_COLLECTION, FIREBASE_PROPERTY_COLLECTION


def parse_json_list(value: object) -> list[object]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON array in the SQLite database.")
    return parsed


def read_sqlite_records(database_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database_path}")
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        properties = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM property_submissions ORDER BY id"
            ).fetchall()
        ]
        enquiries = [
            dict(row)
            for row in connection.execute("SELECT * FROM enquiries ORDER BY id").fetchall()
        ]

    for property_record in properties:
        property_record["amenities"] = parse_json_list(
            property_record.get("amenities")
        )
        property_record["additional_images"] = parse_json_list(
            property_record.get("additional_images")
        )
        property_record["is_featured"] = bool(property_record.get("is_featured"))
        property_record["is_verified"] = bool(property_record.get("is_verified"))
    return properties, enquiries


def migrate(database_path: Path, *, apply: bool, overwrite: bool) -> tuple[int, int]:
    properties, enquiries = read_sqlite_records(database_path)
    print(f"SQLite source: {database_path}")
    print(f"Properties: {len(properties)}")
    print(f"Enquiries: {len(enquiries)}")
    if not apply:
        print("Dry run only. Re-run with --apply to write these records to Firebase.")
        return len(properties), len(enquiries)

    store = initialize_store()
    existing_properties = {
        str(record["id"])
        for record in store.list_records(FIREBASE_PROPERTY_COLLECTION)
    }
    existing_enquiries = {
        str(record["id"])
        for record in store.list_records(FIREBASE_ENQUIRY_COLLECTION)
    }
    conflicts = (
        existing_properties.intersection(str(row["id"]) for row in properties)
        | existing_enquiries.intersection(str(row["id"]) for row in enquiries)
    )
    if conflicts and not overwrite:
        sample_ids = ", ".join(sorted(conflicts)[:5])
        raise RuntimeError(
            f"Firebase already contains {len(conflicts)} matching record ID(s) "
            f"({sample_ids}). No data was changed. Use --overwrite to replace "
            "only those matching IDs."
        )

    for record in properties:
        store.set_record(
            FIREBASE_PROPERTY_COLLECTION,
            str(record["id"]),
            record,
        )
    for record in enquiries:
        store.set_record(
            FIREBASE_ENQUIRY_COLLECTION,
            str(record["id"]),
            record,
        )
    print("Migration complete. SQLite data was retained as a backup.")
    return len(properties), len(enquiries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DATABASE_PATH,
        help=f"SQLite source path (default: {DATABASE_PATH})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write records to Firebase; otherwise perform a dry run.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace Firebase records whose IDs already exist in SQLite.",
    )
    args = parser.parse_args()
    migrate(args.sqlite.expanduser(), apply=args.apply, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
