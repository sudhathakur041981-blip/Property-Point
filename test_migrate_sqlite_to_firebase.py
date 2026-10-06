import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from migrate_sqlite_to_firebase import read_sqlite_records
from server import initialize_database


class SQLiteMigrationTests(unittest.TestCase):
    def test_reads_both_tables_and_converts_json_and_boolean_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "property_point.sqlite3"
            initialize_database(database_path)
            with closing(sqlite3.connect(database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO property_submissions (
                            id, owner_name, owner_phone, purpose, location, title,
                            property_type, area_sqft, expected_price_paise, status,
                            created_at, amenities, additional_images, is_featured,
                            is_verified
                        ) VALUES (
                            'property-1', 'Asha Mehta', '+919876543210', 'Sell',
                            'Kharghar', 'Sunny home', 'Flat', 1250, 850000000,
                            'approved', '2026-10-06T00:00:00+00:00',
                            '[\"Lift\"]', '[\"one.jpg\"]', 1, 1
                        )
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO enquiries (
                            id, name, phone, requirement, created_at
                        ) VALUES (
                            'enquiry-1', 'Ravi Shah', '+919876543210', 'Buy',
                            '2026-10-06T00:00:00+00:00'
                        )
                        """
                    )

            properties, enquiries = read_sqlite_records(database_path)

        self.assertEqual(properties[0]["amenities"], ["Lift"])
        self.assertEqual(properties[0]["additional_images"], ["one.jpg"])
        self.assertIs(properties[0]["is_featured"], True)
        self.assertIs(properties[0]["is_verified"], True)
        self.assertEqual(properties[0]["owner_name"], "Asha Mehta")
        self.assertEqual(enquiries[0]["requirement"], "Buy")


if __name__ == "__main__":
    unittest.main()
