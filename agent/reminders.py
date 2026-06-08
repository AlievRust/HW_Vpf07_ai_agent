from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def default_reminders_path() -> Path:
    return Path(__file__).resolve().parent / "reminders.json"


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"entries": []}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("reminders.json должен содержать JSON-объект")
    payload.setdefault("entries", [])
    if not isinstance(payload["entries"], list):
        raise ValueError("reminders.json: поле entries должно быть списком")
    return payload


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _local_timezone() -> timezone:
    tz = datetime.now().astimezone().tzinfo
    return tz if tz is not None else timezone.utc


def _parse_datetime(raw: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Время напоминания не может быть пустым")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_local_timezone())
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_positive_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "" or value == 0 or value == "0":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Поле {field_name} должно быть целым числом") from exc
    if parsed <= 0:
        raise ValueError(f"Поле {field_name} должно быть положительным числом")
    return parsed


def _normalize_status(value: Any) -> str:
    status = str(value or "active").strip().lower()
    if status not in {"active", "completed", "cancelled"}:
        return "active"
    return status


def _non_empty_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    created_at = _format_datetime(
        _parse_datetime(entry.get("created_at") or datetime.now(timezone.utc).isoformat())
    )
    next_run_at = _format_datetime(_parse_datetime(entry.get("next_run_at")))
    last_fired_at_raw = entry.get("last_fired_at")
    last_fired_at = (
        _format_datetime(_parse_datetime(last_fired_at_raw))
        if last_fired_at_raw
        else None
    )
    repeat_every_minutes = _parse_positive_int(entry.get("repeat_every_minutes"), "repeat_every_minutes")
    reminder_id = _non_empty_text(entry.get("id"), str(uuid.uuid4()))
    title = _non_empty_text(entry.get("title"), "Напоминание")
    notes = str(entry.get("notes") or "").strip()

    sanitized = {
        "id": reminder_id,
        "title": title,
        "notes": notes,
        "created_at": created_at,
        "next_run_at": next_run_at,
        "repeat_every_minutes": repeat_every_minutes,
        "last_fired_at": last_fired_at,
        "status": _normalize_status(entry.get("status")),
    }
    return sanitized


def format_due_reminder(reminder: dict[str, Any]) -> str:
    note = f" — {reminder['notes']}" if reminder.get("notes") else ""
    repeat = reminder.get("repeat_every_minutes")
    if repeat:
        repeat_text = f" (повторяется каждые {repeat} мин.)"
    else:
        repeat_text = ""
    return f"Напоминание: {reminder['title']}{note}{repeat_text}"


@dataclass
class ReminderStore:
    path: Path
    max_entries: int = 500

    @classmethod
    def from_path(cls, path: str | Path) -> "ReminderStore":
        return cls(Path(path))

    def load(self) -> dict[str, Any]:
        data = _load_json_file(self.path)
        data["entries"] = [self._sanitize_entry(entry) for entry in data.get("entries", [])]
        return data

    def compact(self) -> None:
        _write_json_file(self.path, self.load())

    def _sanitize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_entry(entry)

    def append(self, reminder: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        entries = data.setdefault("entries", [])
        entries.append(self._sanitize_entry(reminder))
        if len(entries) > self.max_entries:
            del entries[: len(entries) - self.max_entries]
        _write_json_file(self.path, data)
        return entries[-1]

    def create(
        self,
        title: str,
        run_at_iso: str,
        repeat_every_minutes: int = 0,
        notes: str = "",
    ) -> dict[str, Any]:
        repeat_minutes = _parse_positive_int(repeat_every_minutes, "repeat_every_minutes")
        reminder = {
            "id": str(uuid.uuid4()),
            "title": _non_empty_text(title, "Напоминание"),
            "notes": str(notes or "").strip(),
            "created_at": _format_datetime(datetime.now(timezone.utc)),
            "next_run_at": _format_datetime(_parse_datetime(run_at_iso)),
            "repeat_every_minutes": repeat_minutes,
            "last_fired_at": None,
            "status": "active",
        }
        return self.append(reminder)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        entries = self.load().get("entries", [])
        normalized_status = str(status or "").strip().lower()
        if normalized_status and normalized_status != "all":
            entries = [entry for entry in entries if entry["status"] == normalized_status]
        return entries

    def cancel(self, reminder_id: str) -> dict[str, Any]:
        data = self.load()
        entries = data.setdefault("entries", [])
        for entry in entries:
            if entry["id"] != reminder_id:
                continue
            entry["status"] = "cancelled"
            _write_json_file(self.path, data)
            return entry
        raise ValueError(f"Напоминание не найдено: {reminder_id}")

    def drain_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        data = self.load()
        entries = data.setdefault("entries", [])
        notifications: list[dict[str, Any]] = []
        changed = False

        for entry in entries:
            if entry["status"] != "active":
                continue

            next_run_at = _parse_datetime(entry["next_run_at"])
            if next_run_at > current_time:
                continue

            notifications.append(entry.copy())
            repeat_every_minutes = entry.get("repeat_every_minutes")
            if repeat_every_minutes:
                interval = timedelta(minutes=repeat_every_minutes)
                next_run = next_run_at
                while next_run <= current_time:
                    next_run += interval
                entry["next_run_at"] = _format_datetime(next_run)
                entry["last_fired_at"] = _format_datetime(current_time)
            else:
                entry["status"] = "completed"
                entry["last_fired_at"] = _format_datetime(current_time)
            changed = True

        if changed:
            _write_json_file(self.path, data)
        return notifications
