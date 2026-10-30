from datetime import date, datetime, timedelta, timezone
import pytest
from healthtrack import (DuplicateEntryError, HealthApi, HealthEntry,
                         HealthRepository, HealthViewModel,
                         SQLiteHealthEntryDAO, UIState)


def make_entry(**overrides):
    now = datetime.now(timezone.utc).isoformat()
    values = dict(id=None, user_id="user123",
                  entry_date=date.today().isoformat(), sleep_hours=7.0,
                  activity_minutes=30, mood_score=4, notes="Good day",
                  source="manual", created_at=now, updated_at=now)
    values.update(overrides)
    return HealthEntry(**values)


class FakeRepository:
    """Stands in for HealthRepository so the ViewModel is tested alone."""

    def __init__(self, error=None):
        self.saved_entry = None
        self.error = error

    def insert_health_entry(self, entry):
        if self.error:
            raise self.error
        self.saved_entry = entry
        return 1


@pytest.mark.asyncio
async def test_valid_entry_is_saved_and_states_are_emitted():
    repository = FakeRepository()
    view_model = HealthViewModel(repository)
    states = []
    view_model.observe(lambda state: states.append(state.status))

    entry = make_entry()
    await view_model.add_health_entry(entry)

    assert states == ["idle", "loading", "success"]
    assert repository.saved_entry == entry


TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides, expected", [
    ({"user_id": ""}, "User ID is required"),
    ({"entry_date": ""}, "valid date"),
    ({"entry_date": "29/09/2026"}, "valid date"),
    ({"entry_date": TOMORROW}, "future"),
    ({"sleep_hours": None, "activity_minutes": None, "mood_score": None},
     "at least one measurement"),
    ({"sleep_hours": 25}, "Sleep hours"),
    ({"activity_minutes": -10}, "Activity minutes"),
    ({"mood_score": 6}, "Mood score"),
    ({"notes": "x" * 501}, "Notes"),
])
async def test_invalid_entries_are_rejected(overrides, expected):
    repository = FakeRepository()
    view_model = HealthViewModel(repository)

    await view_model.add_health_entry(make_entry(**overrides))

    assert view_model.state.status == "error"
    assert expected in view_model.state.message
    assert repository.saved_entry is None


@pytest.mark.asyncio
async def test_storage_failure_results_in_error_state():
    view_model = HealthViewModel(FakeRepository(error=RuntimeError("disk")))
    await view_model.add_health_entry(make_entry())
    assert view_model.state == UIState(
        "error", "The health entry could not be saved.")


@pytest.mark.asyncio
async def test_duplicate_entry_is_reported():
    view_model = HealthViewModel(FakeRepository(error=DuplicateEntryError()))
    await view_model.add_health_entry(make_entry())
    assert "already exists" in view_model.state.message


@pytest.fixture
def dao():
    return SQLiteHealthEntryDAO(":memory:")


def test_insert_and_retrieve_round_trip(dao):
    entry = make_entry()
    new_id = dao.insert_entry(entry)
    [stored] = dao.get_entries_for_user("user123")
    assert stored.id == new_id
    assert stored.sleep_hours == entry.sleep_hours
    assert stored.synced is False


def test_user_only_retrieves_own_entries(dao):
    dao.insert_entry(make_entry(user_id="alice"))
    dao.insert_entry(make_entry(user_id="bob"))
    assert [e.user_id for e in dao.get_entries_for_user("alice")] == ["alice"]


def test_duplicate_date_and_source_is_rejected(dao):
    dao.insert_entry(make_entry())
    with pytest.raises(DuplicateEntryError):
        dao.insert_entry(make_entry())


class FailingApi(HealthApi):
    def upload_entries(self, entries):
        raise ConnectionError("offline")


class RecordingApi(HealthApi):
    def __init__(self):
        self.uploaded = []

    def upload_entries(self, entries):
        self.uploaded.extend(entries)


def test_entries_stay_unsynced_while_offline(dao):
    dao.insert_entry(make_entry())
    with pytest.raises(ConnectionError):
        HealthRepository(dao, api=FailingApi()).sync()
    assert len(dao.get_unsynced_entries()) == 1


def test_sync_uploads_and_marks_entries(dao):
    dao.insert_entry(make_entry())
    api = RecordingApi()
    assert HealthRepository(dao, api=api).sync() == 1
    assert len(api.uploaded) == 1
    assert dao.get_unsynced_entries() == []


@pytest.mark.asyncio
async def test_worker_thread_insert_with_real_database(dao):
    view_model = HealthViewModel(HealthRepository(dao))
    await view_model.add_health_entry(make_entry())
    assert view_model.state.status == "success"
    assert len(dao.get_entries_for_user("user123")) == 1
