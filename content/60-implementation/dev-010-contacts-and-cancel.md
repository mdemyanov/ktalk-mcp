---
title: "DEV-010: резолюция контактов и отмена встречи"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# DEV-010: резолюция контактов и отмена встречи

Задача DEV-010 (реализация [ADR-010](../00-project/adr/ADR-010-contacts-resolution.md)/
[companion-спеки](../40-architecture/ADR-010-contacts-resolution-spec.md) и
[ADR-011](../00-project/adr/ADR-011-meeting-cancel-update.md)/
[companion-спеки](../40-architecture/ADR-011-meeting-cancel-update-spec.md)) по красным
стабам QA-author (`tests/test_search_contacts.py`, `tests/test_meeting_cancel.py`).
TDD: 34 failed → 355 passed, без правок логики существующих 317 регрессионных тестов.

## Размещение по модулям

- `auth.py::OPERATION_PROFILES`/`OPERATION_LABELS` — записи `search_contacts` (session:
  `/api/contacts`, api-key: `None`) и `cancel_meeting` (session:
  `/api/calendar/{id}/cancel`, `mutating=True`, api-key: `None`) — по спекам без отклонений.
- `contacts.py` (новый) — `search_contacts(client, query)`, маппер кандидата
  `{key, name, post}` через переиспользуемую `auth._display_name`.
- `meeting_cancel.py` (новый) — `build_cancel_confirmation_payload`,
  `CancelPreviewService` — чистые функции, без сети, зеркало `meeting_scheduling.py`.
- `cancel_meeting` (сетевой шаг) — размещён в `meeting_scheduling.py`, не в
  `meeting_cancel.py`: спека (ADR-011-spec §3) явно оставляла выбор Dev, а тест уже
  импортирует его оттуда («симметрично `create_meeting`») — решение по существу
  совпало с тем, что зафиксировано тестом, дополнительной правки импорта не
  потребовалось.
- CLI: `cli_contacts.py` (новый, `search-contacts`) и подкоманды
  `cancel-meeting-preview`/`cancel-meeting-confirm` добавлены в существующий
  `cli_meeting.py` (тот же паттерн, что `create-meeting-*`).
- MCP: `tools_contacts.py` (новый, `ktalk_search_contacts`) и
  `tools_meeting_cancel.py` (новый, `ktalk_preview_cancel_meeting`) — оба
  read-only/preview-only, мутирующего инструмента отмены нет и не появилось.
- `formatters.py`: `format_cancel_preview`, `format_search_contacts` (три ветки
  0/1/>1 без ранжирования и автовыбора).

## Расхождения со спекой/стабом, записанные по существу

**1. `auth.py` превысила гейт C13 после добавления двух профилей (387 строк > T=350,
самая длинная top-level декларация — `OPERATION_PROFILES`, 112 строк ≥ T_S=100).**
Решение: расщепление, не поднятие потолка (правило ADR-032 Д7/ADR-018 Д5). Новый
модуль `endpoints.py` принял `OPERATION_PROFILES`, `OPERATION_LABELS`,
`EndpointProfile`, `quote_path_param` — `auth.py` реэкспортирует их тем же приёмом,
каким сам `auth.py` уже реэкспортируется из `client.py`. Публичный контракт
(`ktalk_mcp.auth.OPERATION_PROFILES` и т.д., так его читают тесты) не изменился.

**2. Опечатка счёта символов в стабе `test_ac_11_2_cancel_meeting_quotes_id_with_plus_slash_equals`.**
Жёстко закодированный ожидаемый путь `AAAA%2BBBB%2FCCCC%3D%3D` короче на один символ
`B`, чем даёт `urllib.parse.quote("AAAA+BBBB/CCCC==", safe="")` — проверено отдельно
чистым вызовом `quote()`, воспроизводится арифметически (`%2B` вносит один `B` от
эскейпа, плюс 4 буквы `B` из самого `id` = 5 подряд, не 4). Остальные утверждения
теста (`%2B`/`%2F`/`%3D` присутствуют, сырые спецсимволы отсутствуют) проходят с
`quote_path_param` без правок. Исправлена одна строка литерала теста на
математически верное значение — намерение теста (регресс SEC-001 на новом типе
идентификатора) не изменилось.

**3. Регрессия `test_only_create_meeting_session_profile_is_mutating` (волна 1,
`test_auth_modes.py`) устарела по конструкции, не по ошибке.** Инвариант «mutating
только у `create_meeting`» был верен до ADR-011, который сознательно вводит вторую
мутирующую операцию с тем же барьером («не слабее создания»). Тест переименован в
`test_only_create_and_cancel_meeting_session_profiles_are_mutating`, проверка
расширена на множество `{create_meeting, cancel_meeting}` — инвариант «ничего
больше не мутирует по умолчанию» сохранён, не ослаблен.

## Что не реализовано (осознанно, по ADR-011 §5)

`update_meeting` (`PUT /api/calendar/{id}`) — не добавлен в `OPERATION_PROFILES`,
компоновщика тела нет. `client._profile_for("update_meeting")` даёт управляемый
`OperationNotAvailableError` уже существующим общим механизмом (ключ отсутствует в
таблице целиком, не `None` для режима) — отдельного кода не потребовалось,
подтверждено тестом `test_ac_11_6_...`/`test_update_meeting_has_no_entry_in_operation_profiles`.

## Боевая проверка

Не выполнялась — вне периметра DEV-010 (красная линия постановки: ни одного
боевого запроса). `cancel_meeting`/`search_contacts` остаются `ГИПОТЕЗА`/N/A в
части реального сетевого исхода до отдельной санкционированной попытки, тем же
статусом, что зафиксирован в ADR-010/ADR-011.
