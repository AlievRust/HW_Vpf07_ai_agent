from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .agent import TerminalAgent, _default_env_path
from .output import expand_sections_to_messages, render_turn_sections
from .reminders import format_due_reminder

LOGGER = logging.getLogger(__name__)


def _load_environment() -> None:
    load_dotenv(_default_env_path(), override=False)


def _require_telegram_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "Не задан TELEGRAM_BOT_TOKEN. Укажи его в agent/.env или в переменных окружения."
        )
    return token


@dataclass
class TelegramBotRunner:
    agent: TerminalAgent
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def build_application(self, token: str) -> Application:
        application = (
            ApplicationBuilder()
            .token(token)
            .concurrent_updates(False)
            .build()
        )

        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        application.add_error_handler(self.handle_error)
        return application

    async def _send_sections(self, message, sections: list[str]) -> None:
        for chunk in expand_sections_to_messages(sections):
            await message.reply_text(chunk)

    async def _drain_due_notifications(self) -> list[str]:
        async with self._lock:
            reminders = self.agent.reminders.drain_due()
        return [format_due_reminder(reminder) for reminder in reminders]

    async def _respond(self, prompt: str):
        async with self._lock:
            return await asyncio.to_thread(self.agent.respond, prompt)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return

        notifications = await self._drain_due_notifications()
        if notifications:
            await self._send_sections(
                message,
                render_turn_sections("", "", notifications, show_memory_summary=False),
            )

        await message.reply_text(
            "Терминальный AI-агент готов. Просто напиши запрос в чат, и я отвечу через тот же core, что и CLI."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return

        notifications = await self._drain_due_notifications()
        if notifications:
            await self._send_sections(
                message,
                render_turn_sections("", "", notifications, show_memory_summary=False),
            )

        await message.reply_text(
            "Отправь обычный текстовый запрос. CLI и Telegram используют общий агент, память и напоминания."
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return

        prompt = (message.text or "").strip()
        if not prompt:
            return

        try:
            turn = await self._respond(prompt)
        except Exception as exc:  # noqa: BLE001
            await message.reply_text(f"Ошибка: {exc}")
            return

        sections = render_turn_sections(
            answer=turn.answer,
            memory_summary=turn.memory_summary,
            notifications=turn.notifications,
            show_memory_summary=self.agent.show_memory_summary,
        )
        await self._send_sections(message, sections)

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        LOGGER.error(
            "Telegram handler error: %s",
            context.error,
            exc_info=(type(context.error), context.error, context.error.__traceback__),
        )
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(f"Ошибка: {context.error}")


def main() -> int:
    _load_environment()
    token = _require_telegram_token()
    agent = TerminalAgent()
    runner = TelegramBotRunner(agent)
    application = runner.build_application(token)
    application.run_polling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
