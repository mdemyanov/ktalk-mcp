---
title: "AT-design: персональный API-ключ и расширение возможностей"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: персональный API-ключ и расширение возможностей

Тест-дизайн и failing stubs для эпика 0.5.0. Источник AC —
[personal-api-key.md](../30-requirements/personal-api-key.md) (FR-1..FR-11, FR-14, FR-15,
NFR-1..NFR-5). Архитектурный контекст — [ADR-003](../00-project/adr/ADR-003-auth-modes.md) +
[companion-спека](ADR-003-auth-modes-spec.md) (авторизация, диагностика, диспетчер) и
[client-modules-spec.md](client-modules-spec.md) (раскладка модулей, сигнатуры, пагинация,
дообогащение). Stubs — в `tests/`, по одному файлу на функциональную область (гейт C13
`test`: T=600, T_S=150, warn — ни один файл не приближается к порогу).

## Как читать таблицу

- **Тип**: `unit` — чистая функция/мок без сети; `integration` — httpx-мок или реальная SQLite;
  `manual` — требует боевого домена (BA/SA явно пометили; api-key-путь на момент написания
  требования и спек эмпирически не проверен ни разу, зонд Ф-11).
- **Статус**: `red (stub)` — новый failing stub, падает на отсутствии функциональности;
  `green (existing)` — уже покрыто существующим регрессионным тестом, дублирующий stub не
  создавался; `green (guard)` — новый тест, зелёный уже сегодня, служит снимком-регрессией на
  будущее (не тестирует новую функциональность); `manual only` — нет и не будет
  автоматического теста, см. отдельный раздел ниже.

## Покрытие AC

### Группа А — авторизация (FR-1, FR-2, FR-3, FR-4, FR-6, NFR-2)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-1 AC-1 | `KTALK_PERSONAL_API_KEY` задан -> доступен клиенту | `settings.auth_mode == API_KEY`, `settings.auth_credential == <key>` | unit | `test_ac_fr1_1_personal_api_key_available_when_set` / `test_auth_modes.py` | red (stub) |
| FR-1 AC-2 | Ключ отсутствует -> конфигурация грузится без ошибки | `Settings()` не поднимает исключение, `.ktalk_personal_api_key is None` | unit | `test_ac_fr1_2_personal_api_key_absent_no_error_at_load` / `test_auth_modes.py` | red (stub) |
| FR-2 AC-1 | Запрос несёт `X-Auth-Token`, не несёт `sessionToken` | `request.headers["X-Auth-Token"] == key`, `"sessionToken" not in str(request.url)` | integration | `test_ac_fr2_1_apikey_request_has_header_no_query_param` / `test_auth_modes.py` | red (stub) |
| FR-2 AC-2 | Оба заданы -> побеждает ключ, sessionToken нигде не появляется | заголовок = ключ, query без `sessionToken`, session-значение не встречается нигде в запросе | integration | `test_ac_fr2_2_both_set_key_wins_session_never_sent` / `test_auth_modes.py` | red (stub) |
| FR-3 AC-1 | Только session-токен -> поведение как сегодня (регрессия) | `sessionToken` в query, нет `X-Auth-Token` | integration | `test_list_recordings` и др. / `test_client.py` (**существующий, не создавался заново**) | green (existing) |
| FR-3 AC-2 | Ни один не задан -> понятная ошибка, не `KeyError` | `Settings()` не падает, `.auth_mode` поднимает `KTalkConfigError` | unit | `test_ac_fr3_2_neither_set_raises_explicit_config_error_not_keyerror` / `test_auth_modes.py` | red (stub) |
| FR-4 AC-1 | Session-режим: список/детали/транскрипт/саммари работают | — | integration | `test_list_recordings`, `test_get_recording`, `test_get_transcript`, `test_get_summary*` / `test_client.py` (**существующие**) | green (existing) |
| FR-4 AC-2 | Api-key-режим: те же 4 операции работают | путь выбран верно (мок) | unit + manual | `test_ac_fr6_2_apikey_mode_uses_domain_v2_path` (диспетчеризация) / `test_auth_modes.py`; семантика ответа — боевой домен | red (stub) + manual |
| FR-4 AC-3 | Api-key и session дают семантически один набор записей | — | manual | — | manual only |
| FR-6 AC-1 | Session-режим -> внутренний контур (`/api/recordings`) | `/api/recordings` в URL, `/api/Domain` отсутствует | unit | `test_ac_fr6_1_session_mode_uses_internal_list_path` / `test_auth_modes.py` | green (guard) — session-путь уже сегодня `/api/recordings`, тест зелёный сразу, служит регрессией на будущий диспетчер |
| FR-6 AC-2 | Api-key-режим -> `/api/Domain/recordings/v2` | путь в URL | unit + manual | `test_ac_fr6_2_apikey_mode_uses_domain_v2_path` / `test_auth_modes.py`; боевое подтверждение — manual | red (stub) + manual |
| FR-6 AC-3 | Операция без профиля -> явный отказ ДО сети | `OperationNotAvailableError`, `httpx_mock.get_requests() == []` | unit | `test_ac_fr6_3_operation_without_profile_refuses_before_network_call` / `test_auth_modes.py` | red (stub) |
| NFR-2 | Приоритет ключ->сессия->ошибка на всех 4 комбинациях env | 4 сценария подряд на одном тесте | unit | `test_ac_nfr2_priority_order_across_four_env_combinations` / `test_auth_modes.py` | red (stub) |
| — (доп.) | `KTalkClient.from_settings` конфигурирует транспорт один раз | заголовок присутствует на реальном запросе | integration | `test_from_settings_builds_apikey_transport` / `test_auth_modes.py` | red (stub) |

### Группа Б — диагностика (FR-5, FR-11)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-5 AC-1 | 401/403 api-key -> сообщение про `KTALK_PERSONAL_API_KEY`/scope | `KTalkAuthError` матчит `KTALK_PERSONAL_API_KEY`; 403 -> `KTalkScopeError` матчит `application.recording.read` | unit | `test_ac_fr5_1_401_apikey_mentions_personal_api_key_var`, `test_ac_fr5_1b_403_apikey_names_missing_scope` / `test_diagnostics.py` | red (stub) |
| FR-5 AC-2 | 401/403 session -> сообщение про `KTALK_SESSION_TOKEN`, без scope | `KTalkAuthError` матчит `KTALK_SESSION_TOKEN`; 403 не `KTalkScopeError`, не содержит "scope" | unit | `test_ac_fr5_2_401_session_mentions_session_token_var` (уже покрыто существующим поведением, **green** сразу — регрессионный guard), `test_ac_fr5_2b_403_session_generic_access_denied_no_scope_concept` (red — `KTalkScopeError` ещё не существует) / `test_diagnostics.py` | green (guard) + red (stub) |
| FR-5 AC-3 | Тело не JSON -> читаемое сообщение без трейсбэка | `"Traceback" not in str(exc)`, сырой HTML не просачивается | unit | `test_ac_fr5_3_unparseable_error_body_still_readable_message` / `test_diagnostics.py` | red (stub) |
| — (доп.) | 403 с пустым телом не ломает классификацию | `KTalkScopeError` поднимается даже при `content=b""` | unit | `test_diagnostics_403_empty_body_does_not_break_classification` / `test_diagnostics.py` | red (stub) |
| FR-11 AC-1 | Api-key: `access-info` -> живой запрос, scopes+expiredAt | `status.alive is True`, `status.scopes is not None`, реальный запрос к `access-info` в моке | integration + manual | `test_ac_fr11_1_auth_status_apikey_full_scopes` / `test_diagnostics.py`; боевое подтверждение пути — manual | red (stub) + manual |
| FR-11 AC-2 | Истёкший ключ -> результат, не исключение | `get_auth_status()` не поднимает исключение, `status.alive is True` | integration + manual | `test_ac_fr11_2_auth_status_apikey_expired_key_still_returns_result` / `test_diagnostics.py`; боевое поведение API — manual | red (stub) + manual |
| FR-11 AC-3 | Session: честный ответ, реальный probe | `status.scopes is None`, `status.note` объясняет, реальный запрос к `/api/recordings` в моке | integration | `test_ac_fr11_3_auth_status_session_mode_real_probe_not_fake` / `test_diagnostics.py` | red (stub) |
| — (доп.) | `access-info` 403 -> деградация (`alive=True`, `scopes=None`) | сценарий деградации ADR-003-spec | integration | `test_auth_status_apikey_403_degrades_alive_true_scopes_none` / `test_diagnostics.py` | red (stub) |
| — (доп.) | `access-info` 401 -> ключ мёртв | `status.alive is False` | integration | `test_auth_status_apikey_401_key_dead` / `test_diagnostics.py` | red (stub) |
| — (доп.) | Сетевая ошибка ≠ "ключ мёртв" | исключение пробрасывается, не `AuthStatus(alive=False)` | integration | `test_auth_status_network_error_is_not_reported_as_dead_key` / `test_diagnostics.py` | red (stub) |

### Группа В — нормализация и пагинация (FR-9, FR-14)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-9 AC-1 | Окно дат + границы пагинации 1-100 (боевой домен) | — | manual | — | manual only |
| FR-9 AC-2 | Архив читается полностью за пределами одной страницы | `len(meetings) == <весь набор>`, `len(requests) > 1` | integration | `test_ac_fr9_2_archive_reads_beyond_single_page` / `test_pagination.py` | red (stub) |
| FR-9 AC-3 | Session-режим -> явное сообщение "архив только в api-key", без сети | `OperationNotAvailableError` матчит "архив", 0 запросов | unit | `test_ac_fr9_3_session_mode_archive_explicit_message_not_raw_401` / `test_archive.py` | red (stub) |
| FR-9 AC-4 | Фильтр по комнатам (боевой домен) | — | manual | — | manual only |
| FR-14 AC-1 | `top` никогда не выходит за 1-100 (регрессия `top=1000`) | `1 <= int(qs["top"]) <= 100` на реальном исходящем запросе | integration | `test_ac_fr14_1_sync_never_sends_top_over_100` / `test_pagination.py` | red (stub) |
| FR-14 AC-2 | `skip`-пагинация продолжается до пустой страницы | 2 запроса (полная + пустая), реестр содержит все 100 записей | integration | `test_ac_fr14_2_skip_pagination_continues_past_first_page_to_empty` / `test_pagination.py` | red (stub) |
| FR-14 AC-3 | Окно >100 записей -> все в реестре | `len(reg.list_recordings()) == 250` (3 страницы: 100+100+50) | integration | `test_ac_fr14_3_sync_window_over_100_records_all_present_in_registry` / `test_pagination.py` | red (stub) |
| — (доп.) | `paginate_pages` термination-логика (пседокод) | пустая первая страница, falsy-курсор после items | unit | `test_paginate_pages_empty_first_page_returns_zero_pages`, `test_paginate_pages_stops_on_falsy_cursor_after_yielding_items` / `test_pagination.py` | red (stub) |
| — (доп.) | Полная последняя страница -> один лишний запрос (по дизайну) | `calls == [0, 2]`, цикл корректно завершается | unit | `test_skip_pages_full_last_page_makes_one_extra_empty_request` / `test_pagination.py` | red (stub) |
| — (доп.) | Нормализация session-формы -> единая внутренняя форма | `NormalizedPage.items`/`.cursor` по правилу «полная/короткая/пустая страница» | unit | `test_normalize_list_session_*` (3 теста) / `test_pagination.py` | red (stub) |
| — (доп.) | Нормализация api-key-формы -> единая внутренняя форма | курсор из `nextPageToken`; `null` и отсутствующее поле эквивалентны | unit | `test_normalize_list_apikey_*` (2 теста, один параметризован x2) / `test_pagination.py` | red (stub) |

### Группа Г — расширение возможностей (FR-7, FR-8, FR-10)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-7 AC-1 | Session: скачивание по `qualities[].fileUrl` (боевой поток) | — | manual | — | manual only |
| FR-7 AC-2 | `900p`/`900 p` не ломают URL, дают одинаковый результат | `build_download_url(k,"900p") == build_download_url(k,"900 p")`, без пробела в URL | unit | `test_build_download_url_quotes_space_correctly`, `test_ac_fr7_2_quality_with_and_without_space_produce_same_url` / `test_download.py` | red (stub) |
| FR-7 AC-3 | Незапрошенное качество -> читаемая ошибка со списком доступных | текст исключения содержит доступные качества | integration | `test_ac_fr7_3_unknown_quality_gives_readable_message_with_available_list` / `test_download.py` | red (stub) |
| FR-7 AC-4 | Потоковая передача, не полная буферизация | файл на диске побайтово совпадает с payload; см. примечание ниже | integration | `test_ac_fr7_4_download_streams_to_disk_without_full_content_response` / `test_download.py` | red (stub) — см. примечание |
| FR-8 AC-1 | Дообогащение при `participants < participantsCount` (строго `<`) | дообогащённый список из 6 -> 8 через `get_recording`; при равенстве — сети нет | unit + integration | `test_ac_fr8_1_*`, `test_ac_fr8_1b_*` / `test_enrichment.py` | red (stub) |
| FR-8 AC-2 | Анонимный участник не отбрасывается | `map_participants([...]) == [{"ktalk_id": "anon-1", "name": "Гость 1"}]` | unit | `test_ac_fr8_2_anonymous_participant_not_dropped` / `test_enrichment.py` | red (stub) |
| FR-8 AC-3 | >10 участников -> все присутствуют (боевой домен) | синтетическая проверка механизма (dual-source + `incomplete`) автоматическая; реальный случай >10 — ручной | integration + manual | `test_ac_fr8_3_dual_source_merge_dedups_and_flags_incomplete` / `test_enrichment.py`; боевой случай — manual | red (stub) + manual |
| FR-9/FR-10 (доп.) | Частичный отказ в fan-out не роняет остальные | 500 на одной записи, вторая успешно дообогащается | integration | `test_enrich_batch_partial_failure_does_not_abort_others` / `test_enrichment.py` | red (stub) |
| — (доп.) | `map_participants` совместим по схеме с `participants_from_api` | `== [{"ktalk_id": "u1", "name": "Иванов Пётр"}]` | unit | `test_map_participants_named_user_matches_participants_from_api_schema` / `test_enrichment.py` | red (stub) |
| FR-10 AC-1 | Session: известный канал -> сообщения через историю встречи (боевой домен) | — | manual | — | manual only |
| FR-10 AC-2 | Канал не указан -> клиент резолвит доступные каналы, не 400 | запрос идёт с `channel=general`, результат не пуст | integration | `test_ac_fr10_2_missing_channel_resolves_available_channels_first` / `test_chat.py` | red (stub) |
| FR-10 AC-3 | Api-key: отчётный путь профиля (боевой домен) | — | manual | — | manual only |
| FR-10 AC-4 | 403 на конкретном канале -> сообщение о нехватке прав | текст содержит имя канала + "прав" | integration | `test_ac_fr10_4_forbidden_channel_gives_readable_permission_message` / `test_chat.py` | red (stub) |
| — (доп.) | Оркестрация `recording_key -> conferenceKey -> канал -> сообщения` | цепочка из 3 запросов даёт результат | integration | `test_get_chat_messages_resolves_conference_key_from_recording_key` / `test_chat.py` | red (stub) |

### Группа Д — сверка идентификаторов (FR-15) и секрет (NFR-5)

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| FR-15 AC-1 | Сверка множеств id перед первым api-key sync | `compare_id_sets` находит полное совпадение / расхождение по обеим сторонам | unit + manual | `test_ac_fr15_1_compare_id_sets_full_match`, `test_ac_fr15_1b_compare_id_sets_detects_mismatch` / `test_reconciliation.py`; обязательный ручной прогон на боевом домене — manual (README) | red (stub) + manual |
| FR-15 AC-2 | Расхождение блокирует боевой sync без решения оператора | `ktalk sync --dry-run` при расхождении -> `rc != 0`, реестр не изменён | integration + manual | `test_ac_fr15_2_dry_run_mismatch_blocks_sync_without_confirmation` / `test_reconciliation.py`; см. примечание про допущение UX ниже | red (stub) + manual |
| FR-15 AC-3 | Совпадение -> обычная синхронизация может выполняться | `ktalk sync --dry-run` при совпадении -> `rc == 0` | integration (частично) + manual | `test_ac_fr15_3_dry_run_full_match_allows_proceeding` / `test_reconciliation.py`; BA пометил AC целиком ручной — manual | red (stub) + manual |
| — (доп.) | Пустой реестр -> явное сообщение "нет данных", не тихий OK | JSON-вывод содержит соответствующий текст | integration | `test_dry_run_on_empty_registry_reports_no_data_not_silent_ok` / `test_reconciliation.py` | red (stub) |
| NFR-5 | Ключ не в исключениях/логах/CLI-выводе (представительный набор) | `SECRET not in str(exc)`, `not in captured.out/.err` (текст, `--json`, `auth-status`) | integration | `test_secret_not_in_auth_error_message`, `test_secret_not_in_generic_exception_str_or_repr`, `test_secret_not_in_auth_status_cli_output` / `test_secret_masking.py` | red (stub) |
| NFR-5 (доп.) | То же, `ktalk sync` в текстовом/`--json` режиме | `SECRET not in captured.out/.err` | integration | `test_secret_not_in_cli_text_output`, `test_secret_not_in_cli_json_output` / `test_secret_masking.py` | green (vacuous) — сегодня `sync` падает раньше на `Settings()` (нет `KTALK_SESSION_TOKEN`), секрет и не должен там появиться; тест начнёт проверять реальный путь с ключом после FR-1/FR-3 (поля Settings становятся опциональными) |

### NFR-1, NFR-3, NFR-4 — вне таблиц выше

| AC ID | Формулировка (кратко) | Assertion outline | Тип | Тест-функция / файл | Статус |
|---|---|---|---|---|---|
| NFR-1 | Имена/обязательные параметры 5 инструментов не меняются | снимок `mcp.list_tools()` до/после (`required` из JSON-схемы) | integration | `test_nfr1_five_existing_tool_names_and_required_params_unchanged` / `test_public_interface.py` | green (guard) — уже проходит сегодня, служит регрессионным снимком на весь эпик |
| NFR-3 | `pytest`+`ruff` оба завершаются кодом 0 | — | gate | `bash scripts/check.sh --fast` (нет отдельного pytest-stub — бессмысленно проверять «pytest зелёный» изнутри pytest) | N/A — покрыто гейтом, не тестом |
| NFR-4 | README описывает ключ/ротацию/отличия | текстовое ревью README | manual | — | manual only |

## Boundary cases (сверх дословных формулировок AC)

- Полная последняя страница `skip`-пагинации -> один лишний (пустой) запрос по дизайну — тест
  подтверждает, что это не бесконечный цикл и не off-by-one (`test_skip_pages_full_last_page_makes_one_extra_empty_request`).
- `nextPageToken: null` явно в JSON vs отсутствующее поле — оба эквивалентны «последняя
  страница» (`test_normalize_list_apikey_no_cursor_when_token_null_or_absent`, параметризован).
- `participantsCount == len(participants)` ровно — НЕ должно запускать дообогащение (строгое
  `<`, не `<=`) — `test_ac_fr8_1b_no_enrichment_when_participants_count_matches_exactly`.
- `access-info` 403 — трактуется как «ключ жив», инверсия интуиции («403 обычно серьёзнее 401») —
  явно протестировано отдельно от «ключ мёртв» (`test_auth_status_apikey_403_degrades_alive_true_scopes_none`).
- Пустая страница на первой же попытке (архив/список без записей в окне) —
  `test_paginate_pages_empty_first_page_returns_zero_pages`.
- Дообогащение участников: `get_recording` и `get_conference` дают частично пересекающиеся,
  частично разные множества — дедуп по ключу участника (`userInfo.key`/`anonymousId`), не по
  позиции в массиве (`test_ac_fr8_3_dual_source_merge_dedups_and_flags_incomplete`).

## Error cases

- 401/403 без валидного JSON-тела — не должны приводить к сырому трейсбэку
  (`test_ac_fr5_3_unparseable_error_body_still_readable_message`).
- 403 с пустым телом (Content-Length: 0, зонд Ф-12) — диагностика всё равно работает
  (`test_diagnostics_403_empty_body_does_not_break_classification`).
- Операция без профиля для текущего режима — управляемый отказ до сети, не голый 401/403
  (`test_ac_fr6_3_*`, `test_ac_fr9_3_*`).
- Сетевая ошибка/таймаут при `auth_status` — отдельный класс отказа, не путается с «ключ мёртв»
  (`test_auth_status_network_error_is_not_reported_as_dead_key`).
- Частичный отказ в конкурентном дообогащении (500 на одной записи из N) — остальные
  дозавершаются (`test_enrich_batch_partial_failure_does_not_abort_others`).
- Запрошенное качество скачивания отсутствует в списке — читаемое сообщение, не необработанное
  исключение (`test_ac_fr7_3_*`).
- 403 на конкретном чат-канале — сообщение называет канал (`test_ac_fr10_4_*`).

## Не покрываем автоматически (нужна боевая проверка)

Все ниже помечены BA/SA как ручная проверка, преимущественно по одной причине: персональный
API-ключ на момент BA/SA-работы был выдан без `application.recording.read`/`.reporting.read`/
`.applications.read` (зонд Ф-11) — ни один api-key-путь эпика не проверен эмпирически ни разу.

| AC | Почему нельзя автоматизировать сейчас |
|---|---|
| FR-4 AC-2 (частично), AC-3 | Семантическая эквивалентность записей между режимами — требует живого сравнения на боевом домене, не воспроизводима фикстурой |
| FR-6 AC-2 (частично) | Диспетчеризация по пути протестирована (мок); что реальный `/api/Domain/recordings/v2` под ключом действительно отвечает 200 и валидной формой — не проверено (Ф-11) |
| FR-7 AC-1 | Реальный поток скачивания в session-режиме зондом не проверялся, только наличие поля `qualities[].fileUrl` |
| FR-8 AC-3 (частично) | Дедуп-механизм и флаг `incomplete` протестированы синтетически; реальная запись с `participantsCount > 10` зондом не найдена (проверено только 8 из 8) |
| FR-9 AC-1, AC-4 | Архив — весь api-key-путь непроверен эмпирически; фильтр по комнатам — то же |
| FR-10 AC-1, AC-3 | Session-чат — зонд подтвердил конкретный запрос, не весь маппинг ответа; api-key-чат — путь не проверен |
| FR-11 AC-1, AC-2 (частично) | Механизм автоматизирован на моке; реальный ответ `access-info` (включая поведение для истёкшего ключа) не подтверждён |
| FR-15 AC-1 (частично), AC-2 (частично), AC-3 | Сама механика сравнения id автоматизирована; совпадают ли `id` между контурами реально — открытый блокирующий риск требования, проверяется только на боевом домене перед первым api-key sync (обязательная процедура, README) |
| NFR-4 | README — текстовый документ, ревью читаемости не автоматизируется |

## Допущения, требующие внимания Dev (не баги AC, а решения по контракту вызова)

Указаны там, где ни одна спека не фиксирует сигнатуру дословно — тесты кодируют рабочую
гипотезу, взятую из ближайшего доступного текста спек; замена — точечная правка импорта/вызова
в тесте, сам проверяемый сценарий не меняется:

- Расположение `AuthMode`/`KTalkConfigError` — `ktalk_mcp.config`; `AuthContext`,
  `OperationNotAvailableError`, `KTalkScopeError`, нормализаторы (`normalize_list_session`,
  `normalize_list_apikey`) — `ktalk_mcp.client` (сгруппированы по ADR-003-spec «Модель данных»).
- `AuthStatus.alive`/`.scopes`/`.expired_at`/`.note` — имена `alive`/`scopes`/`note` дословно из
  ADR-003-spec (таблица деградации + фраза «AuthStatus.note всегда объясняет...»); `expired_at`
  (snake_case) — по аналогии с остальными полями `NormalizedRecording`.
- `KTalkClient(base_url, session_token=None, personal_api_key=None)` — обратная совместимость с
  существующими вызовами (`session_token=` как раньше), `personal_api_key=` новый kwarg.
- `skip_pages(fetch, page_size)` — сигнатура `fetch(skip, top) -> {"recordings": [...]}` — рабочая
  гипотеза по псевдокоду client-modules-spec §5, не зафиксирована дословно.
- `download_recording_file(client, recording_key, target_path, quality)` /
  `build_download_url(recording_key, quality)` — вызовы в тестах позиционные, чтобы не зависеть
  от точных имён kwarg.
- FR-15 AC-2/AC-3 (UX подтверждения оператора) — требование не фиксирует механизм «осознанного
  решения оператора» после расхождения/совпадения; тесты используют exit-код `ktalk sync --dry-run`
  как gate (0 = можно продолжать, не 0 = заблокировано), по аналогии с уже принятым в проекте
  паттерном `show --json` (`rc=1` при ошибке). Если SA/Dev спроектируют отдельный флаг
  подтверждения — правка сценария теста, не самого AC.
- FR-7 AC-4 (потоковая передача) — тест доказывает наблюдаемое поведение (файл на диске
  побайтово корректен для payload'а, который не поместился бы в типичный единичный буфер), не
  отсутствие буферизации на уровне памяти напрямую — это достижимый автоматический прокси,
  а не полная гарантия (сама ADR-003-spec относит эту AC к уровню integration «без реальной
  сети — мок-стрим», не к профилированию памяти).

## Известные конфликты с существующей регрессионной базой (не трогать, только фиксировать)

- **`tests/test_config.py::test_settings_requires_session_token`** ожидает, что `Settings()` без
  `KTALK_SESSION_TOKEN` поднимает исключение при самом конструировании. Архитектура ADR-003
  требует ОБРАТНОГО: `ktalk_session_token`/`ktalk_personal_api_key` становятся `str | None = None`
  (оба опциональны на уровне полей), а ошибка (`KTalkConfigError`) поднимается только при
  обращении к `.auth_mode`. Это прямое противоречие: после реализации FR-1..FR-3 существующий
  тест перестанет проходить (`Settings()` больше не будет падать сама по себе). Это не наша
  правка (red line — существующие тесты не трогаем), фиксируется как решение для BA/SA/Dev:
  либо тест меняется вместе с реализацией (осознанно, в PR эпика, с объяснением в описании ПР),
  либо `Settings()` обязана продолжать поднимать исключение немедленно при отсутствии обеих
  переменных — тогда `KTalkConfigError` при `.auth_mode` избыточен и AC FR-3/2 нужно
  переформулировать. QA-author не решает это сам — выносит в отчёт.
- **`tests/test_cli.py::test_sync_inserts_dedups_and_expires`** — не связано с этим эпиком:
  тест уже красный на исходном (до этой задачи) коде из-за зависимости от `date.today()`
  (создан с расчётом на "сегодня" около дат фикстур; при текущей системной дате запись `fresh`
  с `createdDate=2026-06-25` тоже считается протухшей и попадает в `expired`). Подтверждено
  `git stash` прогоном на чистом коммите до этой задачи — обнаружено, не создано.

## Сводка объёма stub-файлов

| Файл | Тест-функций | Строк (примерно) |
|---|---|---|
| `tests/test_auth_modes.py` | 10 | ~215 |
| `tests/test_diagnostics.py` | 12 | ~225 |
| `tests/test_pagination.py` | 12 (2 параметра x1) | ~290 |
| `tests/test_enrichment.py` | 6 | ~165 |
| `tests/test_download.py` | 4 | ~95 |
| `tests/test_chat.py` | 3 | ~85 |
| `tests/test_archive.py` | 1 | ~30 |
| `tests/test_reconciliation.py` | 5 | ~150 |
| `tests/test_secret_masking.py` | 5 | ~110 |
| `tests/test_public_interface.py` | 1 | ~35 |

Ни один файл не приближается к порогу гейта C13 (`test`, T=600); самое длинное объявление в
пакете — не более ~30-40 строк (парная метрика T_S=150 не срабатывает нигде).
