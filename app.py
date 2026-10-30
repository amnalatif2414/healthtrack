"""HealthTrack desktop demo - the UI layer on top of healthtrack.py.

The window only collects input, forwards actions to the ViewModel and
renders the UIState it receives. All validation, storage and sync logic
stays in healthtrack.py, exactly as described in the case study.

Run with:  python app.py
"""
import asyncio
import queue
import random
import threading
import tkinter as tk
from datetime import date, datetime, timezone
from tkinter import ttk

from healthtrack import (HealthApi, HealthRepository, HealthViewModel,
                         HealthEntry, SQLiteHealthEntryDAO)


# ---------------------------------------------------------------- data side
class DemoBackend(HealthApi):
    """Simulated backend. 'online' is switched by the checkbox in the UI."""

    def __init__(self):
        self.online = False
        self.received = []

    def upload_entries(self, entries):
        if not self.online:
            raise ConnectionError("Device is offline")
        self.received.extend(entries)


class AppViewModel(HealthViewModel):
    """Adds the two extra screen actions the demo needs (load and sync)."""

    async def load_entries(self, user_id):
        return await asyncio.to_thread(self.repository.get_user_entries, user_id)

    async def sync(self):
        try:
            count = await asyncio.to_thread(self.repository.sync)
            return f"Synced {count} entr{'y' if count == 1 else 'ies'} with the backend."
        except ConnectionError:
            return "Offline - entries stay saved locally and will sync later."


def sensor_reading(user_id):
    """Sensor adapter: turns a (simulated) sensor reading into a HealthEntry."""
    now = datetime.now(timezone.utc).isoformat()
    return HealthEntry(id=None, user_id=user_id, entry_date=date.today().isoformat(),
                       sleep_hours=round(random.uniform(5.5, 9.0), 1),
                       activity_minutes=random.randint(10, 120), mood_score=None,
                       notes="Imported from sensor", source="sensor",
                       created_at=now, updated_at=now)


# ------------------------------------------------------------------ UI side
class HealthTrackApp:
    COLORS = {"idle": "#555555", "loading": "#1F4E79",
              "success": "#2E7D32", "error": "#C62828"}

    def __init__(self, root):
        self.root = root
        root.title("HealthTrack - Personal Wellness App")
        root.minsize(760, 560)

        # Background event loop, so async work never freezes the window.
        self.loop = asyncio.new_event_loop()
        # Results from the background thread are queued and handled by the
        # window itself, because Tkinter must only be updated from its own thread.
        self.ui_queue = queue.Queue()
        self._poll_queue()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        self.backend = DemoBackend()
        dao = SQLiteHealthEntryDAO("healthtrack.db")
        self.view_model = AppViewModel(HealthRepository(dao, api=self.backend))

        self._build_form()
        self._build_table()
        # UI observes the ViewModel; updates are passed to the Tk thread.
        self.view_model.observe(lambda s: self.post(self.render_state, s))
        self.refresh_entries()

    # ----- layout
    def _build_form(self):
        form = ttk.LabelFrame(self.root, text="Daily health entry", padding=10)
        form.pack(fill="x", padx=12, pady=(12, 6))

        self.fields = {}
        rows = [("User ID", "user_id", "user123"),
                ("Date (YYYY-MM-DD)", "entry_date", date.today().isoformat()),
                ("Sleep (hours)", "sleep_hours", ""),
                ("Activity (minutes)", "activity_minutes", "")]
        for i, (label, key, default) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            ttk.Entry(form, textvariable=var, width=28).grid(row=i, column=1, sticky="w", pady=2)
            self.fields[key] = var

        ttk.Label(form, text="Mood (1-5)").grid(row=4, column=0, sticky="w", pady=2)
        self.fields["mood_score"] = tk.StringVar(value="")
        ttk.Combobox(form, textvariable=self.fields["mood_score"], width=25,
                     values=["", "1 - very low", "2", "3", "4", "5 - very good"],
                     state="readonly").grid(row=4, column=1, sticky="w", pady=2)

        ttk.Label(form, text="Notes").grid(row=5, column=0, sticky="nw", pady=2)
        self.notes = tk.Text(form, width=40, height=3)
        self.notes.grid(row=5, column=1, columnspan=3, sticky="w", pady=2)

        buttons = ttk.Frame(form)
        buttons.grid(row=0, column=2, rowspan=5, sticky="n", padx=(24, 0))
        ttk.Button(buttons, text="Save entry", command=self.on_save).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Import sensor reading", command=self.on_sensor).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Sync now", command=self.on_sync).pack(fill="x", pady=2)
        self.online = tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons, text="Device online", variable=self.online,
                        command=self.on_toggle_online).pack(anchor="w", pady=(6, 0))

        self.status = tk.Label(self.root, text="", anchor="w", font=("Segoe UI", 10, "bold"))
        self.status.pack(fill="x", padx=14, pady=(2, 4))

    def _build_table(self):
        frame = ttk.LabelFrame(self.root, text="Past entries for this user", padding=8)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cols = ("date", "sleep", "activity", "mood", "source", "synced", "notes")
        heads = ("Date", "Sleep h", "Activity min", "Mood", "Source", "Synced", "Notes")
        widths = (95, 65, 90, 55, 70, 60, 240)
        self.table = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for c, h, w in zip(cols, heads, widths):
            self.table.heading(c, text=h)
            self.table.column(c, width=w, anchor="w")
        self.table.pack(fill="both", expand=True)

    # ----- helpers
    def run_async(self, coro, on_done=None):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_done:
            future.add_done_callback(
                lambda f: self.post(on_done, f.result()))

    def post(self, func, *args):
        self.ui_queue.put((func, args))

    def _poll_queue(self):
        while not self.ui_queue.empty():
            func, args = self.ui_queue.get_nowait()
            func(*args)
        self.root.after(50, self._poll_queue)

    def show_message(self, text, status="idle"):
        self.status.config(text=text, fg=self.COLORS[status])

    @staticmethod
    def _number(text, kind, label):
        text = text.strip()
        if not text:
            return None
        try:
            return kind(text)
        except ValueError:
            raise ValueError(f"{label} must be a number.")

    # ----- user actions (forwarded to the ViewModel)
    def on_save(self):
        try:
            mood = self.fields["mood_score"].get()
            now = datetime.now(timezone.utc).isoformat()
            entry = HealthEntry(
                id=None,
                user_id=self.fields["user_id"].get(),
                entry_date=self.fields["entry_date"].get().strip(),
                sleep_hours=self._number(self.fields["sleep_hours"].get(), float, "Sleep"),
                activity_minutes=self._number(self.fields["activity_minutes"].get(), int, "Activity"),
                mood_score=int(mood[0]) if mood else None,
                notes=self.notes.get("1.0", "end").strip() or None,
                source="manual", created_at=now, updated_at=now)
        except ValueError as exc:
            self.show_message(str(exc), "error")
            return
        self.run_async(self.view_model.add_health_entry(entry),
                       lambda _: self.refresh_entries())

    def on_sensor(self):
        entry = sensor_reading(self.fields["user_id"].get())
        self.run_async(self.view_model.add_health_entry(entry),
                       lambda _: self.refresh_entries())

    def on_sync(self):
        def done(message):
            self.show_message(message, "success" if message.startswith("Synced") else "error")
            self.refresh_entries()
        self.run_async(self.view_model.sync(), done)

    def on_toggle_online(self):
        self.backend.online = self.online.get()
        self.show_message("Device is now " + ("online." if self.online.get() else "offline."))

    # ----- rendering
    def render_state(self, state):
        self.show_message(state.message, state.status)

    def refresh_entries(self):
        self.run_async(self.view_model.load_entries(self.fields["user_id"].get()),
                       self._fill_table)

    def _fill_table(self, entries):
        self.table.delete(*self.table.get_children())
        show = lambda v: "" if v is None else v
        for e in entries:
            self.table.insert("", "end", values=(
                e.entry_date, show(e.sleep_hours), show(e.activity_minutes),
                show(e.mood_score), e.source, "yes" if e.synced else "no",
                show(e.notes)))


if __name__ == "__main__":
    root = tk.Tk()
    HealthTrackApp(root)
    root.mainloop()
