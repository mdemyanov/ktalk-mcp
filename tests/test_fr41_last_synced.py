"""AT-design: FR-41 — наблюдаемость момента последней синхронизации реестра
(`content/40-architecture/at-design-adr023-open-issues.md`, раздел «FR-41»).

Покрывает 3 AC FR-41 из `content/30-requirements/registry-sync-observability.md`
(BA-014) через `#### Scenario:` капабилити-спеки `openspec/specs/registry-sync-window/
spec.md`, раздел «The last sync moment is exposed by a reading command, not only
recorded internally»:
- FR41-AC1 — `dashboard --json` после `sync` отдаёт то же значение, что записал `sync`.
- FR41-AC2 — свежий реестр без единого `sync` -> ключ `last_synced` присутствует,
  значение явный `null`, не пропуск поля.
- FR41-AC3 — серия чтений `dashboard --json` не меняет статусы записей реестра.

Решение SA (ADR-023 §2): `last_synced` — поле ВЕРХНЕГО уровня JSON-ответа `dashboard
--json` (не внутри `stats` — тот однородный `{статус: count}`), значение
`Registry.get_meta("last_synced")` как есть, формат ISO-8601 `YYYY-MM-DD` (точность
до дня, `cli_sync.py:126` не меняется).

Красные по замыслу: `_cmd_dashboard` (`cli.py:210`) сегодня печатает только `{"new":
new, "stats": stats}` — поля `last_synced` в ответе нет вовсе. Стабы падают на
`assert`/`KeyError` через `out["last_synced"]`, не на импорте — модуль и функция уже
существуют, меняется состав их JSON-ответа. Реализация — DEV-019 (после этого файла).

Классы обязательного покрытия (контракт QA-author):
- **Испорченный/опечатанный ввод** — N/A для FR-41: `dashboard --json` не принимает от
  пользователя ни идентификатор записи, ни сегмент URL, ни поисковый запрос — команда
  без позиционных аргументов, читает весь реестр целиком. Испорченный `--db` путь —
  предмет других файлов (не FR-41 конкретно), не дублируется здесь.
- **Замаскированный отказ** — FR41-AC2 и есть этот класс дословно: `null` должен быть
  ЯВНЫМ значением ключа, не тихим пропуском поля (что было бы неотличимо от дефекта
  сериализации) и не тихой заменой на другое значение по умолчанию. Отдельный
  усиленный тест ниже проверяет это конкретно на уровне текста ответа, не только на
  уровне распарсенного словаря.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def _seed_mixed_statuses(db: Path) -> None:
    from ktalk_cli.registry import Registry

    today = date.today().isoformat()
    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "a", "name": "Standup", "date": today}, now=today
        )
        reg.upsert_recording(
            {"recording_id": "b", "name": "1-1", "date": today}, now=today
        )
        reg.set_status("b", "done")
        reg.upsert_recording(
            {"recording_id": "c", "name": "Retro", "date": today}, now=today
        )
        reg.set_status("c", "partial")
        reg.upsert_recording(
            {"recording_id": "d", "name": "Old", "date": today}, now=today
        )
        reg.set_status("d", "skipped")


def _run_sync(db: Path, monkeypatch, httpx_mock, capsys) -> None:
    """Реальный `ktalk sync` через CLI (не прямой `reg.set_meta`) — FR41-AC1 сверяет
    ответ `dashboard --json` со значением, которое сама команда `sync` записала,
    воспроизводя путь AC дословно: "сравнение значения из --json-ответа со значением
    Registry.get_meta("last_synced") после sync". Явно вычищает буфер `capsys` после
    себя — иначе собственный JSON-вывод `sync` конкатенируется с последующим выводом
    `dashboard --json` в одном захвате и ломает `json.loads` `Extra data`-ошибкой,
    маскируя реальную причину падения теста своей собственной (control-flow
    ошибка теста, не отсутствующее поведение под тестом)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "tok-fr41")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    httpx_mock.add_response(json={"recordings": []})  # одна пустая страница -> sync done

    from ktalk_cli.cli import main

    rc = main(["--db", str(db), "sync", "--days", "7", "--json"])
    assert rc == 0, "предпосылка теста: sync должен пройти успешно"
    capsys.readouterr()  # вычищает собственный вывод sync перед вызовами dashboard


# === FR41-AC1: значение после sync совпадает с записанным ==================================


def test_fr41_ac1_dashboard_json_last_synced_matches_registry_get_meta_after_sync(
    tmp_path, monkeypatch, httpx_mock, capsys
):
    from ktalk_cli.cli import main
    from ktalk_cli.registry import Registry

    db = tmp_path / "r.db"
    _run_sync(db, monkeypatch, httpx_mock, capsys)

    with Registry(db) as reg:
        recorded = reg.get_meta("last_synced")
    assert recorded is not None, "предпосылка: sync должен был записать last_synced"

    rc = main(["--db", str(db), "dashboard", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "last_synced" in out, (
        "FR41-AC1: `dashboard --json` обязан отдавать `last_synced` верхнего уровня "
        f"после хотя бы одной синхронизации, получен ответ без ключа: {out}"
    )
    assert out["last_synced"] == recorded, (
        "FR41-AC1: значение в ответе должно совпадать со значением, которое записала "
        f"сама sync — записано {recorded!r}, в ответе {out.get('last_synced')!r}"
    )


def test_fr41_ac1_last_synced_is_top_level_not_nested_in_stats(
    tmp_path, monkeypatch, httpx_mock, capsys
):
    """Решение SA (ADR-023 §2): поле верхнего уровня, НЕ внутри `stats` (тот
    однородный `{статус: count}` — чужеродное поле ломает эту форму для потребителя,
    итерирующего по нему)."""
    from ktalk_cli.cli import main

    db = tmp_path / "r.db"
    _run_sync(db, monkeypatch, httpx_mock, capsys)

    rc = main(["--db", str(db), "dashboard", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "last_synced" not in out.get("stats", {}), (
        "FR41-AC1 (форма ответа, ADR-023 §2): `last_synced` не должен жить внутри "
        f"`stats` — обнаружен там: {out.get('stats')}"
    )


# === FR41-AC2: свежий реестр без sync -> явный null, не пропуск ключа ======================


def test_fr41_ac2_never_synced_registry_reports_explicit_null_not_missing_key(
    tmp_path, capsys
):
    from ktalk_cli.cli import main

    db = tmp_path / "r.db"  # реестр создаётся с нуля, sync ни разу не вызывался

    rc = main(["--db", str(db), "dashboard", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "last_synced" in out, (
        "FR41-AC2: ключ `last_synced` обязан присутствовать в ответе даже без единой "
        f"синхронизации — тихий пропуск поля запрещён требованием, получен ответ: {out}"
    )
    assert out["last_synced"] is None, (
        "FR41-AC2: без единой синхронизации значение обязано быть явным `null`, "
        f"получено {out['last_synced']!r}"
    )


def test_fr41_ac2_masked_failure_null_is_literal_json_null_not_omitted_field(
    tmp_path, capsys
):
    """Класс «замаскированный отказ»: наивная реализация могла бы тихо ОПУСТИТЬ ключ,
    когда `get_meta` возвращает `None` (обычный паттерн `if value: payload[...] = ...`)
    — снаружи это неотличимо от дефекта сериализации, тот самый риск, который AC2
    называет прямым текстом. Проверяем на уровне сырого текста stdout, не только
    распарсенного словаря — исключает случай, где парсер молча подставляет `None` за
    отсутствующий ключ и маскирует разницу между "ключа нет" и "ключ есть, там null"."""
    from ktalk_cli.cli import main

    db = tmp_path / "r.db"

    rc = main(["--db", str(db), "dashboard", "--json"])
    raw = capsys.readouterr().out

    assert rc == 0
    assert '"last_synced"' in raw, (
        "FR41-AC2 (замаскированный отказ): литерал ключа `\"last_synced\"` обязан "
        f"присутствовать в сыром JSON-тексте ответа, получено: {raw!r}"
    )


# === FR41-AC3: серия чтений не мутирует статусы записей =====================================


def test_fr41_ac3_repeated_dashboard_json_calls_do_not_change_any_recording_status(
    tmp_path, monkeypatch, httpx_mock, capsys
):
    from ktalk_cli.cli import main
    from ktalk_cli.registry import Registry

    db = tmp_path / "r.db"
    _run_sync(db, monkeypatch, httpx_mock, capsys)  # last_synced присутствует, не только пустой реестр
    _seed_mixed_statuses(db)

    with Registry(db) as reg:
        before = {r["recording_id"]: r["status"] for r in reg.list_recordings()}

    for _ in range(5):
        rc = main(["--db", str(db), "dashboard", "--json"])
        capsys.readouterr()
        assert rc == 0

    with Registry(db) as reg:
        after = {r["recording_id"]: r["status"] for r in reg.list_recordings()}

    assert after == before, (
        "FR41-AC3: пятикратный вызов `dashboard --json` (в т.ч. читающего "
        f"`last_synced`) не должен менять статусы записей — было {before}, стало {after}"
    )


def test_fr41_ac3_repeated_dashboard_json_calls_do_not_change_sync_meta(
    tmp_path, monkeypatch, httpx_mock, capsys
):
    """Узкая версия AC3: сам `last_synced`/`sync_count` в `meta` — не только статусы
    записей — не должны сдвигаться от чтения (не только не регрессировать в другой
    статус, но и не «обновляться» будто чтение — это ползучий sync)."""
    from ktalk_cli.cli import main
    from ktalk_cli.registry import Registry

    db = tmp_path / "r.db"
    _run_sync(db, monkeypatch, httpx_mock, capsys)

    with Registry(db) as reg:
        synced_before = reg.get_meta("last_synced")
        count_before = reg.get_meta("sync_count")

    for _ in range(3):
        main(["--db", str(db), "dashboard", "--json"])
        capsys.readouterr()

    with Registry(db) as reg:
        synced_after = reg.get_meta("last_synced")
        count_after = reg.get_meta("sync_count")

    assert synced_after == synced_before
    assert count_after == count_before, (
        "FR41-AC3: чтение `dashboard --json` не должно инкрементировать `sync_count` "
        f"— было {count_before}, стало {count_after}"
    )
