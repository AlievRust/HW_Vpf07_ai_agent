# Терминальный AI-агент

CLI-агент для работы через OpenAI-совместимый интерфейс. Агент понимает задачи на естественном языке, выбирает инструменты и сохраняет краткую память диалога в `agent/memory.json`.
Также доступен Telegram-бот на polling-режиме с тем же ядром.

## Возможности
- веб-поиск через DuckDuckGo;
- HTTP-запросы;
- чтение и запись файлов внутри workspace;
- безопасный запуск ограниченных терминальных команд;
- погода через Open-Meteo;
- цена криптовалюты через CoinGecko;
- курсы обычных валют через Frankfurter;
- напоминания и расписание с сохранением в `agent/reminders.json`;
- долговременная память диалога.

Для веб-поиска используется библиотека `ddgs` вместо устаревшего `duckduckgo-search`.

## Настройка
Создай `agent/.env` и заполни:

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-nano
WORKSPACE_ROOT=/home/xrust/ai_agent_007
SHOW_MEMORY_SUMMARY=true
SHORT_TERM_MEMORY_LIMIT=10
TELEGRAM_BOT_TOKEN=...
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

Telegram-бот запускается отдельно:

```bash
python -m agent.telegram_bot
```

Если видишь ошибку `No module named 'agent'`, значит пакет не установлен в текущее окружение. Повтори:

```bash
python -m pip install -e .
```

## Память
- `memory.json` хранит только краткое резюме и список использованных инструментов.
- `SHOW_MEMORY_SUMMARY=true|false` управляет тем, показывать ли резюме после ответа.
- `SHORT_TERM_MEMORY_LIMIT` задаёт число последних вопросов пользователя, которые агент учитывает в текущей сессии. По умолчанию это `10`.

## Напоминания
- Напоминания сохраняются в `agent/reminders.json` и переживают перезапуск.
- Повторяющиеся напоминания задаются фиксированным интервалом в минутах.
- Если напоминание просрочено, агент покажет его в CLI при следующем запуске или следующем запросе.

## Курсы валют
- Для курсов обычных валют используй инструмент `get_currency_rates`.
- По умолчанию он работает с базой и списком из `USD`, `EUR`, `RUB`.
- Для криптовалют используй `get_crypto_price`, для обычных валют - `get_currency_rates`.

## Telegram
- Бот работает в polling-режиме.
- CLI и Telegram используют одно и то же ядро агента.
- Контекст не разделяется по Telegram user id.

## Проверка
```bash
pytest
python -m compileall .
```
