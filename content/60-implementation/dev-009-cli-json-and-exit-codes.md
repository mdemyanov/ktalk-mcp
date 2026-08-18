---
title: "DEV-009: `--json` и коды возврата на трёх командах CLI (волна 5)"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-009: `--json` и коды возврата на трёх командах CLI (волна 5)

Находка SA-006/QA-005/PM (независимо, трижды): `create-meeting-preview`,
`cancel-meeting-preview`, `search-contacts` не регистрировали `--json`; `search-contacts`
маскировал отказ под тем же `rc == 1`, что и «0 найдено». Оба пункта закрыты в этой задаче.

## `--json` — что добавлено, что нет

`--json` добавлен только на `*-preview`, не на `*-confirm`. `*-confirm` — TTY-only
(NFR-22/NFR-23), программно не вызывается промт-слоем; машиночитаемый вывод там не нужен, и
раньше не запрашивался ни одним артефактом. `argparse` на `*-confirm --json` по-прежнему
`SystemExit(2)` — зафиксировано тестом
`test_ac_34_1c_cancel_meeting_commands_reject_json_flag` (для `-confirm`-ветки; ветка `-preview`
того же теста перевёрнута — см. ниже).

| Команда | JSON-форма (`--json`) | Без `--json` |
|---|---|---|
| `create-meeting-preview` | `{"body": {...}}` | markdown (`format_meeting_preview`), без изменений |
| `cancel-meeting-preview` | `{"payload": {"operation": "cancel_meeting", "id", "reason"}}` | markdown (`format_cancel_preview`), без изменений |
| `search-contacts` | `{"query": "...", "candidates": [...]}` | markdown (`format_search_contacts`), без изменений |

**`confirmation_id` не входит ни в один JSON.** По ADR-015 он не переживает границу процессов —
`*-confirm` не принимает `--id`/`--confirmation-id` от предыдущего `preview`, строит своё
подтверждение заново из тех же флагов. Класть значение, которое выглядит как основание для
подтверждения, но им не является, — источник ошибки промт-слоя (он мог бы попытаться передать
его дальше). Markdown-путь по-прежнему печатает `confirmation_id` с пометкой «справочно, не
межпроцессный» (`format_meeting_preview`/`format_cancel_preview`, без изменений) — там это не
проблема, оператор читает текст, не парсит поле программно.

Полная команда `*-confirm` (с теми же флагами) в JSON не кладётся — это не поле модели, а текст,
который промт-слой уже способен собрать сам (он помнит собственные аргументы вызова
`*-preview`); "не выдумывать поле, которого нет в модели" — буквально это.

Инвариант «ноль сетевых вызовов у `*-preview`» не затронут — оба пути (`--json`/markdown) идут
через один и тот же `PreviewService`/`CancelPreviewService`, JSON-ветка добавлена после вызова
сервиса, не меняет его. Покрыто тестами:
`test_dev009_cli_create_meeting_preview_json_zero_network_no_confirmation_id`
(`tests/test_cli_meeting.py`) и
`test_dev009_cancel_meeting_preview_json_zero_network_no_confirmation_id`
(`tests/test_cli_meetings_surface.py`).

## Коды возврата `search-contacts`

Было: `0` — один кандидат, `1` — и «0 найдено», и сетевой/авторизационный отказ (различимо
только каналом). Стало:

| Код | Значение |
|---|---|
| `0` | найден хотя бы один кандидат |
| `1` | сетевая/авторизационная ошибка (`Ошибка:` на stderr) — без изменений |
| `2` | 0 кандидатов, отказа не было (`Ничего не найдено по запросу «…»` на stdout) |

Различение по каналу (stdout vs stderr) сохранено как независимая, более старая гарантия —
код и канал теперь совпадающе избыточны, не единственный способ различить.

**Совместимость.** Единственный существующий потребитель кода возврата —
`tests/test_search_contacts.py::test_ac_10_1_zero_matches_cli_message_names_the_query_and_nonzero_exit`
— проверяет `rc != 0`, не конкретное значение; `2` его не ломает. MCP-инструмент
`ktalk_search_contacts` (`tools_contacts.py`) код возврата CLI не использует вовсе — отдельный
процесс, отдаёт текст через `render_tool_output`. В `content/`/промт-слое пакета `ktalk-mcp`
жёсткой зависимости от значения `1` на «0 найдено» не нашлось (грепом по `content/`, `tests/`,
`scripts/`) — единственные места, кодировавшие именно это ожидание, были два стаба QA-005 (ниже).

## Судьба перевёрнутых стабов QA-005

- **`test_ac_34_1c_cancel_meeting_commands_reject_json_flag`** — было: оба parse_args
  (`-preview`/`-confirm`) должны падать `SystemExit` на `--json`. Стало: `-preview` принимает
  `--json` (`args.json is True`), `-confirm` по-прежнему падает `SystemExit(2)`. Имя теста
  сохранено (трассировка из at-design), тело переписано, не удалено.
- **`test_search_contacts_rejects_json_flag`** — было: `SystemExit` на `--query x --json`.
  Стало: `--json` принят, `args.json is True`. Имя сохранено.
- **`test_ac_35_3_zero_matches_vs_network_error_share_exit_code_distinguishable_only_by_channel`**
  переименован в
  `test_ac_35_3_zero_matches_vs_network_error_are_distinguishable_by_exit_code_and_channel` —
  старое имя утверждало «различимо только каналом», это стало не так (различимо и кодом), имя
  таким же составом слов сохранить не удалось без лжи в самом имени теста; сценарий (AC-35-3)
  тот же, реализован полностью (было `assert False`-заглушка QA-author, дописан Dev).

Обе первые правки — точечный переворот, не молчаливое удаление: старое ожидание было
характеризационным тестом текущего (на момент QA-005) поведения, at-design прямо пометил его
`red (stub)`/«известное расхождение», не постоянным контрактом.

## `content/40-architecture/ktalk-plugin-meetings-spec.md` (SA-006)

Точечно поправлены строки, описывавшие отсутствие `--json` (было: «нет флага» для трёх команд) и
единый код `1` `search-contacts` (карта FR-33/FR-34/FR-35, `compat.json`, «Edge cases»). Спека не
переписана целиком. Текст промта (`SKILL.md`, дерево `ktalk-plugin`), написанный под старое
поведение (markdown-only парсинг этих трёх команд), не тронут — другой репозиторий, вне
периметра; его собственная ревизия под новый `--json`/коды возврата — отдельная задача в дереве
плагина.

## Требования (`content/30-requirements/ktalk-plugin-meetings.md`)

AC-35-3 и NFR-20 сформулированы через «ненулевой код возврата»/«CLI приоритетный интерфейс» без
привязки к конкретному значению `1` — правки не потребовалось, таблица трассировки не менялась.

## Итог прогонов

`uv run pytest` — 441 passed, 15 failed. Все 15 — преэкзистующие красные стабы QA-005 вне
периметра этой задачи (`list-calendar`/`get-room` детали, `cancel-meeting-*` позитивные TTY/pty
сценарии, `AC-37-1` passthrough, `AC-38-1` registry-free) — их чинит не эта задача.
`uv run ruff check src/ tests/ --no-cache` — чисто. `bash scripts/check.sh --fast` —
`Errors: 0` (см. коммит).

## Незакрытое

- 15 стабов QA-005 вне периметра `--json`/кодов возврата остаются красными — не задача DEV-009.
- Ревизия текста промта `SKILL.md` (дерево `ktalk-plugin`) под новый `--json`/коды возврата — вне
  периметра, другой репозиторий; спека SA-006 явно передаёт это отдельной задаче.
- Номер релиза пакета `ktalk_mcp`/правка `compat.json` плагина под новые флаги — вопрос выпуска,
  не решён здесь (версия в `pyproject.toml` не менялась).
