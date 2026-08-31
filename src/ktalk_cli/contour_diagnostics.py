"""Корреляционная диагностика недокументированного контура (ADR-004).

Единственный переиспользуемый компонент FR-17/FR-18 (rooms.py, calendar_reader.py):
отказ на недокументированном пути сам по себе неотличим от обычного auth/сетевого
сбоя — модуль запускает контрольный вызов (`list_recordings(top=1)`, уже подтверждён
рабочим в обоих режимах) и решает, где локализована проблема.
"""

from __future__ import annotations

import httpx

from ktalk_cli.client import (
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


def _describe_control_failure(control_error: Exception) -> str:
    """DEV-008: класс/HTTP-код/текст контрольного вызова — тот же формат, что
    `_status_hint`, но не глотает исключение целиком. Нужен, когда контроль ТОЖЕ
    падает: раньше его исход терялся в `raise error from None`, и человек не мог
    отличить «контроль упал» от «диагностика не отработала»."""
    status = getattr(control_error, "status_code", None)
    status_part = f"HTTP {status}" if status is not None else "без HTTP-кода"
    return f"{type(control_error).__name__} ({status_part}): {control_error}"


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
    except TRANSIENT_ERRORS as control_error:
        # DEV-008: контроль тоже упал — это не "диагностика не отработала", а
        # самостоятельный факт, который должен дойти до человека вместе с
        # исходной ошибкой, не молча (`except TRANSIENT_ERRORS: raise error from
        # None` раньше терял его целиком).
        error.control_probe = (
            "Контрольный вызов list_recordings(top=1) тоже упал: "
            f"{_describe_control_failure(control_error)}."
        )
        raise error from None
    if isinstance(error, KTalkAuthError) and not isinstance(error, KTalkScopeError):
        new_exc = KTalkWriteAuthMismatchError(
            f"Операция «{operation}» вернула {_status_hint(error)}, хотя тот же credential "
            "подтверждён рабочим независимой проверкой (list_recordings) в ту же секунду. "
            "Обновлять токен/ключ не нужно — причина в том, как именно эта операция "
            "принимает credential (см. ADR-008), не в его валидности."
        )
        _carry(error, new_exc)
        raise new_exc from error
    new_drift = ContourDriftError(operation, str(error))
    _carry(error, new_drift)
    raise new_drift from error


def _carry(error: Exception, derived: Exception) -> None:
    """DEV-012 (ADR-016 §5): вместе с телом ответа переносится и `status_code`.
    Без него журнал операций не отличал «сервер отказал» от «ответа не было» на той
    ветке, где контроль прошёл, — а именно этот класс исходов и разбирают постфактум."""
    derived.response_body = getattr(error, "response_body", None)
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        derived.status_code = status_code


def require_contract_field(payload: dict, field: str, operation: str) -> None:
    """ContourDriftError вместо тихого KeyError/None при отсутствии поля-якоря
    контракта на коде 200 — без корреляции (доступ уже подтверждён кодом 200)."""
    if field not in payload:
        raise ContourDriftError(
            operation, f"поле-якорь контракта «{field}» отсутствует в ответе 200."
        )
