---
title: "AT-design: промт-поверхность плагина ktalk для встреч — CLI-контракты"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# AT-design: промт-поверхность плагина ktalk для встреч — CLI-контракты

Тест-дизайн и failing stubs для QA-005 (волна 5). Источник AC —
[ktalk-plugin-meetings.md](../30-requirements/ktalk-plugin-meetings.md) (FR-32…FR-38,
NFR-20…NFR-23). Архитектурный контекст —
[ktalk-plugin-meetings-spec.md](ktalk-plugin-meetings-spec.md) (SA-006, карта
FR → CLI-команда, точные флаги) и
[ADR-015-cli-authority-and-write-handoff-spec.md](ADR-015-cli-authority-and-write-handoff-spec.md)
(контракт handoff, TTY-барьер, запрет автоповтора).

## Граница периметра (обязательна к прочтению перед таблицей)

Обе companion-спеки (SA-006 «Test-pyramid рекомендация», ADR-015-spec «Test-pyramid
рекомендация») относят почти весь текст AC FR-32…FR-38/NFR-20…23 к дереву плагина
`ktalk-plugin` (снимок промта `SKILL.md`, grep `check-plugin-composition.sh`) — это
другой git-репозиторий, недостижимый для `pytest` здесь, и задача прямо запрещает
его касаться. Периметр этой задачи — **CLI-факты пакета `ktalk-mcp`, на которые
опирается текст промта**: флаги команд, наличие/отсутствие `--json`, форма вывода,
коды возврата, канал (stdout/stderr), TTY-барьер, отсутствие автоповтора на уровне
самого `cmd_*_confirm`. Если промт плагина соврёт об одном из этих фактов (например,
предположит `--json` там, где его нет), это либо уже поймано тестом ниже, либо стало
находкой в разделе «Находки о существующем коде».

Для каждого AC ниже колонка «Здесь / плагин» разделяет: `CLI-факт` — покрыт stub'ом
в этом пакете; `плагин` — уже назначен другому дереву обеими companion-спеками,
здесь `N/A` не по умолчанию, а по явному повторному указанию, не пропуск.

## Как читать таблицу

Тот же формат, что `at-design-contacts-and-cancel.md`: `unit` — argparse/CLI
entrypoint с моком транспорта (`pytest_httpx`) или без сети вовсе; `Статус`:
`red (stub)` — новый failing stub; `green (guard)` — уже верно сегодня, регрессионный
снимок. Файл: `tests/test_cli_meetings_surface.py` — новый, не пересекается с
`test_cli_meeting.py` (create-meeting CLI, уже покрыт волной 0.6.0/ADR-009).

## Покрытие сценариев

### FR-32 — просмотр расписания (`ktalk list-calendar`)

| AC ID | Сценарий спеки | Здесь / плагин | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|---|
| AC-32-1 | AC1: агент вызывает с явными `--start`/`--end` | плагин (снимок промта — SA-006 test-pyramid) | N/A здесь | — | — | — |
| AC-32-1b | Опора факта: `--start`/`--end` обязательны, отсутствие -> `SystemExit(2)` до сети, не тихий дефолт периода | CLI-факт | `parser.parse_args(["list-calendar"])` -> `SystemExit`; `parser.parse_args(["list-calendar", "--start", "2026-08-01"])` (без `--end`) -> `SystemExit` | unit | `test_ac_32_1b_list_calendar_requires_start_and_end_no_silent_default` | red (stub) |
| AC-32-2 | AC2: предупреждение о неполном сегменте остаётся видимым | CLI-факт (форма `--json`) | `--json` вывод — валидный JSON с ключом `incomplete_segments`, непустой список сохранён дословно (не урезан/не превращён в булев флаг) | unit | `test_ac_32_2_list_calendar_json_preserves_incomplete_segments_verbatim` | red (stub) |
| AC-32-3 | AC3: код ≠0 не показан как «встреч нет» | CLI-факт | Успех с пустым `items` -> `rc == 0`, `stdout` содержит валидный JSON `{"items": [], ...}`; отказ (мок исключения клиента) -> `rc == 1`, текст на **stderr** с префиксом `Ошибка:`, `stdout` пуст — два исхода различимы по `(rc, channel)`, не только по тексту | unit | `test_ac_32_3_empty_items_success_vs_error_are_distinguishable_by_exit_code_and_channel` | red (stub) |
| — | Испорченный ввод: `--start 2026-13-45` (невалидный ISO) не роняет процесс необработанным traceback | CLI-факт (испорченный ввод) | `rc == 1`, `Ошибка:` на stderr, без Python traceback в выводе | unit | `test_list_calendar_malformed_start_date_fails_closed_not_traceback` | red (stub) |

### FR-34 — отмена встречи (`ktalk cancel-meeting-preview`/`-confirm`)

| AC ID | Сценарий спеки | Здесь / плагин | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|---|
| AC-34-1 | AC1: агент вызывает только `-preview`, показывает точную команду `-confirm` | плагин (снимок промта) | N/A здесь | — | — | — |
| AC-34-1b | Опора факта: `cancel-meeting-preview` не выполняет сеть, всегда `rc == 0`, эхо `id`/`reason` в выводе (промт обязан взять их отсюда, не изобрести) | CLI-факт | `httpx_mock.get_requests() == []`; `rc == 0`; вывод содержит переданный `id` и `reason` дословно | unit | `test_ac_34_1b_cancel_meeting_preview_zero_network_echoes_id_and_reason` | red (stub) |
| AC-34-1c | Опора факта: `cancel-meeting-preview`/`-confirm` не принимают `--json` (известное расхождение, см. «Находки») | CLI-факт | `parser.parse_args(["cancel-meeting-preview", "--id", "x", "--json"])` -> `SystemExit` (аргумент не распознан) | unit | `test_ac_34_1c_cancel_meeting_commands_reject_json_flag` | red (stub) |
| AC-34-2 | AC2: нет `id` -> агент не изобретает | плагин (текстовый снимок сценария) | N/A здесь | — | — | — |
| AC-34-2b | Опора факта: `--id` обязателен на обеих подкомандах — argparse отказывает, не подставляет пустую строку | CLI-факт | `parser.parse_args(["cancel-meeting-preview"])` -> `SystemExit`; то же для `cancel-meeting-confirm` | unit | `test_ac_34_2b_cancel_meeting_id_is_required_on_both_subcommands` | red (stub) |
| NFR-23 (cancel) | Ни один путь не вызывает `cancel-meeting-confirm` программно | плагин (grep дерева плагина) | N/A здесь; факт, на который опирается запрет, — TTY-барьер ниже | — | — | — |
| NFR-23-b | TTY-барьер: `cancel-meeting-confirm` без реального терминала отказывает до сети | CLI-факт | Под pytest `sys.stdin.isatty() is False` уже верно (как в `test_cli_meeting.py`); `rc != 0`, `httpx_mock.get_requests() == []`, текст называет «терминал» | unit | `test_nfr23_cancel_meeting_confirm_refuses_without_tty` | red (stub) |
| NFR-22 (cancel) | Без автоповтора после «исход неизвестен» | CLI-факт (не покрыто ранее на уровне CLI — только `meeting_cancel.py`) | Реальный `pty`, подтверждение "да", мок `ConnectError` на `POST .../cancel` -> ровно один POST-запрос, текст называет `исход неизвестен`/`list-calendar` | unit (реальный pty) | `test_nfr22_cancel_meeting_confirm_network_failure_no_retry_exactly_one_post` | red (stub) |

### FR-35 — поиск участника (`ktalk search-contacts`) — зона известного расхождения

| AC ID | Сценарий спеки | Здесь / плагин | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|---|
| AC-35-1 | AC1: >1 кандидат — весь список, без автовыбора | плагин + уже покрыто `test_search_contacts.py` (сервисный уровень) | N/A здесь (дубль) | — | — | — |
| AC-35-2 | AC2: явная подстановка `key` до передачи дальше | плагин (текстовый снимок) | N/A здесь | — | — | — |
| AC-35-3 | AC3: «не найдено» ≠ ошибка сети/авторизации | CLI-факт, **известное расхождение** | 0 кандидатов: `rc == 1`, текст «Ничего не найдено» на **stdout**, stderr пуст. Ошибка сети: `rc == 1`, `Ошибка:` на **stderr**, stdout пуст. Тест пришпиливает, что различение возможно **только по каналу**, не по `rc` — оба случая дают одинаковый `rc == 1` | unit | `test_ac_35_3_zero_matches_vs_network_error_share_exit_code_distinguishable_only_by_channel` | red (stub) |
| — | Опора факта: `search-contacts` не принимает `--json` (известное расхождение) | CLI-факт | `parser.parse_args(["search-contacts", "--query", "x", "--json"])` -> `SystemExit` | unit | `test_search_contacts_rejects_json_flag` | red (stub) |

### FR-36 — диагностика комнаты (`ktalk get-room`)

| AC ID | Сценарий спеки | Здесь / плагин | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|---|
| AC-36-1 | AC1: безусловное предупреждение о побочном эффекте | плагин (SA-006: текст предупреждения — целиком промт-слой, CLI его не печатает) | N/A здесь — явно: CLI `get-room` не эмитирует такое предупреждение вообще, обязанность полностью на промте | — | — | — |
| AC-36-2 | AC2: не используется как проверка занятости имени | CLI-факт (структурная граница) | В `register_subparsers` `get-room` нет флага/подкоманды, предполагающей «проверить доступность» (`--check`, `--available`, `--exists` отсутствуют) — контур физически не предлагает такой операции | unit | `test_get_room_has_no_availability_check_flag` | red (stub) |
| — | Опора факта: `get-room --json` даёт валидный JSON с полями комнаты | CLI-факт | `rc == 0`, `stdout` — валидный JSON, содержит переданное имя комнаты в теле ответа (мок) | unit | `test_get_room_json_flag_prints_valid_json_room_payload` | red (stub) |
| — | Отказ: сетевая/авторизационная ошибка -> `rc == 1`, `Ошибка:` на stderr, не на stdout | CLI-факт | Мок исключения клиента -> `rc == 1`, `stderr` содержит `Ошибка:`, `stdout` пуст | unit | `test_get_room_error_goes_to_stderr_not_stdout` | red (stub) |

### FR-37/FR-38 — деградация и эскалация (сквозные)

| AC ID | Сценарий спеки | Здесь / плагин | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|---|
| AC-37-1 | AC1: текст CLI передаётся без искажения | CLI-факт (опора: сам текст CLI не переформулирует исходную ошибку) | `list-calendar`/`get-room`/`search-contacts` на мок-исключении `RuntimeError("сообщение сервера")` -> stderr/stdout содержит `"сообщение сервера"` дословно (после `redact_secrets`, без замены на общее «что-то пошло не так») | unit (параметризован по 3 командам) | `test_ac_37_1_cli_error_text_passthrough_not_replaced_by_generic_message[*]` | red (stub) |
| AC-37-2 | AC2: не намекает на вероятный успех | плагин (текстовый снимок промта — сам CLI не формулирует вероятностных суждений, у него бинарный `rc`) | N/A здесь | — | — | — |
| AC-38-1 | AC1: путь эскалации к `auth-status` достижим | CLI-факт (структурная опора) | `auth-status`/`config` — в `_REGISTRY_FREE_COMMANDS` **вместе** с `list-calendar`/`get-room`/`search-contacts`/`cancel-meeting-*` (эскалация доступна из того же процесса без реестра, регрессия уже покрыта `test_fr19_auth_status.py` для `auth-status` — здесь фиксируется структурное соседство для всех FR-32…FR-36 команд) | unit | `test_ac_38_1_meetings_commands_and_escalation_targets_are_all_registry_free` | red (stub) |
| AC-38-2 | AC2: не единственная гипотеза при не-авторизационной ошибке | плагин (текстовый снимок) | N/A здесь | — | — | — |

### NFR-20/NFR-21 — только CLI, без утечки секретов (наследуется, регресс)

| AC ID | Сценарий | Здесь / плагин | Обоснование |
|---|---|---|---|
| NFR-20 | Промт не называет MCP-инструмент | плагин (новый `check` в `check-plugin-composition.sh`, DEV-006) | N/A здесь дословно — этот пакет не содержит промтов |
| NFR-21 | Секреты не в тексте, показанном оператору | CLI-факт, уже покрыт регрессией (`_print_error` + `redact_secrets`, `test_cli_meeting.py::test_print_error_masks_secret_inside_response_body`) | Не дублируется — существующий тест покрывает тот же механизм (`redact_secrets`), которым пользуются все команды FR-32…FR-36 |

## Boundary cases

- `list-calendar --start`/`--end` отсутствуют по отдельности и вместе — оба случая
  дают `SystemExit(2)` до сети (AC-32-1b).
- `search-contacts`/`cancel-meeting-preview`/`cancel-meeting-confirm` с `--json` —
  argparse отклоняет неизвестный флаг, не молча его игнорирует (AC-34-1c, тест
  `test_search_contacts_rejects_json_flag`).
- `get-room` — нет флага, предполагающего проверку занятости имени, структурная
  граница на уровне парсера (AC-36-2).

## Испорченный/опечатанный ввод (обязательный класс 1)

- `list-calendar --start 2026-13-45` (синтаксически похожая на дату строка, но
  невалидный ISO — опечатка месяца) -> `date.fromisoformat` бросает `ValueError`,
  пойманный общим `except Exception` в `_run` -> `rc == 1`, `Ошибка:` на stderr, без
  необработанного traceback (`test_list_calendar_malformed_start_date_fails_closed_not_traceback`).
- `get-room ""` (пустое имя комнаты, позиционный аргумент) — сеть отказывает
  (мок), путь совпадает с обычной сетевой ошибкой; отдельного теста не заводится —
  тот же путь, что `test_get_room_error_goes_to_stderr_not_stdout`, было бы
  дублированием одного и того же ассерта на другом фикстурном значении.

## Замаскированный отказ (обязательный класс 2)

- **`search-contacts`: 0 кандидатов и сетевая ошибка дают одинаковый `rc == 1`.**
  Если промт-слой (или любой другой потребитель) проверяет только код возврата, он
  не отличит «участник не найден» от «сеть недоступна» — рискует показать оператору
  неверный диагноз или, наоборот, отчитаться об ошибке при честном «не найдено».
  Различение возможно только по каналу (stdout/stderr), что и пришпилен тестом
  `test_ac_35_3_zero_matches_vs_network_error_share_exit_code_distinguishable_only_by_channel`
  — это ровно замаскированный отказ (наблюдаемый исход один и тот же — `1` — при
  двух разных причинах), не испорченный ввод.
- **`get-room` на новом имени комнаты — молчаливое создание объекта.** ADR-006 п.2:
  `get-room` на ранее не встречавшемся имени создаёт комнату как побочный эффект,
  и сервер не отдаёт сигнала «это было создание, не чтение» — оператор получает
  `rc == 0` и данные комнаты неотличимо от чтения существующей. Это фактический
  замаскированный отказ на уровне домена (действие иное, чем заявлено), но CLI
  физически не может его отличить (ADR-006 п.2 — сервер не даёт сигнала) —
  обязанность предупредить лежит целиком на промт-слое (AC-36-1, текст уже
  зафиксирован SA-006 дословно). Здесь — не пропуск, а явный `N/A` с обоснованием:
  автоматического теста в этом пакете для этого случая не существует и не может
  существовать без изменения контура сервера.

## Не покрываем (вне scope)

| Сценарий | Почему |
|---|---|
| Снимок текста `SKILL.md` (handoff-сообщение, три части) | Дерево плагина `ktalk-plugin`, задача прямо запрещает его касаться; назначено SA-006/ADR-015-spec «Test-pyramid» другому QA-заходу (DEV-006) |
| `check-plugin-composition.sh`, новый `check` NFR-20 | То же — состав плагина, DEV-006 |
| `search_contacts`/`cancel_meeting` сервисный уровень (0/1/>1, хеш подтверждения, квотирование `id`) | Уже покрыто `test_search_contacts.py`/`test_meeting_cancel.py` (QA-010) — регрессии не требует |
| `create-meeting-preview`/`-confirm` CLI-уровень целиком | Уже исчерпывающе покрыт `test_cli_meeting.py` (0.6.0/ADR-009) — новых фактов эта волна не добавляет |
| Живой сетевой вызов любой из команд на боевом домене | Красная линия задачи — никаких боевых запросов |
| Текст предупреждения `get-room` (ADR-006 п.2), формулировка handoff (ADR-015 п.2) | Дословный текст — предмет промта плагина, не CLI; здесь тестируется факт, на котором текст обязан основываться (побочный эффект существует, эхо `id`/`reason` в выводе), не сама формулировка |

## Находки о существующем коде (не план, констатация)

1. **`create-meeting-preview`, `cancel-meeting-preview`, `search-contacts` не
   поддерживают `--json`.** NFR-20 писалась в расчёте на `--json` у промт-поверхности
   («парсят его `--json`»). Для этих трёх команд промт-слой физически вынужден
   парсить markdown-вывод (`format_meeting_preview`/`format_cancel_preview`/
   `format_search_contacts`), не JSON — это делает извлечение полей (`id`,
   `confirmation_id`, список кандидатов) текстовым парсингом markdown, более хрупким
   к правкам форматтеров, чем парсинг JSON-схемы. Тесты
   `test_ac_34_1c_cancel_meeting_commands_reject_json_flag`/
   `test_search_contacts_rejects_json_flag` пришпиливают этот факт как текущее
   поведение (характеризационный тест), не как желаемое.
2. **`search-contacts` возвращает `rc == 1` и на «0 найдено», и на ошибку —
   различие только по каналу.** Единообразный код возврата на два семантически
   разных исхода — риск замаскированного отказа для любого потребителя, который
   проверяет только `rc` (см. раздел «Замаскированный отказ»). Правка (например,
   отдельный код возврата на «не найдено» либо `--json` с полем `reason`) —
   отдельная задача Dev; здесь она не выполняется и не рекомендуется как
   единственный путь — решение по ней ещё не принято.
3. **`cancel-meeting-preview`/`-confirm` не имели CLI-уровневого теста до этой
   задачи** (только сервисный уровень `meeting_cancel.py`/`CancelPreviewService`
   в `test_meeting_cancel.py`). Это не расхождение с уже работающим кодом — CLI
   уже корректно делегирует сервису и проходит через тот же `isatty()`-барьер, что
   `create-meeting-confirm` (симметрично по коду, `cli_meeting.py`), — но
   регрессионного снимка на CLI-уровне (флаги, `--json`, TTY, отсутствие retry)
   не существовало. Stubs этой задачи закрывают именно этот пробел, не
   поведенческую ошибку.
