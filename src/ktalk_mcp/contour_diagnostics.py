"""Корреляционная диагностика недокументированного контура (ADR-004).

Единственный переиспользуемый компонент FR-17/FR-18 (rooms.py, calendar_reader.py):
отказ на недокументированном пути сам по себе неотличим от обычного auth/сетевого
сбоя — модуль запускает контрольный вызов (`list_recordings(top=1)`, уже подтверждён
рабочим в обоих режимах) и решает, где локализована проблема.
"""

from __future__ import annotations

import httpx

from ktalk_mcp.client import KTalkClient, KTalkError

TRANSIENT_ERRORS = (KTalkError, httpx.HTTPError)


class ContourDriftError(KTalkError):
    """Контрольная операция в порядке, но недокументированный путь отказал —
    сбой локализован там, не в правах/сети (ADR-004 «Механизм детекции»)."""

    def __init__(self, operation: str, detail: str) -> None:
        self.operation = operation
        self.detail = detail
        super().__init__(
            f"Недокументированная операция «{operation}» ведёт себя не так, как "
            f"ожидалось (контроль авторизации прошёл): {detail}"
        )


async def diagnose_undocumented_failure(
    client: KTalkClient, operation: str, error: Exception
) -> None:
    """Всегда завершается исключением: либо перевыбрасывает `error` (контроль тоже
    провалился — не дрейф контура), либо поднимает `ContourDriftError` (контроль в
    порядке — сбой локализован в недокументированном пути)."""
    try:
        await client.list_recordings(top=1)
    except TRANSIENT_ERRORS:
        raise error from None
    raise ContourDriftError(operation, str(error)) from error


def require_contract_field(payload: dict, field: str, operation: str) -> None:
    """ContourDriftError вместо тихого KeyError/None при отсутствии поля-якоря
    контракта на коде 200 — без корреляции (доступ уже подтверждён кодом 200)."""
    if field not in payload:
        raise ContourDriftError(
            operation, f"поле-якорь контракта «{field}» отсутствует в ответе 200."
        )
