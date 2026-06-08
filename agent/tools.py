from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import requests
from ddgs import DDGS
from langchain_core.tools import StructuredTool

from .reminders import ReminderStore, default_reminders_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKSPACE_ROOT = Path(
    os.getenv("WORKSPACE_ROOT") or PROJECT_ROOT
).expanduser().resolve()

MAX_TEXT_CHARS = 20_000
MAX_HTTP_BODY_CHARS = 8_000
MAX_LIST_ITEMS = 80
MAX_REMINDER_TITLE_CHARS = 200

UNSAFE_SHELL_PATTERN = re.compile(r"[|;&<>`]")
ALLOWED_SHELL_COMMANDS = {
    "cat",
    "echo",
    "find",
    "git",
    "head",
    "ls",
    "pwd",
    "python",
    "python3",
    "rg",
    "sed",
    "tail",
    "pytest",
}

WEATHER_CODE_MAP = {
    0: "ясно",
    1: "в основном ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    61: "слабый дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "слабый снег",
    73: "снег",
    75: "сильный снег",
    80: "слабые ливни",
    81: "ливни",
    82: "сильные ливни",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}

FX_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


def workspace_root(workspace_root: str | Path | None = None) -> Path:
    root = Path(workspace_root or os.getenv("WORKSPACE_ROOT") or DEFAULT_WORKSPACE_ROOT)
    return root.expanduser().resolve()


def _resolve_workspace_path(
    path: str | Path,
    workspace_root_path: str | Path | None = None,
) -> Path:
    root = workspace_root(workspace_root_path)
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Файловые операции разрешены только внутри workspace") from exc
    return resolved


def _truncate_text(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _json_or_empty(value: str) -> Any:
    if not value:
        return None
    return json.loads(value)


def _normalize_currency_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if not FX_CODE_PATTERN.match(code):
        raise ValueError(f"Некорректный код валюты: {value}")
    return code


def _parse_quote_codes(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        raw_codes = re.split(r"[,\s]+", value)
    else:
        raw_codes = list(value)
    codes = [_normalize_currency_code(code) for code in raw_codes if str(code).strip()]
    if not codes:
        raise ValueError("Нужно указать хотя бы одну валюту для запроса")
    deduplicated: list[str] = []
    for code in codes:
        if code not in deduplicated:
            deduplicated.append(code)
    return deduplicated


def web_search(query: str, max_results: int = 5) -> str:
    results: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            results.append(
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("href") or item.get("url") or ""),
                    "snippet": str(item.get("body", "")),
                }
            )
    return json.dumps({"query": query, "results": results}, ensure_ascii=False)


def http_request(
    method: str,
    url: str,
    params_json: str = "",
    headers_json: str = "",
    json_body_json: str = "",
    body_text: str = "",
    timeout_seconds: int = 20,
) -> str:
    params = _json_or_empty(params_json) or {}
    headers = _json_or_empty(headers_json) or {}
    json_body = _json_or_empty(json_body_json)
    data = body_text if body_text else None

    response = requests.request(
        method.upper(),
        url,
        params=params,
        headers=headers,
        json=json_body,
        data=data,
        timeout=timeout_seconds,
    )
    body = _truncate_text(response.text, MAX_HTTP_BODY_CHARS)
    summary = {
        "status_code": response.status_code,
        "url": response.url,
        "headers": {
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "cache-control", "date"}
        },
        "body": body,
    }
    return json.dumps(summary, ensure_ascii=False)


def read_file(path: str, workspace_root_path: str | Path | None = None) -> str:
    target = _resolve_workspace_path(path, workspace_root_path)
    text = target.read_text(encoding="utf-8")
    return _truncate_text(text)


def write_file(
    path: str,
    content: str,
    workspace_root_path: str | Path | None = None,
) -> str:
    target = _resolve_workspace_path(path, workspace_root_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return json.dumps(
        {
            "path": str(target),
            "bytes_written": len(content.encode("utf-8")),
        },
        ensure_ascii=False,
    )


def list_directory(
    path: str = ".",
    workspace_root_path: str | Path | None = None,
) -> str:
    target = _resolve_workspace_path(path, workspace_root_path)
    entries: list[dict[str, Any]] = []
    for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        entries.append(
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
        )
        if len(entries) >= MAX_LIST_ITEMS:
            break
    return json.dumps(
        {
            "path": str(target),
            "entries": entries,
        },
        ensure_ascii=False,
    )


def _validate_terminal_command(command: str) -> list[str]:
    if not command.strip():
        raise ValueError("Команда терминала не может быть пустой")
    if "\n" in command or UNSAFE_SHELL_PATTERN.search(command):
        raise ValueError("Команда содержит недопустимые shell-символы")

    args = shlex.split(command, posix=True)
    if not args:
        raise ValueError("Команда не распознана")

    executable = args[0]
    if executable not in ALLOWED_SHELL_COMMANDS:
        raise ValueError(f"Команда '{executable}' не разрешена")

    if executable in {"python", "python3"}:
        if len(args) < 3 or args[1] != "-m":
            raise ValueError("Разрешены только команды вида `python -m <module>`")
    return args


def run_terminal_command(
    command: str,
    timeout_seconds: int = 30,
    workspace_root_path: str | Path | None = None,
) -> str:
    args = _validate_terminal_command(command)
    root = workspace_root(workspace_root_path)
    completed = subprocess.run(
        args,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
    )
    result = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": _truncate_text(completed.stdout),
        "stderr": _truncate_text(completed.stderr),
    }
    return json.dumps(result, ensure_ascii=False)


def _geocode_city(city: str) -> dict[str, Any]:
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "ru", "format": "json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or []
    if not results:
        raise ValueError(f"Не удалось найти город: {city}")
    return results[0]


def get_weather(city: str) -> str:
    location = _geocode_city(city)
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current_weather": "true",
            "timezone": "auto",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current_weather") or {}
    weather_code = current.get("weathercode")
    data = {
        "city": location.get("name", city),
        "country": location.get("country"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "temperature_c": current.get("temperature"),
        "windspeed_kmh": current.get("windspeed"),
        "weather_code": weather_code,
        "condition": WEATHER_CODE_MAP.get(weather_code, "неизвестно"),
    }
    return json.dumps(data, ensure_ascii=False)


def get_crypto_price(coin: str, currency: str) -> float:
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin, "vs_currencies": currency},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return float(payload[coin][currency])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Не удалось получить цену для {coin}/{currency}") from exc


def get_currency_rates(base_currency: str, quote_currencies: str = "USD,EUR,RUB") -> str:
    base = _normalize_currency_code(base_currency)
    quotes = [quote for quote in _parse_quote_codes(quote_currencies) if quote != base]
    if not quotes:
        default_quotes = ["USD", "EUR", "RUB"]
        quotes = [quote for quote in default_quotes if quote != base]
    if not quotes:
        raise ValueError("Для запроса курсов не осталось доступных валют")
    response = requests.get(
        "https://api.frankfurter.dev/v2/rates",
        params={"base": base, "quotes": ",".join(quotes)},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Некорректный ответ валютного API")

    rates: dict[str, float] = {}
    date = ""
    response_base = base
    for item in payload:
        if not isinstance(item, dict):
            continue
        date = date or str(item.get("date") or "")
        response_base = str(item.get("base") or response_base).upper()
        quote = str(item.get("quote") or "").upper()
        rate = item.get("rate")
        if not quote:
            continue
        try:
            rates[quote] = float(rate)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Некорректный курс для {quote}") from exc

    return json.dumps(
        {
            "base": response_base,
            "date": date,
            "rates": rates,
        },
        ensure_ascii=False,
    )


def create_reminder(
    title: str,
    run_at_iso: str,
    repeat_every_minutes: int = 0,
    notes: str = "",
) -> str:
    store = ReminderStore.from_path(default_reminders_path())
    reminder = store.create(
        title=title,
        run_at_iso=run_at_iso,
        repeat_every_minutes=repeat_every_minutes,
        notes=notes,
    )
    return json.dumps(reminder, ensure_ascii=False)


def list_reminders(status: str = "active") -> str:
    store = ReminderStore.from_path(default_reminders_path())
    reminders = store.list(status=status)
    return json.dumps({"entries": reminders}, ensure_ascii=False)


def cancel_reminder(reminder_id: str) -> str:
    store = ReminderStore.from_path(default_reminders_path())
    reminder = store.cancel(reminder_id)
    return json.dumps(reminder, ensure_ascii=False)


def build_tools(workspace_root_path: str | Path | None = None) -> list[StructuredTool]:
    root = workspace_root(workspace_root_path)

    return [
        StructuredTool.from_function(
            func=web_search,
            name="web_search",
            description="Поиск информации в интернете через DuckDuckGo. Используй для общих информационных запросов.",
        ),
        StructuredTool.from_function(
            func=http_request,
            name="http_request",
            description="Выполнение HTTP-запроса к внешнему API. Передавай method, url и при необходимости JSON-строки для params, headers или тела.",
        ),
        StructuredTool.from_function(
            func=lambda path: read_file(path, root),
            name="read_file",
            description="Прочитать текстовый файл внутри workspace.",
        ),
        StructuredTool.from_function(
            func=lambda path, content: write_file(path, content, root),
            name="write_file",
            description="Записать текст в файл внутри workspace.",
        ),
        StructuredTool.from_function(
            func=lambda path=".": list_directory(path, root),
            name="list_directory",
            description="Показать содержимое каталога внутри workspace.",
        ),
        StructuredTool.from_function(
            func=lambda command: run_terminal_command(command, workspace_root_path=root),
            name="run_terminal_command",
            description="Запустить только ограниченную и безопасную команду терминала внутри workspace.",
        ),
        StructuredTool.from_function(
            func=get_weather,
            name="get_weather",
            description="Получить текущую погоду по названию города через Open-Meteo.",
        ),
        StructuredTool.from_function(
            func=lambda coin, currency: str(get_crypto_price(coin, currency)),
            name="get_crypto_price",
            description="Получить цену криптовалюты через CoinGecko. Возвращает число в строковом виде.",
        ),
        StructuredTool.from_function(
            func=get_currency_rates,
            name="get_currency_rates",
            description="Получить актуальные курсы обычных валют через Frankfurter. Поддерживает base и список quotes через запятую.",
        ),
        StructuredTool.from_function(
            func=create_reminder,
            name="create_reminder",
            description="Создать напоминание. Передавай title, run_at_iso и при необходимости repeat_every_minutes и notes.",
        ),
        StructuredTool.from_function(
            func=list_reminders,
            name="list_reminders",
            description="Показать список напоминаний из JSON-хранилища.",
        ),
        StructuredTool.from_function(
            func=cancel_reminder,
            name="cancel_reminder",
            description="Отменить напоминание по id.",
        ),
    ]
