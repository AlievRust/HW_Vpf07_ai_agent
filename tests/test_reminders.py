from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.reminders import ReminderStore, format_due_reminder


def test_reminder_store_creates_lists_and_cancels(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")

    reminder = store.create("Позвонить", "2026-06-09T10:00:00+00:00", notes="Клиент")
    payload = json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))

    assert payload["entries"][0]["title"] == "Позвонить"
    assert reminder["status"] == "active"
    assert store.list()[0]["id"] == reminder["id"]

    cancelled = store.cancel(reminder["id"])
    assert cancelled["status"] == "cancelled"
    assert store.list("cancelled")[0]["id"] == reminder["id"]


def test_reminder_store_drain_marks_one_off_completed(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    store.create("Выключить духовку", "2026-06-09T10:00:00+00:00")

    notifications = store.drain_due(now=datetime(2026, 6, 9, 11, 0, tzinfo=timezone.utc))

    assert len(notifications) == 1
    assert notifications[0]["title"] == "Выключить духовку"
    assert store.list("completed")[0]["status"] == "completed"


def test_reminder_store_drain_reschedules_recurring(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    store.create(
        "Проверить почту",
        "2026-06-09T10:00:00+00:00",
        repeat_every_minutes=60,
        notes="Каждый час",
    )

    notifications = store.drain_due(now=datetime(2026, 6, 9, 11, 0, tzinfo=timezone.utc))

    assert len(notifications) == 1
    active = store.list("active")[0]
    assert active["status"] == "active"
    assert active["next_run_at"] == "2026-06-09T12:00:00+00:00"
    assert active["last_fired_at"] == "2026-06-09T11:00:00+00:00"
    assert "повторяется каждые 60 мин." in format_due_reminder(active)
