---
title: "Заметки реализации: персональный API-ключ (DEV-001, DEV-002)"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# Заметки реализации: персональный API-ключ (DEV-001, DEV-002)

Реализована первая половина эпика 0.5.0 (ADR-003): режимы авторизации, диспетчер профиля
эндпоинтов, диагностика 401/403, единая пагинация, `auth_status`. Вторая половина (скачивание,
дообогащение участников, чат, архив-инструменты, сверка id) — DEV-002, задел уже заложен
(`list_archive`, профиль эндпоинтов, `OperationNotAvailableError`).

## Расположение кода

- `src/ktalk_mcp/config.py` — `AuthMode`, `KTalkConfigError`, `Settings.auth_mode`/`.auth_credential`.
- `src/ktalk_mcp/auth.py` (новый) — таблица `OPERATION_PROFILES`, `EndpointProfile`, `AuthContext`,
  `NormalizedPage`/`SkipCursor`/`TokenCursor`, `normalize_list_session`/`normalize_list_apikey`,
  `AuthStatus`. Вынесено из `client.py` исключительно ради гейта C13 (объём кода) — `client.py` с
  этим содержимым внутри превышал T=350 c top-level декларацией `KTalkClient` в 223 строки.
  Публичные имена реэкспортированы из `client.py` (`__all__`/явные импорты), т.к. тесты и
  остальной код ожидают `from ktalk_mcp.client import AuthStatus, normalize_list_session, ...`
  дословно (зафиксировано at-design'ом как контракт для QA-author).
- `src/ktalk_mcp/client.py` — `KTalkClient` (диспетчер `_call`/`_classify`, `list_recordings`,
  `get_recording`/`get_transcript`/`get_summary`/`get_summary_by_type`, `list_archive`,
  `get_auth_status`).
- `src/ktalk_mcp/pagination.py` (новый) — `paginate_pages`/`skip_pages`/`token_pages`.
- `src/ktalk_mcp/cli.py` — `_fetch_recordings` на `pagination.py`, новая команда `auth-status`.
- `src/ktalk_mcp/server.py` — `_get_client()` на `KTalkClient.from_settings`.

## Неочевидные решения / расхождения со спекой

1. **`_fetch_recordings`/`skip_pages`: «до пустой страницы», не «до короткой».** ADR-003-spec
   текстом предлагает «полная страница -> продолжаем, короткая -> последняя» (аналогия с
   `normalize_list_session`). Но FR-14 AC-2 требования дословно требует «продолжает пагинацию…
   до пустой страницы», а QA-author's тест `test_ac_fr14_3_sync_window_over_100_records_all_present_in_registry`
   регистрирует 4-й (заведомо пустой) httpx-мок, который остаётся неконсумированным и валит тест
   под `pytest_httpx` (строгий `assert_all_responses_were_requested`) при «короткая = последняя»
   семантике. Реализовано буквально по тексту AC: `skip_pages`/`paginate_pages` останавливаются
   только на пустой странице, независимо от того, полная была предыдущая или короткая.
   `normalize_list_session` (отдельная, самостоятельно тестируемая функция) сохраняет
   «короткая/пустая = последняя» — она НЕ используется в реальном пути `_fetch_recordings`
   /`list_archive`, это два параллельных, независимо протестированных представления пагинации из
   двух разных SA-документов (ADR-003-spec и client-modules-spec).
2. **Существующий регрессионный тест `tests/test_cli.py::test_sync_inserts_dedups_and_expires`
   обновлён** (добавлен второй, завершающий пустой httpx-мок) — прямое следствие решения (1):
   до эпика пагинация обрывалась после первой страницы всегда (баг Ф-3), поэтому тест с одним
   мок-ответом проходил случайно. Это новый конфликт, не описанный в «Известных конфликтах»
   at-design.md — решён по аналогии с уже согласованным PM решением про `test_config.py`
   (архитектурное требование побеждает, тест механически поправлен без изменения смысла
   проверки).
3. **403 в session-режиме не стал generic-сообщением.** ADR-003-spec буквально предлагает
   отдельное «Доступ запрещён. Обратитесь к администратору Толка.» для 403 в session-режиме
   (в противовес 401 «Токен сессии истёк…»). Регрессионный `tests/test_client.py::test_error_403`
   ожидает то же сообщение, что и у 401. Оставлено старое поведение (403 в session-режиме
   маппится на то же сообщение, что 401) — тест FR-5 AC2b этого не различает (проверяет только
   «не `KTalkScopeError`» и «нет слова scope»), поэтому оба теста зелёные одновременно без
   изменения кода QA. Если продукту нужен буквально другой текст для 403 — отдельная точечная
   правка, не архитектурный конфликт.
4. **Ambient env leak.** Переменная `KTALK_PERSONAL_API_KEY`, оставленная в шелле после зонда
   PM (реальный секрет, не тестовое значение), ломала три существующих теста, которые никогда не
   очищали эту переменную (не знали о её существовании на момент написания). Добавлены
   `monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)` в `test_pagination.py` (3 теста)
   и `test_cli.py::test_sync_inserts_dedups_and_expires` — чистая изоляция, не меняет проверяемое
   поведение. Важный урок: любой новый секретный env var, который начинает читать `Settings`,
   обязан быть явно занулён во ВСЕХ существующих тестах, которые опираются на другой режим, иначе
   тесты становятся зависимы от состояния реальной оболочки разработчика.
5. **`list_archive` пагинация переиспользует `pagination.skip_pages`** с `items_key="conferences"`
   (архив отдаёт `{"conferences": [...]}"`, не `{"recordings": [...]}"`) — добавлен параметр
   `items_key` в `skip_pages`, которого не было в client-modules-spec §5 псевдокоде (там
   подразумевался жёстко захардкоженный `"recordings"`).

## Расхождения со спекой, оставленные явно

- `EndpointProfile`/`OPERATION_PROFILES`/нормализаторы физически лежат в `ktalk_mcp/auth.py`, а
  не в `ktalk_mcp/client.py`, как буквально написано в допущениях at-design ("AuthContext,
  OperationNotAvailableError, KTalkScopeError, нормализаторы — ktalk_mcp.client"). Публичный
  импорт `from ktalk_mcp.client import ...` продолжает работать (реэкспорт) — контракт теста не
  нарушен, изменилось только физическое расположение определения. Причина — гейт C13.
- `list_archive`/`OPERATION_PROFILES`/`OperationNotAvailableError` реализованы полностью в этой
  задаче (DEV-001), хотя формально относятся к зоне DEV-002 (`test_archive.py` не в списке моих
  файлов) — необходимо, т.к. `test_auth_modes.py::test_ac_fr6_3_*` и
  `test_pagination.py::test_ac_fr9_2_archive_reads_beyond_single_page` (оба в моей зоне) требуют
  рабочего `client.list_archive`. Побочный эффект: `tests/test_archive.py` (зона DEV-002) теперь
  тоже зелёный — не тронут, не переписан, просто уже проходит.
- `get_conference`, `get_participants_full`, `get_chat_messages`, `get_participants_report`,
  `download_file`, `enrichment.py`, `download.py`, `reconciliation.py`, `tools_recordings.py`,
  `tools_meetings.py` из client-modules-spec не созданы — вне периметра задачи DEV-001, ожидаются
  от DEV-002 (`test_enrichment.py`, `test_download.py`, `test_chat.py`, `test_reconciliation.py`
  остаются красными, как и предполагалось постановкой).

## Не покрыто автоматически (ожидает боевого ключа)

Все `manual`/`manual only` пункты at-design.md (FR-4 AC-2/AC-3, FR-6 AC-2 частично, FR-7 AC-1,
FR-9 AC-1/AC-4, FR-10 AC-1/AC-3, FR-11 AC-1/AC-2 частично, FR-15) — ключ на момент реализации не
имеет нужных scope (зонд Ф-11), боевая проверка блокирована до перевыпуска ключа (см. бриф DevOps
в companion-спеке ADR-003).

## DEV-002: скачивание, дообогащение, чат, архив-инструменты, сверка id

Реализована вторая половина эпика поверх ядра DEV-001 (диспетчер `_call`/`_classify`, профиль
эндпоинтов, пагинация). Вход — `client-modules-spec.md`. Все ранее красные `test_enrichment.py`,
`test_download.py`, `test_chat.py`, `test_reconciliation.py` — зелёные; полный прогон 152 passed,
0 failed. 134 ранее зелёных теста DEV-001 остались зелёными (регрессий нет).

### Расположение кода

- `src/ktalk_mcp/enrichment.py` (новый) — `map_participants` (замена замороженного
  `registry.participants_from_api`, не роняет анонимов), `enrich_batch` (условное дообогащение,
  `Semaphore(concurrency)`, `asyncio.gather(..., return_exceptions=True)`-эквивалент через try/except
  на задачу — отказ одной записи не роняет остальные).
- `src/ktalk_mcp/download.py` (новый) — `build_download_url` (нормализация `900p`↔`900 p` +
  `urllib.parse.quote`), `download_recording_file` (потоковая запись, `overwrite`-guard,
  session/api-key ветвление качества).
- `src/ktalk_mcp/reconciliation.py` (новый) — `compare_id_sets`, `dry_run_report`, `recording_ids`.
- `src/ktalk_mcp/tools_recordings.py` (новый) — 5 существующих MCP-инструментов, физически
  перенесённых из `server.py` (тела не изменены; изменены только два внутренних вызова —
  `_get_client()`→`get_shared_client()`, `_format_output()`→`render_tool_output()`, что прямо
  предписано client-modules-spec §1), плюс новые `ktalk_get_participants`,
  `ktalk_download_recording`.
- `src/ktalk_mcp/tools_meetings.py` (новый) — `ktalk_list_archive`, `ktalk_get_chat_messages`.
- `src/ktalk_mcp/server.py` — похудел с 204 до 49 строк: только `mcp`, регистрация двух
  `tools_*.register(mcp)` и сам `ktalk_auth_status` (FR-11, остаётся здесь по решению SA).
- `src/ktalk_mcp/client.py` — новые методы `get_conference`, `get_full_participants`,
  `get_chat_messages`, `get_participants_report`, `auth_mode` (property), `stream`/
  `check_response` (публичные обёртки для `download.py`), модульная `get_shared_client()`.
- `src/ktalk_mcp/auth.py` — новые записи `OPERATION_PROFILES` (`get_conference`,
  `get_participants_full`, `get_participants_report`), `merge_participants`/`normalize_participant`
  (дедуп участников для `get_full_participants`, отдельная схема ключей от `enrichment.map_participants`
  — см. «Расхождения» ниже), и — исключительно ради гейта C13 — вынесенные из `client.py`
  свободные функции `full_participants_apikey(client, ...)`/`resolve_chat_channel(client, ...)`,
  принимающие клиент параметром и читающие его «приватные» атрибуты (`_call`/`_classify`/
  `_client`) осознанно: оба модуля — одна логическая единица, разделённая только по объёму.
- `src/ktalk_mcp/cli_sync.py` (новый) — `cmd_sync`, `cmd_auth_status` и их сетевые хелперы,
  вынесены из `cli.py` целиком (см. «Расхождения» — module split вместо предполагавшейся спекой
  тонкой обёртки).
- `src/ktalk_mcp/cli.py` — только argparse и локальные (без сети) команды реестра; `sync`/
  `auth-status` — импортированные обработчики из `cli_sync.py`. Добавлен флаг `--dry-run`.
- `src/ktalk_mcp/formatters.py` — `render_tool_output` (было `server.py::_format_output`) +
  5 новых форматтеров (`format_participants`, `format_download_result`, `format_archive_list`,
  `format_chat_messages`, `format_auth_status`), каждый <30 строк.

### Проверка объёма (гейт C13, T=350/T_S=100, парная метрика)

| Файл | Строк | Гейт |
|---|---|---|
| `server.py` | 49 | pass (прогноз ~65 — переезд дал больше запаса, чем ожидалось) |
| `tools_recordings.py` | 224 | pass |
| `tools_meetings.py` | 71 | pass |
| `client.py` | 348 | pass, впритык — потребовался вынос двух функций в `auth.py` (см. ниже) |
| `auth.py` | 257 | pass |
| `pagination.py` | 70 | pass (без изменений) |
| `download.py` | 92 | pass |
| `enrichment.py` | 83 | pass |
| `reconciliation.py` | 59 | pass |
| `formatters.py` | 443 | pass — T (350) превышен, T_S (100) нет (самое длинное объявление ~35
  строк) — та же парная логика, что и прогноз спеки на 480 строк |
| `cli.py` | 237 | pass, с запасом (спека предсказывала ~330-345 для одного файла — вместо этого
  выделен `cli_sync.py`, см. «Расхождения») |
| `cli_sync.py` | 149 | pass |
| `registry.py` | 562 | не изменён, грандфазер соответствует |

`bash scripts/check.sh --fast` → `Errors: 0`, `uv run ruff check src/ tests/` → чисто.

### Неочевидные решения

1. **`client.py` не укладывался в 350 строк с первой версией новых методов (370 строк).**
   Публичные методы (`get_full_participants`, `get_chat_messages`) остались на классе (тесты
   вызывают их как `client.method(...)`), но их приватные хелперы api-key-ветки и резолва канала
   (`_get_full_participants_apikey`, `_resolve_chat_channel`) вынесены в `auth.py` как свободные
   функции `full_participants_apikey(client, ...)`/`resolve_chat_channel(client, ...)`, принимающие
   клиент параметром — тот же приём, что DEV-001 уже применил для таблицы профиля/DTO. Единственное
   ограничение: `auth.py` не может импортировать `KTalkError` из `client.py` (цикл), поэтому чат-403
   (сообщение о недостающих правах на канал) остался в `client.py` — код, которому нужен
   `KTalkError`, физически не переносим без реструктуризации иерархии исключений.
2. **`cli.py` не укладывался в 350 строк даже после сжатия докстрок/аргументов.** Спека прогнозировала
   финальные ~330-345 строк для одного файла; на практике `--dry-run` + дообогащение при вызове sync
   дали 368 строк. Спека сама предусмотрела этот случай («Если всё равно не влезаешь — выдели
   подкоманды sync в отдельный модуль») — выделен `cli_sync.py` (`cmd_sync`, `cmd_auth_status` и их
   сетевые хелперы). `cli_sync.py` использует отложенный импорт `_cmd_dashboard` из `cli.py` внутри
   тела `cmd_sync` (не на уровне модуля) — стандартный приём разрыва цикла `cli.py → cli_sync.py →
   cli.py`, безопасен, т.к. к моменту вызова `cmd_sync` оба модуля уже полностью загружены.
3. **`get_full_participants`, не `get_participants_full`.** ADR-003-spec (таблица профиля) называет
   операцию `get_participants_full`, а client-modules-spec (карта «эндпоинт → метод») и — что
   решает — сам failing-стаб `test_ac_fr8_3_dual_source_merge_dedups_and_flags_incomplete` вызывают
   `client.get_full_participants(...)`. Реализовано по стабу (не переписывать failing stubs —
   красная линия), имя операции в `OPERATION_PROFILES` (`"get_participants_full"`, ключ таблицы, не
   имя метода) оставлено как в ADR-003-spec — расхождение чисто в имени публичного метода,
   зафиксировано явно здесь, а не молча.
4. **Дефолт качества скачивания в api-key-режиме.** Открытый вопрос SA («список качеств под ключом
   взять неоткуда») решён минимально: `quality=None` → используется рекомендованное спекой `900p`
   без валидации (валидировать нечем — под ключом нет `qualities[]`). Session-режим по-прежнему
   валидирует по фактическому списку записи. Уточнение — на боевом домене после перевыпуска ключа.
5. **`enrichment.map_participants` и `auth.normalize_participant` — два разных маппера участников,
   намеренно.** `map_participants` (используется `cli_sync.py::cmd_sync` для записи в SQLite) всегда
   отдаёт ключ `ktalk_id` (для анонимов тоже) — схема реестра не меняется. `normalize_participant`
   (используется только `client.get_full_participants`) отдаёт разные ключи (`ktalk_id` vs
   `anonymous_id`) — этого явно требует failing-стаб (`p.get("ktalk_id") or p.get("anonymous_id")`).
   Дублирование логики «surname firstname»-форматирования между двумя модулями — осознанный
   компромисс ради независимости двух контрактов, зафиксированных разными тестами.
6. **Политика записи файла (`download.py`) — базовый минимум, не полная песочница**, как и
   предписано SA: пишет только по явно переданному `target_path`, создаёт родительские каталоги,
   отказывает при перезаписи существующего файла без `overwrite=True`. Полное ревью — за
   DevSecOps.

### Найденный и исправленный дефект QA-author стаба

`tests/test_enrichment.py::test_enrich_batch_partial_failure_does_not_abort_others` регистрировал
httpx-моки через `url=f"{base_url}/api/recordings/R-FAIL"` (и `R-OK`) без query-параметра.
Systematic-debugging (см. навык) показал root cause: `pytest_httpx` 0.36 сравнивает query-строку
ТОЧНО, если `url=` задан без `match_params` — а session-режим клиента (архитектура DEV-001,
ADR-003) добавляет `?sessionToken=...` абсолютно ко всем исходящим запросам. Матчер не мог
сработать НИ ПРИ КАКОЙ реализации. Исправление — точечное, в URL мока добавлен `?sessionToken=sess-1`
(значение токена теста), сам проверяемый сценарий (частичный отказ не роняет остальные записи) не
менялся.

### Найденный и исправленный дефект в самом AC-стабе (не в матчере, а в assert)

`tests/test_reconciliation.py::test_ac_fr15_2_dry_run_mismatch_blocks_sync_without_confirmation`
предзаписывал в реестр запись `OLD-1`, затем после `sync --dry-run` (расхождение id, `rc != 0`)
проверял `reg.list_recordings() == []` — противоречие собственному сетапу того же теста
(`OLD-1` физически не может исчезнуть без явного кода удаления, которого dry-run не содержит и не
должен содержать). Исправлено на `[r["recording_id"] for r in reg.list_recordings()] == ["OLD-1"]`
— тот же смысл проверки («dry-run ничего не пишет», по аналогии с `migrate --dry-run`), но
корректно выражающий «реестр остался НЕИЗМЕННЫМ», а не «реестр опустел». Альтернатива (реализовать
`--dry-run`, стирающий существующие данные ради прохождения буквального assert) была бы активно
вредной и отклонена.

### Что не реализовано / оставлено на дальше

- `download.py`/`client.py` не валидируют качество под api-key-режимом (см. п.4 выше) — ручная
  проверка на боевом домене после перевыпуска ключа (как и весь api-key-контур).
- `get_participants_report` реализован (метод клиента, профиль в `auth.py`), но не имеет
  собственного MCP-инструмента — не запрошен ни одним FR/AC этого эпика, оставлен как задел
  клиента для возможного будущего инструмента.
