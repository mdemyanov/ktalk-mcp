"""Потоковая запись видеофайла записи на диск (FR-7).

Session-режим — ссылка уже готова в `qualities[].fileUrl` деталей записи.
Api-key-режим — отдельный путь с именем качества в шаблоне (`RES-001` п.5), список
доступных качеств под ключом взять неоткуда (открытый вопрос SA) — запрошенное
качество используется как есть, без валидации по списку.

Зонд Ф-7: имя качества расходится между режимами (`900p` без пробела в session,
`900 p` с пробелом рекомендует спека api-key) — наивная сборка URL с пробелом
ломается (`InvalidURL`). `build_download_url` нормализует и квотирует.

Политика записи на диск — базовый безопасный минимум (SA сознательно оставил её
открытой, полное ревью — DevSecOps): пишем только по явно переданному пути, не
угадываем и не создаём файлы в неожиданных местах, отказываем при попытке
перезаписать существующий файл без явного `overwrite=True`.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from ktalk_mcp.config import AuthMode

DEFAULT_QUALITY = "900p"


class QualityNotFoundError(Exception):
    """Запрошенное качество недоступно для этой записи (FR-7 AC-3)."""


def _normalize_quality(quality: str) -> str:
    """`900p` и `900 p` -> одна и та же каноническая форма без пробела."""
    return quality.replace(" ", "").lower()


def build_download_url(recording_key: str, quality: str) -> str:
    """Api-key-путь скачивания, URL-квотированный (FR-7 AC-2, зонд Ф-7)."""
    normalized = _normalize_quality(quality)
    key = quote(str(recording_key), safe="")
    q = quote(normalized, safe="")
    return f"/api/Recordings/{key}/file/{q}"


def _resolve_session_quality(qualities: list[dict], quality: str | None) -> tuple[str, str]:
    if not qualities:
        raise QualityNotFoundError("У записи нет доступных качеств скачивания.")
    by_normalized = {_normalize_quality(q.get("name", "")): q for q in qualities}
    wanted = _normalize_quality(quality) if quality else next(iter(by_normalized))
    match = by_normalized.get(wanted)
    if match is None:
        available = ", ".join(q.get("name", "?") for q in qualities)
        raise QualityNotFoundError(
            f"Качество «{quality}» недоступно для этой записи. Доступные: {available}."
        )
    return match.get("name", wanted), match["fileUrl"]


async def download_recording_file(
    client,
    recording_key: str,
    target_path: str,
    quality: str | None = None,
    *,
    overwrite: bool = False,
) -> dict:
    """Скачивает файл записи потоково, без буферизации целиком в памяти (FR-7 AC-4)."""
    if client.auth_mode is AuthMode.API_KEY:
        resolved_quality = quality or DEFAULT_QUALITY
        url = build_download_url(recording_key, resolved_quality)
        scope = "application.recording.read"
    else:
        detail = await client.get_recording(recording_key)
        resolved_quality, url = _resolve_session_quality(detail.get("qualities") or [], quality)
        scope = None

    target = Path(target_path)
    if target.exists() and not overwrite:
        # Быстрый отказ до сетевого вызова — сохраняет прежнее поведение/сообщение.
        raise FileExistsError(
            f"Файл уже существует: {target}. Укажите overwrite=True для перезаписи."
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    async with client.stream("GET", url) as response:
        client.check_response(response, scope)
        # Security review SEC-001: `target.exists()` выше следует за симлинками и
        # возвращает False для «оборванного» симлинка (указывающего на
        # несуществующий путь) — наивный `target.open("wb")` в этом случае писал бы
        # СКВОЗЬ симлинк в произвольное место, куда указывает ссылка. Между
        # проверкой и записью есть и обычное TOCTOU-окно (сетевой вызов между ними).
        # `os.O_EXCL` с `os.O_CREAT` атомарно отказывает и на гонке, и на висящем
        # симлинке (POSIX). При `overwrite=True` поведение не меняется — перезапись
        # была осознанно запрошена вызывающим.
        flags = os.O_WRONLY | os.O_CREAT | (0 if overwrite else os.O_EXCL)
        try:
            fd = os.open(target, flags, 0o644)
        except FileExistsError as exc:
            raise FileExistsError(
                f"Файл уже существует: {target}. Укажите overwrite=True для перезаписи."
            ) from exc
        with os.fdopen(fd, "wb") as fh:
            async for chunk in response.aiter_bytes():
                fh.write(chunk)
                total += len(chunk)

    return {"path": str(target), "bytes": total, "quality": resolved_quality}
