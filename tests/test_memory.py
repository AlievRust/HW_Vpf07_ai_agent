from __future__ import annotations

import json
from pathlib import Path

from agent.agent import MemoryStore, SessionMemory, _parse_response_payload


def test_memory_store_appends_and_trims(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    store = MemoryStore(path=memory_path, max_entries=2)

    store.append("Резюме 1", ["web_search"])
    store.append("Резюме 2", ["get_weather"])
    store.append("Резюме 3", ["get_crypto_price"])

    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 2
    assert payload["entries"][0]["summary"] == "Резюме 2"
    assert "get_crypto_price" in payload["entries"][1]["tools"]
    assert "user" not in payload["entries"][1]
    assert "assistant" not in payload["entries"][1]


def test_memory_context_formats_entries(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    store = MemoryStore(path=memory_path)
    store.append("Сейчас ясно", ["get_weather"])

    context = store.render_context()
    assert "Сейчас ясно" in context
    assert "get_weather" in context


def test_session_memory_keeps_last_questions() -> None:
    memory = SessionMemory(max_questions=2)
    memory.add("Вопрос 1")
    memory.add("Вопрос 2")
    memory.add("Вопрос 3")

    assert memory.questions == ["Вопрос 2", "Вопрос 3"]
    assert "Вопрос 2" in memory.render_context()
    assert "Вопрос 1" not in memory.render_context()


def test_response_payload_parser_handles_json_and_markers() -> None:
    answer, summary = _parse_response_payload(
        '{"answer": "Привет", "memory_summary": "Пользователь поздоровался"}'
    )
    assert answer == "Привет"
    assert summary == "Пользователь поздоровался"

    answer, summary = _parse_response_payload(
        "ОТВЕТ:\nПривет\n\nРЕЗЮМЕ ДЛЯ ПАМЯТИ:\nПользователь поздоровался"
    )
    assert answer == "Привет"
    assert summary == "Пользователь поздоровался"
