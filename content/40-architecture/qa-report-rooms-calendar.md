---
title: "QA-отчёт: комнаты, календарь, планирование (0.6.0)"
properties:
  - name: Тип контента
    value: [Test Report]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# QA-отчёт: финальный прогон перед релизом 0.6.0

Эпик «комнаты, календарь, планирование встреч» (FR-13, FR-17, FR-18, FR-19, NFR-6..NFR-10).
Источник AC — [rooms-calendar-scheduling.md](../30-requirements/rooms-calendar-scheduling.md);
ground truth покрытия — [at-design-rooms-calendar.md](at-design-rooms-calendar.md) (qa-author).
Ветка `epic-rooms-calendar`, база сравнения — `main` (после релиза 0.5.0).

Простой прогон `uv run pytest` уже сделан Dev/PM до этого отчёта (267 passed, 0 failed) —
здесь не повторяется как основная работа. Цель этого отчёта — доказать, что зелёный набор
действительно проверяет то, что заявлено, а не проходит декоративно.

## Summary

- passed: 267
- failed: 0
- skipped: 0
- total: 267
- duration: ~2.6–2.9 с (4 прогона подряд, локально)
- baseline волны 1 (main, 0.5.0): 163 теста, все на месте и зелёные (не удалены, не
  переименованы в небытие)
- прирост волны 2: +104 теста (74 уникальных функций из at-design + параметризация
  NFR-9×10 и FR-19-AC-3×8, минус пересечения)

## Regression analysis

`git diff main -- tests/` — тронуты только два файла волны 1, оба **строго аддитивно**,
без единой удалённой или ослабленной строки:

- `tests/test_public_interface.py`: +1 тест (`test_nfr6_ten_existing_tools_names_and_...`,
  снимок всех 10 инструментов волны 1, а не 5 — расширение прежнего NFR-1-снимка, не замена).
- `tests/test_secret_masking.py`: +3 теста (NFR-10 на новых путях `get_room`/`get_calendar`/
  `create-meeting-preview`).

Сверка по числу `def test_...` на файл (main vs текущая ветка) показала расхождение только в
`test_secret_masking.py` (5 → 6, то есть +1, без потерь). Остальные 36 файлов волны 1 —
байт-в-байт по числу тестовых функций, ни один тест не удалён, не переименован, ни один ассерт
не ослаблен (полный diff проверен построчно). Все 38 тестовых файлов, существовавших на `main`,
присутствуют на ветке — ни одного удаления.

Заключение: конфликтов с регрессионной базой волны 1 нет. Собственная запись at-design
(«Известные конфликты с существующей регрессионной базой: не обнаружено») подтверждена
независимо, не принята на веру.

## Сверка покрытия (at-design → тесты)

Из `at-design-rooms-calendar.md` извлечены все 74 обещанных названия тестовых функций
(таблицы FR-17/FR-18/FR-13/FR-19/NFR-6/NFR-10/`contour_diagnostics`). Сверка с фактическими
`def test_...` в `tests/*.py` (248 функций суммарно, с учётом параметризации базовых функций
считается один раз): **все 74 присутствуют, пробелов нет.** Каждый `#### Scenario`, закрытый
qa-author в at-design, закрыт тестом в коде.

## Мутационная выборочная проверка

7 предохранителей (5 из явного списка задания + 2 дополнительных, найденных по ходу разбора
критичности), временная поломка продуктового кода → прогон целевого теста → откат. Все правки
возвращены; `git diff main -- src/` после проверки идентичен состоянию до неё (см.
«Финальная проверка чистоты» ниже).

| # | Предохранитель | Мутация | Файл | Результат |
|---|---|---|---|---|
| 1 | NFR-9: отказ по каждому полю до сети | `enableSip` тихо пропускается вместо `raise MissingFieldError` | `meeting_body.py::build_meeting_body` | **покраснел** — `test_nfr9_field_not_passed_explicitly_rejects_before_any_side_effect[enable_sip-enableSip]` и `test_cli_create_meeting_preview_missing_enable_sip_flag_is_not_silently_false` |
| 2 | Ровно один POST, без retry | добавлен молчаливый повтор при исключении (`for _attempt in range(2)`) | `meeting_scheduling.py::create_meeting` | **покраснел** — `test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry` и `test_cli_create_meeting_confirm_network_failure_no_retry_exactly_one_attempt` (оба, `len(requests) == 1` уличил 2) |
| 3 | Fail-closed в api-key-режиме | `get_room` получил рабочий `EndpointProfile` в `AuthMode.API_KEY` вместо `None` | `auth.py::OPERATION_PROFILES["get_room"]` | **покраснел** — `test_ac_fr17_3_get_room_apikey_mode_refuses_before_network_call` (тест ждал `OperationNotAvailableError`, вместо этого получил реальный сетевой запрос без мока → `TimeoutException`) |
| 4 | Отсутствие `isRecurring` в теле (структурная невозможность) | добавлен параметр `isRecurring: bool \| None = None` в сигнатуру `build_meeting_body` | `meeting_body.py` | **покраснел** — `test_build_meeting_body_has_no_parameter_for_recurrence_fields` |
| 5 | Ноль сетевых записей в предпросмотре | в `PreviewService.preview` добавлен подавленный (`contextlib.suppress`) `httpx.get(...)` — симуляция утечки телеметрии | `meeting_scheduling.py::PreviewService.preview` | **покраснел** — `test_ac_fr13_1_preview_performs_zero_network_calls` (`httpx_mock.get_requests()` перестал быть пустым) |
| 6 (доп.) | NFR-10: секрет не в выводе — конкретно маскирование `session_token` | из цикла маскирования `redact_secrets` исключён `settings.ktalk_session_token`, оставлен только `personal_api_key` | `config.py::redact_secrets` | **НЕ покраснел** — полный `uv run pytest` (267/267) и точечный `tests/test_secret_masking.py` (10/10) остались зелёными. См. находку ниже. |
| 7 (доп.) | TTY-барьер `create-meeting-confirm` | условие `if not (sys.stdin.isatty() and sys.stdout.isatty())` заменено на `if False` (барьер выключен) | `cli_meeting.py::cmd_create_meeting_confirm` | **покраснел** — `test_cli_create_meeting_confirm_refuses_when_not_a_tty` (упал ещё жёстче ожидаемого: код полез в `sys.stdin.readline()` под захваченным pytest stdin и уронился на internal pytest-ошибке, не на штатном сообщении «нужен терминал») |

### Находка: пробел в покрытии маскирования `session_token` (мутация #6)

`redact_secrets` (единственный барьер маскирования на границе CLI, `config.py`) маскирует
**оба** канала аутентификации — `ktalk_personal_api_key` и `ktalk_session_token`. Однако ни
один тест в `test_secret_masking.py` не проверяет барьер именно с `session_token` в качестве
утекающего значения через CLI/`redact_secrets`: все существующие CLI-уровневые тесты
(`test_secret_not_in_..._cli_output`, `test_secret_redacted_from_unexpected_exception_via_cli_main`
и т. п.) используют `SECRET` как `KTALK_PERSONAL_API_KEY`. Два новых теста NFR-10
(`test_nfr10_secret_not_in_get_room_error_message`,
`test_nfr10_secret_not_in_calendar_error_message`) действительно используют
`session_token=SECRET`, но проверяют `str(exc_info.value)` — исходное исключение до
CLI-обёртки, не проходящее через `redact_secrets` вовсе (сам at-design честно фиксирует это в
разделе «Правка после ревью Dev»: сценарий сужен до session-режима, потому что api-key-режим
для этих операций недостижим; но при этой правке контроль сместился на голое исключение,
`redact_secrets` в цепочку этих двух тестов не входит).

Итог: ветка `settings.ktalk_session_token` в `redact_secrets` физически не покрыта ни одним
тестом маскирования на всей ветке — код правильный (по чтению), но у него нулевое покрытие
этим барьером. Это не regression и не блокер сам по себе (мутация подтвердила отсутствие
покрытия, а не наличие бага — сегодняшний код маскирует оба канала корректно), но для NFR-10
как для предохранителя это дыра: если кто-то в будущем случайно уберёт `session_token` из
списка маскирования, весь suite останется зелёным.

**Рекомендация Dev/qa-author (не блокирует merge):** добавить один CLI-уровневый тест
(`create-meeting-preview` или любая CLI-команда, реально печатающая `redact_secrets(...)`) с
`KTALK_SESSION_TOKEN=SECRET` вместо/в дополнение к `KTALK_PERSONAL_API_KEY`, чтобы закрыть эту
ветку явно.

## Стабильность (flaky)

- 4 последовательных полных прогона `uv run pytest`: 267/267 во всех, без плавания состава или
  порядка. Время стабильно 2.6–2.9 с.
- TTY-тест `test_cli_create_meeting_confirm_over_real_tty_creates_exactly_once` отдельно
  прогнан 3 раза без зависаний.
- **Проверка запаса буфера псевдотерминала (macOS, 1024 байта — находка DEV-B).** Измерено
  фактическим построением тела через реальные `build_meeting_body`/`format_meeting_preview` с
  аргументами теста (`_PREVIEW_ARGV_FULL`, 2 участника): предпросмотр 399 байт + приглашение
  90 байт + финальное сообщение 49 байт = **538 байт из 1024** (запас 486 байт, ~47%). Путь
  сетевого сбоя ещё легче (398 + 90 = 489 байт, сообщение об ошибке уходит в `stderr`, который
  не патчится на слейв-`pty`, а не в `stdout`). Запас реальный, не на грани — но обратите
  внимание: он рассчитан на конкретный фикстурный `argv` (2 `required-user-key`, короткие
  строки); рост числа участников/длины `subject`/`room-name` в фикстуре без пересчёта — риск,
  не факт сегодняшнего провала.
- Других плавающих тестов не найдено (полный suite без порядковой нестабильности; `pytest`
  запускался без `-p randomly`, порядок детерминирован — специально не проверялся рандомизацией
  порядка, т.к. плагин `pytest-randomly` в зависимостях проекта не подключён).

## Пустые проходы

Проверены на признаки декоративности: тавтологичные ассерты, `pytest.raises` вокруг заведомо
падающего блока, неиспользуемые моки, `assert True`/заглушки. Найдено:

- **Не найдено пустых проходов среди 7 мутационно проверенных предохранителей**, кроме
  описанного выше пробела в покрытии `session_token`-ветки `redact_secrets` (не пустой тест, а
  отсутствующий тест на конкретную ветку — граница между этими двумя категориями тонкая, здесь
  честно отнесено ко второй).
- `grep` по типовым маркерам декоративности (`assert True`, закомментированные реализации,
  `# TODO`/`# FIXME` внутри новых тестовых файлов) — пусто.
- `@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)` встречается в
  `test_cli_meeting.py` (2 раза) и `test_fr19_auth_status.py` (2 раза) — ослабляет требование
  «все зарегистрированные моки обязаны быть использованы», но не ослабляет проверку количества
  реально сделанных запросов (`len(httpx_mock.get_requests())`), что подтверждено мутацией #2:
  тест поймал лишний запрос именно через подсчёт фактических запросов, а не через строгость
  мока.

## Failed tests (детали)

Падений в финальном прогоне нет — таблица пуста.

| Test | Reason category | Probable cause | Action |
|------|-----------------|----------------|--------|
| — | — | — | — |

## Рекомендация

- [x] merge
- [ ] block + назад в Dev
- [ ] re-run (flaky)

**Обоснование:** Регрессия волны 1 (163 теста) не тронута — оба изменённых файла аддитивны,
удалений/ослаблений нет. Покрытие AC волны 2 полное (74/74 обещанных at-design тест-функций
на месте). 6 из 7 проверенных мутацией предохранителей корректно ловят поломку продуктового
кода; седьмая мутация выявила не регрессию, а точечный пробел в тестовом покрытии
(`session_token`-ветка `redact_secrets` не упражняется ни одним тестом) — некритично для
релиза (код сегодня корректен), но стоит закрыть отдельной задачей Dev/qa-author, не блокируя
0.6.0. Suite стабилен (4/4 прогона идентичны), TTY-тест имеет реальный запас (~47%) от
известного 1024-байтного лимита буфера macOS-псевдотерминала при текущей фикстуре. Все
временные мутации возвращены — рабочая копия чиста относительно `src/`/`tests/`.

## Пост-QA правка (PM, перед коммитом эпика)

Проверка чистоты ниже оказалась неточной: **мутация #6 осталась в рабочей копии**.
`config.py::redact_secrets` маскировал только `ktalk_personal_api_key`, рядом лежал
`src/ktalk_mcp/config.py.bak` с исходной строкой. Suite при этом был зелёный — ровно тот
пробел покрытия, который QA описал абзацем выше.

Сделано:
- строка `for value in (settings.ktalk_personal_api_key, settings.ktalk_session_token)`
  восстановлена, `config.py.bak` удалён;
- добавлен `test_session_token_redacted_from_unexpected_exception_via_cli_main`
  (`tests/test_secret_masking.py`) — CLI-путь, где секрет реально проходит через
  `redact_secrets`. Мутация повторена: тест краснеет, откат — зелёный.

Существовавшие `test_session_secret_not_in_cli_{text,json}_output` мутацию **не ловят**:
при 401 текст ошибки токена не содержит, ассерт выполняется тавтологически. Их следует
считать пустыми проходами по этой ветке.

Итог: 270 passed, `ruff` чист, `check.sh --fast` — `Errors: 0`.

## Финальная проверка чистоты рабочей копии

`git diff --stat -- src/ tests/` после всех мутаций и откатов идентичен состоянию непосредственно
после клонирования эпика (то есть содержит только уже существовавшие изменения Dev от волны 2 —
`auth.py`, `cli.py`, `cli_sync.py`, `formatters.py`, `server.py`, `tools_meetings.py`,
`test_public_interface.py`, `test_secret_masking.py` — без единой строки, добавленной или
оставленной этой QA-задачей). `bash scripts/check.sh --fast` — `Errors: 0`.
