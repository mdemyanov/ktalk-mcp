---
title: "DEV-017: локальная проверка формата --timezone"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-017: локальная проверка формата `--timezone`

Реализация [ADR-020](../00-project/adr/ADR-020-timezone-format-validation.md) по companion-спеке
[ADR-020-spec](../40-architecture/ADR-020-timezone-format-validation-spec.md), FR-40
([rooms-calendar-scheduling.md](../30-requirements/rooms-calendar-scheduling.md)). TDD на стабах
QA-author: 31 red → 36 green (`tests/test_fr40_timezone_format.py`).

## Реализация — без расхождений со спекой

Код совпадает со спекой дословно: `TimezoneFormatError`, регулярка `_TIMEZONE_RE` из ADR-020-spec
§1 (диапазон `GMT-14..GMT+14`, обязательный знак, регистрозависимость), вызов после цикла
`_REQUIRED` в `build_meeting_body` (`src/ktalk_mcp/meeting_body.py`), докстринг функции, `--help` в
`cli_meeting_args.py`, перехват `except (MissingFieldError, TimezoneFormatError)` в
`cli_meeting.py` и `cli_meeting_confirm.py`.

Проверено, а не принято на веру: `tools_scheduling.py` действительно не требует правки —
`_AUTH_ERRORS = (KTalkError,)` (строка 17) ловит `TimezoneFormatError` как подкласс `KTalkError`
на строке 86, спека верна.

## Мина фикстур — шире заявленных QA четырёх файлов

QA-011 называл четыре файла с `timezone="Europe/Moscow"`. Фактический список — семь: не только
прямые фикстуры `build_meeting_body`/CLI, но и косвенные потребители (журнал операций, маскирование
секретов, бюджет санкции), где `Europe/Moscow` — часть тела встречи, проходящего через
`build_meeting_body` внутри теста.

| Файл | Вхождений | Природа |
|---|---|---|
| `tests/test_meeting_body.py` | 1 (правлено) + 1 (не правлено) | `FULL_KWARGS["timezone"]` правлена на `GMT+3`; отдельное вхождение в комментарии строки 208 — описание арифметики `start`/`end` → UTC (`+03:00` смещение datetime, не строка поля `timezone`) — не тот же факт, не правилось |
| `tests/test_meeting_scheduling.py` | 1 | `FULL_KWARGS`, дублирует `test_meeting_body.py` осознанно (комментарий в файле: «`tests/` не пакет, кросс-модульный импорт ненадёжен») |
| `tests/test_cli_meeting.py` | 1 | `_PREVIEW_ARGV_FULL` |
| `tests/test_cli_meeting_sanctioned.py` | 1 | `_MEETING_ARGS` |
| `tests/test_write_journal.py` | 1 | `_MEETING_ARGS` |
| `tests/test_write_sanction.py` | 1 | `build_meeting_body(..., timezone="Europe/Moscow", ...)` inline в тесте prompt-injection темы |
| `tests/test_secret_masking.py` | 1 | inline `--timezone Europe/Moscow` в argv CLI |

Итого 7 правленных вхождений (значение), плюс одно намеренно не тронутое (комментарий, другой
факт). Правка точечная: `sed` по строке, не `replace_all` в `test_meeting_body.py` — иначе
затронул бы комментарий 208, который описывает не форму `timezone`, а смещение `+03:00` в примере
UTC-конвертации (тот факт неизменен: `GMT+3` даёт то же смещение, но комментарий ссылался на
исходное IANA-имя как на читаемый ярлык часового пояса, не на проверяемое значение поля).

## Верификация

```
uv run --with pytest --with pytest-xdist pytest tests/test_fr40_timezone_format.py -q -n 8
→ 36 passed (было 5 passed / 31 failed)

uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
→ 550 passed (было 514 до появления файла стабов, 519/31 failed после)

bash scripts/check.sh --fast
→ Errors: 0 | Warnings: 3 (те же грандфазер-warnings, не новые)
```

`src/ktalk_mcp/registry.py` не тронут.
