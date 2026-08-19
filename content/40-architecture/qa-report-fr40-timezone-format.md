---
title: "QA-отчёт: FR-40 формат `--timezone` (QA-012, волна 9)"
properties:
  - name: Тип контента
    value: [Test Report]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# QA-отчёт: FR-40 — прогон после DEV-017

Источник AC — [rooms-calendar-scheduling.md](../30-requirements/rooms-calendar-scheduling.md)
FR-40 (5 AC). Ground truth покрытия — [at-design-rooms-calendar.md](at-design-rooms-calendar.md)
(ревизия FR-40, QA-011). Архитектурное решение —
[ADR-020](../00-project/adr/ADR-020-timezone-format-validation.md) +
[companion-спека](ADR-020-timezone-format-validation-spec.md). Реализация — DEV-017
(`content/60-implementation/dev-017-timezone-format-validation.md`).

PM заявил параллельный прогон 550 passed, 9.81 с. Этот отчёт — независимая проверка: пять
параллельных прогонов подряд, один последовательный, гейт, разбор регрессионных правок фикстур
(7 файлов, `Europe/Moscow` → `GMT+3`), сверка покрытия AC.

## Summary

Пять параллельных прогонов (`-n 8`), подряд:

| # | passed | failed | errors | duration |
|---|--------|--------|--------|----------|
| 1 | 550 | 0 | 0 | 9.61 с |
| 2 | 550 | 0 | 0 | 9.80 с |
| 3 | 550 | 0 | 0 | 9.60 с |
| 4 | 550 | 0 | 0 | 9.70 с |
| 5 | 550 | 0 | 0 | 9.69 с |

Один последовательный прогон (`uv run --with pytest pytest tests/ -q`): 550 passed, 0 failed,
13.95 с. Состав совпадает с параллельными прогонами, расхождений нет.

- passed: 550
- failed: 0
- skipped: 0
- total: 550
- duration: 9.60–9.80 с (параллельно, 5×), 13.95 с (последовательно)

Заявленное PM число (550 passed, 9.81 с) подтверждено независимо, устойчиво на пяти прогонах.

`bash scripts/check.sh --fast` — Errors: 0, Warnings: 3. Все три — существующие грандфазеры на
замороженном потолке (`scripts/_drift_check.py` 487 строк, `scripts/validate-profile.py` 652
строки, `src/ktalk_mcp/registry.py` 562 строки; ADR-032 Д7, ADR-018 Д5), к этой волне не
относятся, до неё уже существовали.

## Regression analysis

Полный suite зелёный на всех шести прогонах (пять параллельных + один последовательный),
расхождений в составе нет — flaky-кандидатов не найдено. Единственные тронутые Dev'ом
существующие файлы — 7 файлов тестов, где `timezone="Europe/Moscow"` заменено на
`timezone="GMT+3"` (разбор ниже). Новый файл — `tests/test_fr40_timezone_format.py` (QA-011,
36 тестов). Регрессий на существующей базе не обнаружено.

## Разбор правки фикстур — `Europe/Moscow` → `GMT+3` в 7 файлах

**Правка (`git diff tests/`):** DEV-017 ввёл `_TIMEZONE_RE`, отклоняющую любую форму, кроме
`GMT±N` (FR-40 «Решение»). Семь существующих файлов использовали `timezone="Europe/Moscow"` как
фикстуру для сценариев, не связанных с FR-40 (тело встречи, сохранение секретов, журнал записи,
санкция записи) — после DEV-017 эта фикстура стала бы отклоняться новой проверкой, тесты упали
бы не по своей теме. Dev заменил значение на `GMT+3` в каждом из семи файлов:
`test_cli_meeting.py`, `test_cli_meeting_sanctioned.py`, `test_meeting_body.py`,
`test_meeting_scheduling.py`, `test_secret_masking.py`, `test_write_journal.py`,
`test_write_sanction.py`.

**Проверка — только вход, не ожидание.** По каждому файлу `git diff` — ровно одна строка
диффа, входное значение поля (константа `FULL_KWARGS`/CLI-аргумент), ни один assert не
тронут. `grep` по каждому файлу на предмет остаточных упоминаний `Europe/Moscow` в
проверочной части — не найдено ни одного (кроме одного стал-комментария, см. ниже). Подгонки
под код (ослабления ожидания вместо входа) нет ни в одном из семи файлов.

**Отдельная находка — стал-комментарий.** `tests/test_meeting_body.py:208`:
`# Europe/Moscow +03:00 -> UTC: 10:00 -> 07:00, 11:00 -> 08:00` — комментарий не обновлён вместе
со значением фикстуры на той же строке файла (`timezone` поле теперь `GMT+3`). Ассерты ниже
(`body["start"] == "...07:00.000Z"`) корректны и не зависят от этого комментария: конвертация в
UTC берёт смещение `+03:00` из ISO-строки `start`/`end` напрямую, не из поля `timezone` —
семантика теста не пострадала. Находка класса `new`, косметическая (устаревший комментарий,
не тест), не блокирует merge.

**Вердикт по правке фикстур: обоснована, не ослабляет проверяемое поведение.** Единственная
находка — стал-комментарий, не влияющий на корректность проверки.

## Покрытие AC FR-40

Все 5 AC требования закрыты тест-функциями в `tests/test_fr40_timezone_format.py` (QA-011, 36
тестов с учётом параметризации):

| AC | Тест(ы) |
|----|---------|
| AC-1 (`GMT+3` принят, тело без изменений) | `test_ac1_gmt_plus_3_accepted_body_unchanged_snapshot` |
| AC-2 (семь отклонённых форм → `TimezoneFormatError` до сети) | `test_ac2_rejected_form_raises_timezoneformaterror_unit` (×7), `test_ac2_preview_surface_rejects_before_any_network_call` (×7), `test_ac2_confirm_surface_rejects_before_any_network_call` (×7) |
| AC-3 (отказ по формату не расходует бюджет и не выдаёт `confirmation_id`) | `test_ac3_format_rejection_issues_no_confirmation_id`, `test_ac3_format_rejection_does_not_consume_write_sanction_budget` |
| AC-4 (сообщение называет формат и пример, не сырой `CalendarTimeZoneParse`) | `test_ac4_error_message_names_format_and_example_not_raw_server_text` |
| AC-5 (`--help` CLI и докстринг называют формат явно) | `test_ac5_cli_help_names_timezone_format`, `test_ac5_build_meeting_body_docstring_names_timezone_format` |

Пробелов нет: ни одного AC без теста, ни одного теста без соответствия AC. Сверх AC — три
boundary-теста (`test_boundary_regex_accepts_edge_of_declared_range`,
`test_boundary_regex_rejects_out_of_range_or_malformed`,
`test_boundary_timezone_none_raises_missing_field_not_timezone_format`) из at-design'а
(ADR-020 §3), не расширяют формальный контракт AC, но не противоречат ему.

## Failed tests (детали)

Падений нет — таблица пуста.

| Test | Reason category | Probable cause | Action |
|------|-----------------|----------------|--------|
| — | — | — | — |

## Рекомендация

- [x] merge
- [ ] block + назад в Dev
- [ ] re-run (flaky)

**Обоснование:** пять параллельных прогонов подряд и один последовательный дают идентичный
состав — 550 passed, 0 failed, flaky-кандидатов нет. `check.sh --fast` — Errors: 0, все три
warning — грандфазеры, существовавшие до этой волны. Все 5 AC FR-40 закрыты тестами без
пробелов. Правка 7 файлов фикстур (`Europe/Moscow` → `GMT+3`) меняет только входное значение,
не ожидание — подгонки под код нет; единственная находка — некритичный стал-комментарий в
`test_meeting_body.py:208`, не влияющий на корректность проверки.
