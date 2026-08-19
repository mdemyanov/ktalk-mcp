---
title: "ADR-020 spec: локальная проверка формата --timezone"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-020 spec: точки правки, тексты, брифы

Companion-спека к [ADR-020](../00-project/adr/ADR-020-timezone-format-validation.md). Реализует
[FR-40](../30-requirements/rooms-calendar-scheduling.md).

## Компоненты

| Компонент | Ответственность | Входы | Выходы | Зависимости |
|---|---|---|---|---|
| `meeting_body.py::TimezoneFormatError` | Новый класс исключения, форма присутствует, но не проходит регулярку | значение `timezone` | сообщение с форматом и примером | `KTalkError` (`auth.py:41`) |
| `meeting_body.py::_TIMEZONE_RE` | Компилированная регулярка формы | — | bool через `.match` | `re` |
| `meeting_body.py::build_meeting_body` | Точка вызова проверки после цикла `_REQUIRED` | `timezone: str` (уже не `None`) | `TimezoneFormatError` либо продолжение сборки | `_TIMEZONE_RE`, `_REQUIRED` |
| `cli_meeting.py::cmd_create_meeting_preview` | Ловит `TimezoneFormatError` наравне с `MissingFieldError` | — | `print_error` + код 1 | `TimezoneFormatError` |
| `cli_meeting_confirm.py::_run_confirm` | Ловит `TimezoneFormatError` наравне с `MissingFieldError` в `preview(store)` | — | `print_error` + `EXIT_ERROR` | `TimezoneFormatError` |
| `tools_scheduling.py::ktalk_preview_meeting` | Ловит через `_AUTH_ERRORS = (KTalkError,)` — правка не нужна | — | `str(e)` в ответе | `KTalkError` |

## Границы

- Проверка не расходует бюджет санкции записи и не выдаёт `confirmation_id`: `build_meeting_body`
  вызывается из `PreviewService.preview` (`meeting_scheduling.py:24`) ДО `store.issue` — исключение
  прерывает функцию раньше строки, выдающей id.
- Проверка не нормализует и не конвертирует значение — принимает или отклоняет ровно то, что
  передал вызывающий (решение владельца, FR-40 «Решение», не переоткрывается).
- Проверка не интерпретирует ответ сервера — `CalendarTimeZoneParse` остаётся сырым текстом
  (ADR-020 §5), перевод в отдельный класс не входит в объём.

## Реализация

### 1. Класс ошибки и регулярка (`meeting_body.py`)

Рядом с `MissingFieldError` (после блока, до `build_required_attendees`):

```python
import re

_TIMEZONE_RE = re.compile(r"^GMT[+-](?:[0-9]|1[0-4])$")


class TimezoneFormatError(KTalkError):
    """Форма `timezone` не распознана — отказ до сетевого вызова (FR-40).

    ГИПОТЕЗА: диапазон `GMT-14..GMT+14` не измерен целиком, подтверждено
    замером только `GMT+3` (rooms-calendar-scheduling.md:357-368,
    ADR-020 §3). Границы взяты по общемировому диапазону смещений UTC, не по
    факту API — ревизуются следующим боевым замером с иным значением.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f'Часовой пояс «{value}» не распознан. Требуемый формат: `GMT±N` '
            "(пример: `GMT+3`). Другие нотации (IANA, Windows ID, ISO-смещение, "
            "аббревиатуры) сервер не принимает — см. FR-40."
        )
        self.value = value
```

### 2. Вызов в `build_meeting_body` (после цикла `_REQUIRED`, `meeting_body.py:113-115`)

```python
for field in _REQUIRED:
    if body[field] is None:
        raise MissingFieldError(field)
if not _TIMEZONE_RE.match(body["timezone"]):
    raise TimezoneFormatError(body["timezone"])
```

Порядок: обязательность → форма (ADR-020 §4). `body["timezone"]` в этой точке гарантированно
`str` (цикл выше уже исключил `None`).

### 3. Докстринг `build_meeting_body` — формат явно (FR-40 AC4)

Добавить в docstring функции (после существующего абзаца про `is None`):

> `timezone` принимает единственную форму `GMT±N` (пример `GMT+3`, диапазон `GMT-14..GMT+14`,
> ГИПОТЕЗА — измерен только `GMT+3`). Другая нотация отклоняется `TimezoneFormatError` до сборки
> тела.

### 4. `--help` CLI (`cli_meeting_args.py::add_meeting_args`)

```python
parser.add_argument(
    "--timezone",
    default=None,
    help="Формат GMT±N, пример: GMT+3 (единственная подтверждённая форма, FR-40)",
)
```

### 5. Перехват на обеих ветках

`cli_meeting.py:52` и `cli_meeting_confirm.py:132`:

```python
except (MissingFieldError, TimezoneFormatError) as exc:
```

Импорт `TimezoneFormatError` добавляется рядом с существующим импортом `MissingFieldError` в обоих
файлах.

## Data flow

Вызывающий (CLI/MCP) → `build_meeting_body(timezone=...)` → цикл `_REQUIRED` (обязательность) →
`_TIMEZONE_RE.match` (форма) → тело собрано → `canonical_body_hash` → `store.issue` →
`confirmation_id`. Отказ на любом из первых двух шагов не доходит до `store.issue` — сеть и
бюджет санкции не затронуты.

## NFR mapping

- FR-40 AC1 (`GMT+3` принимается) → `_TIMEZONE_RE` матчит, тело собирается без изменений.
- FR-40 AC2 (семь отклонённых форм, ноль сетевых вызовов) → `TimezoneFormatError` до
  `PreviewService.preview` → `store.issue`.
- FR-40 AC3 (бюджет/`confirmation_id` не расходуются) → см. «Data flow»: исключение раньше
  `store.issue` физически.
- FR-40 AC4 (сообщение называет формат и пример, не сырой `CalendarTimeZoneParse`) →
  `TimezoneFormatError.__init__`, текст не содержит подстроку `CalendarTimeZoneParse`.
- FR-40 AC5 (`--help`/докстринг называют формат) → §3, §4 выше.

## Контракт с QA-author

**Acceptance-сценарии (полный список из FR-40):**
- `GMT+3` принимается, тело уходит без изменений.
- Каждая из семи отклонённых форм замера (`Europe/Moscow`, `Russian Standard Time`, `+03:00`,
  `MSK`, `180`, `RTZ 2 (MSK)`, `(UTC+03:00) Москва, Санкт-Петербург`) отклоняется до сети.
- Отказ по формату не списывает бюджет санкции и не выдаёт `confirmation_id`.
- Сообщение об ошибке называет формат и пример, не пересказывает `CalendarTimeZoneParse`.
- `--help` и докстринг `build_meeting_body` называют формат явно.

**Архитектурный контекст:**
- Компоненты: `meeting_body.py` (`TimezoneFormatError`, `_TIMEZONE_RE`), `PreviewService`
  (`meeting_scheduling.py`), три поверхности вызова (`cli_meeting.py`, `cli_meeting_confirm.py`,
  `tools_scheduling.py`).
- Интеграции: нет сетевого вызова на этом пути — по определению самой проверки.
- Границы доверия: вход `timezone` — от вызывающего (оператор/агент), без предварительной
  валидации до `build_meeting_body`.

**Edge cases / граничные условия:**
- Диапазон `GMT-14..GMT+14` — экстраполяция, не факт (ADR-020 §3); значение вне диапазона,
  которое сервер мог бы принять, локально отклоняется — не покрывается регрессией на измеренных
  данных (нет замера).
- Значение внутри диапазона, но отличное от `GMT+3` (например `GMT+5`), проходит регулярку и
  уходит на сеть — при отказе сервера `CalendarTimeZoneParse` возвращается как сырой текст
  (ADR-020 §5), не как `TimezoneFormatError`.
- Пустая строка, `None` (уже отдельная ветка `MissingFieldError`), значения с пробелами,
  регистр (`gmt+3`) — регулярка регистрозависима, `gmt+3` отклоняется.
- Порядок: `timezone=None` даёт `MissingFieldError`, не `TimezoneFormatError` — параметризованный
  тест на обе ветки цикла.

**Рекомендация по пирамиде тестов:**

| Группа AC | Уровень | Обоснование |
|---|---|---|
| `GMT+3` принят, семь форм отклонены, порядок проверок | unit | чистая функция `build_meeting_body`, без сети и БД |
| Бюджет санкции/`confirmation_id` не расходуются при отказе по форме | unit | тот же процесс, `PreviewService` с `ConfirmationStore` в памяти/temp-файле |
| Текст сообщения (снимок) | unit | сравнение строки, без внешних зависимостей |
| `--help` CLI и докстринг (текстовый снимок) | unit | статическая проверка вывода `argparse`/`__doc__` |
| Обе ветки CLI (`*-preview`, `*-confirm`) ловят исключение и возвращают код 1 | integration | проход через `argparse`/`sys.exit`, реальный CLI entrypoint |
| MCP-путь `ktalk_preview_meeting` возвращает читаемую ошибку | integration | `_AUTH_ERRORS` перехват через FastMCP-обёртку |

## Бриф для Dev

**Architecture:** этот файл. **Requirement:** [FR-40](../30-requirements/rooms-calendar-scheduling.md). **Phase:** Production.
**Implement:** `TimezoneFormatError` + `_TIMEZONE_RE` в `meeting_body.py`; вызов после цикла
`_REQUIRED`; докстринг `build_meeting_body`; `--help` в `cli_meeting_args.py`; перехват в
`cli_meeting.py` и `cli_meeting_confirm.py` (`except (MissingFieldError, TimezoneFormatError)`).
**Order:** fixtures (8 значений замера как параметры теста) → `TimezoneFormatError`/регулярка →
вызов в `build_meeting_body` → перехват на CLI-ветках → `--help`/докстринг → тесты.
**Acceptance scenarios:** см. «Контракт с QA-author» выше — все пять пунктов FR-40.

## Бриф для DevOps

**Architecture:** этот файл.
**Prepare:** изменений инфраструктуры нет — проверка целиком локальная, без новых зависимостей,
эндпоинтов или мониторинга. Runbook/rollback не меняются (правка не затрагивает `OPERATION_PROFILES`
и сетевые пути).
**NFRs from BA:** нет новых NFR сверх уже действующих NFR-8 (гейт объёма кода — правка укладывается
в существующий бюджет `meeting_body.py`) и NFR-9 (без тихих дефолтов — проверка не подставляет
значение, только отклоняет).
