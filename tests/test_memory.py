from __future__ import annotations

import json
from pathlib import Path

from agent.agent import MemoryStore


def test_memory_store_appends_and_trims(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    store = MemoryStore(path=memory_path, max_entries=2)

    store.append("Запрос 1", "Ответ 1", ["web_search"])
    store.append("Запрос 2", "Ответ 2", ["get_weather"])
    store.append("Запрос 3", "Ответ 3", ["get_crypto_price"])

    payload = json.loads(memory_path.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 2
    assert payload["entries"][0]["user"] == "Запрос 2"
    assert "get_crypto_price" in payload["entries"][1]["tools"]


def test_memory_context_formats_entries(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    store = MemoryStore(path=memory_path)
    store.append("Найди погоду", "Сейчас ясно", ["get_weather"])

    context = store.render_context()
    assert "Найди погоду" in context
    assert "get_weather" in context
