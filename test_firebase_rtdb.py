import unittest

from firebase_rtdb import RealtimeDatabaseStore


class MemoryReference:
    def __init__(self, database, path=()):
        self.database = database
        self.path = path

    def child(self, name):
        return MemoryReference(self.database, (*self.path, *name.split("/")))

    def get(self):
        value = self.database
        for part in self.path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def set(self, value):
        parent = self._parent()
        parent[self.path[-1]] = value

    def transaction(self, update):
        current = self.get()
        result = update(current)
        if result is not None:
            self.set(result)
        return result

    def _parent(self):
        value = self.database
        for part in self.path[:-1]:
            value = value.setdefault(part, {})
        return value


class RealtimeDatabaseStoreTests(unittest.TestCase):
    def setUp(self):
        self.database = {
            "property_submissions": {
                "property-1": {"status": "pending", "title": "Home"},
                "property-2": {"status": "approved", "title": "Flat"},
            }
        }
        self.store = RealtimeDatabaseStore(MemoryReference(self.database))

    def test_list_and_get_records_include_database_key_as_id(self):
        records = self.store.list_records("property_submissions")
        self.assertEqual(
            {record["id"] for record in records},
            {"property-1", "property-2"},
        )
        self.assertEqual(
            self.store.get_record("property_submissions", "property-1")["title"],
            "Home",
        )
        self.assertIsNone(self.store.get_record("property_submissions", "missing"))

    def test_update_pending_record_is_conditional(self):
        self.assertTrue(
            self.store.update_pending_record(
                "property_submissions",
                "property-1",
                {"status": "approved", "reviewed_at": "now"},
            )
        )
        self.assertFalse(
            self.store.update_pending_record(
                "property_submissions",
                "property-2",
                {"status": "rejected"},
            )
        )
        self.assertFalse(
            self.store.update_pending_record(
                "property_submissions",
                "missing",
                {"status": "approved"},
            )
        )

    def test_set_record_writes_to_collection_by_id(self):
        self.store.set_record(
            "enquiries",
            "enquiry-1",
            {"id": "enquiry-1", "name": "Ravi"},
        )
        self.assertEqual(
            self.database["enquiries"]["enquiry-1"]["name"],
            "Ravi",
        )


if __name__ == "__main__":
    unittest.main()
