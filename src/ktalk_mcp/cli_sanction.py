"""ADR-016 §3: `ktalk sanction status|grant|revoke` — выдача и отзыв мандата на запись.

TTY-проверка живёт здесь, а не в `write_sanction.py`: модуль остаётся тестируемым,
барьер — непроходимым из кода. Флага `--force`/`--yes` и переменной окружения,
обходящей проверку, нет намеренно: обходной путь «для тестов» является обходным
путём и в бою (ADR-014 §8).
"""

from __future__ import annotations

import argparse
import json
import sys

from ktalk_mcp import write_sanction
from ktalk_mcp.write_sanction import DEFAULT_HOURS, DEFAULT_OPERATIONS, OPERATIONS

EXIT_OK = 0
EXIT_BAD_ARGS = 2
EXIT_INTERNAL = 20
EXIT_NO_TTY = 43

_CLI_TO_OPERATION = {operation.replace("_", "-"): operation for operation in OPERATIONS}


def register_subparsers(sub) -> None:
    parser = sub.add_parser("sanction", help="Санкция на запись в контур (ADR-016)")
    actions = parser.add_subparsers(dest="sanction_action")

    p_status = actions.add_parser("status", help="Состояние санкций")
    p_status.add_argument("--json", action="store_true")

    p_grant = actions.add_parser("grant", help="Выдать санкцию (только в терминале)")
    p_grant.add_argument("operation", choices=sorted(_CLI_TO_OPERATION))
    p_grant.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    p_grant.add_argument("--operations", type=int, default=DEFAULT_OPERATIONS)

    p_revoke = actions.add_parser("revoke", help="Отозвать санкцию")
    p_revoke.add_argument("operation", choices=[*sorted(_CLI_TO_OPERATION), "all"])


def _state_json(state) -> dict:
    return {
        "status": state.status,
        "active": state.active,
        "expires_at": state.expires_at,
        "remaining": state.remaining,
    }


def _cmd_status(args: argparse.Namespace) -> int:
    states = {operation: write_sanction.read_state(operation) for operation in OPERATIONS}
    if args.json:
        print(json.dumps({key: _state_json(state) for key, state in states.items()}))
    else:
        for operation, state in states.items():
            suffix = (
                f", до {state.expires_at}, осталось операций: {state.remaining}"
                if state.expires_at
                else ""
            )
            print(f"{operation}: {state.status}{suffix}")
        print(f"Файл: {write_sanction.sanction_path()}")
    return EXIT_OK


def _cmd_grant(args: argparse.Namespace) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            "Санкция на запись выдаётся только в интерактивном терминале. "
            f"Запустите вручную: ktalk sanction grant {args.operation}",
            file=sys.stderr,
        )
        return EXIT_NO_TTY

    operation = _CLI_TO_OPERATION[args.operation]
    try:
        state = write_sanction.grant(
            operation, hours=args.hours, operations=args.operations
        )
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    print(
        f"Санкция «{args.operation}» выдана до {state.expires_at} "
        f"на {state.remaining} операц(ий).\n"
        f"Отзыв: ktalk sanction revoke {args.operation}\n"
        f"Файл: {write_sanction.sanction_path()}"
    )
    return EXIT_OK


def _cmd_revoke(args: argparse.Namespace) -> int:
    targets = OPERATIONS if args.operation == "all" else (_CLI_TO_OPERATION[args.operation],)
    for operation in targets:
        write_sanction.revoke(operation)
        print(f"Санкция «{operation.replace('_', '-')}» отозвана.")
    return EXIT_OK


def cmd_sanction(_reg, args: argparse.Namespace) -> int:
    action = getattr(args, "sanction_action", None)
    handler = {"status": _cmd_status, "grant": _cmd_grant, "revoke": _cmd_revoke}.get(action)
    if handler is None:
        print("Укажите действие: sanction status | grant | revoke", file=sys.stderr)
        return EXIT_BAD_ARGS
    return handler(args)
