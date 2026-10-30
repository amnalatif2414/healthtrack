from dataclasses import dataclass
from typing import Optional


@dataclass
class HealthEntry:
    id: Optional[int]
    user_id: str
    entry_date: str                   # ISO 8601 date, e.g. "2026-09-29"
    sleep_hours: Optional[float]
    activity_minutes: Optional[int]
    mood_score: Optional[int]         # 1 = very low ... 5 = very good
    notes: Optional[str]
    source: str                       # "manual" or "sensor"
    created_at: str
    updated_at: str
    synced: bool = False


from abc import ABC, abstractmethod
from typing import List


class DuplicateEntryError(Exception):
    """Raised when an entry for the same user, date and source exists."""


class HealthEntryDAO(ABC):

    @abstractmethod
    def insert_entry(self, entry: HealthEntry) -> int: ...

    @abstractmethod
    def get_entries_for_user(self, user_id: str) -> List[HealthEntry]: ...

    @abstractmethod
    def get_unsynced_entries(self) -> List[HealthEntry]: ...

    @abstractmethod
    def mark_synced(self, entry_ids: List[int]) -> None: ...

    @abstractmethod
    def delete_entry(self, entry_id: int) -> None: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS health_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT    NOT NULL,
    entry_date       TEXT    NOT NULL,
    sleep_hours      REAL    CHECK (sleep_hours BETWEEN 0 AND 24),
    activity_minutes INTEGER CHECK (activity_minutes BETWEEN 0 AND 1440),
    mood_score       INTEGER CHECK (mood_score BETWEEN 1 AND 5),
    notes            TEXT    CHECK (length(notes) <= 500),
    source           TEXT    NOT NULL CHECK (source IN ('manual', 'sensor')),
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    synced           INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, entry_date, source)
);
CREATE INDEX IF NOT EXISTS idx_entries_user_date
    ON health_entries (user_id, entry_date);
"""


import sqlite3
import threading

SELECT_COLUMNS = """SELECT id, user_id, entry_date, sleep_hours,
       activity_minutes, mood_score, notes, source,
       created_at, updated_at, synced
FROM health_entries"""


class SQLiteHealthEntryDAO(HealthEntryDAO):

    def __init__(self, db_path: str):
        # The connection is used from worker threads (asyncio.to_thread),
        # so the same-thread check is disabled and a lock serialises access.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    @staticmethod
    def _to_entry(row) -> HealthEntry:
        return HealthEntry(*row[:-1], synced=bool(row[-1]))

    def insert_entry(self, entry):
        try:
            with self._lock, self._conn:   # commits, or rolls back on error
                cursor = self._conn.execute(
                    """INSERT INTO health_entries
                       (user_id, entry_date, sleep_hours, activity_minutes,
                        mood_score, notes, source, created_at, updated_at,
                        synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry.user_id, entry.entry_date, entry.sleep_hours,
                     entry.activity_minutes, entry.mood_score, entry.notes,
                     entry.source, entry.created_at, entry.updated_at,
                     int(entry.synced)))
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                raise DuplicateEntryError() from exc
            raise

    def get_entries_for_user(self, user_id):
        with self._lock:
            rows = self._conn.execute(
                SELECT_COLUMNS + " WHERE user_id = ? ORDER BY entry_date DESC",
                (user_id,)).fetchall()
        return [self._to_entry(row) for row in rows]

    def get_unsynced_entries(self):
        with self._lock:
            rows = self._conn.execute(
                SELECT_COLUMNS + " WHERE synced = 0").fetchall()
        return [self._to_entry(row) for row in rows]

    def mark_synced(self, entry_ids):
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE health_entries SET synced = 1 WHERE id = ?",
                [(entry_id,) for entry_id in entry_ids])

    def delete_entry(self, entry_id):
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM health_entries WHERE id = ?", (entry_id,))


class HealthApi(ABC):
    """Backend interface; a real implementation calls the server over HTTPS."""

    @abstractmethod
    def upload_entries(self, entries: List[HealthEntry]) -> None: ...


class HealthRepository:

    def __init__(self, dao: HealthEntryDAO, api: Optional[HealthApi] = None):
        self.dao = dao
        self.api = api

    def insert_health_entry(self, entry: HealthEntry) -> int:
        return self.dao.insert_entry(entry)

    def get_user_entries(self, user_id: str) -> List[HealthEntry]:
        return self.dao.get_entries_for_user(user_id)

    def delete_health_entry(self, entry_id: int) -> None:
        self.dao.delete_entry(entry_id)

    def sync(self) -> int:
        """Upload unsynced entries; they stay unsynced if the upload fails."""
        if self.api is None:
            return 0
        pending = self.dao.get_unsynced_entries()
        if not pending:
            return 0
        self.api.upload_entries(pending)          # raises when offline
        self.dao.mark_synced([entry.id for entry in pending])
        return len(pending)


import asyncio
import logging
from datetime import date
from typing import Callable

logger = logging.getLogger("healthtrack")


@dataclass(frozen=True)
class UIState:
    status: str = "idle"          # idle | loading | success | error
    message: str = ""


class HealthViewModel:

    MAX_NOTES_LENGTH = 500

    def __init__(self, repository: HealthRepository):
        self.repository = repository
        self._state = UIState()
        self._observers: List[Callable[[UIState], None]] = []

    @property
    def state(self) -> UIState:
        return self._state

    def observe(self, callback: Callable[[UIState], None]) -> None:
        """Register a UI callback; it receives the current and future states."""
        self._observers.append(callback)
        callback(self._state)

    def _set_state(self, new_state: UIState) -> None:
        self._state = new_state
        for callback in self._observers:
            callback(new_state)

    def validate_entry(self, entry: HealthEntry) -> Optional[str]:
        if not entry.user_id.strip():
            return "User ID is required."
        try:
            day = date.fromisoformat(entry.entry_date)
        except ValueError:
            return "Entry date must be a valid date (YYYY-MM-DD)."
        if day > date.today():
            return "Entry date cannot be in the future."
        if entry.source not in ("manual", "sensor"):
            return "Unknown data source."
        if all(value is None for value in (entry.sleep_hours,
                                           entry.activity_minutes,
                                           entry.mood_score)):
            return "Enter at least one measurement (sleep, activity or mood)."
        if entry.sleep_hours is not None and not 0 <= entry.sleep_hours <= 24:
            return "Sleep hours must be between 0 and 24."
        if (entry.activity_minutes is not None
                and not 0 <= entry.activity_minutes <= 1440):
            return "Activity minutes must be between 0 and 1440."
        if entry.mood_score is not None and not 1 <= entry.mood_score <= 5:
            return "Mood score must be between 1 and 5."
        if entry.notes and len(entry.notes) > self.MAX_NOTES_LENGTH:
            return "Notes must not exceed 500 characters."
        return None

    async def add_health_entry(self, entry: HealthEntry) -> None:
        error = self.validate_entry(entry)
        if error:
            self._set_state(UIState("error", error))
            return

        self._set_state(UIState("loading", "Saving health entry..."))
        try:
            await asyncio.to_thread(self.repository.insert_health_entry, entry)
        except DuplicateEntryError:
            self._set_state(UIState(
                "error", "An entry for this date and source already exists."))
        except Exception:
            # Log the technical cause only - never the health values.
            logger.exception("Saving a health entry failed")
            self._set_state(UIState(
                "error", "The health entry could not be saved."))
        else:
            self._set_state(UIState(
                "success", "Health entry saved successfully."))
