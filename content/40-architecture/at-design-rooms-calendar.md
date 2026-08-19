---
title: "AT-design: комнаты, календарь, планирование встреч"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: комнаты, календарь и планирование встреч

Тест-дизайн и failing stubs для эпика 0.6.0. Источник AC —
[rooms-calendar-scheduling.md](../30-requirements/rooms-calendar-scheduling.md) (FR-17, FR-18,
FR-13, FR-19, NFR-6..NFR-10). Архитектурный контекст — [rooms-calendar-spec.md](rooms-calendar-spec.md)
(раскладка модулей, «Контракт с QA-author», §598) + companion-спеки
[ADR-004-undocumented-contour-spec.md](ADR-004-undocumented-contour-spec.md) (детекция дрейфа
контура) и [ADR-005-write-operations-spec.md](ADR-005-write-operations-spec.md) (протокол
предпросмотра/подтверждения). Stubs — в `tests/`, по одному файлу на модуль SA-раскладки
(гейт C13 `test`: T=600, T_S=150, warn — самый длинный файл здесь 425 строк, ни один не
приближается к порогу).

## Как читать таблицу

- **Тип**: `unit` — чистая функция/httpx-мок без реальной сети; `integration` — CLI/реестр/
  реальный `pty`; `manual`/`заблокирована` — требует боевого домена или санкции владельца
  (BA явно пометил в требовании).
- **Статус**: `red (stub)` — новый failing stub; `green (guard)` — новый тест, уже зелёный
  сегодня, служит регрессионным снимком (не тестирует новую функциональность);
  `manual only` — нет и не будет автоматического теста.

## Покрытие AC

### FR-17 — чтение комнаты (`tests/test_rooms.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-17 AC-1 | Комната существует -> объект с 18 полями | `map_room(raw)` содержит все `ROOM_FIELDS`; `get_room` happy path на моке | unit + manual | `test_map_room_extracts_all_18_fields_from_live_probe_fixture`, `test_ac_fr17_1_get_room_session_mode_happy_path`; официальная проверка AC — ручная (постановка §5, уже подтверждена живым GET на момент требования) | red (stub) + manual |
| FR-17 AC-2 | Несуществующее имя -> понятное сообщение, не сырое исключение | — заблокирована требованием (поведение сервера не проверено) | manual | — | manual only (заблокирована) |
| FR-17 AC-2 (сужение SA §4.2) | Любой не-2xx при рабочем контрольном вызове -> `ContourDriftError`, не «комната не найдена» | мок 404 + control 200 -> `ContourDriftError` | unit | `test_get_room_any_non_2xx_with_working_control_raises_contour_drift_not_not_found` | red (stub) |
| FR-17 AC-3 | Api-key без профиля -> отказ до сети | `OperationNotAvailableError`, `httpx_mock.get_requests() == []` | unit | `test_ac_fr17_3_get_room_apikey_mode_refuses_before_network_call` | red (stub) |
| NFR-7 (доп.) | `ktalk_get_room` — новый MCP-инструмент, `room_name` обязателен | снимок JSON-схемы | unit | `test_ktalk_get_room_mcp_tool_registered_with_room_name_required` | red (stub) |
| — (доп.) | Маппер терпим к отсутствию неякорных полей | `map_room({"roomName": ...})` не поднимает исключение | unit | `test_map_room_tolerates_missing_non_anchor_fields` | red (stub) |
| — (доп.) | Отсутствие якоря контракта (`roomName`) на 200 -> `ContourDriftError` | — | unit | `test_map_room_missing_anchor_field_raises_contour_drift` | red (stub) |

### FR-18 — чтение календаря (`tests/test_calendar.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-18 AC-1 | Окно <=7 дней -> все встречи окна | 1 сегмент, все id присутствуют | unit + manual | `test_ac_fr18_1_window_within_7_days_returns_all_items_single_segment` | red (stub) + manual |
| FR-18 AC-2 | Окно >7 дней -> без потерь и без дублей на стыках | 2 сегмента (7+3), объединение без дублей | unit | `test_ac_fr18_2_window_over_7_days_covers_full_period_without_loss_or_dup` | red (stub) |
| FR-18 AC-3 | `start` не указан -> отказ до сети | вызов `.fn` инструмента напрямую, `httpx_mock.get_requests() == []` | unit | `test_ac_fr18_3_missing_start_rejected_before_network_call` | red (stub) |
| FR-18 AC-4 | Сегмент ровно 100 элементов -> предупреждение о неполноте | `result.incomplete_segments` не пусто | unit | `test_ac_fr18_4_segment_with_exactly_100_items_flags_incomplete`, `test_segment_with_fewer_than_100_items_does_not_flag_incomplete` | red (stub) |
| FR-18 AC-5 | Фильтр `roomName` передаётся как есть | `"roomName=..."` в URL запроса | unit | `test_ac_fr18_5_room_name_filter_passed_through_to_server` | red (stub) |
| FR-18 AC-6 | `query` не входит в публичный интерфейс | `"query" not in schema["properties"]` | unit | `test_ac_fr18_6_query_parameter_not_in_public_tool_schema` | red (stub) |
| FR-18 AC-7 | Текст не утверждает «ваш календарь» | текст форматтера/докстроки инструмента не содержит "ваш календарь"/"your calendar" | unit | `test_ac_fr18_7_calendar_formatter_does_not_claim_personal_calendar`, `test_ac_fr18_7_calendar_tool_docstring_does_not_claim_personal_calendar` | red (stub) |
| — (доп.) | `split_window`: 7/8/14 дней, 1 день | границы сегментов (rooms-calendar-spec §5.3) | unit | `test_split_window_exactly_7_days_gives_one_segment`, `test_split_window_8_days_gives_two_segments_7_plus_1`, `test_split_window_14_days_gives_two_segments_of_7`, `test_split_window_single_day_start_equals_end`, `test_split_window_segments_are_contiguous_no_gap_no_overlap` | red (stub) |
| — (доп.) | Дедуп на стыке сегментов (искусственный дубль id) | элемент на границе — один раз в результате | unit | `test_dedup_at_segment_boundary_same_id_in_two_adjacent_segments` | red (stub) |
| — (доп.) | Маппер (20 полей, Ф-28): недокументированные `meetId`/`urlParams` сохраняются, документированные-но-невиданные поля не требуются | — | unit | `test_calendar_item_fields_constant_has_20_documented_fields`, `test_map_calendar_item_preserves_undocumented_but_contractual_fields`, `test_map_calendar_item_tolerates_absent_documented_but_never_seen_fields`, `test_map_calendar_item_missing_anchor_raises_contour_drift` | red (stub) |
| — (доп., §5.5 решающая таблица) | 200 без `items` -> drift без корреляции; известный 400 -> обычная ошибка без корреляции; неизвестный 400 -> корреляция+drift; сетевая ошибка -> корреляция+drift | подсчёт запросов (1 vs 2) + тип исключения | unit | `test_fetch_segment_200_items_absent_raises_contour_drift_without_correlation`, `test_fetch_segment_known_400_text_gives_plain_error_without_correlation`, `test_fetch_segment_unknown_400_text_triggers_correlation_and_drift`, `test_fetch_segment_network_error_triggers_correlation_and_drift`, `test_known_400_texts_catalog_matches_f26_dословно` | red (stub) |
| NFR-7 (доп.) | `get_calendar`/api-key -> отказ до сети (ADR-004 п.2, «без записи» несмотря на живой 200) | `OperationNotAvailableError`, 0 запросов | unit | `test_nfr7_get_calendar_apikey_mode_refuses_before_network_call` | red (stub) |

### FR-39 — включительная правая граница окна чтения календаря (`tests/test_fr39_calendar_inclusive_end.py`, ревизия волны 7, QA-009)

Мок сервера в этих тестах — честный: фильтрует фикстуры по `[start 00:00, end 00:00)`
РЕАЛЬНО запрошенных параметров (Ф-60 RES-004), не отдаёт заготовленный список — ловит
любую реализацию, не компенсирующую полуоткрытость, включая текущую. `AC-3`/доп. тест
на стыке специально изолируют «потерю на стыке сегментов» от «потери на правом крае
всего окна» — фикс, чинящий только последний сегмент, здесь всё равно красный.

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-39 AC-1 | CLI `--start D --end D` -> встречи дня D | `ids == {"E1"}` на честном моке дня D | integration | `test_ac1_cli_single_day_window_returns_that_days_meetings` | red (stub) |
| FR-39 AC-2 | MCP `ktalk_list_calendar` даёт тот же результат, что CLI, на том же окне | `ids == {"E1"}` через `tool.fn(...)` с реальным `get_shared_client()` | integration | `test_ac2_mcp_single_day_window_matches_cli_result` | red (stub) |
| FR-39 AC-3 | Окно шире 7 дней (17-30) -> все 14 дней, без потерь и без дублей на стыках | множество id совпадает с `{E17..E30}`; отдельно — узкий тест на день 23 (стык сегментов (17,23)/(24,30)), изолированно от правого края окна (30) | integration | `test_ac3_wide_window_17_to_30_covers_every_day_no_loss_no_dup`, `test_ac3_stitch_boundary_day_23_not_lost_not_just_right_edge_day_30` | red (stub) |
| FR-39 AC-4 | Три однодневных окна (начало/середина/конец диапазона) -> каждое отдаёт встречу своего дня | параметризовано на 17/20/23 августа | integration | `test_ac4_single_day_window_at_start_middle_end_returns_that_day[...]` (×3) | red (stub) |
| FR-39 AC-5 | `start > end` отклоняется до сети, кодом != 0, без пересказа сырого 400 | `rc != 0`, `httpx_mock.get_requests() == []`, сырой текст Ф-64 отсутствует в stderr | integration | `test_ac5_start_after_end_rejected_before_network_call` | red (stub) |
| FR-39 AC-6 | Честное «пусто» (код 0) и отклонённый ввод (код != 0) не делят код возврата; замаскированный отказ (день с реальной встречей молча даёт «пусто») недопустим | `rc_empty != rc_invalid`; отдельно — день с событием не должен вернуть `items == []` при коде 0 | integration | `test_ac6_honest_empty_day_and_rejected_reversed_window_never_share_exit_code`, `test_ac6_masked_failure_day_with_real_events_must_not_report_as_honest_empty` | red (stub) (первый тест зелёный уже сегодня — коды и так различны, второй красный) |

### FR-13 — планирование встречи (`tests/test_meeting_body.py`, `test_confirmation.py`, `test_meeting_scheduling.py`, `test_cli_meeting.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-13 AC-1 | Предпросмотр -> ноль сетевых запросов на запись | `httpx_mock.get_requests() == []` после `PreviewService.preview(...)` | unit | `test_ac_fr13_1_preview_performs_zero_network_calls` / `test_meeting_scheduling.py` | red (stub) |
| FR-13 AC-2 | Предпросмотр и создание дают одно и то же тело | `sent_body == body` (JSON тела POST совпадает с телом предпросмотра) | unit | `test_ac_fr13_2_preview_body_matches_body_sent_at_create` / `test_meeting_scheduling.py` | red (stub) |
| FR-13 AC-3 | Одного вызова с параметрами недостаточно — нужна отдельная ссылка на предпросмотр | `store.match(неизвестный_id, hash) is False` независимо от параметров | unit | `test_match_false_for_unknown_confirmation_id` / `test_confirmation.py` | red (stub) |
| NFR-9 (= FR-13 AC про поля) | Поле из таблицы NFR-9 не передано явно -> отказ до сети с именем поля | параметризовано по 10 полям (9 физических NFR-9 + `subject`) | unit | `test_nfr9_field_not_passed_explicitly_rejects_before_any_side_effect[...]` (10 кейсов) / `test_meeting_body.py` | red (stub) |
| FR-13 AC (тело) | `isRecurring`/`recurrence` и поля вне состава физически отсутствуют в теле | инспекция сигнатуры `build_meeting_body` — нет параметра для них | unit | `test_build_meeting_body_has_no_parameter_for_recurrence_fields`, `test_build_meeting_body_has_no_parameter_for_fields_outside_agreed_scope` / `test_meeting_body.py` | red (stub) |
| FR-13 AC-6 | Сетевая ошибка -> ровно одна попытка, без авто-retry | `len(httpx_mock.get_requests()) == 1` после мока сбоя | unit + integration | `test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry` / `test_meeting_scheduling.py`; `test_cli_create_meeting_confirm_network_failure_no_retry_exactly_one_attempt` / `test_cli_meeting.py` (полный CLI-цикл через реальный `pty`) | red (stub) |
| FR-13 AC-7 (боевая) | Санкционированное создание на тестовой комнате | — | manual | — | manual only (заблокирована, нет санкции владельца) |
| NFR-7 (доп.) | `create_meeting`/api-key -> отказ до сети | `OperationNotAvailableError`, 0 запросов | unit | `test_nfr7_create_meeting_apikey_mode_refuses_before_network_call` / `test_meeting_scheduling.py` | red (stub) |

### FR-13 — `ConfirmationStore` (ADR-005-spec «Форма подтверждения», `tests/test_confirmation.py`)

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| `issue` даёт непредсказуемый токен, не производный от хеша | `id != hash`, `hash not in id`, два `issue()` одного хеша дают разные id | unit | `test_issue_returns_a_token_not_derived_from_the_hash`, `test_two_issues_of_the_same_hash_give_different_tokens` | red (stub) |
| `match` — happy path сразу после `issue` | `True` | unit | `test_match_true_right_after_issue_with_same_hash` | red (stub) |
| `match` — хеш не совпал (drift тела между preview и confirm) | `False` | unit | `test_match_false_when_hash_does_not_match_issued_hash` | red (stub) |
| `consume` -> повторный `match` -> `False` (single-use) | — | unit | `test_consume_then_match_returns_false_single_use` | red (stub) |
| TTL истёк -> `match` -> `False`, даже с верным хешем | инжектируемые часы, `advance(TTL + 1s)` | unit | `test_ttl_expiry_makes_match_false_even_with_correct_hash` | red (stub) |
| В пределах TTL -> `match` -> `True` | `advance(TTL - 1s)` | unit | `test_within_ttl_match_still_true` | red (stub) |
| `CONFIRMATION_TTL == 10 минут` (дизайн-выбор, снимок-регрессия) | — | unit | `test_confirmation_ttl_is_ten_minutes` | red (stub) |

### FR-13 — CLI `create-meeting-preview`/`create-meeting-confirm` (`tests/test_cli_meeting.py`)

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| `_tri_bool`: `TRUE`/`False` (регистр) принимаются, `yes`/`1` отклоняются | `argparse.ArgumentTypeError` на невалидных токенах | unit | `test_tri_bool_accepts_true_false_case_insensitively`, `test_tri_bool_rejects_non_true_false_tokens` | red (stub) |
| Обе подкоманды зарегистрированы | `build_parser().parse_args([...]).command` | unit | `test_build_parser_registers_both_create_meeting_subcommands` | red (stub) |
| Предпросмотр с полными флагами -> 0 сетевых вызовов | `httpx_mock.get_requests() == []` | integration | `test_cli_create_meeting_preview_full_flags_zero_network_calls` | red (stub) |
| Отсутствие `--room-name` -> сообщение называет `roomName` | текст содержит имя JSON-поля | integration | `test_cli_create_meeting_preview_missing_room_name_names_the_field` | red (stub) |
| **Отсутствие `--enable-sip` != `False`** (NFR-9, не `store_true`) | отказ, текст называет `enableSip` | integration | `test_cli_create_meeting_preview_missing_enable_sip_flag_is_not_silently_false` | red (stub) |
| `--no-required-users` без `--required-user-key` -> явный `[]`, предпросмотр проходит | `rc == 0` | integration | `test_cli_create_meeting_preview_no_required_users_flag_gives_explicit_empty_list` | red (stub) |
| Ни `--required-user-key`, ни `--no-required-users` -> отказ с `requiredUserKeys` | — | integration | `test_cli_create_meeting_preview_neither_required_user_key_nor_no_required_users_rejects` | red (stub) |
| `confirm` без реального терминала (под pytest — уже пайп) -> отказ до сети | `httpx_mock.get_requests() == []`, текст про терминал | integration | `test_cli_create_meeting_confirm_refuses_when_not_a_tty` | red (stub) |
| `confirm` через реальный `pty` + ввод «да» -> ровно один `POST` | `len(requests) == 1` | integration | `test_cli_create_meeting_confirm_over_real_tty_creates_exactly_once` | red (stub) |

### FR-19 — `auth-status` без реестра (`tests/test_fr19_auth_status.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR-19 AC-1 | Реестр недоступен -> диагностика всё равно выполняется | текст «unable to open database file» отсутствует, `rc == 0` | integration | `test_ac_fr19_1_auth_status_runs_diagnostics_despite_unavailable_registry` | red (stub) |
| FR-19 AC-2 | Ошибка диагностики не подменяется ошибкой БД | текст об ошибке БД отсутствует при 401 | integration | `test_ac_fr19_2_auth_diagnostics_error_not_replaced_by_database_message` | red (stub) |
| FR-19 AC-3 | Остальные команды по-прежнему требуют реестр (регрессия) | `rc != 0` на 8 командах при недоступном `--db` | integration | `test_ac_fr19_3_other_commands_still_require_available_registry[...]` (8 параметров: list/dashboard/show/mark-processing/export/migrate/set-vault-id/sync) | **green (guard)** — уже верно сегодня, снимок-регрессия |
| — (доп., rooms-calendar-spec §7.1) | `create-meeting-preview` работает (до `MissingFieldError`) при недоступном реестре | текст об ошибке БД отсутствует | integration | `test_fr19_create_meeting_preview_works_despite_unavailable_registry` | red (stub) |

### NFR-6 — публичный интерфейс 10 существующих MCP-инструментов не меняется (`tests/test_public_interface.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR-6 | Имена/обязательные параметры 10 инструментов волны 1 не меняются | снимок `mcp.list_tools()` (`required` из JSON-схемы) по всем 10 | integration | `test_nfr6_ten_existing_tools_names_and_required_params_unchanged` | **green (guard)** — уже верно сегодня (три новых инструмента волны 2 ещё не существуют, старые 10 не тронуты), служит регрессионным снимком на всю волну |

### NFR-7 — новые операции только через `OPERATION_PROFILES`

Нет отдельной таблицы — покрыто распределённо по трём операциям выше (`test_ac_fr17_3_*`,
`test_nfr7_get_calendar_apikey_mode_refuses_before_network_call`,
`test_nfr7_create_meeting_apikey_mode_refuses_before_network_call`): каждая из трёх новых
операций отказывает до сети в api-key-режиме тем же механизмом `_profile_for`, что уже
покрывает волна 1 (`test_ac_fr6_3_*`/`test_ac_fr9_3_*` в `test_auth_modes.py`/`test_archive.py`).

### NFR-8 — гейт объёма кода (C13) не поднимается

Не тест, а гейт pre-commit (`bash scripts/check.sh --fast`) — нет смысла проверять «гейт
зелёный» изнутри pytest (тот же принцип, что NFR-3 волны 1). N/A для этой таблицы.

### NFR-10 — секреты не в логах/трейсбеках/выводе CLI, включая новые пути (`tests/test_secret_masking.py`)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR-10 | Секрет не в тексте ошибки `get_room` (**session-режим** — `get_room`/api-key в этой волне без записи профиля, ADR-004 §2, отказ fail-closed до сети, замоканный 401 туда физически не достижим; см. правку ниже) | `SECRET not in str(exc)`, 2 замоканных ответа 401 (недокументированный путь + контрольный вызов ADR-004, 401/401 → reraise оригинала) | integration | `test_nfr10_secret_not_in_get_room_error_message` | green |
| NFR-10 | Секрет не в тексте ошибки чтения календаря (**session-режим**, тот же принцип) | `SECRET not in str(exc)`, 2 замоканных ответа 401 | integration | `test_nfr10_secret_not_in_calendar_error_message` | green |
| NFR-10 | Секрет не в выводе `create-meeting-preview` (в т.ч. предпросмотр) | `SECRET not in captured.out/.err` | integration | `test_nfr10_secret_not_in_create_meeting_preview_cli_output` | green |

**Правка после ревью Dev (2026-08-14).** Первые два теста изначально конструировали клиент с
`personal_api_key=SECRET` и ждали `KTalkAuthError` от замоканного 401 — недостижимый сценарий:
`get_room`/`get_calendar` в api-key-режиме этой волной не имеют записи `OPERATION_PROFILES`
(ADR-004 §2, `AuthMode.API_KEY: None`), поэтому `_profile_for` отказывает fail-closed ДО
сетевого вызова (`OperationNotAvailableError`) — замоканный 401 не запрашивался вовсе, тест
падал на несовпадении типа исключения, а `httpx_mock` дополнительно ругался на неиспользованный
мок при teardown. Ошибка стаба: скопирован с соседнего теста для `list_recordings`, у которой
api-key-профиль в этой волне легитимен, без учёта, что `get_room`/`get_calendar` — session-only
до отдельного пересмотра ADR-004 §2. Исправлено на `session_token=SECRET` — там у обеих операций
есть рабочий профиль, 401 реально достигает `_classify`, и (после появления в коде корреляционной
диагностики) второй, контрольный вызов `list_recordings(top=1)` тоже отвечает 401 → тот же режим
матрицы ADR-004 (401/401 → перевыброс оригинала), что уже покрыт `test_contour_diagnostics.py`.
Отдельного теста на fail-closed api-key для этих двух операций не добавлено — он уже существует
(`test_ac_fr17_3_get_room_apikey_mode_refuses_before_network_call` /
`test_nfr7_get_calendar_apikey_mode_refuses_before_network_call`, оба в соответствующих файлах
модуля), дублировать не было необходимости.

### `contour_diagnostics.py` — переиспользуемый механизм (`tests/test_contour_diagnostics.py`)

Не привязан к одному FR напрямую — переиспользуемый компонент FR-17/FR-18 (ADR-004-spec
«Контракт с QA-author»). Покрывает комбинаторную матрицу (недокументированный ответ x
контрольный ответ): 404/200, 401/401, 403/403, неизвестный-400/200, сетевая-ошибка/200.

| Сценарий | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| Якорь контракта отсутствует на 200 -> `ContourDriftError`, не KeyError | — | unit | `test_require_contract_field_missing_anchor_raises_contour_drift`, `test_require_contract_field_present_field_does_not_raise` | red (stub) |
| `ContourDriftError` — подкласс `KTalkError` | `issubclass(...)` | unit | `test_contour_drift_error_is_a_ktalk_error` | red (stub) |
| 404/200 -> drift; 401/401, 403/403 -> перевыброс оригинала; неизвестный-400/200 -> drift; сетевая-ошибка/200 -> drift | — | unit | `test_diag_404_undocumented_control_200_raises_contour_drift`, `test_diag_401_undocumented_control_401_reraises_original`, `test_diag_403_undocumented_control_403_reraises_original`, `test_diag_unknown_400_undocumented_control_200_raises_contour_drift`, `test_diag_network_error_undocumented_control_200_raises_contour_drift` | red (stub) |
| `TRANSIENT_ERRORS` включает `KTalkError` и `httpx.HTTPError` | — | unit | `test_diag_transient_errors_tuple_covers_ktalk_error_and_httpx_error` | red (stub) |

## Boundary cases (сверх дословных формулировок AC)

- `split_window`: окно ровно 7 дней (1 сегмент, не 2), 8 дней (7+1, не 4+4), 14 дней (2×7),
  окно из одного дня (`start == end`) — все пять из rooms-calendar-spec «Контракт с QA-author».
- Сегмент ровно 100 элементов (не 99, не 101) — граница фактического потолка Ф-21.
- `pinCode`/`requiredUserKeys` — явное пустое значение (`""`/`[]`) отличается от отсутствия
  (`None`): оба случая проходят разные ветки `build_meeting_body`, оба протестированы отдельно.
- `enableSip`/`enableAutoRecording`/`allowAnonymous` — явный `False` не путается с
  отсутствием значения (`is None`, не truthiness) — параметризовано на True/False.
- TTL подтверждения: на 1 секунду раньше истечения — валидно; на 1 секунду позже — невалидно
  (инжектируемые часы, без реального ожидания).
- `_tri_bool`: регистр (`TRUE`/`False`) не имеет значения, но `yes`/`1` — невалидные токены.
- `--required-user-key` и `--no-required-users` не переданы одновременно ни разу (оба
  отсутствуют) -> `MissingFieldError` — SA явно оставила поведение при одновременной
  передаче ОБОИХ флагов не специфицированным («Dev выбирает детерминированный порядок... и
  фиксирует тестом») — не покрыто здесь намеренно, ждём решения Dev (см. «Не покрываем»).

## Error cases

- Любой не-2xx у `get_room` (нет собственного каталога ошибок, в отличие от календаря) —
  корреляционная диагностика вместо тихой классификации.
- 200 с усечённым телом (пропал `roomName`/`items`/`start`) — `ContourDriftError`, не
  `KeyError`/пустой список.
- Известный текст 400 календаря (каталог Ф-26) — обычная `KTalkError`, без лишнего сетевого
  вызова на корреляцию (цена корреляции не ложится на штатную валидационную ошибку).
- Неизвестный текст 400 / сетевая ошибка / 404 / 401 / 403 у недокументированных путей —
  запускают корреляцию с контрольным вызовом `list_recordings(top=1)`.
- Сетевая ошибка/таймаут при `POST /calendar` — ровно одна попытка, без retry (и на уровне
  `create_meeting`, и на уровне полного CLI-цикла через `pty`).
- `confirm` без реального терминала (пайп/CI, что уже воспроизводится под pytest без
  дополнительного мокирования) — отказ до `ConfirmationStore`, до сети.
- Неизвестный/просроченный/уже потреблённый `confirmation_id` — единая недифференцированная
  ошибка (ADR-005-spec: причины не различаются наружу, чтобы не подсказывать обход).

## Не покрываем автоматически (нужна боевая проверка или решение Dev)

| Сценарий | Почему нельзя автоматизировать сейчас |
|---|---|
| FR-17 AC-1 (семантика полей на боевом домене) | Официально ручная проверка требования — уже подтверждена живым GET на момент постановки (§5); маппер здесь покрыт unit-тестом на синтетической фикстуре, это не заменяет боевую проверку |
| FR-17 AC-2 (буквальный текст) | Поведение сервера для несуществующего имени комнаты не проверено ни разу (заблокирована требованием) — сужение SA (§4.2) протестировано вместо неё |
| FR-18 AC-1 (боевые параметры/лимиты) | Параметры и 7-дневный лимит подтверждены живыми зондами RES-003, но сама автоматизация — на моке; боевое подтверждение — вне пирамиды |
| FR-13 AC-7 | Заблокирована постановкой до санкции владельца на конкретный боевой `POST /calendar` (тестовая комната, уборка после) |
| FR-17/FR-18 под api-key (позитивный кейс) | Не проверено эмпирически ни разу (комната) / необъяснимый асимметричный 200 (календарь, ADR-004) — оба остаются «без записи», позитивный сетевой путь под api-key недостижим, пока профиль не появится |
| Точный текст ответа на `--required-user-key` + `--no-required-users` одновременно | SA явно оставила решение Dev («выбирает детерминированный порядок... и фиксирует тестом») — тест появится вместе с реализацией, не раньше |
| Позитивный TTY-сценарий: точный принимаемый токен подтверждения | SA не фиксирует его дословно — тест кодирует рабочую гипотезу "да" (см. «Допущения» ниже), не факт спеки |
| Живой смоук-прогон недокументированного контура (`GET /api/rooms`, `GET /api/calendar`, боевой `POST /calendar`) | Вне пирамиды тестов QA-author — ручной чек-лист DevOps/оператора (ADR-004-spec/ADR-005-spec «Бриф для DevOps») |

## Допущения, требующие внимания Dev (не баги AC, а решения по контракту вызова)

- **Токен подтверждения в интерактивном CLI** — ADR-005-spec/rooms-calendar-spec не фиксируют
  дословно, что должен ввести оператор в ответ на приглашение `create-meeting-confirm`. Тесты
  `test_cli_create_meeting_confirm_over_real_tty_creates_exactly_once` и
  `..._network_failure_no_retry_exactly_one_attempt` кодируют рабочую гипотезу — литерал `"да"`
  (регистронезависимо), по аналогии с русскоязычным CLI-текстом остальных сообщений проекта.
  Замена — точечная правка одной строки (`_with_real_pty(monkeypatch, "да")`), сам проверяемый
  сценарий (ровно один POST / ровно одна попытка при сбое) не меняется.
- **Сообщение об ошибке проверяется по подстроке JSON-имени поля** (например, `"roomName" in
  captured.out + captured.err`), не по точному тексту целиком — устойчиво к формулировке
  Dev, но требует, чтобы `MissingFieldError`/CLI-обработчик действительно включали именно
  JSON-имя поля (`roomName`, не `room_name`/«комната») в сообщение, как того явно требует
  NFR-9 AC («с указанием конкретного отсутствующего поля»).
- **`ktalk_list_calendar` вызывается через `tool.fn(...)` напрямую**, минуя
  `get_shared_client()`/полный MCP-транспорт — оправдано тем, что по архитектуре (§5.6)
  проверка `start is None` идёт до получения клиента; если Dev расположит её иначе, тест
  `test_ac_fr18_3_missing_start_rejected_before_network_call` придётся передвинуть на уровень
  `mcp.call_tool(...)` — сигнал об этом даст сам тест (не упадёт на `httpx_mock.get_requests()
  == []`, а раньше, на отсутствии исключения).
- **`get_shared_client()` — процесс-широкий синглтон, не сбрасывается между тестами.** Ни один
  stub этой волны не вызывает MCP-инструменты, которые реально дошли бы до сети через него
  (только `.fn(...)` для чисто структурных/валидационных проверок и `list_tools()` для схемы)
  — осознанное ограничение, чтобы не вносить межтестовую зависимость через глобальное
  состояние, которого до сих пор не было ни у одного теста в проекте.

## Известные конфликты с существующей регрессионной базой

Не обнаружено. Все 163 теста, существовавшие до этой задачи, остаются зелёными (проверено
прогоном `uv run pytest` до и после добавления stubs). Два новых теста этой волны
(`test_nfr6_ten_existing_tools_names_and_required_params_unchanged`,
`test_ac_fr19_3_other_commands_still_require_available_registry` x8 параметров) —
`green (guard)` уже сегодня, не создают конфликта, служат регрессионным снимком на волну.

## Сводка объёма stub-файлов

| Файл | Тест-функций (без параметризации) | Строк |
|---|---|---|
| `tests/test_contour_diagnostics.py` | 9 | 157 |
| `tests/test_rooms.py` | 8 | 172 |
| `tests/test_calendar.py` | 24 | 425 |
| `tests/test_meeting_body.py` | 9 (+10 параметризованных вариантов одного теста) | 195 |
| `tests/test_confirmation.py` | 9 | 131 |
| `tests/test_meeting_scheduling.py` | 6 | 163 |
| `tests/test_cli_meeting.py` | 11 | 257 |
| `tests/test_fr19_auth_status.py` | 4 (+8 параметризованных вариантов одного теста) | 110 |
| `tests/test_public_interface.py` (расширен) | +1 (NFR-6) | +34 |
| `tests/test_secret_masking.py` (расширен) | +3 (NFR-10) | +76 |

Ни один файл не приближается к порогу гейта C13 (`test`, T=600, warn); самое длинное
объявление в пакете — не более ~30 строк (парная метрика T_S=150 не срабатывает нигде).

**Итог прогона на момент написания (до реализации Dev):** `uv run pytest` — 95 failed (red
stubs этой задачи), 172 passed (163 существующих регрессионных теста + 9 новых green-guard:
1×NFR-6 + 8×NFR-19-AC-3-параметризация). `uv run ruff check tests/` — чист.
`bash scripts/check.sh --fast` — `Errors: 0`.

**Итог прогона после реализации Dev и правки двух дефектных стабов (2026-08-14):**
`uv run pytest` — 267 passed, 0 failed, 0 errors (все stubs этой задачи стали green — волна
реализована; правка `test_nfr10_secret_not_in_get_room_error_message`/
`test_nfr10_secret_not_in_calendar_error_message` описана выше в разделе NFR-10). `uv run ruff
check tests/` — чист. `bash scripts/check.sh --fast` — `Errors: 0`.

## Ревизия FR-39 (волна 7, QA-009, 2026-08-19) — включительная правая граница окна

Дополняет секцию «FR-39» выше (таблица покрытия AC). Отдельный failing-stub-файл
`tests/test_fr39_calendar_inclusive_end.py` (не расширение `test_calendar.py` — самостоятельный
дефект боевой поверхности, отдельный от исходной волны 0.6.0, по аналогии с
`test_fr19_auth_status.py`/`test_fr21_no_vault_layout.py`).

**Boundary cases FR-39 (сверх дословных AC):**
- Три однодневных окна на разных позициях многодневного диапазона (начало/середина/конец,
  17/20/23 августа) — не только `start == end` в отрыве от контекста.
- Стык двух смежных сегментов сегментации (17-23 / 24-30) изолирован от правого края всего
  окна отдельным узким тестом — фикс, чинящий только последний сегмент, не проходит.
- Честно пустой день (в фикстуре нет событий вообще) — граница между «нет данных» и «данные
  есть, но граница их не отдаёт» проверяется явно (AC-6, два теста).

**Error cases FR-39 — оба класса, явно:**
- **Испорченный/опечатанный ввод** (целевой пользователь перепутал местами `--start`/`--end`):
  `start > end` — `test_ac5_start_after_end_rejected_before_network_call`. Второй класс
  испорченного ввода для этого требования (например, невалидный формат даты) не добавляется
  здесь отдельно — уже покрыт вне FR-39 (`test_list_calendar_malformed_start_date_fails_closed_not_traceback`,
  `tests/test_cli_meetings_surface.py`), FR-39 узко про перепутанные границы, не про формат.
- **Замаскированный отказ** (система молча отдаёт «пусто» вместо наблюдаемой ошибки): день с
  реальной встречей, потерянной полуоткрытой границей, возвращает код 0 и `items == []` —
  неотличимо от честного «встреч нет» —
  `test_ac6_masked_failure_day_with_real_events_must_not_report_as_honest_empty`.

**Мок — честный, не заготовленный.** `_honest_calendar_callback` в тест-файле вычисляет ответ
по РЕАЛЬНО полученным `start`/`end` из `request.url.params`, применяя `[start 00:00, end 00:00)`
(Ф-60), лимит `(end-start).days<=7` (Ф-63) и текст 400 при `start>end` (Ф-64) — тест ловит
любую реализацию, которая не компенсирует полуоткрытость (включая сегодняшнюю), а не только
конкретную форму будущего фикса.

**Допущение, отменяющее прежнее ограничение волны 0.6.0.** Секция «Допущения» выше фиксировала:
«ни один stub этой волны не вызывает MCP-инструменты, которые реально дошли бы до сети через
`get_shared_client()`» — AC-2 FR-39 требует именно этого (паритет CLI/MCP на честном сетевом
моке). Решение: `monkeypatch.setattr(client_module, "_shared_client", None)` перед каждым
вызовом — `monkeypatch` откатывает изменение автоматически после теста, межтестовой утечки нет
(тот же механизм, которым `test_cli_meetings_surface.py` уже штатно управляет `KTALK_*`
env-переменными). Синглтон не закрывается (`aclose()` не вызывается) — тот же риск уже
принимается самим MCP-сервером на весь процесс его жизни, не новый для тестов.

**Прогон на момент написания (до реализации Dev, DEV-013):** `uv run --with pytest-xdist --with
pytest pytest tests/ -q -n 8` — 9 failed (все стабы этой задачи, `tests/test_fr39_calendar_inclusive_end.py`),
505 passed (весь остальной набор, включая существующий `test_calendar.py`, не тронут).
`bash scripts/check.sh --fast` — см. итог ниже.

**Существующий `test_split_window_single_day_start_equals_end` (`tests/test_calendar.py:80`) —
не тронут, флаг для Dev, не факт дефекта.** Тест сегодня зелёный и проверяет только форму
кортежа сегментов (`split_window(D, D) == [(D, D)]`), не сетевое поведение — он не ловит
дефект FR-39, потому что дефект живёт в том, как `seg_end` подаётся в исключающий параметр
`end` сервера (`_fetch_segment`), не в форме, которую возвращает сама `split_window`. Останется
ли этот тест валидным после ADR-017/DEV-013 — зависит от того, где SA решит разместить
компенсацию полуоткрытости: если она войдёт в `_fetch_segment`/сетевой параметр (значения
`split_window` как календарные даты не меняются) — тест переживёт фикс как есть; если SA
перенесёт исключающую семантику в саму `split_window` (сегменты станут «сетевыми», не
«календарными») — тест сломается и должен быть переписан Dev'ом осознанно, не мной сейчас
(ADR-017 на момент этой задачи не написан).
