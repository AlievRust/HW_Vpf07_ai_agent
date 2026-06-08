from __future__ import annotations

from typing import Iterable


TELEGRAM_MESSAGE_LIMIT = 4000


def render_turn_sections(
    answer: str,
    memory_summary: str,
    notifications: list[str] | None = None,
    show_memory_summary: bool = True,
) -> list[str]:
    sections: list[str] = []
    normalized_notifications = [notification.strip() for notification in notifications or [] if notification.strip()]
    if normalized_notifications:
        lines = ["Напоминания:"]
        lines.extend(f"- {notification}" for notification in normalized_notifications)
        sections.append("\n".join(lines))

    answer_text = answer.strip()
    if answer_text:
        sections.append(answer_text)

    summary_text = memory_summary.strip()
    if show_memory_summary and summary_text:
        sections.append(f"Резюме для памяти: {summary_text}")

    return sections


def chunk_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    current = ""
    for line in normalized.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""

        if len(line) <= limit:
            current = line
            continue

        start = 0
        while start < len(line):
            chunks.append(line[start : start + limit])
            start += limit

    if current:
        chunks.append(current)

    return chunks


def expand_sections_to_messages(sections: Iterable[str]) -> list[str]:
    messages: list[str] = []
    for section in sections:
        messages.extend(chunk_text(section))
    return messages
