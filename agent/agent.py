from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .reminders import ReminderStore, default_reminders_path, format_due_reminder
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
- если нужен курс обычных валют, используй `get_currency_rates`;
- если нужно создать, показать или отменить напоминание, используй `create_reminder`, `list_reminders` и `cancel_reminder`;
- если нужно прочитать или записать данные, используй файловые инструменты;
- если нужно выполнить действие в терминале, используй только `run_terminal_command`;
- если нужен доступ к внешнему HTTP API, используй `http_request`.

Безопасность:
- никогда не используй опасные shell-команды;
- не пытайся выходить за пределы workspace;
- не раскрывай секреты;
- если запрос двусмысленный, сначала уточни его.

Формат ответа:
- верни только JSON без Markdown и без пояснений;
- структура: {"answer": "...", "memory_summary": "..."};
- `answer` — основной ответ для пользователя;
- `memory_summary` — очень короткое резюме для `memory.json`, без полного диалога;
- коротко, структурировано, без лишней воды.
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


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on", "да"}:
        return True
    if normalized in {"0", "false", "no", "off", "нет"}:
        return False
    return default


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _parse_response_payload(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "", ""

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            answer = str(
                payload.get("answer")
                or payload.get("response")
                or payload.get("output")
                or ""
            ).strip()
            summary = str(
                payload.get("memory_summary")
                or payload.get("summary")
                or payload.get("memo")
                or ""
            ).strip()
            if answer or summary:
                return answer, summary

    marker_pattern = re.compile(r"(?im)^\s*резюме(?: для памяти)?\s*:\s*$")
    match = marker_pattern.search(stripped)
    if match:
        answer_part = stripped[: match.start()].strip()
        summary_part = stripped[match.end() :].strip()
        answer_part = re.sub(r"(?im)^\s*ответ(?: пользователю)?\s*:\s*", "", answer_part).strip()
        summary_part = re.sub(
            r"(?im)^\s*резюме(?: для памяти)?\s*:\s*",
            "",
            summary_part,
        ).strip()
        if answer_part or summary_part:
            return answer_part, summary_part

    return stripped, ""


@dataclass
class MemoryStore:
    path: Path
    max_entries: int = 100

    @classmethod
    def from_path(cls, path: str | Path) -> "MemoryStore":
        return cls(Path(path))

    def load(self) -> dict[str, Any]:
        data = _load_json_file(self.path)
        data["entries"] = [self._sanitize_entry(entry) for entry in data.get("entries", [])]
        return data

    def compact(self) -> None:
        _write_json_file(self.path, self.load())

    def _sanitize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        summary = str(entry.get("summary", "")).strip()
        if not summary:
            summary = "Пустое резюме"
        tools = [
            str(tool).strip()
            for tool in entry.get("tools", [])
            if str(tool).strip()
        ]
        timestamp = str(entry.get("timestamp") or datetime.now(timezone.utc).isoformat())
        return {
            "timestamp": timestamp,
            "summary": summary,
            "tools": tools,
        }

    def render_context(self, limit: int = 5) -> str:
        data = self.load()
        entries = data.get("entries", [])[-limit:]
        if not entries:
            return "Пока нет долговременной памяти."

        lines = []
        for item in entries:
            timestamp = item.get("timestamp", "")
            summary = item.get("summary", "")
            tools = ", ".join(item.get("tools", [])) or "без инструментов"
            lines.append(
                f"- [{timestamp}] Память: {_truncate(summary)} | Инструменты: {tools}"
            )
        return "\n".join(lines)

    def append(self, summary: str, tools_used: list[str]) -> None:
        data = self.load()
        entries = data.setdefault("entries", [])
        entries.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "tools": tools_used,
            }
        )
        if len(entries) > self.max_entries:
            del entries[: len(entries) - self.max_entries]
        _write_json_file(self.path, data)


@dataclass
class SessionMemory:
    max_questions: int = 10
    questions: list[str] | None = None

    def __post_init__(self) -> None:
        if self.questions is None:
            self.questions = []

    def add(self, question: str) -> None:
        self.questions.append(question)
        if len(self.questions) > self.max_questions:
            del self.questions[: len(self.questions) - self.max_questions]

    def render_context(self) -> str:
        if not self.questions:
            return "Пока нет краткосрочной памяти."

        lines = []
        for index, question in enumerate(self.questions, start=1):
            lines.append(f"{index}. {question}")
        return "\n".join(lines)


@dataclass
class TurnResult:
    answer: str
    memory_summary: str
    tools_used: list[str]
    notifications: list[str]


class TerminalAgent:
    def __init__(
        self,
        workspace_root_path: str | Path | None = None,
        memory_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(__file__).resolve().parent.parent
        self.workspace_root = workspace_root(workspace_root_path)
        self.memory = MemoryStore.from_path(memory_path or (self.project_root / "agent" / "memory.json"))
        self.memory.compact()
        self.reminders = ReminderStore.from_path(default_reminders_path())
        self.reminders.compact()

        load_dotenv(_default_env_path(), override=False)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
        model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-5.4-nano"

        if not api_key:
            raise ValueError(
                "Не задан OPENAI_API_KEY. Укажи его в agent/.env или в переменных окружения."
            )

        self.show_memory_summary = _parse_bool_env("SHOW_MEMORY_SUMMARY", True)
        self.short_term_memory_limit = _parse_positive_int_env("SHORT_TERM_MEMORY_LIMIT", 10)
        self.session_memory = SessionMemory(max_questions=self.short_term_memory_limit)

        self.model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0,
        )
        self.tools = build_tools(self.workspace_root)

    def _build_system_prompt(self) -> str:
        long_term_memory = self.memory.render_context()
        short_term_memory = self.session_memory.render_context()
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"Краткосрочная память текущей сессии (последние {self.short_term_memory_limit} вопросов пользователя):\n"
            f"{short_term_memory}\n\n"
            f"Долговременная память:\n{long_term_memory}"
        )

    def _build_graph(self):
        return create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=self._build_system_prompt(),
        )

    def _extract_turn_result(self, result: dict[str, Any], user_message: str) -> TurnResult:
        messages = result.get("messages", [])
        assistant_message = ""
        for message in reversed(messages):
            if _message_field(message, "type") == "ai":
                assistant_message = _message_content(message).strip()
                break
        if not assistant_message and messages:
            assistant_message = _message_content(messages[-1]).strip()

        answer, memory_summary = _parse_response_payload(assistant_message)
        if not answer:
            answer = assistant_message
        tools_used: list[str] = []
        for message in messages:
            tool_name = _message_field(message, "name", "")
            if tool_name and tool_name not in tools_used:
                tools_used.append(tool_name)

        if not memory_summary:
            tools_text = ", ".join(tools_used) if tools_used else "без инструментов"
            memory_summary = (
                f"Пользователь спросил: {_truncate(user_message, 120)}. "
                f"Агент ответил и использовал инструменты: {tools_text}."
            )

        return TurnResult(
            answer=answer.strip(),
            memory_summary=memory_summary.strip(),
            tools_used=tools_used,
            notifications=[],
        )

    def respond(self, user_message: str) -> TurnResult:
        graph = self._build_graph()
        result = graph.invoke({"messages": [{"role": "user", "content": user_message}]})
        turn = self._extract_turn_result(result, user_message)
        notifications = [format_due_reminder(reminder) for reminder in self.reminders.drain_due()]
        turn.notifications = notifications
        self.memory.append(turn.memory_summary, turn.tools_used)
        self.session_memory.add(user_message)
        return turn

    def answer(self, user_message: str) -> str:
        return self.respond(user_message).answer
