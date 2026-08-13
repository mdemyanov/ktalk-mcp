"""Дообогащение состава участников (FR-8).

Срабатывает ТОЛЬКО когда `len(participants) < participantsCount` (строгое `<`,
не `<=`) — иначе полный `ktalk sync` (~1316 записей) слал бы лишний запрос на
каждую запись домена вместо ~23% (зонд, Ф-4). Конкурентность ограничена
`asyncio.Semaphore` — предела rate limiting API нигде не задокументировано
(RES-001), поэтому дефолт консервативен, а не выведен из замера пропускной
способности. Отказ по одной записи не должен прерывать fan-out целиком
(`asyncio.gather(..., return_exceptions=True)`).
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def _display_name(info: dict) -> str:
    surname = info.get("surname")
    firstname = info.get("firstname")
    if surname and firstname:
        return f"{surname} {firstname}"
    return surname or firstname or info.get("login") or "Неизвестный"


def map_participants(raw: list[dict]) -> list[dict]:
    """Замена замороженного `registry.participants_from_api`: не роняет анонимов.

    Аноним -> `{"ktalk_id": anonymousId, "name": anonymousName or "Аноним"}`.
    Именованный -> та же схема ключей `ktalk_id`/`name` — формат строки
    `participants` в SQLite (`registry.py`) не меняется.
    """
    out: list[dict] = []
    for p in raw:
        info = p.get("userInfo")
        if info:
            ktalk_id = info.get("key") or info.get("login")
            if not ktalk_id:
                continue
            out.append({"ktalk_id": str(ktalk_id), "name": _display_name(info)})
            continue
        anon_id = p.get("anonymousId")
        if not anon_id:
            continue
        out.append({"ktalk_id": str(anon_id), "name": p.get("anonymousName") or "Аноним"})
    return out


async def enrich_batch(
    records: list[dict],
    client,
    *,
    concurrency: int = 5,
) -> dict[str, list[dict]]:
    """Возвращает `{recording_id: participants[]}` только для записей, где
    `len(participants) < participantsCount`. Остальные не трогает.

    Отказ по одной записи (сеть/500/таймаут) не прерывает остальные — лог
    предупреждения, запись просто отсутствует в результате этого прохода
    (согласуется с общей веротерпимостью sync к частичным данным).
    """
    targets = [
        r for r in records if len(r.get("participants") or []) < r.get("participantsCount", 0)
    ]
    if not targets:
        return {}

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _enrich_one(record: dict) -> tuple[str, list[dict] | None]:
        rid = str(record.get("id") or record.get("key") or "")
        async with semaphore:
            try:
                detail = await client.get_recording(rid)
            except Exception:  # noqa: BLE001 - одна запись не должна ронять весь sync
                logger.warning("Не удалось дообогатить участников записи %s", rid)
                return rid, None
        return rid, map_participants(detail.get("participants") or [])

    results = await asyncio.gather(*(_enrich_one(r) for r in targets))
    return {rid: parts for rid, parts in results if parts is not None}
