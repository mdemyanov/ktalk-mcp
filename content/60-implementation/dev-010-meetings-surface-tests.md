---
title: "DEV-010: 15 стабов CLI-поверхности встреч закрыты — все без правки src/ (волна 5)"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-010: 15 стабов CLI-поверхности встреч закрыты — все без правки src/ (волна 5)

Продолжение [DEV-009](dev-009-cli-json-and-exit-codes.md). Задача — закрыть 15 оставшихся
`assert False` стабов QA-005 в `tests/test_cli_meetings_surface.py` (три из восемнадцати уже
закрыты DEV-009). AT-design —
[at-design-ktalk-plugin-meetings.md](../40-architecture/at-design-ktalk-plugin-meetings.md).

## Итог

**15/15 стабов позеленели без единой правки `src/`.** Каждый стаб описывал факт, который CLI
уже реализовывал корректно (`cli_meeting.py`, `cli_meetings_read.py`, `cli_contacts.py`,
`cli.py::_REGISTRY_FREE_COMMANDS` — все написаны раньше, DEV-002/DEV-009), но не был снят
регрессионным тестом на CLI-уровне до этой волны. Находок кода нет. Единственная находка —
техническая (мок ADR-007 контрольного GET), не поведенческая, см. ниже.

`uv run pytest`: `15 failed, 441 passed` → `456 passed`.
`bash scripts/check.sh --fast`: `Errors: 0` (было и осталось; 3 warning — заморозка
`registry.py`/`_drift_check.py`/`validate-profile.py`, грандфазер, не по этой задаче).

## По каждому стабу — что доказано

| Тест | AC | Что подтвердил (без правки кода) |
|---|---|---|
| `test_ac_32_1b_...no_silent_default` | AC-32-1b | `--start`/`--end` оба `required=True` в argparse; позитивная ветка (оба переданы) не падает |
| `test_ac_32_2_...incomplete_segments_verbatim` | AC-32-2 | Сегмент из 100 элементов (потолок `_PAGE_SIZE`) даёт `incomplete_segments` дословно в `--json`-выводе, не булев флаг |
| `test_ac_32_3_...distinguishable_by_exit_code_and_channel` | AC-32-3 | Пустой календарь → `rc==0`, валидный JSON, stderr пуст; сетевой отказ → `rc==1`, `Ошибка:` на stderr, stdout пуст |
| `test_list_calendar_malformed_start_date_fails_closed_not_traceback` | — (испорченный ввод) | `--start 2026-13-45` → `ValueError` из `date.fromisoformat` пойман общим `except Exception` в `_run`, не утекает traceback'ом |
| `test_ac_34_1b_...echoes_id_and_reason` | AC-34-1b | `cancel-meeting-preview` — ноль сетевых запросов, `id`/`reason` эхо в markdown-выводе дословно |
| `test_ac_34_2b_...id_is_required_on_both_subcommands` | AC-34-2b | `--id` `required=True` на обеих подкомандах; позитивная ветка проверена |
| `test_nfr23_cancel_meeting_confirm_refuses_without_tty` | NFR-23-b | Тот же TTY-барьер, что `create-meeting-confirm` (симметричный код `cmd_cancel_meeting_confirm`), под pytest `rc!=0`, ноль сети |
| `test_nfr22_...network_failure_no_retry_exactly_one_post` | NFR-22 (cancel) | Реальный `pty`, `ConnectError` на POST → ровно один POST среди запросов (второй запрос — контрольный GET ADR-007, не повтор POST); текст называет «исход неизвестен» и `ktalk_list_calendar` |
| `test_get_room_has_no_availability_check_flag` | AC-36-2 | `get-room` не регистрирует `check`/`available`/`exists`/`occupied` — структурная невозможность проверки занятости имени |
| `test_get_room_json_flag_prints_valid_json_room_payload` | — (форма `--json`) | `--json` — валидный JSON, имя комнаты присутствует в теле |
| `test_get_room_error_goes_to_stderr_not_stdout` | — (канал ошибки) | Сетевой отказ → `rc==1`, `Ошибка:` на stderr, stdout пуст |
| `test_ac_37_1_...[list-calendar\|get-room\|search-contacts]` | AC-37-1 | `RuntimeError("уникальный текст")` доходит до вывода дословно (после `redact_secrets`, не искажён), не заменён на общую фразу |
| `test_ac_38_1_...registry_free` | AC-38-1 | `meetings_commands` и `escalation_targets` (`auth-status`, `config`) — подмножество `_REGISTRY_FREE_COMMANDS`, эскалация достижима из того же процесса без реестра |

## Единственная техническая деталь, не находка

`list-calendar`/`get-room` на `ConnectError` вызывают `diagnose_undocumented_failure`
(ADR-007) — тот делает контрольный `GET /api/recordings?...top=1` тем же клиентом. Без мока
этого второго запроса `pytest_httpx` падает на `assert_all_requests_were_expected`
(«unexpected request»), не по вине CLI. Тесты `test_ac_32_3_...`/`test_get_room_error_...`
регистрируют вторую `httpx_mock.add_response` для этого контрольного GET — тот же приём, что
уже применён в `test_cli_meeting.py` (DEV-007/DEV-008, `_DEV008_MATRIX`). `search-contacts`
этой ловушки не имеет — `contacts.py::search_contacts` не вызывает `diagnose_undocumented_failure`
вовсе (уже было так до этой задачи, не тронуто).

## Незакрытое

Нет. Ноль failed в `uv run pytest`, `Errors: 0` в `check.sh --fast`. Находка №2 из
at-design «Находки о существующем коде» (`search-contacts` делит `rc==1` между «0 найдено» и
отказом) закрыта раньше DEV-009 — эта задача её не переоткрывает.
