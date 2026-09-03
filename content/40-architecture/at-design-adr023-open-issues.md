---
title: "AT-design: наблюдаемость последней синхронизации, обнаружимость подмены транскрипта"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: волна открытых issue (FR-41, NFR-17, issue #3)

Тест-дизайн и failing stubs QA-013 к [ADR-023](../00-project/adr/ADR-023-open-issues-observability-and-runbook-home.md)
(решения принятые на gate-sa, **редакция 2a2f6e3**, не 81b379a) и его
[companion-спеке](ADR-023-open-issues-observability-and-runbook-home-spec.md). Источник AC —
[registry-sync-observability.md](../30-requirements/registry-sync-observability.md) (FR-41) и
[transcript-identity-observability.md](../30-requirements/transcript-identity-observability.md)
(NFR-17); капабилити-спеки —
[registry-sync-window/spec.md](../../openspec/specs/registry-sync-window/spec.md) и
[recording-data-access/spec.md](../../openspec/specs/recording-data-access/spec.md).
Issue #3 (`gh issue view 3 --repo mdemyanov/ktalk-cli`) не имеет требования — регресс
`.get("id", fallback)` в `formatters.py:126`/`:165`, покрытие на усмотрение QA-author
(companion-спека, «Контекст»: «дефект возвращает существующее поведение, не архитектурное
решение», сюда не входит по предмету ADR, но красная линия «не только happy path» требует
закрыть его отдельно).

Красная линия роли: код реализации не пишется (`transcript_identity.py`, правки
`cli_content.py`/`cli.py`/`formatters.py` — DEV-019). Стабы падают на `assert`/поведение,
не на импорте/синтаксисе (см. «Базис прогона» ниже) — импорт внутри тела каждой тест-функции,
не на уровне модуля (конвенция `test_enrichment.py`/`test_fr40_timezone_format.py`), файл
собирается целиком независимо от того, существует ли ещё `transcript_identity.py`.

## Как читать таблицу

- **Тип**: `unit` — чистая функция без сети; `integration` — CLI + мок транспорта
  (`pytest_httpx`) или реальная тестовая SQLite.
- **Статус**: `red (stub)` — новый failing stub; `green (guard)` — тест уже зелёный сегодня,
  регрессионный снимок существующего корректного поведения, не тестирует новую функциональность.

## Покрытие AC — FR-41 (`tests/test_fr41_last_synced.py`)

Решение SA (ADR-023 §2, не изменено поправкой): `last_synced` — поле ВЕРХНЕГО уровня
`dashboard --json` (не внутри `stats`), значение `Registry.get_meta("last_synced")` как есть,
`null` при отсутствии синхронизации.

| AC ID | `#### Scenario:` капабилити-спеки | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| FR41-AC1 | «A reading command surfaces the last completed sync moment» | `sync` через CLI (мок HTTP) -> `Registry.get_meta("last_synced")` -> `dashboard --json`; значение в ответе == записанному | integration | `test_fr41_ac1_dashboard_json_last_synced_matches_registry_get_meta_after_sync` | red (stub) |
| FR41-AC1 (форма ответа, доп.) | то же — решение SA о РАСПОЛОЖЕНИИ поля | `"last_synced" not in out["stats"]` | integration | `test_fr41_ac1_last_synced_is_top_level_not_nested_in_stats` | green (guard) — поле сегодня отсутствует и там, и там, форма пока не нарушена |
| FR41-AC2 | «An unsynced registry states absence explicitly» | свежий реестр, `dashboard --json`: `"last_synced" in out and out["last_synced"] is None` | integration | `test_fr41_ac2_never_synced_registry_reports_explicit_null_not_missing_key` | red (stub) |
| FR41-AC2 (замаскированный отказ, доп.) | то же — литерал ключа в сыром тексте, не только в распарсенном словаре | `'"last_synced"' in raw_stdout` | integration | `test_fr41_ac2_masked_failure_null_is_literal_json_null_not_omitted_field` | red (stub) |
| FR41-AC3 | «Reading the sync moment never mutates registry data» | 5× `dashboard --json` подряд -> статусы записей реестра (`Registry.list_recordings()`) неизменны | integration | `test_fr41_ac3_repeated_dashboard_json_calls_do_not_change_any_recording_status` | green (guard) — чтение и сегодня не мутирует статусы |
| FR41-AC3 (сужение, доп.) | то же — сама `meta` (`last_synced`/`sync_count`) тоже не должна «ползти» от чтения | 3× `dashboard --json` -> `get_meta("last_synced")`/`get_meta("sync_count")` неизменны | integration | `test_fr41_ac3_repeated_dashboard_json_calls_do_not_change_sync_meta` | green (guard) |

## Покрытие AC — NFR-17 (`tests/test_nfr17_identity_verification.py`)

Решение SA, **поправленное владельцем на gate-sa** (ADR-023 §1, ред. 2a2f6e3): сверка ВКЛЮЧЕНА
ПО УМОЛЧАНИЮ у `get-transcript`; флаг `--no-verify-identity` её ОТКЛЮЧАЕТ. Более ранняя
редакция (`--verify-identity` как opt-in) — отклонённый вариант из Alternatives Considered.

| AC ID | `#### Scenario:` капабилити-спеки | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR17-AC1 | «An indistinguishable-by-default response is made distinguishable» | `check_identity`: составы не пересекаются и оба непусты -> `result == "mismatch"` | unit | `test_nfr17_ac1_check_identity_mismatch_on_disjoint_nonempty_sets` | red (stub) |
| NFR17-AC1 (интеграционный уровень, доп.) | то же — признак доступен уже в `--json`-ответе `get-transcript`, без отдельного вызова | CLI: расходящиеся составы -> `out["identity_check"]["result"] == "mismatch"` | integration | `test_nfr17_ac1_mismatch_surfaced_in_default_on_json_response` | red (stub) |
| NFR17-AC2 | «A correctly matched response does not trigger a false mismatch» | `check_identity`: пересечение непусто (в т.ч. лишний неговоривший участник записи) -> `result == "match"`, не `"mismatch"` | unit | `test_nfr17_ac2_check_identity_match_on_genuinely_overlapping_response` | red (stub) |
| NFR17-AC3 | «An unavailable verification path is reported, not silently skipped» | `get_recording` бросает `ConnectError` -> `identity_check` присутствует, `result == "not_checked"`, не `"match"`; основной транскрипт (`rc == 0`, тело в ответе) возвращается | integration | `test_nfr17_ac3_get_recording_network_failure_yields_not_checked_transcript_still_returned` | red (stub) |
| — (доп., умолчание-включено) | Поправка владельца ADR-023 §1 — без флага второй вызов ОБЯЗАН произойти сам | `len(httpx_mock.get_requests()) == 2` без флага; `out["identity_check"]` присутствует | integration | `test_nfr17_default_on_no_flag_calls_get_recording_and_adds_identity_check` | red (stub) |
| — (доп., отказ от сверки) | `--no-verify-identity` — единственный путь к нулевой цене (ADR-023 §1 «Цена») | `--no-verify-identity` -> РОВНО один сетевой вызов, `"identity_check" not in out` | integration | `test_nfr17_no_verify_identity_flag_skips_second_call_entirely` | red (stub) — CLI не знает флага, `argparse` -> `SystemExit(2)` |
| — (boundary, companion-спека «Edge cases») | Оба множества пусты одновременно -> `inconclusive`, не `match` (пустое пересечение пустых множеств — не совпадение) | `check_identity([], [])` -> `result == "inconclusive"` | unit | `test_nfr17_boundary_check_identity_inconclusive_when_both_sets_empty` | red (stub) |
| — (boundary) | Пуст только состав спикеров транскрипта | `check_identity` -> `inconclusive` | unit | `test_nfr17_boundary_check_identity_inconclusive_when_transcript_has_no_speakers` | red (stub) |
| — (boundary) | Пуст только состав участников записи | `check_identity` -> `inconclusive` | unit | `test_nfr17_boundary_check_identity_inconclusive_when_recording_has_no_participants` | red (stub) |
| — (boundary, companion-спека «transcript_identity.py») | `speaker` отсутствует, есть `diarizedSpeaker` — не должен теряться | `speaker_identities` включает идентичность из `diarizedSpeaker` | unit | `test_nfr17_boundary_speaker_identities_falls_back_to_diarized_speaker` | red (stub) |
| — (boundary) | И `speaker`, и `diarizedSpeaker` отсутствуют — трек не подмешивает `None` в множество | `None not in identities`, `identities == set()` | unit | `test_nfr17_boundary_speaker_identities_drops_track_without_any_speaker_info` | red (stub) |
| — (boundary) | Анонимный участник/спикер (без `userInfo`) сверяется по `anonymousId` | общий `anonymousId` -> `match` | unit | `test_nfr17_boundary_anonymous_participants_identified_by_anonymous_id` | red (stub) |
| — (регресс, companion-спека «Оркестрация», edge case) | `--chunk N` вне диапазона + умолчание-включено + `--json` — обёртка `{"transcript":...}` не должна крашиться на нестрого-JSON тексте чанка | 2 сетевых вызова происходят; `rc == 0`; сообщение о несуществующем чанке доходит как есть | integration | `test_nfr17_out_of_range_chunk_with_default_verify_does_not_crash_on_json_parse` | red (stub) |

## Покрытие — issue #3 (`tests/test_issue3_null_id_fallback.py`, отдельный файл)

Не расширяет `tests/test_formatters.py` (109 строк, самый большой файл дерева тестов):
дефект — по оси «`null`-vs-отсутствие ключа» `dict.get`, не по теме существующих классов
`TestFormatRecording*` (форматирование ВАЛИДНЫХ данных). Отдельный файл читается как единица
предмета, не требует понимания остального `test_formatters.py`.

| Предмет | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|
| Карточка (`format_recording`, `formatters.py:126`), `id: null` + непустой `key` | `"ABC-123" in result`, `"None" not in result` | unit | `test_issue3_card_prints_key_when_id_is_explicit_null` | red (stub) |
| Карточка, регресс-guard: валидный `id` не игнорируется | `"REAL-ID-1" in result` | unit | `test_issue3_card_still_uses_id_when_id_is_a_real_non_null_value` | green (guard) — уже верно сегодня |
| Карточка, оба идентификатора `null` | `"None" not in result` | unit | `test_issue3_card_falls_back_to_na_when_both_id_and_key_are_null` | red (stub) |
| Список (`format_recordings_list`, `formatters.py:165`), `id: null` + непустой `key` | `"ABC-123" in result`, ячейка `\| ID \|` не буквальный `None` | unit | `test_issue3_list_prints_key_when_id_is_explicit_null` | red (stub) |
| Список, регресс-guard: валидный `id` не игнорируется | `"REAL-ID-2" in result` | unit | `test_issue3_list_still_uses_id_when_id_is_a_real_non_null_value` | green (guard) |
| Список, оба идентификатора `null` | ячейка ID не буквальный `None` | unit | `test_issue3_list_falls_back_to_na_when_both_id_and_key_are_null` | red (stub) |
| Список, несколько записей одновременно (испорченный ввод одной не портит соседние) | все 3 записи присутствуют, `null`-запись не путает соседние | unit | `test_issue3_list_multiple_records_mixed_null_and_real_ids_not_confused` | red (stub) |

## Обязательные классы покрытия

### Испорченный/опечатанный ввод (не пропуск/значение вне диапазона)

- **FR-41**: N/A — `dashboard --json` не принимает от пользователя ни идентификатор, ни
  URL-сегмент, ни поисковый запрос; команда без позиционных аргументов, читает весь реестр.
  Испорченный `--db` — предмет других файлов, не дублируется здесь.
- **NFR-17**: `test_nfr17_malformed_mistyped_recording_key_get_recording_404_yields_not_checked`
  — пользователь опечатал `recording_key`; сам транскрипт сервер тем не менее отдаёт (RES-006
  не связывает причину подмены с валидностью запроса), независимый источник (`get_recording`
  на тот же неверный ключ) отвечает `404` — специфическая форма недоступности источника,
  отличная от общего сетевого сбоя NFR17-AC3.
- **Issue #3**: `test_issue3_list_multiple_records_mixed_null_and_real_ids_not_confused` —
  смешанный ввод (часть записей с `id: null`, часть с валидным `id`) в одном ответе.

### Замаскированный отказ (тихое приятие/редирект/умолчание вместо наблюдаемой ошибки)

- **FR-41**: NFR17-AC2 в требовании и есть этот класс дословно —
  `test_fr41_ac2_masked_failure_null_is_literal_json_null_not_omitted_field` проверяет ЛИТЕРАЛ
  ключа в сыром тексте stdout, не только распарсенный словарь — ловит наивную реализацию
  `if value: payload[...] = ...`, тихо ОПУСКАЮЩУЮ ключ при `None`.
- **NFR-17**: NFR17-AC3 — `test_nfr17_ac3_get_recording_network_failure_yields_not_checked_transcript_still_returned`
  проверяет явно: (а) `identity_check` не пропущен, (б) `result != "match"` при отказе
  (недоступность источника не трактуется как подтверждение). Дополнительно —
  `test_nfr17_no_verify_identity_flag_skips_second_call_entirely` проверяет обратный риск:
  тихий always-on второй вызов ВОПРЕКИ явно переданному `--no-verify-identity`.
- **Issue #3**: тихая подстановка `None` вместо `key` — сам предмет регресса.

## Базис прогона

`uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8` на момент написания:
**570 passed, 22 failed** (было 565 passed/0 failed на `4ae1456`). Разница — 5 новых
green-guard тестов (регрессионные снимки уже корректного сегодня поведения: FR41-AC1
расположение, FR41-AC3 ×2, issue #3 карточка/список «валидный id не игнорируется») + 22 красных
стаба. Каждый красный стаб падает на `AssertionError`/`KeyError`/`ModuleNotFoundError`
(последний — только внутри тела теста, не на уровне импорта модуля файла, см. «Красная линия
роли» выше) по СВОЕЙ причине — не на опечатке теста, не на общей ошибке коллекции. Полная карта
причин — в test-report QA-runner (стор задач эпика, не `content/`).

`bash scripts/check.sh --fast` не запускает `pytest` (проверено: `grep -n pytest
scripts/check.sh scripts/*.py` — пусто) — красные стабы не блокируют pre-commit гейт.

## Не покрыто (out of scope)

- **NFR-17, живое конкурентное воспроизведение подмены** (первый AC требования, «условия
  воспроизведения — RES-006») — ручная проверка, заблокирована отсутствием санкции на
  live-тест контура; не автоматизируется этим тест-дизайном.
- **Дом OPS-001 (issue #7)** — не предмет QA-013 (нет функционального поведения кода для
  тестирования, DevOps-задача материализации файла рунбука).
- **Мониторинг `identity_check.result == "mismatch"` как сигнал инцидента у плагина-обёртки**
  — вне пакета `ktalk-cli`, ответственность вызывающего плагина (бриф DevOps companion-спеки).
