"""ADR-010-spec §Dev: CLI `search-contacts --query` — текстовый поиск, не
подставляет `key` никуда автоматически (оператор передаёт его вручную дальше
в `--required-attendee-key`).

DEV-009: коды возврата разведены на три исхода, не два — `0 найдено` и «сетевой/
авторизационный отказ» раньше делили один и тот же `rc == 1`, различимый только
каналом stdout/stderr. Потребитель, читающий только `rc`, эту разницу не видел
(находка SA-006/QA-005/PM). Таблица кодов:

    0 — найден хотя бы один кандидат
    1 — сетевая/авторизационная ошибка (без изменений, `Ошибка:` на stderr)
    2 — 0 кандидатов, отказа не было (`Ничего не найдено` на stdout)

Совместимость: единственный существующий потребитель кода возврата —
`tests/test_search_contacts.py::test_ac_10_1_zero_matches_cli_message_names_the_query_and_nonzero_exit`,
он проверяет `rc != 0`, не конкретное значение — новый код 2 его не ломает.
MCP-инструмент `ktalk_search_contacts` (`tools_contacts.py`) код возврата CLI не
использует вовсе (свой процесс, отдаёт текст через `render_tool_output`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ktalk_mcp.client import KTalkClient
from ktalk_mcp.config import Settings, redact_secrets
from ktalk_mcp.contacts import search_contacts
from ktalk_mcp.formatters import format_raw, format_search_contacts


def register_subparsers(sub) -> None:
    p = sub.add_parser("search-contacts", help="Поиск контактов (ADR-010)")
    p.add_argument("--query", required=True, help="Текст имени/фамилии (не логин)")
    p.add_argument("--json", action="store_true")


async def _search_over_network(query: str) -> list[dict]:
    async with KTalkClient.from_settings(Settings()) as client:
        return await search_contacts(client, query)


def cmd_search_contacts(_reg, args: argparse.Namespace) -> int:
    try:
        candidates = asyncio.run(_search_over_network(args.query))
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1

    if args.json:
        print(format_raw({"query": args.query, "candidates": candidates}))
    else:
        print(format_search_contacts(candidates, query=args.query))
    return 0 if candidates else 2
