"""ADR-010-spec §Dev: CLI `search-contacts --query` — текстовый поиск, не
подставляет `key` никуда автоматически (оператор передаёт его вручную дальше
в `--required-attendee-key`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ktalk_mcp.client import KTalkClient
from ktalk_mcp.config import Settings, redact_secrets
from ktalk_mcp.contacts import search_contacts
from ktalk_mcp.formatters import format_search_contacts


def register_subparsers(sub) -> None:
    p = sub.add_parser("search-contacts", help="Поиск контактов (ADR-010)")
    p.add_argument("--query", required=True, help="Текст имени/фамилии (не логин)")


async def _search_over_network(query: str) -> list[dict]:
    async with KTalkClient.from_settings(Settings()) as client:
        return await search_contacts(client, query)


def cmd_search_contacts(_reg, args: argparse.Namespace) -> int:
    try:
        candidates = asyncio.run(_search_over_network(args.query))
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1

    print(format_search_contacts(candidates, query=args.query))
    return 0 if candidates else 1
