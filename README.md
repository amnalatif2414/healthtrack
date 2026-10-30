# HealthTrack – Personal Wellness App

Code accompanying the case study **Task 2: HealthTrack – Personal Wellness App**
for the course DLBCSEMSE01-01 – Mobile Software Engineering (IU International University of Applied Sciences).

The project implements the MVVM architecture described in the case study in Python:
a `HealthEntry` entity, a DAO interface with an SQLite implementation, a repository with
offline-first synchronization, and an observable `HealthViewModel` with asynchronous data insertion.

## Files

| File | Content | Case study section |
|---|---|---|
| `healthtrack.py` | Entity, DAO interface, SQLite DAO, repository, ViewModel | Sections 3 and 4 |
| `example.py` | Data insertion example | Section 4.4 |
| `test_healthtrack.py` | Automated tests (18 test cases) | Section 7 |
| `app.py` | Tkinter desktop interface demonstrating the complete flow | Appendix A |
| `requirements.txt` | Test dependencies (pytest, pytest-asyncio) | Section 7 |

## Requirements

- Python 3.9 or newer
- Tkinter (included in the standard Python installer for Windows and macOS)

## Setup

```
python -m pip install -r requirements.txt
```

## Running

Data insertion example:

```
python example.py
```

Automated tests:

```
python -m pytest -v
```

Desktop interface:

```
python app.py
```

The example and the desktop interface store their data in a local file `healthtrack.db`,
which is created automatically. Delete it to start with an empty database.
