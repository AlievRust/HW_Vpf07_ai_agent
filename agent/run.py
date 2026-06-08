from __future__ import annotations

import argparse
import sys

from .agent import TerminalAgent
from .output import render_turn_sections


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Терминальный AI-агент")
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Запрос для одноразового запуска. Если не задан, откроется интерактивный режим.",
    )
    return parser


def run_interactive(agent: TerminalAgent) -> None:
    print("Терминальный AI-агент. Введите запрос или `exit` для выхода.")
    while True:
        try:
            user_input = input("> ").strip()
        except EOFError:
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "выход"}:
            break

        try:
            turn = agent.respond(user_input)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка: {exc}")
            continue

        sections = render_turn_sections(
            answer=turn.answer,
            memory_summary=turn.memory_summary,
            notifications=turn.notifications,
            show_memory_summary=agent.show_memory_summary,
        )
        for index, section in enumerate(sections):
            if index:
                print()
            print(section)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    agent = TerminalAgent()
    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("Пустой запрос")
        try:
            turn = agent.respond(prompt)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 1
        sections = render_turn_sections(
            answer=turn.answer,
            memory_summary=turn.memory_summary,
            notifications=turn.notifications,
            show_memory_summary=agent.show_memory_summary,
        )
        for index, section in enumerate(sections):
            if index:
                print()
            print(section)
        return 0

    run_interactive(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
