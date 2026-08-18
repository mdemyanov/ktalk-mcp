---
title: "AT-дизайн волны 6: запись агентом по санкции (QA-007)"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# AT-дизайн волны 6: запись агентом по санкции (QA-007)

Тест-дизайн и красные стабы **до** реализации DEV-012/DEV-013. Источники:
[FR-33, FR-34, NFR-22, NFR-23, NFR-24](../30-requirements/ktalk-plugin-meetings.md),
[ADR-016](../00-project/adr/ADR-016-agent-executed-writes.md) и
[companion-спека](ADR-016-agent-executed-writes-spec.md) §9.

Все тесты герметичны: транспорт подменён `pytest_httpx`, `XDG_CONFIG_HOME`/`XDG_STATE_HOME`
уводятся в `tmp_path` автouse-фикстурой `conftest.py` (без неё тесты писали бы санкцию и журнал в
настоящий `$HOME` пользователя). Ни одной боевой операции против KTalk.

## Таблица AC → тест

| AC | Тест | Файл |
|---|---|---|
| FR-33 AC1 (санкции нет → отказ, POST нет) | `test_confirm_without_sanction_refuses_and_makes_no_request` | `test_cli_meeting_sanctioned.py` |
| FR-33 AC2 (запись по санкции + `--confirmation-id`) | `test_confirm_with_sanction_and_confirmation_id_creates_exactly_once` | `test_cli_meeting_sanctioned.py` |
| FR-33 AC2 (без `--confirmation-id` в неинтерактивном канале) | `test_confirm_without_confirmation_id_refuses` | `test_cli_meeting_sanctioned.py` |
| FR-33 AC3 (подмена тела между шагами) | `test_confirm_refuses_when_body_changed_after_preview` | `test_cli_meeting_sanctioned.py` |
| FR-33 AC5 / NFR-23 п.6 (журнал) | `test_journal_records_attempt_and_outcome_for_successful_write` | `test_write_journal.py` |
| FR-34 AC1 (отмена по санкции) | `test_cancel_confirm_with_sanction_cancels_exactly_once` | `test_cli_meeting_sanctioned.py` |
| FR-34 AC2 (ключи независимы) | `test_create_sanction_does_not_authorize_cancel` | `test_cli_meeting_sanctioned.py` |
| NFR-22 (повтор с потреблённым id) | `test_repeat_with_consumed_confirmation_id_refuses_exactly_one_post` | `test_cli_meeting_sanctioned.py` |
| NFR-22 (бюджет списывается на неизвестном исходе) | `test_budget_is_consumed_on_unknown_outcome` | `test_cli_meeting_sanctioned.py` |
| NFR-23 п.1 (`grant` без TTY) | `test_cli_sanction_grant_refuses_without_tty_and_writes_nothing` | `test_write_sanction.py` |
| NFR-23 п.2 (срок) | `test_expired_sanction_is_not_active` / `test_confirm_with_expired_sanction_returns_41` | `test_write_sanction.py`, `test_cli_meeting_sanctioned.py` |
| NFR-23 п.2 (бюджет) | `test_exhausted_sanction_is_not_active` / `test_confirm_with_exhausted_sanction_returns_42` | там же |
| NFR-23 п.2 (потолки) | `test_grant_beyond_ceiling_is_rejected` | `test_write_sanction.py` |
| NFR-23 п.4 (отзыв) | `test_revoke_takes_effect_on_next_attempt` | `test_cli_meeting_sanctioned.py` |
| NFR-23 п.5 (fail-closed) | `test_broken_sanction_file_reads_as_absent` (параметризован) | `test_write_sanction.py` |
| NFR-23 п.6 (журнал недоступен → записи нет) | `test_unwritable_journal_blocks_the_network_call` | `test_write_journal.py` |
| NFR-24 (данные контура) | `test_injection_like_subject_does_not_change_body_or_sanction` | `test_write_sanction.py` |
| ADR-016 §5 (TTY-канал жив) | `test_tty_channel_works_without_sanction_and_logs_channel_tty` | `test_cli_meeting_sanctioned.py` |
| ADR-016 §2 (`confirmation_id` в JSON превью) | `test_preview_json_exposes_confirmation_id` | `test_cli_meeting_sanctioned.py` |

## Что проверяется текстом навыка, не pytest'ом

Проверяется в репозитории `ktalk-plugin` (`check-plugin-composition.sh` + чтение `SKILL.md`),
отмечено `N/A` для pytest: FR-33 AC1 в части «агент показывает команду `sanction grant` как текст
и не выполняет её сам», FR-33 AC4 (нет захардкоженных дефолтов полей NFR-9), FR-34 AC3 (откуда
берётся `id`), NFR-24 AC1 (оговорка «данные, не инструкции» во вводной секции навыка).

## Граничные случаи и почему именно они

- **Отказ по санкции проверяется раньше подтверждения.** Иначе перебор `--confirmation-id`
  различал бы состояния санкции по коду возврата. Отдельного теста нет: покрыто тем, что
  `test_confirm_without_sanction_refuses_and_makes_no_request` вызывается **с валидным** id и всё
  равно получает 40.
- **Бюджет списывается до сетевого вызова.** Проверяется на исходе «неизвестно» (сетевой сбой):
  после него `remaining` уменьшен, как и на успехе. Обратное поведение вернуло бы бесплатный
  автоповтор, запрещённый NFR-22.
- **Битый файл санкции** параметризован пятью формами (нет файла, нет секции, `allowed` не
  булев, неразбираемый TOML, `expires_at` мусор) — все дают один исход, `absent`.
- **`grant` без TTY** проверяется без pty по тому же правилу, что ADR-014 §8: эмуляция терминала
  обошла бы проверяемый барьер. Позитивная ветка записи проверяется вызовом модульной `grant()`,
  минуя CLI, — TTY-проверка живёт в `cli_sanction.py`, а не в `write_sanction.py`, и это
  сознательное разделение: модуль остаётся тестируемым, барьер — непроходимым из кода.
- **Канал `tty`** проверяется существующим `pty`-сценарием `test_cli_meeting.py` (волна 0.6.0) плюс
  один новый тест на то, что журнал получает `channel: "tty"` и санкция при этом не тратится.

## Ожидаемое красное состояние

До DEV-012 отсутствуют модули `ktalk_mcp.write_sanction`, `ktalk_mcp.write_journal`,
`ktalk_mcp.cli_sanction`, `ktalk_mcp.cli_meeting_confirm`, флаг `--confirmation-id` и подкоманда
`sanction`. Все стабы падают на импорте или на коде возврата — это ожидаемое красное, не дефект.

## Регрессия, которую волна ломает намеренно

`test_cli_meeting.py::test_cli_create_meeting_confirm_refuses_when_not_a_tty` проверял, что без
терминала команда отказывает **с текстом про терминал**. Отказ сохраняется (нет санкции → 40), но
текст меняется на санкционный. Тест правится в DEV-012 и разбирается в отчёте QA-008 как
«ожидаемая смена контракта», не как поломка.
