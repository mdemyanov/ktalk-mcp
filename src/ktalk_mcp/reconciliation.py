"""Сверка идентификаторов перед первым api-key sync (FR-15).

Внутренний контур отдаёт только `id`, интеграторский — `id` и `key`; совпадают ли
значения между контурами не проверено эмпирически (ключ выдан без нужных scope,
зонд Ф-11/Ф-14). Если разойдутся, первый `ktalk sync` под ключом задвоит реестр
(~1316 записей) — обязателен `ktalk sync --dry-run` до первого боевого прогона.
"""

from __future__ import annotations


def recording_ids(recordings: list[dict]) -> list[str]:
    """Извлекает id (fallback на key, как `registry.recording_fields_from_api`)."""
    return [rid for r in recordings if (rid := r.get("id") or r.get("key"))]


def compare_id_sets(fetched: list[str], existing: list[str]) -> dict:
    """Сравнивает множество id из API-ответа с уже существующими строками реестра."""
    fetched_set = set(fetched)
    existing_set = set(existing)
    return {
        "only_in_fetched": fetched_set - existing_set,
        "only_in_existing": existing_set - fetched_set,
        "common": fetched_set & existing_set,
    }


def dry_run_report(fetched_ids: list[str], existing_ids: list[str]) -> dict:
    """Отчёт для `ktalk sync --dry-run` (FR-15 AC-2/AC-3).

    `ok=True` — можно продолжать обычную синхронизацию (полное совпадение либо
    реестр ещё пуст, сверивать не с чем). `ok=False` — расхождение идентификаторов,
    боевой sync заблокирован до осознанного решения оператора (используется как
    exit-код CLI, по аналогии с уже принятым в проекте `migrate --dry-run`).
    """
    if not existing_ids:
        return {
            "ok": True,
            "message": (
                "Реестр пуст — нет данных для сравнения. Сверка id будет возможна "
                "после первого сохранённого sync."
            ),
            "only_in_fetched": sorted(set(fetched_ids)),
            "only_in_existing": [],
        }
    comparison = compare_id_sets(fetched_ids, existing_ids)
    mismatch = bool(comparison["only_in_fetched"] or comparison["only_in_existing"])
    message = (
        "Обнаружено расхождение идентификаторов — боевой sync заблокирован до "
        "осознанного решения оператора."
        if mismatch
        else "Идентификаторы полностью совпадают — можно продолжать обычную синхронизацию."
    )
    return {
        "ok": not mismatch,
        "message": message,
        "only_in_fetched": sorted(comparison["only_in_fetched"]),
        "only_in_existing": sorted(comparison["only_in_existing"]),
    }
