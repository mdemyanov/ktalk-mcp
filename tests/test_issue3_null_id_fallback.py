"""Регресс issue #3 (`gh issue view 3 --repo mdemyanov/ktalk-cli`) — не входит в
ADR-023 (companion-спека, «Контекст»: «дефект возвращает существующее поведение,
не архитектурное решение»), покрытие не требует ни требования, ни `#### Scenario:`
капабилити-спеки, но красная линия QA-author («не покрывать только happy path»)
требует его закрыть отдельно от волны FR-41/NFR-17.

Дефект: `data.get("id", fallback)` возвращает `None`, когда ключ `"id"` ПРИСУТСТВУЕТ
со значением `null` — `dict.get(key, default)` подставляет `default` только при
ОТСУТСТВИИ ключа, не при falsy-значении. Два подтверждённых места:
- `formatters.py:126` (`format_recording`, карточка записи):
  `f"- **Ключ:** {data.get('id', data.get('key', 'N/A'))}"`
- `formatters.py:165` (`format_recordings_list`, список записей):
  `rec_id = rec.get("id", rec.get("key", "N/A"))`

Правильная форма уже применена соседями (`or`-цепочка, не `.get(key, default)`):
`registry.py:68` (`rec.get("id") or rec.get("key") or ""`), `enrichment.py:73`
(`record.get("id") or record.get("key") or ""`), `reconciliation.py:14`
(`r.get("id") or r.get("key")`) — тесты ниже проверяют ПОВЕДЕНИЕ (что печатается),
не требуют именно `or`-цепочки как реализации.

Отдельный файл, не расширение `test_formatters.py` (109 строк, самый большой файл
дерева тестов): регресс не по теме существующих классов `TestFormatRecording*` в
том файле (форматирование полей на ВАЛИДНЫХ данных), а по теме конкретно
null-vs-missing различия `dict.get` — иная ось тестирования, отдельный файл читается
как единица, не требует понимания остального `test_formatters.py`, чтобы понять
предмет регресса.

Красные по замыслу: воспроизведено вручную перед написанием этого файла —
`format_recording({"id": None, "key": "ABC-123", ...})` печатает буквальную строку
"None" (не воспроизводит текущий баг стаб не может, потому что баг уже есть в коде
сегодня, не отсутствующая функциональность) — падение на `assert`, не на импорте:
`format_recording`/`format_recordings_list` существуют уже сегодня.
"""

from __future__ import annotations


def _make_recording(**over) -> dict:
    base = {
        "id": None,
        "key": "ABC-123",
        "title": "Стендап",
        "createdDate": "2026-04-01T10:00:00Z",
        "createdBy": {"surname": "Иванов", "firstname": "Иван"},
        "duration": 600,
        "participantsCount": 0,
        "participants": [],
    }
    base.update(over)
    return base


# === Карточка записи (format_recording, formatters.py:126) =================================


def test_issue3_card_prints_key_when_id_is_explicit_null():
    from ktalk_cli.formatters import format_recording

    data = _make_recording(id=None, key="ABC-123")

    result = format_recording(data)

    assert "ABC-123" in result, (
        f"issue #3: `id: null` + непустой `key` должен печатать key, "
        f"получено:\n{result}"
    )
    assert "None" not in result, (
        f"issue #3: буквальная строка 'None' не должна попадать в вывод при "
        f"`id: null`, получено:\n{result}"
    )


def test_issue3_card_still_uses_id_when_id_is_a_real_non_null_value():
    """Регресс-guard в обратную сторону: фикс не должен начать ИГНОРИРОВАТЬ валидный
    `id`, когда он реально задан (не откатываться всегда на `key`)."""
    from ktalk_cli.formatters import format_recording

    data = _make_recording(id="REAL-ID-1", key="ABC-123")

    result = format_recording(data)

    assert "REAL-ID-1" in result, (
        f"валидный непустой `id` должен использоваться как есть, получено:\n{result}"
    )


def test_issue3_card_falls_back_to_na_when_both_id_and_key_are_null():
    """Граница: оба идентификатора отсутствуют/`null` -> явный `N/A` (или
    эквивалентный явный плейсхолдер), не `None` и не падение."""
    from ktalk_cli.formatters import format_recording

    data = _make_recording(id=None, key=None)

    result = format_recording(data)

    assert "None" not in result, (
        f"оба идентификатора отсутствуют — вывод не должен содержать буквальный "
        f"'None', получено:\n{result}"
    )


# === Список записей (format_recordings_list, formatters.py:165) ============================


def test_issue3_list_prints_key_when_id_is_explicit_null():
    from ktalk_cli.formatters import format_recordings_list

    data = {"recordings": [_make_recording(id=None, key="ABC-123")]}

    result = format_recordings_list(data)

    assert "ABC-123" in result, (
        f"issue #3 (список): `id: null` + непустой `key` должен печатать key, "
        f"получено:\n{result}"
    )
    # Строгая проверка: не просто "нет буквы N-o-n-e где-то в тексте" (могла бы
    # случайно совпасть с частью другого слова), а именно ячейка колонки ID —
    # ищем разделённое table-пайпами значение.
    id_cell_is_none = any(
        line.strip().startswith("| None ") for line in result.splitlines()
    )
    assert not id_cell_is_none, (
        f"issue #3 (список): ячейка колонки ID не должна быть буквальным 'None', "
        f"получено:\n{result}"
    )


def test_issue3_list_still_uses_id_when_id_is_a_real_non_null_value():
    from ktalk_cli.formatters import format_recordings_list

    data = {"recordings": [_make_recording(id="REAL-ID-2", key="ABC-123")]}

    result = format_recordings_list(data)

    assert "REAL-ID-2" in result, (
        f"валидный непустой `id` должен использоваться как есть в списке, "
        f"получено:\n{result}"
    )


def test_issue3_list_falls_back_to_na_when_both_id_and_key_are_null():
    from ktalk_cli.formatters import format_recordings_list

    data = {"recordings": [_make_recording(id=None, key=None)]}

    result = format_recordings_list(data)

    id_cell_is_none = any(
        line.strip().startswith("| None ") for line in result.splitlines()
    )
    assert not id_cell_is_none, (
        f"issue #3 (список): оба идентификатора отсутствуют — ячейка ID не должна "
        f"быть буквальным 'None', получено:\n{result}"
    )


def test_issue3_list_multiple_records_mixed_null_and_real_ids_not_confused():
    """Boundary: несколько записей одновременно, часть с `id: null`, часть с
    валидным `id` — фикс не должен путать записи местами и не должен ломаться на
    смешанном вводе (испорченный ввод одной записи не должен портить соседние)."""
    from ktalk_cli.formatters import format_recordings_list

    data = {
        "recordings": [
            _make_recording(id=None, key="KEY-ONE", title="Первая"),
            _make_recording(id="REAL-TWO", key="KEY-TWO", title="Вторая"),
            _make_recording(id=None, key=None, title="Третья"),
        ]
    }

    result = format_recordings_list(data)

    assert "KEY-ONE" in result
    assert "REAL-TWO" in result
    assert "Первая" in result
    assert "Вторая" in result
    assert "Третья" in result
