"""Корреляционная диагностика недокументированного контура (ADR-004).

Единственный переиспользуемый компонент FR-17/FR-18 (rooms.py, calendar_reader.py):
отказ на недокументированном пути сам по себе неотличим от обычного auth/сетевого
сбоя — модуль запускает контрольный вызов (`list_recordings(top=1)`, уже подтверждён
рабочим в обоих режимах) и решает, где локализована проблема.
"""

from __future__ import annotations

import httpx

from ktalk_mcp.client import (
    KTalkAuthError,
    KTalkClient,
    KTalkError,
    KTalkScopeError,
    KTalkWriteAuthMismatchError,
)

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


def _status_hint(error: Exception) -> str:
    """Код ответа для текста сообщения (ADR-008 §2). `_with_status` (client.py)
    прикрепляет `status_code` на исключении при классификации — используется,
    если есть; иначе — общая формулировка без числа (не должно происходить для
    401/403, оставлено как защита от рассинхронизации)."""
    status = getattr(error, "status_code", None)
    return f"HTTP {status}" if status is not None else "ошибку авторизации"


async def diagnose_undocumented_failure(
    client: KTalkClient, operation: str, error: Exception
) -> None:
    """Всегда завершается исключением: либо перевыбрасывает `error` (контроль тоже
    провалился — не дрейф контура), либо поднимает `KTalkWriteAuthMismatchError`
    (ADR-008: исходная ошибка — 401/403, не scope-специфичная, контроль в порядке —
    credential подтверждён рабочим независимой проверкой), либо `ContourDriftError`
    (прочие классы сбоя — контроль в порядке, сбой локализован в недокументированном
    пути)."""
    try:
        await client.list_recordings(top=1)
    except TRANSIENT_ERRORS:
        raise error from None
    if isinstance(error, KTalkAuthError) and not isinstance(error, KTalkScopeError):
        new_exc = KTalkWriteAuthMismatchError(
            f"Операция «{operation}» вернула {_status_hint(error)}, хотя тот же credential "
            "подтверждён рабочим независимой проверкой (list_recordings) в ту же секунду. "
            "Обновлять токен/ключ не нужно — причина в том, как именно эта операция "
            "принимает credential (см. ADR-008), не в его валидности."
        )
        new_exc.response_body = getattr(error, "response_body", None)
        raise new_exc from error
    new_drift = ContourDriftError(operation, str(error))
    new_drift.response_body = getattr(error, "response_body", None)
    raise new_drift from error


def require_contract_field(payload: dict, field: str, operation: str) -> None:
    """ContourDriftError вместо тихого KeyError/None при отсутствии поля-якоря
    контракта на коде 200 — без корреляции (доступ уже подтверждён кодом 200)."""
    if field not in payload:
        raise ContourDriftError(
            operation, f"поле-якорь контракта «{field}» отсутствует в ответе 200."
        )
