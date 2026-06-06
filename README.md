# Терминальный AI-агент

CLI-агент для работы через OpenAI-совместимый интерфейс. Агент понимает задачи на естественном языке, выбирает инструменты и сохраняет краткую память диалога в `agent/memory.json`.

## Возможности
- веб-поиск через DuckDuckGo;
- HTTP-запросы;
- чтение и запись файлов внутри workspace;
- безопасный запуск ограниченных терминальных команд;
- погода через Open-Meteo;
- цена криптовалюты через CoinGecko;
- долговременная память диалога.

## Настройка
Создай `agent/.env` и заполни:

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-nano
WORKSPACE_ROOT=/home/xrust/ai_agent_007
```

## Быстрый старт в venv
Если ты работаешь на VPS или локально из чистой оболочки, сначала активируй виртуальное окружение и установи проект в editable-режиме:

```bash
cd ~/ai_agent_007
source .venv/bin/activate
python -m pip install -e .
```

Если `.venv` ещё не создан, сделай это один раз:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Запуск
После активации `venv` запускай агент так:

```bash
python -m agent.run
python -m agent.run "Какая погода в Екатеринбурге?"
```

Если видишь ошибку `No module named 'agent'`, значит пакет не установлен в текущее окружение. Повтори:

```bash
python -m pip install -e .
```

## Проверка
```bash
pytest
python -m compileall .
```
