from healthtrack import *
import asyncio
from datetime import date, datetime, timezone


async def main():
    dao = SQLiteHealthEntryDAO("healthtrack.db")
    view_model = HealthViewModel(HealthRepository(dao))
    view_model.observe(lambda s: print(f"{s.status}: {s.message}"))

    now = datetime.now(timezone.utc).isoformat()
    entry = HealthEntry(
        id=None, user_id="user123", entry_date=date.today().isoformat(),
        sleep_hours=7.5, activity_minutes=45, mood_score=4,
        notes="Felt energetic today.", source="manual",
        created_at=now, updated_at=now)

    await view_model.add_health_entry(entry)


asyncio.run(main())
