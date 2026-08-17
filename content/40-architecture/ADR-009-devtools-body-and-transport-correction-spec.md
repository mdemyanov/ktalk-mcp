---
title: "ADR-009 spec: тело create_meeting по браузерному снимку, X-Platform, резолюция key"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-009 spec: тело create_meeting по браузерному снимку, X-Platform, резолюция key

Companion-спека к [ADR-009](../00-project/adr/ADR-009-devtools-body-and-transport-correction.md).
Источник фактов — обезличенный разбор DevTools-снимка владельца (постановка SA-004, `docs/`,
не в git). Секреты, куки, реальные значения из снимка сюда не переносятся.

## 1. Таблица полей — было / стало

| Поле JSON | ADR-005 (было) | ADR-009 (стало) | Источник значения |
|---|---|---|---|
| `subject` | обязателен, `str` | без изменений | вызывающий (NFR-9) |
| `description` | опционален, `""` тихий дефолт | без изменений | вызывающий / `""` |
| `start`/`end` | локальное смещение `+03:00` | UTC, суффикс `Z`, миллисекунды | вызывающий (локальное время) → конвертация в `meeting_body.py` |
| `timezone` | `"GMT+3"` | без изменений (совпало) | вызывающий |
| `roomName` | обязателен, `str` | без изменений — непрозрачный идентификатор (ADR-006) | вызывающий |
| `allowAnonymous` | обязателен, `bool` | без изменений | вызывающий (NFR-9) |
| `anonymousAccessExpirationDate` | отсутствовало | `None`, если `allow_anonymous=False`; **новый обязательный** параметр, если `True` | вызывающий (только при `True`) |
| `pinCode` | обязателен, `str`, `""` при «без PIN» | обязателен, `str \| None`, `None` — валидное явное «без PIN» | вызывающий, новый CLI-флаг `--no-pin-code` |
| `enableAutoRecording` | обязателен, `bool` | без изменений | вызывающий (NFR-9) |
| `autoRunDeepFakeDetection` | отсутствовало | фиксированный литерал `None` | архитектура (не параметр) |
| `isRecurring` | физически недостижимо (ADR-005) | фиксированный литерал `False` (та же недостижимость для `True`) | архитектура (не параметр) |
| `requiredUserKeys` (`list[str]`, логин) | обязателен | **удалено**, заменено на `requiredAttendees` | — |
| `requiredAttendees` | отсутствовало | `[{"type": "user", "key": str}]`, `key` — числовой id строкой | вызывающий, новый параметр `required_attendee_keys: list[str]` (числовые id) |
| `maskingSettings` | отсутствовало | фиксированный литерал `{"nameMaskingMode": "none", "postMaskingMode": "none", "showAdditionalInfo": true}` | архитектура (не параметр) |
| `enableSip` | обязателен, `bool` | **удалено** — поля нет в реальном API | — |

Итог: 12 полей от вызывающего/архитектуры + `description` с тихим дефолтом = 13 ключей тела
(было 11). Отсутствие `enableSip` — та же структурная невозможность, что уже была применена к
`isRecurring` в ADR-005: параметра для него в `build_meeting_body` физически нет.

## 2. `meeting_body.py` — новая сигнатура (псевдокод)

```python
_REQUIRED = (
    "subject", "start", "end", "timezone", "roomName", "requiredAttendees",
    "allowAnonymous", "pinCode", "enableAutoRecording",
)  # anonymousAccessExpirationDate проверяется отдельным условным правилом (§3), не общим циклом

_FIXED = {
    "isRecurring": False,
    "autoRunDeepFakeDetection": None,
    "maskingSettings": {
        "nameMaskingMode": "none", "postMaskingMode": "none", "showAdditionalInfo": True,
    },
}  # архитектурные константы — не параметры build_meeting_body, не проверяются на None

def build_meeting_body(
    *,
    subject: str | None = None,
    start: str | None = None,   # локальное ISO с оффсетом от вызывающего — конвертация в UTC внутри
    end: str | None = None,
    timezone: str | None = None,
    room_name: str | None = None,
    required_attendee_keys: list[str] | None = None,  # числовые id строкой, НЕ логины
    description: str | None = None,
    enable_auto_recording: bool | None = None,
    pin_code: str | None = None,          # None — валидное явное "без PIN" (JSON null)
    pin_code_explicit_none: bool = False, # различает "не решено" (MissingFieldError) и "решено: нет PIN"
    allow_anonymous: bool | None = None,
    anonymous_access_expiration: str | None = None,  # обязателен, если allow_anonymous is True
) -> dict:
    ...
```

`enableSip`-параметр удаляется из сигнатуры целиком (вызывающий код, передающий его, — ошибка
времени правки, не рантайма: параметр перестаёт существовать).

`pin_code`/`pin_code_explicit_none` — та же развилка «отличить не-решено от явного пустого», что
`--required-user-key`/`--no-required-users` уже решают в CLI (rooms-calendar-spec.md §6.5): без
обоих сигналов — `MissingFieldError("pinCode")`; `pin_code_explicit_none=True` — `pinCode: null` в
теле независимо от значения `pin_code`.

## 3. `anonymousAccessExpirationDate` — условное правило (не в общем `_REQUIRED`-цикле)

```python
if allow_anonymous is True and anonymous_access_expiration is None:
    raise MissingFieldError("anonymousAccessExpirationDate")
body["anonymousAccessExpirationDate"] = (
    anonymous_access_expiration if allow_anonymous else None
)
```

**N/A — формула дефолта не выведена.** Снимок даёт один пример (`start` 2026-08-17T15:00Z →
`anonymousAccessExpirationDate` 2026-08-18T20:59:59.999Z, разница ≈29ч45м) — недостаточно, чтобы
восстановить правило («до конца следующего дня»? «+30 часов»? другое). Anti-fabrication правило
ADR-шаблона: пустое поле лучше правдоподобного — вызывающий указывает значение явно, вычисляемого
дефолта нет.

## 4. `requiredAttendees` — построение

```python
def build_required_attendees(keys: list[str]) -> list[dict]:
    return [{"type": "user", "key": key} for key in keys]
```

`key` — строка с числовым содержимым (снимок сериализует id как `"668"`, не `668`) — не
валидируется на `.isdigit()` компоновщиком (не know'ing формат id других типов участников,
например ботов/групп — вне зафиксированного снимком случая, тип `"user"` остаётся единственным
поддерживаемым).

## 5. Резолюция логина в `key` — пробел, не решение

Проверено: `auth.py::OPERATION_PROFILES` не содержит операции вида «список пользователей домена»
или «пользователь по логину»; `enrichment.py::map_participants` берёт `key` из `userInfo` уже
состоявшейся записи (`GET /api/recordings/{id}` → `participants[].userInfo.key`) — источник
пригоден только для пользователей, уже участвовавших в записанной встрече, не общий справочник.
Календарные элементы (`organizer`, `requiredAttendees`, `optionalAttendees` в `CALENDAR_ITEM_FIELDS`,
rooms-calendar-spec.md §5.4) потенциально несут вложенный `user.login`/`key` (Ф-48 упоминает
`organizer.user.login`), но: (а) точная форма вложенного объекта не подтверждена образцом с полем
`key` внутри — Ф-48 проверял только `.login`/`.mailbox`, не `.key`; (б) `vkuznetsov` отсутствовал
в исследованной выборке 33 элементов (Ф-48) — метод непригоден именно для санкционированного
сценария. **Решение ADR-009 §3: числовой `key` — явный ввод вызывающего**, не автоматическая
резолюция. CLI/MCP параметр переименовывается: `--required-user-key` (логин) →
`--required-attendee-key` (числовой id), сохраняя тот же паттерн `--no-required-attendees` для
явного пустого списка.

**Открытый пробел для PM/BA:** если санкционированный владелец не знает численный id `vkuznetsov`
заранее, взять его неоткуда средствами проекта до появления справочниковой операции — операционный
вопрос следующей боевой попытки, не решается этой спекой.

## 6. Транспорт (`meeting_scheduling.py`) — заголовок без query на мутирующих операциях

**Пересмотрено против первой версии этой спеки и ADR-008-spec §1** (там — аддитивно query+заголовок).
Довод пересмотра — в ADR-009 «Decision» п.1: минимальное расстояние до единственной известной
рабочей конфигурации при одноразовой ставке, не абстрактная безопасность аддитивности.

```python
headers = (
    {"Authorization": f"Session {client._auth.credential}", "X-Platform": "web"}
    if profile.mutating else None
)
request = client._client.build_request(
    "POST", profile.path_template, json=body, headers=headers
)
if profile.mutating:
    # ADR-009: query убирается точечно для этого запроса, не для клиента целиком —
    # httpx.URL.copy_remove_param не трогает client._client.params (ADR-003 инвариант цел),
    # следующий GET того же клиента снова получит sessionToken в query как обычно.
    request.url = request.url.copy_remove_param("sessionToken")
response = await client._client.send(request)
```

`client._client.params` (сборка ADR-003, `__init__`) не меняется — конструктор клиента остаётся
единственной точкой сборки транспорта credential для чтения; вырезание query — операция над
конкретным `httpx.Request` после его построения, специфичная для `create_meeting`, не общий
механизм клиента. Это заменяет и код ADR-007-spec §3 (`client._client.post(...)` напрямую), и
код ADR-008-spec §1/§3 (аддитивные заголовки) — обе спеки остаются верны в остальных пунктах
(диагностика, `response_body`), меняется только строка, формирующая сетевой вызов.

## Границы

- Куки `kontur_ngtoken`/`ngtoken` не реализуются — нет источника (браузерный логин отсутствует в
  контуре проекта). Если следующий боевой POST провалится **именно** на их отсутствие, это
  отдельная находка следующей задачи, не предугадывается здесь.
- Ни один пункт не подтверждён собственным боевым POST — вся правка помечена `ГИПОТЕЗА` по
  дисциплине ADR-007 п.2 в комментариях кода, ревизуется следующей санкционированной попыткой.
- Не меняет `ConfirmationStore`/протокол TTY-барьера (ADR-005 §Решение п.2–3) — только состав
  полей тела и транспорт.
- Удаление query — только для `create_meeting` (единственный `mutating=True`-профиль сегодня);
  механизм (`copy_remove_param` над готовым `httpx.Request`) переиспользуем для будущих мутирующих
  операций без правки конструктора клиента, но каждая новая операция подключает его явно.

## NFR Mapping

- **NFR-9** (нет тихих дефолтов) → §2–3: `anonymousAccessExpirationDate` условно обязателен,
  `pinCode` различает «не решено»/«явно нет», `requiredAttendees` требует явного числового id;
  `isRecurring`/`autoRunDeepFakeDetection`/`maskingSettings` — архитектурные константы, не
  решения вызывающего, поэтому не подпадают под запрет тихих дефолтов (дефолт относится к полю,
  которое вызывающий мог бы решить, но не решил — здесь решать нечего, поле не выставлено
  проектом как настраиваемое).
- **NFR-10** (секреты не в логах) → `X-Platform`/заголовок `Authorization` не логируются нигде
  новым кодом — та же граница, что ADR-008-spec уже устанавливает.

## Контракт с QA-author

**Сценарии приёмки:** новых `#### Scenario:` в требовании нет — задача корректирует состав полей
тела и заголовки под уже принятый FR-13/NFR-9 по факту живого снимка, не добавляет AC. Полная
регрессия `build_meeting_body`, `canonical_body_hash`, `create_meeting` обязательна — состав тела
меняется структурно (переименование/удаление/добавление полей).

**Архитектурный контекст:** `meeting_body.build_meeting_body`, новый
`meeting_body.build_required_attendees`, `meeting_scheduling.create_meeting` (заголовки +
удаление query, §6), `cli_meeting.py` (переименование флага, новый `--no-pin-code`, новый флаг для
`anonymous_access_expiration`).

**Edge cases / boundary conditions:**
- `enableSip`/`requiredUserKeys` в вызывающем коде — `TypeError` на уровне сигнатуры (параметров
  больше нет), не рантайм-ошибка построения тела.
- `allow_anonymous=True`, `anonymous_access_expiration=None` → `MissingFieldError`.
- `allow_anonymous=False`, `anonymous_access_expiration` передан (не `None`) → значение
  отбрасывается или отклоняется как противоречие — конкретное поведение (тихое игнорирование vs.
  явная ошибка) выбирает Dev, тест фиксирует выбор.
- `pin_code=None`, `pin_code_explicit_none=False` → `MissingFieldError("pinCode")` (не путать с
  «явно нет PIN»).
- `pin_code_explicit_none=True`, `pin_code="1234"` (оба одновременно) → порядок разрешения
  конфликта не специфицирован этой спекой, Dev выбирает детерминированное правило и тест.
- `required_attendee_keys=["vkuznetsov"]` (логин вместо числового id) — компоновщик его не
  отвергает (не валидирует формат, §4) — тело уйдёт с некорректным `key`, отказ обнаружится только
  сетевым ответом сервера; тест, проверяющий это поведение как задокументированный предел, а не
  баг.
- Регресс `canonical_body_hash`: хеш меняется при любом изменении состава тела (новая форма
  `requiredAttendees`) — существующие тесты `ConfirmationStore`, построенные на старом теле,
  требуют обновления фикстур под новую форму.
- `create_meeting` — исходящий запрос не содержит `sessionToken` ни в query, ни в теле, при этом
  несёт оба заголовка (`Authorization`, `X-Platform`) — регресс существующего теста ADR-008
  («заголовок добавляется поверх query») меняет ожидание на «заголовок вместо query», не расширяет
  старое поведение.
- Регресс read-путей: `get_room`/`get_calendar`/`list_recordings` (не `mutating`) по-прежнему несут
  `sessionToken` в query того же `client._client` — тест на то, что `copy_remove_param` не
  затрагивает `client._client.params` и следующий GET после `create_meeting` в рамках одного
  клиента не теряет query.

**Test-pyramid рекомендация:**

| Группа | Уровень | Обоснование |
|---|---|---|
| `build_meeting_body` (новый состав, включая `_FIXED`-литералы, условный `anonymousAccessExpirationDate`) | unit | чистая функция |
| `build_required_attendees` | unit | чистая функция |
| `pinCode` None/explicit-None/строка — три исхода | unit | чистая функция, комбинаторика |
| `create_meeting` — заголовки (`X-Platform` + `Authorization`) в запросе, `sessionToken` отсутствует в query | unit со spy на транспорте | без сети |
| `client._client.params` не теряет `sessionToken` для read-путей после вызова `create_meeting` тем же клиентом | unit со spy на транспорте | регресс ADR-003 инварианта |
| Фактическое поведение тела/транспорта на боевом домене | вне пирамиды, живой прогон | требует новой санкции владельца |

## Бриф для Dev

**Архитектура:** этот файл и
[ADR-009](../00-project/adr/ADR-009-devtools-body-and-transport-correction.md).

**Реализовать:**
1. `meeting_body.py`: удалить `enable_sip`/`requiredUserKeys`, добавить `required_attendee_keys`
   → `requiredAttendees` (§2, §4), условное правило `anonymousAccessExpirationDate` (§3),
   `pin_code`/`pin_code_explicit_none` (§2), `_FIXED`-литералы (§2).
2. `meeting_scheduling.py`: заголовок `X-Platform: web` рядом с `Authorization`; `sessionToken`
   вырезается из query запроса через `request.url.copy_remove_param("sessionToken")` (§6) — не
   через правку `client._client.params`.
3. `cli_meeting.py`: переименовать `--required-user-key` → `--required-attendee-key`
   (`--no-required-attendees` вместо `--no-required-users`), добавить `--no-pin-code`, добавить
   `--anonymous-access-expiration` (условно обязателен при `--allow-anonymous true`).
4. `tools_scheduling.py`: параметры `ktalk_preview_meeting` синхронизируются с новой сигнатурой
   компоновщика.

**Порядок:** тест на новую форму `requiredAttendees`/`_FIXED`-литералы → правка `meeting_body.py`
→ тест на условный `anonymousAccessExpirationDate` → тест на `pinCode`-развилку → тест на
заголовки+отсутствие query в запросе `create_meeting` → правка `meeting_scheduling.py` (§6) → тест
на то, что read-пути того же клиента не теряют query после `create_meeting` → правка
`cli_meeting.py`/`tools_scheduling.py` → регресс `ConfirmationStore`/`canonical_body_hash` с
обновлёнными фикстурами.

**Сценарии приёмки:** нет новых `#### Scenario:` — регрессия FR-13/NFR-9 под новым составом тела и
транспортом.

**Известные значения для боевого прогона (числовые id участников).** Владелец санкции подтвердил
конкретные числовые `key` для `vkuznetsov` и второго санкционированного участника по снимку
DevTools — значения не публикуются в этой (git-трекаемой) спеке по правилу анонимизации задачи
(«числовые id реальных людей в статьи не переносить»), которое эта спека соблюдает так же, как
остальные факты снимка. Оператор передаёт значение `--required-attendee-key` при исполнении
`create-meeting-confirm` в момент боевого прогона (TTY, не автоматизация) — значение известно
владельцу из первоисточника, Dev его не хардкодит ни в код, ни в фикстуры, ни в эту спеку.

## Бриф для DevOps

**Архитектура:** этот файл.

**Подготовить:** ничего нового к runbook — следующий боевой POST (проверка гипотез транспорта и
тела) требует отдельной санкции владельца, не входит в эту задачу. При планировании такой попытки
учесть пробел §5 (числовой id участника) заранее — не откладывать до момента исполнения.

**NFR из BA:** NFR-9 (обязательность новых полей), NFR-10 (заголовки/секреты не логируются) — без
изменений по значению, состав проверяемых полей расширен (§ NFR Mapping выше).
