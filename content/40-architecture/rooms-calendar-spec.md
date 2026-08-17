---
title: Комнаты, календарь, планирование — раскладка реализации волны 2
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# Комнаты, календарь, планирование — раскладка реализации волны 2

Companion-уровня спека (SA-005), закрывающая раскладку по файлам для
[«Комнаты, календарь и планирование встреч»](../30-requirements/rooms-calendar-scheduling.md)
(FR-13, FR-17, FR-18, FR-19) поверх решений [ADR-004](../00-project/adr/ADR-004-undocumented-contour.md)
и [ADR-005](../00-project/adr/ADR-005-write-operations.md) и их companion-спек. Требования и
решения ADR не пересматриваются — только раскладываются по коду. Образец глубины и стиля —
[client-modules-spec.md](client-modules-spec.md) (эпик 0.5.0).

## Контекст

Центральное ограничение волны — гейт C13 (`.nauta-gates.yaml`): `client.py` уже на 349 строках
при самом длинном объявлении (`class KTalkClient`) в 287 строк — вторая метрика парного гейта уже
провалена, любая новая строка в файле включает первую и блокирует коммит. Прецедент решения уже
есть: волна 0.5.0 вынесла `auth.py`, `pagination.py`, `enrichment.py`, `download.py`,
`reconciliation.py` из `client.py` ровно по этой причине (см. докстринг `auth.py`). Эта волна
следует тому же приёму жёстче: **`client.py` не получает ни одной новой строки** — три новые
операции (комната, календарь, создание встречи) живут в новых модулях как свободные функции,
принимающие `KTalkClient` и обращающиеся к его «приватным» атрибутам (`_client`, `_profile_for`,
`_classify`) — тот же приём, что `auth.py::full_participants_apikey`/`resolve_chat_channel` уже
применяют к клиенту сегодня.

## 1. Карта файлов

### Не меняется вовсе

| Файл | Строк | Почему |
|---|---|---|
| `client.py` | 349 | Заморожен этой волной жёстче, чем `registry.py` в 0.5.0: там был грандфазер с потолком, здесь потолок уже 0 новых строк — вторая метрика гейта провалена, первая (350) в одном шаге |
| `registry.py` | 562 | Не относится к волне — ни одна из трёх операций не пишет в SQLite (NFR-8 AC) |

### Меняется (аддитивно, без переписывания существующих объявлений)

| Файл | Было | Оценка после | Δ | Новое макс. объявление | Гейт |
|---|---|---|---|---|---|
| `auth.py` | 265 | ~295 | +30 (3 записи `OPERATION_PROFILES`, 3 записи `OPERATION_LABELS`) | ~24 (без изменений — дописываются только словарные литералы, а не `def`/`class`; см. сноску¹) | pass, запас ~55 |
| `formatters.py` | 443 | ~503 | +60 (3 новых форматтера, см. §4.4/§5.4/§6.5) | ~25 (новые), 51 (старый максимум) | pass — T уже превышен, T_S нет, тот же паттерн, что проходит сегодня |
| `tools_meetings.py` | 71 | ~101 | +30 (`ktalk_list_calendar` внутри `register()`) | `register()` ~84 | pass, запас по 100 ~16 строк — держим тонким сознательно (см. §7.1) |
| `server.py` | 49 | ~55 | +6 (регистрация двух новых наборов инструментов) | тривиально | pass |
| `cli.py` | 240 | ~265 | +25 (FR-19 диспетчер, 2 новых подпарсера делегированы в `cli_meeting.py`) | `build_parser()` ~59, `main()` ~26 | pass, запас ~85 |
| `cli_sync.py` | 169 | 170 | +1 (уточнение комментария к `del reg`, см. §7.2 — не функциональная правка) | без изменений | pass |

¹ Модельное допущение, унаследованное из уже принятого в проекте прецедента: измеренный максимум
`auth.py` сегодня — 24 строки, при том что литерал `OPERATION_PROFILES` физически занимает 58
строк (54–111) — то есть гейт считает объявлениями `def`/`class`, не словарные/кортежные
литералы. Раскладка этой спеки полагается на то же допущение для всех новых таблиц-констант
(`ROOM_FIELDS`, `CALENDAR_ITEM_FIELDS`, `KNOWN_400_TEXTS`, `_REQUIRED`).

### Новые файлы

| Файл | Строк (оценка) | Макс. объявление | Ответственность |
|---|---|---|---|
| `contour_diagnostics.py` | ~48 | ~20 (`diagnose_undocumented_failure`) | Переиспользуемая корреляционная диагностика + `ContourDriftError` (ADR-004 п.5) |
| `rooms.py` | ~58 | ~30 (`get_room`) | FR-17: чтение комнаты, маппер 18 полей |
| `calendar_reader.py` | ~145 | ~28 (`_fetch_segment`) | FR-18: сегментация 7-дневного окна, маппер 20 полей, дедуп на стыках |
| `meeting_body.py` | ~52 | ~22 (`build_meeting_body`) | FR-13/NFR-9: allow-list компоновщик тела + хеш |
| `confirmation.py` | ~46 | ~22 (`class ConfirmationStore`) | FR-13: in-memory хранилище подтверждений, TTL, single-use |
| `meeting_scheduling.py` | ~32 | ~10 (`create_meeting`) | FR-13: оркестрация превью (`PreviewService`) + единственная сетевая мутация |
| `cli_meeting.py` | ~115 | ~28 (`cmd_create_meeting_confirm`) | CLI-обработчики `create-meeting-preview`/`create-meeting-confirm`, `isatty()`-барьер |
| `tools_rooms.py` | ~35 | ~25 (`register`) | MCP: `ktalk_get_room` |
| `tools_scheduling.py` | ~55 | ~48 (`register`) | MCP: `ktalk_preview_meeting` (единственный МCP-инструмент FR-13 — без мутации) |

Все новые файлы на порядок ниже порога 350/100 — запас закладывается на случай, если следующая
волна добавит операции того же контура (комнаты/календарь) без повторного пересмотра раскладки.

<mermaid path="./rooms-calendar-spec-modules.mermaid" width="900px" height="640px"/>

## 2. `OPERATION_PROFILES` — дословные записи (`auth.py`)

Три записи добавляются в существующий словарь `OPERATION_PROFILES` (после `get_participants_report`),
плюс три строки в `OPERATION_LABELS`. Ничего из существующих записей не меняется.

```python
    "get_room": {
        # FR-17: внутренний путь, вне спеки, регистронезависим (постановка §5, живой GET).
        AuthMode.SESSION: EndpointProfile("/api/rooms/{room_name}", None),
        # ADR-004, таблица «Подтверждённость»: api-key не проверен вовсе — fail-closed (FR-17 AC3).
        AuthMode.API_KEY: None,
    },
    "get_calendar": {
        # FR-18: внутренний путь, вне спеки, подтверждён исчерпывающе под session (Ф-17–Ф-31 RES-003).
        AuthMode.SESSION: EndpointProfile("/api/calendar", None),
        # ADR-004 п.2: 200 наблюдался под api-key (Ф-34), но необъяснимо (расходится с Ф-33/Ф-35
        # тем же ключом) — не "рабочая" запись несмотря на живой позитивный результат.
        # Ревизуемо отдельной задачей при появлении объяснения, не тихой правкой этой строки.
        AuthMode.API_KEY: None,
    },
    "create_meeting": {
        # FR-13: путь БЕЗ префикса /api (mainpart, Ф-38 RES-003) — не опечатка, отличается от
        # get_room/get_calendar намеренно. Реализовано по документарной экстраполяции
        # (Ф-37–Ф-43) — "рабочая" запись здесь означает "код готов слать по этому пути", а не
        # "подтверждено живым ответом"; статус "неверифицирован боевым POST" явно не снимается
        # наличием записи — см. §6.6 и постановка §6 (критерий приёмки, красная линия разведки).
        AuthMode.SESSION: EndpointProfile("/calendar", None),
        # Не проверено вовсе ни одним сигналом (RES-003 §3) — fail-closed, тот же принцип, что
        # get_room/api-key.
        AuthMode.API_KEY: None,
    },
```

```python
OPERATION_LABELS = {
    "list_archive": "архив",
    "get_participants_full": "полный состав участников",
    "get_participants_report": "отчёт по участникам встречи",
    "get_room": "чтение комнаты",
    "get_calendar": "чтение календаря",
    "create_meeting": "планирование встречи",
}
```

**Закрытый вопрос ADR-004 п.1 (вариант А/Б для `get_calendar`/api-key).** Выбран **вариант Б**
(комментарий в коде со ссылкой на ADR-004, без изменения модели `EndpointProfile`) — записи выше
несут явную ссылку на ADR-004 п.2 в комментарии; решение ревизуемо без миграции структуры данных.
Вариант В (третье состояние доверия) остаётся отклонённым — ADR-004 уже закрыл его в
«Альтернативах», здесь не пересматривается.

## 3. Корреляционная диагностика (`contour_diagnostics.py`)

Единственный переиспользуемый компонент для FR-17/FR-18 — POST (FR-13) в нём не участвует
(ADR-004-spec «Границы»: единственный источник правды для записи — санкционированная боевая
проверка, не корреляция).

```python
TRANSIENT_ERRORS = (KTalkError, httpx.HTTPError)

class ContourDriftError(KTalkError):
    def __init__(self, operation: str, detail: str) -> None: ...

async def diagnose_undocumented_failure(
    client: KTalkClient, operation: str, error: Exception
) -> None:
    """Всегда завершается исключением: либо перевыбрасывает `error` (контроль тоже
    провалился — не дрейф контура), либо поднимает `ContourDriftError` (контроль в порядке
    — сбой локализован в недокументированном пути)."""

def require_contract_field(payload: dict, field: str, operation: str) -> None:
    """ContourDriftError вместо тихого KeyError/None при отсутствии поля-якоря контракта
    на коде 200 — без корреляции (доступ уже подтверждён кодом 200)."""
```

**Закрытый вопрос ADR-004 п.2 (контрольная операция по режиму).** Унифицировано на
**`list_recordings(top=1)` для ОБОИХ режимов** — отступление от иллюстративного (не
нормативного) примера ADR-004-spec («`list_recordings` для session, `get_recording` для
api-key»): `get_recording` требует заведомо валидный `recording_key`, которого в контексте
диагностики комнаты/календаря взять неоткуда без побочного похода за списком; `list_recordings`
уже подтверждена рабочей в обоих режимах (используется как проба в `_auth_status_session`),
не требует предварительного состояния, дёшева по объёму ответа (`top=1`).

**Правило запуска диагностики.** Любой отказ (кроме отсутствия профиля — тот не доходит до сети
вовсе) недокументированного вызова уходит в `diagnose_undocumented_failure`, **кроме** 400 с
текстом, дословно совпадающим с каталогом Ф-26 (см. §5.2) — те трактуются как обычная
валидационная ошибка вызывающего/сегментации, не как сигнал дрейфа, и не тратят лишний сетевой
вызов на корреляцию. Деградация формы на коде 200 (`require_contract_field`) тоже не запускает
корреляцию — доступ уже подтверждён, вопрос только в форме, а не в правах/сети.

## 4. FR-17 — Комната (`rooms.py`, `tools_rooms.py`)

### 4.1 Маппер (18 полей, постановка §5)

```python
ROOM_FIELDS = (
    "roomName", "sessionHalls", "stageConferenceId", "moderators", "anonymousModerators",
    "allowAnonymous", "anonymousAccessExpirationDate", "anonymousAccessModifiedDate",
    "audioPolicy", "videoPolicy", "screenSharePolicy", "isModerator", "conferenceId",
    "sipSettings", "onlineUsers", "simultaneousTranslation", "chatChannelSettings",
    "maskingSettings",
)

def map_room(raw: dict) -> dict:
    require_contract_field(raw, "roomName", "get_room")  # якорь контракта
    return {field: raw.get(field) for field in ROOM_FIELDS}
```

Вложенные объекты (`moderators`, `sipSettings`, `chatChannelSettings`, `maskingSettings`, …)
передаются как есть (без глубокой типизации) — их внутренняя форма не документирована и
зондом отдельно не проверялась; форматтер (§4.4) сериализует их компактным JSON внутри markdown.

### 4.2 Чтение

```python
async def get_room(client: KTalkClient, room_name: str) -> dict:
    """Читает конфигурацию комнаты по имени.

    ПОБОЧНЫЙ ЭФФЕКТ (ADR-006): сервер не различает существующее и ранее не
    встречавшееся имя — оба дают 200 с идентичной по форме заготовкой (Ф-45).
    Вызов с именем, которое в этом контуре ещё не читалось, создаёт объект
    комнаты (Ф-49); отменить средствами проекта нельзя (инструмента удаления
    нет). НЕ использовать эту операцию для проверки занятости/свободности
    имени — сам факт проверки создаёт занятость.
    """
    profile = client._profile_for("get_room")  # fail-closed до сети (FR-17 AC3, api-key)
    path = profile.path_template.format(room_name=quote_path_param(room_name))
    try:
        response = await client._client.get(path)
        client._classify(response, profile.required_scope)
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "get_room", exc)
        raise
    return map_room(response.json())
```

**Решение по FR-17 AC2 — пересмотрено ADR-006 (было: «сужена, ждёт боевой проверки»).** Живой
зонд боевой приёмки (RES-001, Ф-45/Ф-49; сверка QA-001 п.2) показал: сервер отдаёт **200 на любое
имя, включая гарантированно свежее случайное — 404 не отдаёт никогда** (4 независимых зонда). Это
не деградация формы и не отказ, а успешный read-ответ с побочным эффектом записи — класс, для
которого корреляционная диагностика ADR-004 не проектировалась (она реагирует на не-2xx или на
пропажу якорного поля при 200, здесь нет ни того, ни другого). Ветка «любой не-2xx → дрейф
контура» в коде выше остаётся как есть (защищает от иного будущего сбоя, если он появится), но
она никогда не адресовала и не может адресовать найденный случай — гипотетический 404 сюда не
приходит. Собственного каталога ошибок для `get_room`, как у календаря (Ф-26), по-прежнему нет:
единственный подтверждённый живой исход на любое имя — 200.

Контракт операции (ADR-006): `get_room` — read-с-побочным-эффектом-записи, не pure read.
Предупреждение об этом — статичная строка в докстрайне (выше) и в описании MCP-инструмента
(§4.3), безусловная на каждый вызов; условного предупреждения «этот вызов создал новую комнату»
не будет — форма ответа не различает «существовало» и «создано этим вызовом» (Ф-45), детектора для
такого различения не существует. Гейт подтверждения по образцу ADR-005 не вводится — см. ADR-006
п.3 (сработал бы на каждый вызов без разбора, не решая проблему неведения о конкретном имени).

### 4.3 MCP-инструмент — `ktalk_get_room`

Подтверждено имя из постановки (§130 чеклиста) — совпадает с конвенцией `ktalk_<verb>_<noun>`,
`get_` для чтения одного объекта (как `ktalk_get_recording`/`ktalk_get_participants`).

Описание инструмента (видимое вызывающему агенту через MCP-манифест) обязано нести
предупреждение ADR-006: вызов с ранее не читанным в этом контуре именем создаёт комнату как
побочный эффект чтения, необратимый средствами проекта, и что инструмент не пригоден для проверки
занятости имени. Формулировка — на усмотрение Dev, факт наличия предупреждения — часть контракта.

```python
async def ktalk_get_room(room_name: str, format: str = "markdown") -> str
```

### 4.4 Форматтер — `format_room` (`formatters.py`)

Générик по `ROOM_FIELDS`: `roomName` — заголовок, остальные 17 — список `- **field:** value`;
вложенные `dict`/`list` — компактный `json.dumps`. Ни одно новое объявление не превышает 15 строк.

## 5. FR-18 — Календарь (`calendar_reader.py`, расширение `tools_meetings.py`)

### 5.1 Параметры и форма ответа (Ф-17–Ф-29 RES-003)

| Параметр сервера | Публикуется наружу? | Примечание |
|---|---|---|
| `start` | да, обязателен (AC3) | и короткая дата, и полный ISO принимаются одинаково |
| `end` | да, обязателен (решение SA — см. §5.3) | сервер формально допускает `take` вместо `end`, но клиент всегда шлёт `end` (собственная сегментация — см. §5.3) |
| `take` | нет | клиент всегда шлёт `100` (Ф-21: фактический потолок) |
| `skip` | нет | не работает (Ф-22) — не имеет смысла выставлять |
| `roomName` | да, `room_name` (опционально) | реально фильтрует (Ф-23) |
| `query` | **нет** (AC6) | синтаксически принимается, но не фильтрует (Ф-24) — публикация вводила бы в заблуждение |

Ответ — `{"items": [...]}` (Ф-27), сортировка по возрастанию `start` (Ф-29, противоположно
`/api/recordings`).

### 5.2 Каталог известных 400 (Ф-26, дословно)

```python
KNOWN_400_TEXTS = frozenset({
    "Дата начала является обязательной для заполнения",
    "Должна быть задана или дата окончания, или количество запрашиваемых элементов; "
    "Должна быть задана или дата окончания, или количество запрашиваемых элементов",
    "Период запроса не должен превышать 7 дней",
    "Дата окончания должна быть больше даты начала",
    "The field Take must be between 1 and 1000.",
})
```

(«The value '...' is not valid for Start.» из каталога ADR-004-spec не включена дословно, т.к.
содержит переменную часть — распознаётся по префиксу `"The value '"` и суффиксу `"is not valid
for Start."` при сопоставлении, не точным равенством строки.)

### 5.3 Сегментация окна (закрывает открытый вопрос требования)

```python
def split_window(start: date, end: date, *, max_days: int = 7) -> list[tuple[date, date]]:
    """Непересекающиеся сегменты <=7 дней без пропусков и без перекрытия: следующий
    сегмент начинается на день позже конца предыдущего."""
```

Решение: клиент **всегда** передаёт явный `end` на каждый сегмент (никогда не полагается на
режим «только `take`, без `end`», при котором 7-дневный лимит не применяется вовсе, Ф-20) —
предсказуемое, тестируемое поведение важнее теоретической экономии одного параметра. Каждый
сегмент дополнительно получает `take=100` явно (не полагаемся на непроверенный дефолт при
`start`+`end` без `take`).

**Дедуп на стыках (AC — «без потерь и без дублей»).** Идентичность элемента — поле `id` (Ф-28,
уникально на выборке); при его отсутствии — пара `(meetId, start)` (запасной вариант: `meetId`
повторяется у рекуррентных экземпляров, `start` у них разный). Дедуп — по построению набора
`seen`, не по доверию к границам сегментов не перекрываться по данным сервера.

**Потолок 100 на сегмент (AC4).** Сегмент, вернувший ровно 100 элементов, попадает в
`CalendarReadResult.incomplete_segments` — сервер не даёт способа получить остаток (`skip` не
работает, Ф-22); предупреждение, не молчаливое усечение.

**Границы.** Сегменты обходятся последовательно, не конкурентно — для типичной ширины окна
(недели–месяцы) это несущественно; при очень широких окнах (годы) стоило бы ограниченного
fan-out по образцу `enrichment.py`, но требования на такую ширину нет — не реализовано в этой
волне.

### 5.4 Маппер (20 полей, Ф-28)

```python
CALENDAR_ITEM_FIELDS = (
    "busyType", "calendarSource", "description", "end", "id", "isRecurring", "location",
    "locationAttendee", "meetId", "onlineMeetingUrl", "onlineUsers", "optionalAttendees",
    "organizer", "requiredAttendees", "room", "roomName", "start", "stream", "subject",
    "urlParams",
)

def map_calendar_item(raw: dict) -> dict:
    require_contract_field(raw, "roomName", "get_calendar")
    require_contract_field(raw, "start", "get_calendar")
    return {f: raw.get(f) for f in CALENDAR_ITEM_FIELDS}
```

`meetId`/`urlParams` — вне документированной `EmailCalendarItem`, но часть контракта (ADR-004
п.3). Документированные, но ни разу не встреченные поля (`recurrence`, `isCancelled`,
`isAllDayEvent`, `externalMeeting`, `isPrivate`, `onlineUsersCount`) сознательно не входят в
список — их отсутствие не ошибка (не тестируем на присутствие).

### 5.5 Оркестрация и обработка ответа сегмента

```python
async def get_calendar_window(
    client: KTalkClient, start: date, end: date, *, room_name: str | None = None
) -> CalendarReadResult: ...

async def _fetch_segment(
    client: KTalkClient, seg_start: date, seg_end: date, room_name: str | None
) -> tuple[list[dict], bool]:
    profile = client._profile_for("get_calendar")  # fail-closed до сети (api-key)
    ...
```

Решающая таблица `_fetch_segment` (реализация — прямой if/except по этой таблице, не более):

| Ответ сегмента | Действие |
|---|---|
| 200, `items` присутствует | штатно — маппинг + проверка потолка 100 |
| 200, `items` отсутствует | `ContourDriftError` сразу, без корреляции |
| 400, текст ∈ каталогу §5.2 | `KTalkError(текст)` — валидационная ошибка вызывающего/сегментации, без корреляции |
| 400, текст вне каталога | `diagnose_undocumented_failure` |
| 401/403/404 | `diagnose_undocumented_failure` (`_classify` уже даёт осмысленный текст — корреляция уточняет, дрейф это или обычный auth-сбой) |
| сетевая ошибка (`httpx.HTTPError`) | `diagnose_undocumented_failure` |

### 5.6 MCP-инструмент — `ktalk_list_calendar`

```python
async def ktalk_list_calendar(
    start: str | None = None,
    end: str | None = None,
    room_name: str | None = None,
    format: str = "markdown",
) -> str
```

`start`/`end` — `None` по умолчанию в сигнатуре (не «required» на уровне схемы) с явной
проверкой в теле (`if start is None or end is None: raise ValueError(...)`, тот же паттерн, что
уже даёт `KTalkClient.get_chat_messages` для отсутствующих `recording_key`/`conference_key`) —
единый, тестируемый источник сообщения, а не два разных пути (схемная ошибка FastMCP vs наша).
`query` не входит в сигнатуру вовсе (AC6). Докстрока прямо не называет выдачу «вашим календарём»
(AC7, Ф-30) — «встречи, видимые активной авторизации».

### 5.7 Форматтер — `format_calendar` (`formatters.py`)

Таблица `| Тема | Комната | Начало | Конец |` + предупреждения по `incomplete_segments` сверху,
если есть. Заголовок — «Запланированные встречи, видимые активной авторизации (N)», не «Ваш
календарь».

## 6. FR-13 — Планирование встречи (`meeting_body.py`, `confirmation.py`, `meeting_scheduling.py`, `cli_meeting.py`, `tools_scheduling.py`)

### 6.1 Компоновщик тела (`meeting_body.py`)

```python
_REQUIRED = (
    "subject", "start", "end", "timezone", "roomName", "requiredUserKeys",
    "allowAnonymous", "pinCode", "enableSip", "enableAutoRecording",
)  # NFR-9 (8 строк таблицы = 9 физических полей) + subject (обязателен по схеме, Ф-37,
   # не входит в NFR-9, но проверяется тем же None-циклом — не откладывать отказ до сети)

class MissingFieldError(KTalkError):
    def __init__(self, field: str) -> None: ...

def build_meeting_body(
    *,
    subject: str | None = None, start: str | None = None, end: str | None = None,
    timezone: str | None = None, room_name: str | None = None,
    required_user_keys: list[str] | None = None, description: str | None = None,
    enable_auto_recording: bool | None = None, enable_sip: bool | None = None,
    pin_code: str | None = None, allow_anonymous: bool | None = None,
) -> dict:
    """Каждое поле `_REQUIRED` проверяется через `is None` (не truthiness) — явный
    пустой список участников/пустой pinCode/False — валидные явные решения, отсутствие
    значения — нет. `description` — единственный тихий дефолт (`""`), разрешённый NFR-9."""

def canonical_body_hash(body: dict) -> str:
    """sha256(json.dumps(body, sort_keys=True, ensure_ascii=False))."""
```

`isRecurring`/`recurrence` и поля вне списка выше физически не имеют параметра — структурная
невозможность, не рантайм-проверка (ADR-005 «Решение»).

### 6.2 Хранилище подтверждений (`confirmation.py`)

```python
CONFIRMATION_TTL = timedelta(minutes=10)

@dataclass(frozen=True)
class ConfirmationRecord:
    body_hash: str
    expires_at: datetime  # UTC-aware

class ConfirmationStore:
    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)): ...
    def issue(self, body_hash: str) -> str: ...   # secrets.token_urlsafe(24), не производный от хеша
    def match(self, confirmation_id: str, body_hash: str) -> bool: ...  # id неизвестен/consumed/
                                                                          # TTL истёк/хеш не совпал
                                                                          # -> одно и то же False
    def consume(self, confirmation_id: str) -> None: ...  # вызывается ДО сетевой попытки
```

**TTL = 10 минут — дизайн-выбор, не измеренная величина** (тот же класс решения, что
`concurrency=5` в `enrichment.py`, client-modules-spec §4: явно помечен как неоткалиброванный).
Обоснование: достаточно времени прочитать 11-польный предпросмотр и набрать команду/ответ в
терминале; достаточно коротко, чтобы не держать открытым окно "решение принято, но ещё не
исполнено" надолго — если оператор отвлёкся дольше 10 минут, разумнее перечитать актуальный
предпросмотр (комната могла освободиться/занятость измениться), чем исполнять решение по
устаревшим данным.

**Важно: `ConfirmationStore` инстанцируется заново на каждый вызов `preview`/`confirm`, не
синглтон уровня процесса** (в отличие от `KTalkClient::get_shared_client()`). Обоснование — §6.3.

### 6.3 Кросс-процессная граница: почему `confirm` не принимает `--id`

ADR-005-spec описывает пару (хеш, срок), которая «живёт только в памяти работающего процесса», и
одновременно требует, чтобы оператор «покинул диалог с агентом и выполнил команду в своём
терминале». Буквальное прочтение подразумевает, что `confirmation_id`, выданный
`ktalk_preview_meeting` (MCP-сервер, свой процесс), может быть предъявлен `create-meeting-confirm`
(CLI, отдельный процесс каждый запуск) — физически невозможно без дисковой/сетевой синхронизации,
которую ADR-005 явно исключает («Негативные»: «подтверждения не переживают перезапуск процесса —
память, не диск»). Это открытая раскладка, оставленная SA-005 companion-спекой ADR-005
(«не додумывать здесь... вернуть вопрос SA»).

**Решение SA-005.** `create-meeting-confirm` **самодостаточен** и не принимает `--id`:

1. Строит тело из **своих** аргументов (тот же полный набор флагов, что у `create-meeting-preview`).
2. Порождает собственный токен через тот же `PreviewService`/`ConfirmationStore`, что и
   превью-путь, **внутри одного вызова** — переиспользование ради тестируемости той же логики
   (TTL/single-use/hash-match), не ради межпроцессной связи, которой физически нет.
3. Печатает предпросмотр (тот же форматтер, что MCP/CLI preview).
4. Синхронно запрашивает явное «да» с терминала (`input()`, после барьера `isatty()`) — это и
   есть «отдельный шаг, ссылающийся на предшествующий предпросмотр» требования FR-13 AC3: шаг
   реален и синхронен, просто не пересекает границу процесса.
5. `store.match` + `store.consume` — не проверка «то же ли это API-подтверждение, что было
   выдано раньше в другом процессе» (такая проверка здесь недостижима в принципе), а проверка
   «не истёк ли TTL, пока оператор читал и набирал ответ» — содержательна даже внутри одного
   процесса (см. §6.2).
6. Один сетевой POST, без retry.

Следствие: `confirmation_id`, который видит агент через `ktalk_preview_meeting`, — **справочный**
для человека («вот что должно появиться, сверьте с тем, что увидите в терминале»), не
машинно-проверяемая связка между MCP-вызовом и CLI-подтверждением. Указывать это в тексте ответа
инструмента прямо (см. §6.4) — не подразумевать связку, которой нет.

### 6.4 MCP — только `ktalk_preview_meeting`

```python
async def ktalk_preview_meeting(
    subject: str | None = None, start: str | None = None, end: str | None = None,
    timezone: str | None = None, room_name: str | None = None,
    required_user_keys: list[str] | None = None, description: str | None = None,
    enable_auto_recording: bool | None = None, enable_sip: bool | None = None,
    pin_code: str | None = None, allow_anonymous: bool | None = None,
    format: str = "markdown",
) -> str
```

Все 11 полевых параметров — `| None = None`: единый, тестируемый источник диагностики
«поле не передано» — `build_meeting_body`, не смесь схемной валидации FastMCP и нашей (тот же
принцип, что §5.6 применяет к `start`/`end` календаря). Мутирующего инструмента нет и не будет —
только `create-meeting-confirm` в CLI.

### 6.5 CLI — `create-meeting-preview` / `create-meeting-confirm` (`cli_meeting.py`)

```python
def register_subparsers(sub) -> None:
    _add_meeting_args(sub.add_parser("create-meeting-preview", help="Предпросмотр встречи (FR-13)"))
    _add_meeting_args(sub.add_parser("create-meeting-confirm", help="Создать встречу (только TTY)"))

def cmd_create_meeting_preview(_reg, args) -> int: ...   # без TTY-барьера, без сети
def cmd_create_meeting_confirm(_reg, args) -> int: ...   # TTY-барьер первым делом
```

Флаги (идентичны на обеих подкомандах): `--subject --start --end --timezone --room-name
--required-user-key (repeatable) --no-required-users --description --enable-auto-recording
{true|false} --enable-sip {true|false} --pin-code --allow-anonymous {true|false}`.

**Булевы поля — не `store_true`.** `--enable-sip`/`--enable-auto-recording`/`--allow-anonymous`
принимают явный `type=_tri_bool` (`"true"`/`"false"`) с `default=None`: `store_true` дал бы
молчаливый `False` при отсутствии флага — ровно тихий дефолт, который NFR-9 запрещает.

**Явная пустая коллекция участников.** `--required-user-key` (`action="append"`, `default=None`)
не может выразить «явно ноль участников» через отсутствие флага (неотличимо от «не решено») —
отдельный `--no-required-users` (`store_true`) даёт `[]` явно; без обоих флагов остаётся `None`
и отклоняется `build_meeting_body`.

**`isatty()`-барьер — только в `cmd_create_meeting_confirm`, первой строкой:**

```python
if not (sys.stdin.isatty() and sys.stdout.isatty()):
    print("Нужен интерактивный терминал (см. README).", file=sys.stderr)
    return 1
```

До `ConfirmationStore`, до построения тела, до сети — провал здесь не тратит ничего лишнего.

### 6.6 Создание (`meeting_scheduling.py`)

```python
class PreviewService:
    def __init__(self, store: ConfirmationStore) -> None: ...
    def preview(self, **fields) -> tuple[dict, str]:
        """build_meeting_body -> canonical_body_hash -> store.issue. Без сети физически —
        не получает KTalkClient."""

async def create_meeting(client: KTalkClient, body: dict) -> dict:
    """Ровно одна сетевая попытка POST /calendar (без /api), без retry. Эквивалент
    компонента "KTalkClient.create_meeting" из ADR-005-spec — реализован свободной функцией
    вне client.py по той же причине, что get_room/get_calendar."""
    profile = client._profile_for("create_meeting")
    response = await client._client.post(profile.path_template, json=body)
    client._classify(response, profile.required_scope)
    return response.json()
```

`create-meeting-confirm` вызывает `create_meeting` через `asyncio.run` с **свежим**
`KTalkClient.from_settings(Settings())` внутри `async with` (паттерн `cli_sync.py`, не
`get_shared_client()` — CLI-процесс одноразовый, нет смысла в долгоживущем синглтоне).
Сетевая ошибка/4xx/5xx: сообщение «исход неизвестен — проверьте `ktalk_list_calendar` перед
повторной попыткой»; токен уже потреблён (`consume` вызывается перед POST, не после) — повтор
требует нового `create-meeting-confirm`, не автоматического retry (NFR-9, RES-003 §3).

## 7. FR-19 — `auth-status` не зависит от реестра

### 7.1 Диспетчер (`cli.py::main`)

```python
_REGISTRY_FREE_COMMANDS = {"auth-status", "create-meeting-preview", "create-meeting-confirm"}

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(); return 2
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help(); return 2
    try:
        if args.command in _REGISTRY_FREE_COMMANDS:
            return handler(None, args)
        with Registry(resolve_db_path(args.db)) as reg:
            return handler(reg, args)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
```

Единственная развилка — до открытия `Registry`, не после: для команд вне множества поведение
байт-в-байт то же, что сегодня (`resolve_db_path` вызывается в том же месте логически, просто
внутри `else`-ветки) — регрессия для `sync/list/dashboard/show/mark-*/export/migrate/set-vault-id`
структурно невозможна, они физически не проходят через новую ветку (AC3 FR-19).
`create-meeting-preview`/`create-meeting-confirm` добавлены в то же множество: обе никогда не
читают и не пишут реестр (§6) — тот же класс избыточной зависимости, который FR-19 устраняет для
`auth-status`, не регрессия (новые команды, не переиспользование существующего пути).

### 7.2 `cli_sync.py::cmd_auth_status` — без функциональных изменений

`del reg` остаётся (сигнатура обработчика унифицирована под `(reg, args)` для всех записей
`_HANDLERS`); `reg` теперь всегда `None` для этой команды — комментарий на месте `del reg`
уточняется («реестр для этой команды больше не открывается вовсе, FR-19 — `reg` всегда `None`»),
без изменения поведения.

## 8. Что НЕ меняется (NFR-6, NFR-8)

- **`client.py`** — 0 строк, ни одного изменённого/нового объявления (см. Контекст).
- **`registry.py`** — не тронут (NFR-8 AC); схема SQLite, мапперы, дедуп — без изменений.
- **10 существующих MCP-инструментов** (`ktalk_list_recordings`, `ktalk_get_recording`,
  `ktalk_get_transcript`, `ktalk_get_summary`, `ktalk_get_summary_by_type`,
  `ktalk_get_participants`, `ktalk_download_recording`, `ktalk_list_archive`,
  `ktalk_get_chat_messages`, `ktalk_auth_status`) — имена и обязательные параметры не меняются;
  новые три (`ktalk_get_room`, `ktalk_list_calendar`, `ktalk_preview_meeting`) — аддитивны.
- **Существующие CLI-команды** (`sync`, `list`, `dashboard`, `show`, `mark-*`, `export`,
  `migrate`, `set-vault-id`) — поведение и зависимость от реестра не меняются (§7.1).
  `auth-status` — поведение диагностики не меняется, меняется только предусловие запуска.
- **Существующие записи `OPERATION_PROFILES`** — не редактируются, только 3 новых добавляются.

## NFR Mapping

| NFR | Как обеспечивается |
|---|---|
| NFR-6 | §8 — 10 инструментов не меняются; 3 новых аддитивны |
| NFR-7 | §2 — 3 операции только записями таблицы; `_profile_for` (неизменный) даёт fail-closed до сети для отсутствующих записей (api-key всех трёх операций, session ничего не теряет) |
| NFR-8 | §1 — `client.py`/`registry.py` не растут; все новые модули на порядок ниже порога |
| NFR-9 | §6.1 (`is None`-валидация по 9 полям), §6.5 (CLI: явные `true|false`, явная пустая коллекция) |
| NFR-10 | Ни один новый модуль не строит сообщение из `request.url`/заголовков/credential; `cli.py`'s `redact_secrets` — тот же последний рубеж, что и раньше, ничего не обходит новые команды (они проходят через тот же `try/except` в `main()`) |
| Р-3 постановки (детекция дрейфа) | §3, §4.2, §5.5 — корреляция + `ContourDriftError` на форме, живой смоук-прогон — DevOps-процедура (ADR-004-spec) |
| Р-1 постановки (трудно для автомата) | §6.3 — CLI-only мутация, `isatty()`, привязка к содержимому даже внутри одного процесса |

## Контракт с QA-author

Дополняет (не дублирует) контракты ADR-004-spec (§ детекция дрейфа) и ADR-005-spec (§ протокол
подтверждения) — оба остаются в силе целиком для своих зон. Здесь — то, что специфично для файловой
раскладки этой спеки.

**Архитектурный контекст:** новые модули `contour_diagnostics.py`, `rooms.py`,
`calendar_reader.py`, `meeting_body.py`, `confirmation.py`, `meeting_scheduling.py`,
`cli_meeting.py`, `tools_rooms.py`, `tools_scheduling.py` — все чистые/тестируемые без реальной
сети (кроме `_fetch_segment`/`get_room`/`create_meeting`, где сеть мокируется на уровне
`httpx`-транспорта `KTalkClient`).

**Edge cases, специфичные для этой спеки (в дополнение к ADR-004-spec/ADR-005-spec):**
- `split_window`: окно ровно 7 дней (1 сегмент), 8 дней (2 сегмента: 7+1), 14 дней (2×7), окно
  из одного дня (`start == end`).
- Дедуп на стыке сегментов: элемент с одинаковым `id` в двух смежных сегментах (искусственно —
  событие ровно на границе) — должен остаться один раз в `CalendarReadResult.items`.
- `get_room`: любой не-2xx ответ (в т.ч. гипотетический 404) при контрольном вызове,
  вернувшемся 200, — `ContourDriftError`, не «комната не найдена» (см. §4.2 обоснование).
- `get_room`/ADR-006 — живьём подтверждено: сервер отдаёт 200 на любое имя, 404 не приходит
  никогда (Ф-45/Ф-49). Существующий тест на мокированный 404
  (`test_get_room_any_non_2xx_with_working_control_raises_contour_drift_not_not_found`) остаётся
  корректным как проверка кода на гипотетический будущий отказ, но не покрывает найденный живой
  случай. Что должно быть покрыто вместо/в дополнение (решение QA-author, не переписывается здесь):
  200 на ранее не встречавшееся имя не помечается как ошибка/«не найдено»; докстрайн/описание
  инструмента несёт предупреждение о побочном эффекте (можно проверить как факт наличия строки, не
  как поведение сети).
- FR-19: `create-meeting-preview`/`create-meeting-confirm` выполняются успешно (в части
  до сети — MissingFieldError/TTY-барьер) при заведомо недоступном пути реестра (тот же приём
  проверки, что уже покрывает `auth-status`).
- `_tri_bool`: `"TRUE"`/`"False"` (регистр) принимаются; `"yes"`/`"1"` — отклоняются
  (`argparse.ArgumentTypeError`), только `true`/`false`.
- `--required-user-key` не передан и `--no-required-users` не передан → `None` →
  `MissingFieldError("requiredUserKeys")`; оба переданы одновременно — поведение не специфицируется
  этой спекой (Dev выбирает детерминированный порядок, например `--no-required-users` побеждает,
  и фиксирует тестом).

**Test-pyramid:**

| Группа | Уровень | Обоснование |
|---|---|---|
| `split_window`, `map_room`, `map_calendar_item`, `build_meeting_body`, `canonical_body_hash` | unit | чистые функции |
| `diagnose_undocumented_failure` (матрица кодов, см. ADR-004-spec) | unit | оба ответа мокируются |
| `get_room`/`_fetch_segment`/`create_meeting` (сеть мокирована) | unit с mock-транспортом httpx | сеть не нужна реальная — только форма ответа |
| `ConfirmationStore` (TTL/single-use/hash-drift, инжектируемые часы) | unit | ADR-005-spec |
| `cmd_create_meeting_confirm` TTY-барьер | integration | реальный `pty`/pipe, не мокируется как чистая функция (ADR-005-spec) |
| FR-19 (`auth-status`/`create-meeting-*` без доступного реестра) | integration | реальный недоступный путь на файловой системе |
| Живой прогон `GET /api/rooms`, `GET /api/calendar`, боевой `POST /calendar` | вне пирамиды | ADR-004-spec/ADR-005-spec — ручной чек-лист DevOps/оператора |

## Бриф для Dev

**Архитектура:** этот файл, [ADR-004](../00-project/adr/ADR-004-undocumented-contour.md)+[spec](ADR-004-undocumented-contour-spec.md),
[ADR-005](../00-project/adr/ADR-005-write-operations.md)+[spec](ADR-005-write-operations-spec.md),
[ADR-006](../00-project/adr/ADR-006-get-room-side-effect.md) (боевая приёмка 0.6.0: `get_room`
мутирует побочным эффектом — докстрайн + описание MCP-инструмента, §4.2/4.3 этого файла).
**Требование:** [rooms-calendar-scheduling.md](../30-requirements/rooms-calendar-scheduling.md).

**Порядок реализации (fixtures → интерфейсы → реализация → тесты, каждый шаг независим по коду,
но опирается по риску на предыдущий):**
1. `contour_diagnostics.py` — фикстуры кодов ответа/каталога Ф-26 → `ContourDriftError`,
   `diagnose_undocumented_failure`, `require_contract_field`.
2. `auth.py` — 3 записи `OPERATION_PROFILES` + `OPERATION_LABELS` (§2).
3. `rooms.py` + `tools_rooms.py` + `format_room` (§4).
4. `calendar_reader.py` + расширение `tools_meetings.py` + `format_calendar` (§5).
5. `meeting_body.py` + `confirmation.py` + `meeting_scheduling.py` (§6.1–6.2, 6.6) — чистая
   логика, без CLI/MCP ещё.
6. `tools_scheduling.py` (`ktalk_preview_meeting`) + `format_meeting_preview`.
7. `cli_meeting.py` + правка `cli.py::main`/`build_parser` (§6.5, §7.1) — последним, поскольку
   собирает предыдущие модули и требует ручной TTY-проверки для полноценного smoke-теста.

**Сценарии приёмки:** FR-17 (кроме AC2, заблокирован), FR-18 (все, кроме нет заблокированных),
FR-13 (кроме последнего боевого AC), FR-19 (все три), NFR-6/7/8/9/10 — полный текст в требовании
и в ADR-004-spec/ADR-005-spec.

## Бриф для DevOps

**Архитектура:** этот файл. Дополняет брифы ADR-004-spec (живой смоук-прогон недокументированного
контура) и ADR-005-spec (runbook «исход неизвестен», тестовая комната для боевой приёмки FR-13) —
не дублируется здесь.

**Дополнительно к тем брифам:**
- README: раздел о `create-meeting-preview`/`create-meeting-confirm` должен явно объяснить §6.3
  (почему `confirm` не принимает `--id` от предыдущего `preview`/агента) — иначе оператор будет
  ожидать сквозной связки, которой архитектурно нет.
- Убедиться, что смоук-прогон FR-17/FR-18 (ADR-004-spec) включает оба параметра сегментации §5.3
  (окно ровно 7 дней и окно > 7 дней) — не только базовый случай.
