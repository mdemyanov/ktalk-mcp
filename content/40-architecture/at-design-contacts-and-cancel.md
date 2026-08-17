---
title: "AT-design: резолюция контактов и отмена встречи"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: резолюция контактов и отмена встречи

Тест-дизайн и failing stubs для QA-010: [ADR-010](../00-project/adr/ADR-010-contacts-resolution.md) +
[ADR-010 spec](ADR-010-contacts-resolution-spec.md) (резолюция участника через `GET /api/contacts`),
[ADR-011](../00-project/adr/ADR-011-meeting-cancel-update.md) +
[ADR-011 spec](ADR-011-meeting-cancel-update-spec.md) (отмена встречи, `POST /api/calendar/{id}/cancel`).
Оба ADR — прямой контракт с QA-author (капабилити-спека для DEV-010 отдельно BA не заводилась,
тот же приём, что DEV-009). Формат таблицы — по образцу
[at-design-rooms-calendar.md](at-design-rooms-calendar.md).

## Как читать таблицу

`unit` — чистая функция/httpx-мок без реальной сети. `Статус: red (stub)` — новый failing
stub. Ни одного `manual`/боевого сценария в этой задаче — оба ADR прямо запрещают боевые
запросы для отмены/поиска контактов вне отдельной санкции владельца.

## Покрытие сценариев ADR-010 (`tests/test_search_contacts.py`)

| AC ID | Сценарий (дословно из «Контракт с QA-author») | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| AC-10-1 | 0 совпадений -> явный факт «ничего не найдено» с текстом запроса, код возврата ненулевой (CLI) | `search_contacts` даёт `[]`; CLI-формат/сообщение содержит запрос; `rc != 0` | unit | `test_ac_10_1_zero_matches_search_contacts_returns_empty_list`, `test_ac_10_1_zero_matches_cli_message_names_the_query_and_nonzero_exit` | red (stub) |
| AC-10-2 | Ровно 1 совпадение -> карточка с `key`, ФИО, `post`, БЕЗ автоподстановки в тело встречи | `search_contacts` даёт список из 1 элемента с `key`/`name`/`post`; `build_meeting_body` не имеет доступа к результату `search_contacts` (структурная проверка — см. AC-10-6) | unit | `test_ac_10_2_single_match_returns_one_candidate_with_key_name_post` | red (stub) |
| AC-10-3 | >1 совпадений -> полный список без ранжирования, `key` виден по каждому, автовыбора нет | `search_contacts` даёт список из N>1 элементов **в порядке ответа сервера** (не отсортирован по «похожести») | unit | `test_ac_10_3_multiple_matches_returns_full_unranked_list_preserving_server_order` | red (stub) |
| AC-10-4 | `AuthMode.API_KEY` -> отказ до сетевого вызова (`OperationNotAvailableError`) | `pytest.raises(OperationNotAvailableError)`, `httpx_mock.get_requests() == []` | unit | `test_ac_10_4_search_contacts_apikey_mode_refuses_before_network_call` | red (stub) |
| AC-10-5 | Секрет не появляется в тексте ни в одной из веток (0/1/>1/api-key-отказ) | `SECRET not in` текста вывода/исключения по каждой ветке | unit | `test_ac_10_5_secret_not_in_zero_match_output`, `test_ac_10_5_secret_not_in_single_match_output`, `test_ac_10_5_secret_not_in_multi_match_output`, `test_ac_10_5_secret_not_in_apikey_refusal_message` | red (stub) |

### Boundary/структурные тесты сверх дословного контракта

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| `search_contacts` формирует правильный GET (путь, query) | `request.url.path == "/api/contacts"`, `query`/`top=25`/`fillInMeetingStatus=false`/`includeKiosks=true` в параметрах запроса | unit (мок транспорта) | `test_search_contacts_sends_expected_get_request_with_fixed_top_and_flags` | red (stub) |
| `OPERATION_PROFILES["search_contacts"]` — session даёт профиль, api-key `None` | прямая инспекция таблицы | unit | `test_operation_profiles_search_contacts_session_present_apikey_none` | red (stub) |
| Ровно 25 кандидатов — форматтер не обрезает и не переполняет вывод нечитаемо (граница отображения, не сервера) | список из 25 синтетических кандидатов -> все 25 `key` присутствуют в тексте | unit | `test_format_search_contacts_25_candidates_not_truncated` | red (stub) |
| **AC-10-6 (структурная граница компоновщика, ADR-010 п.2)**: `build_meeting_body`/`build_required_attendees` не имеют доступа к сети/поиску — принимают только готовые строки `key` | инспекция сигнатуры `build_required_attendees`/`build_meeting_body`: нет параметра `query`/`search`/`client`; `search_contacts` физически не импортируется `meeting_body.py` | unit | `test_build_meeting_body_has_no_parameter_for_contact_search`, `test_meeting_body_module_does_not_import_search_contacts` | **green (guard)** — уже верно сегодня (`meeting_body.py`/ADR-005 не тронуты этим ADR), регрессионный снимок: ADR-010 п.2 обязывает границу остаться именно такой после реализации `search_contacts` |
| `ktalk_search_contacts` — новый читающий MCP-инструмент, `query` обязателен | снимок JSON-схемы (`required == {"query"}`) | unit | `test_ktalk_search_contacts_mcp_tool_registered_with_query_required` | red (stub) |
| CLI `search-contacts --query` зарегистрирована | `build_parser().parse_args(["search-contacts", "--query", "x"]).command` | unit | `test_build_parser_registers_search_contacts_subcommand` | red (stub) |

## Покрытие сценариев ADR-011 (`tests/test_meeting_cancel.py`)

Раздел «Контракт с QA-author» ADR-011-spec явно говорит: новых `#### Scenario:` в требовании
нет — FR-13/NFR-9 расширяются на вторую мутирующую операцию тем же протоколом (ADR-005), без
изменения текста AC. AC ID здесь пронумерованы по перечню «Edge cases / boundary conditions»
ADR-011-spec (это и есть операциональный контракт приёмки для этой волны).

| AC ID | Сценарий (источник — ADR-011-spec «Edge cases») | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| AC-11-1 | Подтверждение, выданное для `id=A`, `reason="x"`, НЕ проходит для `id=B`, тем же `reason` — привязка хеша к тройке (операция, id, reason), не к голому телу | `store.match(confirmation_id_for_A, hash_for_B) is False`; голый хеш тела (без `id`) совпал бы — регресс именно этого | unit | `test_ac_11_1_confirmation_issued_for_id_a_does_not_match_id_b_same_reason` | red (stub) |
| AC-11-2 | `id` с `+`/`/`/`=` -> путь запроса содержит `%2B`/`%2F`/`%3D`, не сырые символы | `quote_path_param` применён к `id` перед `path_template.format`; `request.url.raw_path` содержит закодированные символы | unit | `test_ac_11_2_cancel_meeting_quotes_id_with_plus_slash_equals` | red (stub) |
| AC-11-3 | `reason=""` (дефолт) — единственная подтверждённая живым запросом конфигурация (Ф-50); успешный путь с этим значением — регресс известного факта | мок 200 на `POST .../cancel`, `reason` не передан явно -> тело `{"reason": ""}` | unit | `test_ac_11_3_default_empty_reason_sends_empty_string_in_body` | red (stub) |
| AC-11-4 | `reason` с непустым значением — построение payload/тела корректно (сетевой ответ не проверен живым POST — не утверждаем код ответа) | `build_cancel_confirmation_payload(id=..., reason="встреча переносится")["reason"] == "встреча переносится"`; тело на проводе `{"reason": "встреча переносится"}` | unit | `test_ac_11_4_non_empty_reason_included_verbatim_in_payload_and_body` | red (stub) |
| AC-11-5 | Повтор `cancel-meeting-confirm`/`cancel_meeting` после сетевого сбоя — нет авто-retry, `store.consume` до сетевой попытки | мок `ConnectError` на `POST .../cancel`; ровно одна попытка мутирующего вызова (второй запрос — контрольный GET диагностики ADR-004, не повтор POST) | unit | `test_ac_11_5_network_failure_does_not_trigger_automatic_retry_exactly_one_post_attempt` | red (stub) |
| AC-11-6 | `update_meeting` вне периметра — вызов операции без записи в `OPERATION_PROFILES` даёт `OperationNotAvailableError`, не `KeyError` | `client._profile_for("update_meeting")` -> `OperationNotAvailableError` (существующий общий механизм, ключ полностью отсутствует в таблице) | unit | `test_ac_11_6_profile_for_missing_update_meeting_raises_not_available_not_keyerror`, `test_update_meeting_has_no_entry_in_operation_profiles` | **green (guard)** — уже верно сегодня (`update_meeting` не добавлен в таблицу, `_profile_for` уже отказывает управляемо на отсутствующий ключ), регрессионный снимок на «не реализовывать по домыслу» (ADR-011 п.5) |

### Транспорт и протокол подтверждения (регрессия ADR-005/ADR-009 на новом предмете хеширования)

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| Предпросмотр отмены -> ноль сетевых вызовов (перехват `httpx.AsyncClient.send`, не чтение кода) | `httpx_mock.get_requests() == []` после `CancelPreviewService(...).preview(id=..., reason=...)` | unit | `test_cancel_preview_performs_zero_network_calls` | red (stub) |
| `CancelPreviewService.preview` физически не получает `client` — структурная невозможность сети | инспекция сигнатуры: `"client" not in params` | unit | `test_cancel_preview_service_has_no_network_client_parameter` | red (stub) |
| `build_cancel_confirmation_payload` — предмет хеша, НЕ тело запроса | `payload == {"operation": "cancel_meeting", "id": id, "reason": reason}` (содержит `operation`/`id`, которых нет в теле на проводе) | unit | `test_build_cancel_confirmation_payload_shape` | red (stub) |
| `cancel_meeting` — заголовки `Authorization: Session <token>` + `X-Platform: web`, БЕЗ query `?sessionToken=` (ADR-009, mutating=True) | `request.headers["Authorization"] == f"Session {token}"`, `request.headers["X-Platform"] == "web"`, `"sessionToken" not in request.url.params`, `token not in request.url.query.decode()` | unit со spy на транспорте | `test_cancel_meeting_sends_mutating_headers_without_session_token_in_query` | red (stub) |
| `cancel_meeting` -> `POST /api/calendar/{id}/cancel` (путь без квотирования у синтетического простого id) | `request.url.path == "/api/calendar/synthetic-id-0001/cancel"`, `request.method == "POST"` | unit | `test_cancel_meeting_posts_to_expected_path` | red (stub) |
| `cancel_meeting`/api-key -> отказ до сети (NFR-7, тот же приём, что `create_meeting`) | `OperationNotAvailableError`, `httpx_mock.get_requests() == []` | unit | `test_nfr7_cancel_meeting_apikey_mode_refuses_before_network_call` | red (stub) |
| `id` не проходит через `ConfirmationStore.match` при отсутствии выданного подтверждения (тот же паттерн FR-13 AC-3) | `store.match("never-issued", hash) is False` | unit | `test_cancel_match_false_for_unknown_confirmation_id` | red (stub) |
| Два `preview()` подряд с одним и тем же `(id, reason)` дают разные `confirmation_id` (непредсказуемость токена не завязана на детерминированность хеша) | `id1 != id2` | unit | `test_cancel_preview_two_issues_of_same_payload_give_different_confirmation_ids` | red (stub) |
| Нет мутирующего MCP-инструмента для отмены (ADR-011 §5) — только `ktalk_preview_cancel_meeting` | `mcp.list_tools()`: ни один инструмент, содержащий «cancel» в имени, не является мутатором (нет инструмента `ktalk_cancel_meeting`/`ktalk_confirm_cancel_meeting` и т.п.) | unit | `test_no_mutating_mcp_tool_exists_for_cancel_meeting` | red (stub) |
| `ktalk_preview_cancel_meeting` зарегистрирован, `id` обязателен | JSON-схема: `"id" in required` | unit | `test_ktalk_preview_cancel_meeting_tool_registered_with_id_required` | red (stub) |
| `format_cancel_preview` — печатает `id`/`reason`/`confirmation_id`, не тело ответа сервера (недокументировано) | текст содержит `id`, `reason`, не выдумывает поля тела ответа | unit | `test_format_cancel_preview_prints_id_reason_confirmation_id` | red (stub) |
| Секрет не появляется в выводе предпросмотра/ошибки отмены (NFR-10, регресс на новой операции) | `SECRET not in` текста | unit | `test_secret_not_in_cancel_meeting_error_message` | red (stub) |

## Boundary cases

- `id` синтетический, несущий ВСЕ ТРИ символа `+`, `/`, `=` одновременно (не по одному) — иначе
  тест не покрывает комбинацию, которую реально несёт base64 Exchange-идентификатор (Ф-56).
  Реальный `id` владельца не используется (правило анонимизации ADR-009-spec).
- `reason` пустая строка vs непустая строка — оба протестированы отдельно (AC-11-3/AC-11-4);
  явный `None` для `reason` не тестируется — CLI/компоновщик уровня `meeting_cancel.py` несёт
  дефолт `""` структурно (сигнатура `reason: str = ""`), `None` как явное «не решено» — не
  предмет этого ADR (в отличие от `create_meeting`, где `None` — сигнал NFR-9).
- Хеш подтверждения: одинаковый `reason`, разные `id` -> `match` даёт `False` (AC-11-1);
  контрольный обратный случай — одинаковый `id`, разные `reason` -> тоже `False` (уже покрыт
  общей механикой `ConfirmationStore.match`, регресс `test_match_false_when_hash_does_not_match`
  из `test_confirmation.py`, не дублируется здесь отдельным тестом).
- `search_contacts`: 0 vs 1 vs >1 — три существенно разных ветки форматтера, каждая
  протестирована отдельно, не одной параметризацией с общим ассертом (SA явно требует
  «различимые оператором/агентом текстом»).

## Error cases

- `search_contacts` под api-key — управляемый `OperationNotAvailableError` до сети, не голый
  401/403 (AC-10-4).
- `cancel_meeting` под api-key — тот же управляемый отказ (регресс NFR-7 на новой операции).
- `cancel_meeting` — сетевая ошибка -> не более одной попытки самого `POST .../cancel`
  (второй запрос в паре — контрольный GET диагностики ADR-004, тот же паттерн, что уже
  покрыт `test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry` для создания).
- `update_meeting` — вызов без профиля даёт `OperationNotAvailableError`, не `KeyError`
  (AC-11-6) — существующий общий механизм `_profile_for`, отдельной реализации не требует.

## Не покрываем (вне scope)

| Сценарий | Почему |
|---|---|
| Живой `GET /api/contacts` на боевом домене | Красная линия SA-010 — боевых запросов не делать; отдельная санкция владельца, аналог RES-003 §5 |
| Живой `POST /api/calendar/{id}/cancel` на боевом домене | Красная линия SA-011/задачи — та же санкция, что и создание; ADR-011 «ГИПОТЕЗА»-статус до отдельной боевой попытки |
| Требование непустого `reason` | N/A по ADR-011 п.4 — не измерялось ни разу, не гипотеза, а честное отсутствие данных |
| Код ответа сервера на повторную отмену/несуществующий `id` | N/A — не наблюдался ни разу (ADR-011-spec «Границы»), поведение не предполагается без факта (тот же принцип, что Ф-45 для `get_room`) |
| Api-key-режим `search_contacts`/`cancel_meeting` — позитивный путь | Р-4: единственный доступный ключ не имеет scope на контакты/мутации календаря; негативный путь (fail-closed до сети) — покрыт (AC-10-4, тест `test_nfr7_cancel_meeting_apikey_mode_refuses_before_network_call`) |
| Приём логина как значение `query` в `search_contacts` | N/A по ADR-010 п.4 — контракт заявляет только текст ФИО, поведение на логине не специфицировано |
| `PUT /api/calendar/{id}` (правка встречи) | Явно отложено ADR-011 п.5/§7 — форма тела не разобрана ни одним живым образцом; проектирование по домыслу запрещено anti-fabrication |
| Позитивный TTY-сценарий `cancel-meeting-confirm` (реальный `pty`, полный CLI-цикл) | Не входит в контракт с QA-author ADR-011-spec (он требует регресс протокола на уровне `ConfirmationStore`/сетевого шага, не полного CLI); CLI-подкоманды `cancel-meeting-preview`/`cancel-meeting-confirm` — код Dev, тестируется тем же паттерном `test_cli_meeting.py` уже сегодня для `create-meeting-confirm`, повторение здесь избыточно до того, как Dev выберет точное имя подкоманды |

## Допущения, требующие внимания Dev

- **Расположение сетевого шага `cancel_meeting`.** ADR-011-spec §3 явно оставляет выбор файла
  Dev'у («meeting_scheduling.py (или соседний вызов из meeting_cancel.py) — решение Dev по
  месту»). Stubs здесь импортируют `cancel_meeting` из `ktalk_mcp.meeting_scheduling`
  (симметрично `create_meeting`, тот же файл держит сетевой шаг обеих мутирующих операций;
  `meeting_cancel.py` по аналогии с `meeting_body.py` держит только чистые функции
  `build_cancel_confirmation_payload`/`CancelPreviewService`). Если Dev разместит `cancel_meeting`
  в `meeting_cancel.py` — правка одной строки импорта в каждом тесте, сам сценарий не меняется.
- **Имя подкоманд CLI не тестируется дословно здесь.** ADR-011-spec §4 предлагает
  `cancel-meeting-preview`/`cancel-meeting-confirm` — тест на регистрацию подкоманд НЕ включён
  в этот дизайн (см. «Не покрываем»); Dev реализует по образцу `create-meeting-*`, тест на CLI
  добавляется вместе с реализацией (или отдельным QA-runner прогоном).
- **Имя MCP-инструмента предпросмотра отмены зафиксировано ADR-011-spec §5 дословно**
  (`ktalk_preview_cancel_meeting`) — тест использует это имя без вариаций.

## Сводка объёма stub-файлов

| Файл | Тест-функций | Из них red (stub) | Из них green (guard) |
|---|---|---|---|
| `tests/test_search_contacts.py` | 16 | 14 | 2 (AC-10-6) |
| `tests/test_meeting_cancel.py` | 22 | 20 | 2 (AC-11-6) |

Оба файла — новые, далеко от порога гейта C13 (`test`, T=600, warn).

## Итог прогона на момент написания (до реализации Dev)

`uv run pytest` — 355 total, **34 failed (red stubs этой задачи), 321 passed** (317 существующих
регрессионных тестов + 4 новых green-guard: AC-10-6 ×2, AC-11-6 ×2 — обе пары уже верны сегодня
и служат регрессионным снимком на инварианты, которые ADR-010/ADR-011 обязаны не нарушить).
`uv run ruff check src/ tests/ --no-cache` — чисто (`All checks passed!`; 36 преэкзистующих ошибок
в `scripts/` не тронуты, не в периметре этой задачи). `bash scripts/check.sh --fast` —
`Errors: 0, Warnings: 3` (все три warning — заморозка грандфазера на файлах, не тронутых этой
задачей: `scripts/_drift_check.py`, `scripts/validate-profile.py`, `src/ktalk_mcp/registry.py`).
