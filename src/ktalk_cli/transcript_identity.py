"""Сверка идентичности транскрипта (NFR-17, issue #5, ADR-023 §1 + companion-спека
«Компоненты — NFR-17»): сверяет состав спикеров транскрипта с составом участников
записи того же `recording_id` через независимый вызов `get_recording` — обнаруживает
подмену транскрипта под конкуренцией (RES-006), не связанную с валидностью самого
запроса.

Чистые функции без сети и побочных эффектов — сеть (`client.get_recording`) и исход
`not_checked` (отказ вызова) живут в оркестрации `cmd_get_transcript`
(`cli_content.py`), не здесь.
"""

from __future__ import annotations


def _identity_key(user_ref: dict | None) -> str | None:
    """Идентификатор пользователя: `userInfo.key` или `.login` (именованный),
    `anonymousId` или `anonymousName` (аноним), `None` если ссылка пуста — та же
    приоритетность, что `_format_user_name(with_id=True)` в `formatters.py`, но
    возвращает сырой токен для сравнения, не строку для вывода."""
    if not user_ref:
        return None
    if user_ref.get("isAnonymous"):
        return user_ref.get("anonymousId") or user_ref.get("anonymousName")
    user_info = user_ref.get("userInfo")
    if not user_info:
        return None
    return user_info.get("key") or user_info.get("login")


def speaker_identities(transcript: dict) -> set[str]:
    """Состав спикеров транскрипта: обход `tracks[]`, `speaker`, при отсутствии —
    `diarizedSpeaker`; треки без обоих не подмешивают `None` в результат."""
    identities: set[str] = set()
    for track in transcript.get("tracks") or []:
        speaker_ref = track.get("speaker") or track.get("diarizedSpeaker")
        key = _identity_key(speaker_ref)
        if key is not None:
            identities.add(key)
    return identities


def participant_identities(recording: dict) -> set[str]:
    """Состав участников записи: обход `recording["participants"]` (`TalkUserRef[]`)."""
    identities: set[str] = set()
    for participant in recording.get("participants") or []:
        key = _identity_key(participant)
        if key is not None:
            identities.add(key)
    return identities


def check_identity(transcript: dict, recording: dict) -> dict:
    """Четыре исхода (`not_checked` не формируется здесь — исход уровня оркестрации,
    когда сам вызов `get_recording` падает):
    - `inconclusive` — любое множество пусто, сравнивать не с чем;
    - `match` — пересечение непусто;
    - `mismatch` — оба множества непусты и не пересекаются (сигнатура RES-006)."""
    transcript_speakers = speaker_identities(transcript)
    recording_participants = participant_identities(recording)

    if not transcript_speakers or not recording_participants:
        return {"result": "inconclusive"}

    result = "match" if transcript_speakers & recording_participants else "mismatch"
    return {
        "result": result,
        "transcript_speakers": sorted(transcript_speakers),
        "recording_participants": sorted(recording_participants),
    }
