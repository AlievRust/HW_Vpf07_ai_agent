from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .tools import build_tools, workspace_root

SYSTEM_PROMPT = """Ты — терминальный AI-агент. Отвечай только на русском языке.

Твоя задача:
- понимать запросы пользователя на естественном языке;
- выбирать подходящий инструмент;
- выполнять только безопасные действия;
- если данных не хватает, задавать уточняющий вопрос;
- после ответа сформировать короткое и понятное резюме для долговременной памяти.

Правила выбора инструмента:
- если нужен интернет-поиск по общей информации, используй `web_search`;
- если нужна погода, используй `get_weather`;
- если нужна цена криптовалюты, используй `get_crypto_price`;
- если нужно прочитать или записать данные, используй файловые инструменты;
- если нужно выполнить действие в терминале, используй только `run_terminal_command`;
- если нужен доступ к внешнему HTTP API, используй `http_request`.

Безопасность:
- никогда не используй опасные shell-команды;
- не пытайся выходить за пределы workspace;
- не раскрывай секреты;
- если запрос двусмысленный, сначала уточни его.

Формат ответа:
- коротко;
- структурировано;
- без лишней воды.
"""


def _default_env_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"entries": []}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("memory.json должен содержать JSON-объект")
    payload.setdefault("entries", [])
    if not isinstance(payload["entries"], list):
        raise ValueError("memory.json: поле entries должно быть списком")
    return payload


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate(text: str, limit: int = 220) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "…"


def _message_field(message: Any, field: str, default: str = "") -> str:
    if isinstance(message, dict):
        value = message.get(field, default)
    else:
        value = getattr(message, field, default)
    return str(value or default)


@dataclass
class MemoryStore:
    path: Path
    max_entries: int = 100

    @classmethod
    def from_path(cls, path: str | Path) -> "MemoryStore":
        return cls(Path(path))

    def load(self) -> dict[str, Any]:
        return _load_json_file(self.path)

    def render_context(self, limit: int = 5) -> str:
        data = self.load()
        entries = data.get("entries", [])[-limit:]
        if not entries:
            return "Пока нет долговременной памяти."

        lines = []
        for item in entries:
            timestamp = item.get("timestamp", "")
            user = item.get("user", "")
            summary = item.get("summary", "")
            tools = ", ".join(item.get("tools", [])) or "без инструментов"
            lines.append(
                f"- [{timestamp}] Пользователь: {_truncate(user)} | Память: {_truncate(summary)} | Инструменты: {tools}"
            )
        return "\n".join(lines)

    def append(self, user_message: str, assistant_message: str, tools_used: list[str]) -> None:
        data = self.load()
        entries = data.setdefault("entries", [])
        summary = self._build_summary(user_message, assistant_message, tools_used)
        entries.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user": user_message,
                "summary": summary,
                "assistant": assistant_message,
                "tools": tools_used,
            }
        )
        if len(entries) > self.max_entries:
            del entries[: len(entries) - self.max_entries]
        _write_json_file(self.path, data)

    def _build_summary(
        self,
        user_message: str,
        assistant_message: str,
        tools_used: list[str],
    ) -> str:
        tools_text = ", ".join(tools_used) if tools_used else "без инструментов"
        return (
            f"Запрос: {_truncate(user_message, 140)}. "
            f"Ответ: {_truncate(assistant_message, 180)}. "
            f"Инструменты: {tools_text}."
        )


class TerminalAgent:
    def __init__(
        self,
        workspace_root_path: str | Path | None = None,
        memory_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(__file__).resolve().parent.parent
        self.workspace_root = workspace_root(workspace_root_path)
        self.memory = MemoryStore.from_path(
            memory_path or (self.project_root / "agent" / "memory.json")
        )

        load_dotenv(_default_env_path(), override=False)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
        model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-5.4-nano"

        if not api_key:
            raise ValueError(
                "Не задан OPENAI_API_KEY. Укажи его в agent/.env или в переменных окружения."
            )

        self.model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
        )
        self.tools = build_tools(self.workspace_root)

    def _build_graph(self, memory_context: str):
        system_prompt = f"{SYSTEM_PROMPT}\n\nДолговременная память:\n{memory_context}"
        return create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=system_prompt,
        )

    def answer(self, user_message: str) -> str:
        memory_context = self.memory.render_context()
        graph = self._build_graph(memory_context)
        result = graph.invoke(
            {"messages": [{"role": "user", "content": user_message}]}
        )
        messages = result.get("messages", [])
        assistant_message = ""
        for message in reversed(messages):
            if _message_field(message, "type") == "ai":
                assistant_message = _message_field(message, "content").strip()
                break
        if not assistant_message and messages:
            assistant_message = _message_field(messages[-1], "content").strip()
        tools_used = []
        for message in messages:
            tool_name = _message_field(message, "name", "")
            if tool_name and tool_name not in tools_used:
                tools_used.append(tool_name)
        self.memory.append(user_message, assistant_message, tools_used)
        return assistant_message
