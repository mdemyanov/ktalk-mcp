---
title: "DEV-002 (волна 3, первая половина): сверка CLI/MCP и закрытие пробела"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-002 (волна 3, первая половина): сверка CLI/MCP и закрытие пробела

[ADR-012 §2а](../00-project/adr/ADR-012-plugin-boundary.md#2а-приоритетный-интерфейс-контура--cli-не-mcp)
называет полноту покрытия CLI-командами непроверенной: «сегодня 13 MCP-инструментов против
набора подкоманд `ktalk`, и соответствие не сверялось». Эта задача — сверка и закрытие
пробела новыми подкомандами (не возврат к MCP). Депараметризация промтов skill/agent
(вторая половина DEV-002 постановки волны 3) — отдельная задача в репозитории плагина,
здесь не выполняется.

## Матрица покрытия

Фактически MCP-инструментов **15**, не 13 — расхождение с числом в ADR-012: `tools_contacts.py`
(`ktalk_search_contacts`, ADR-010) и `tools_meeting_cancel.py` (`ktalk_preview_cancel_meeting`,
ADR-011) добавлены после первой редакции ADR-012 и не учтены в её тексте. Число в ADR не
правлю — статья не моя (SA), фиксирую факт здесь.

| MCP-инструмент | Модуль | Вердикт до задачи | Подкоманда `ktalk` после задачи |
|---|---|---|---|
| `ktalk_list_recordings` | `tools_recordings.py` | не покрыт | `list-recordings` |
| `ktalk_get_recording` | `tools_recordings.py` | не покрыт | `get-recording <key>` |
| `ktalk_get_transcript` | `tools_recordings.py` | не покрыт | `get-transcript <key>` |
| `ktalk_get_summary` | `tools_recordings.py` | не покрыт | `get-summary <key>` |
| `ktalk_get_summary_by_type` | `tools_recordings.py` | не покрыт | `get-summary-type <key> --type` |
| `ktalk_get_participants` | `tools_recordings.py` | не покрыт | `get-participants <key>` |
| `ktalk_download_recording` | `tools_recordings.py` | не покрыт | `download-recording <key> --target` |
| `ktalk_list_archive` | `tools_meetings.py` | не покрыт | `list-archive --from --to` |
| `ktalk_get_chat_messages` | `tools_meetings.py` | не покрыт | `get-chat-messages` |
| `ktalk_list_calendar` | `tools_meetings.py` | не покрыт | `list-calendar --start --end` |
| `ktalk_get_room` | `tools_rooms.py` | не покрыт | `get-room <name>` |
| `ktalk_preview_meeting` | `tools_scheduling.py` | покрыт полностью | `create-meeting-preview` (уже был) |
| `ktalk_preview_cancel_meeting` | `tools_meeting_cancel.py` | покрыт полностью | `cancel-meeting-preview` (уже был) |
| `ktalk_search_contacts` | `tools_contacts.py` | покрыт полностью | `search-contacts --query` (уже был) |
| `ktalk_auth_status` | `server.py` | покрыт полностью | `auth-status` (уже был) |

До задачи: 4/15 покрыты полностью, 11/15 не покрыты вовсе (весь читающий контур —
записи/архив/чат/календарь/комната). Вердикт не подгонялся: ни один инструмент не попал в
категорию «частично» — по каждому либо был точный CLI-эквивалент (мутации/preview/статус),
либо не было вообще ничего (чтение контента). После задачи — 15/15.

## Реализация 11 новых подкоманд

Два новых модуля, по образцу уже существующего разделения (`cli_meeting.py`,
`cli_contacts.py`, `cli_sync.py` — каждый гейт C13 не даёт разрастись одному файлу):

- `cli_content.py` — `list-recordings`, `get-recording`, `get-transcript`, `get-summary`,
  `get-summary-type`, `get-participants`, `download-recording` (сущность «Запись», зеркало
  `tools_recordings.py`).
- `cli_meetings_read.py` — `list-archive`, `get-chat-messages`, `list-calendar`, `get-room`
  (зеркало `tools_meetings.py`/`tools_rooms.py`).

Все 11 — в `_REGISTRY_FREE_COMMANDS`: читают только сеть, SQLite не открывают (симметрично
`search-contacts`/`auth-status`).

**Общий слой, не дублирование.** Обе обёртки (MCP tool и CLI-команда) вызывают один и тот же
`KTalkClient`-метод и один и тот же форматтер (`render_tool_output`, `format_recordings_list`
и т.д.) — задача явно запрещала копировать логику MCP-инструментов внутрь CLI. Единственное
место, где логика раньше была только внутри MCP-обёртки (не общей), — чанкинг транскрипта
(`ktalk_get_transcript`: auto/paged-режим, чанк по границе реплики). Вынес в
`formatters.render_transcript_output(data, fmt, chunk, chunk_size)`; `tools_recordings.py`
теперь тоже вызывает его — было дословное дублирование внутри тела MCP-инструмента, стало
общая функция, вызываемая из двух обёрток. Рефакторинг проверен полным прогоном (405 тестов
до задачи, все зелёные и после переноса, без изменения поведения).

`--json` → `render_tool_output(..., "raw", ...)` = `json.dumps(...)`, валидный JSON в stdout;
без флага — markdown-форматтер, тот же что у MCP. Ошибки — генерический `except Exception`
(симметрично `cmd_search_contacts`), текст через `redact_secrets`, печать в stderr, код 1.

## Не покрыто этой задачей / осознанные пределы

- **Мутирующих команд не добавлено.** `ktalk_preview_meeting`/`ktalk_preview_cancel_meeting`
  и так CLI-first (создание/отмена — только `create-meeting-confirm`/`cancel-meeting-confirm`
  за TTY-барьером, ADR-005). Задача не расширяла контракт подтверждения.
- **`ktalk_get_room` (FR-17) несёт побочный эффект** (ADR-006: чтение новым именем создаёт
  комнату) — CLI-хелп `get-room` называет это явно тем же текстом, что и MCP-докстрока, не
  смягчает формулировку ради краткости справки.
- **`download-recording`** без `--overwrite` — паритет с MCP-инструментом (там тоже нет флага
  перезаписи, `download_recording_file` по умолчанию отказывает на существующем файле).
  Расширение сверх паритета не входило в объём задачи.
- Депараметризация промтов skill/agent, вызывающих новые подкоманды из навыков плагина, —
  вне этого репозитория (ADR-012 §4: плагин живёт отдельно), не тестируется этим `pytest`.

## QA-стабы

Стабов QA-author на эту задачу нет — это разбор пробела ADR-012 §2а, не мейнлайн-фича с
именованными `Scenario:` в требовании. TDD выполнен по fallback-режиму (`nauta:dev` skill):
`tests/test_cli_content.py` написан до реализации (red), затем `cli_content.py`/
`cli_meetings_read.py` (green). 15 тестов: регистрация всех 11 подкоманд в
`_REGISTRY_FREE_COMMANDS` и в парсере, по одному-два happy-path/error-path теста на команду
(валидный JSON на stdout, `--json`-умолчание для `get-transcript`/markdown-текст без флага,
ошибка сети → stderr + rc≠0, `get-chat-messages` без обоих ключей → падение до сети).

## Итог прогонов

- `uv run pytest` — 420 passed, 0 failed (405 было до задачи + 15 новых).
- `uv run ruff check .` — 36 существующих ошибок в `scripts/validate-profile.py` (грандфазер,
  payload плагина nauta, не трогается); файлы задачи (`cli.py`, `cli_content.py`,
  `cli_meetings_read.py`, `formatters.py`, `tools_recordings.py`, `tests/test_cli_content.py`)
  — чисты отдельным прогоном.
- `bash scripts/check.sh --fast` — `Errors: 0`, 3 существующих грандфазер-warning
  (`registry.py` 562/562, два скрипта nauta) — не блокируют, не новые. `cli.py` вырос до 354
  строк (порог C13 — 350), но проходит молча: контейнер из мелких обёрток (самая длинная
  декларация < 100 строк, как и раньше проходил `formatters.py` на 370).
- `wc -l src/ktalk_mcp/registry.py` — 562 (без изменений, грандфазер не тронут).

## Связанные статьи

- [ADR-012: границы плагина ktalk](../00-project/adr/ADR-012-plugin-boundary.md) — §2а,
  источник задачи.
- [DEV-001 (волна 3): конфиг хозяина и центральное хранилище](dev-001-host-config-and-store.md)
  — предыдущий шаг волны, конфиг-слой (`host_config.py`, `store.py`), не тронут этой задачей.
