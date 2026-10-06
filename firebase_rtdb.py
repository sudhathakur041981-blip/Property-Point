"""Firebase Realtime Database persistence for Property Point."""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any


class FirebaseConfigurationError(RuntimeError):
    """Raised when Firebase database settings are missing or invalid."""


class FirebaseStoreError(RuntimeError):
    """Raised when a Firebase Realtime Database operation fails."""


class RealtimeDatabaseStore:
    def __init__(self, root_reference: Any) -> None:
        self.root_reference = root_reference

    @staticmethod
    def _run(operation: Any) -> Any:
        try:
            return operation()
        except Exception as error:
            if type(error).__module__.startswith(
                ("firebase_admin", "requests", "urllib3")
            ):
                raise FirebaseStoreError(
                    "Firebase Realtime Database operation failed."
                ) from error
            raise

    def health_check(self) -> None:
        self._run(lambda: self.root_reference.child(".info/connected").get())

    def list_records(self, collection: str) -> list[dict[str, Any]]:
        records = self._run(lambda: self.root_reference.child(collection).get()) or {}
        if not isinstance(records, dict):
            raise FirebaseStoreError(
                f"Firebase collection {collection!r} must contain an object."
            )
        normalized_records = []
        for record_id, record in records.items():
            if not isinstance(record, dict):
                raise FirebaseStoreError(
                    f"Firebase record {record_id!r} in {collection!r} must be an object."
                )
            normalized_records.append(
                {**record, "id": record.get("id", record_id)}
            )
        return normalized_records

    def get_record(self, collection: str, record_id: str) -> dict[str, Any] | None:
        record = self._run(
            lambda: self.root_reference.child(collection).child(record_id).get()
        )
        if record is None:
            return None
        if not isinstance(record, dict):
            raise FirebaseStoreError(
                f"Firebase record {record_id!r} in {collection!r} must be an object."
            )
        return {**record, "id": record.get("id", record_id)}

    def set_record(
        self,
        collection: str,
        record_id: str,
        record: dict[str, Any],
    ) -> None:
        self._run(
            lambda: self.root_reference.child(collection).child(record_id).set(record)
        )

    def update_pending_record(
        self,
        collection: str,
        record_id: str,
        changes: dict[str, Any],
    ) -> bool:
        reference = self.root_reference.child(collection).child(record_id)
        current_record = self.get_record(collection, record_id)
        if current_record is None or current_record.get("status") != "pending":
            return False

        updated = False

        def update_if_pending(current: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal updated
            updated = False
            if current is None:
                return None
            if current.get("status") != "pending":
                return current
            updated = True
            return {**current, **changes}

        self._run(
            lambda: reference.transaction(update_if_pending)
        )
        return updated


_store_lock = Lock()
_store: RealtimeDatabaseStore | None = None


def initialize_store() -> RealtimeDatabaseStore:
    global _store
    with _store_lock:
        if _store is not None:
            return _store

        database_url = os.environ.get("FIREBASE_DATABASE_URL", "").strip()
        if not database_url:
            raise FirebaseConfigurationError(
                "FIREBASE_DATABASE_URL must be set when "
                "PROPERTY_POINT_DATABASE=realtime_database."
            )

        try:
            import firebase_admin
            from firebase_admin import credentials, db
        except ImportError as error:
            raise FirebaseConfigurationError(
                "Install the Firebase Admin SDK with `pip install -r requirements.txt`."
            ) from error

        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
        try:
            if service_account_json:
                credential = credentials.Certificate(json.loads(service_account_json))
            else:
                credential = credentials.ApplicationDefault()
            app = firebase_admin.initialize_app(
                credential,
                {"databaseURL": database_url},
                name="property-point",
            )
        except (ValueError, json.JSONDecodeError) as error:
            raise FirebaseConfigurationError(
                "FIREBASE_SERVICE_ACCOUNT_JSON must contain valid service-account JSON."
            ) from error

        _store = RealtimeDatabaseStore(db.reference("/", app=app))
        return _store


def reset_store_for_tests() -> None:
    global _store
    with _store_lock:
        _store = None
