---
title: "ADR-007 spec: путь create_meeting, маркеры ФАКТ/ГИПОТЕЗА, диагностика 404"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-007 spec: путь create_meeting, маркеры ФАКТ/ГИПОТЕЗА, диагностика 404

Companion-спека к [ADR-007](../00-project/adr/ADR-007-create-meeting-path-correction.md). Источник
фактов — [rooms-calendar-dev-c2-notes.md](../60-implementation/rooms-calendar-dev-c2-notes.md).

## 1. Правка `OPERATION_PROFILES["create_meeting"]`

`auth.py`, запись `SESSION`: `EndpointProfile("/calendar", None)` → `EndpointProfile("/api/calendar", None)`.
`API_KEY` строка не меняется (`None`, fail-closed).

Комментарий над записью переписывается по маркерам (см. §2), не удаляется — история решения (путь
скопирован без поправки на базовый URL источника) остаётся частью кода, но с честным статусом
проверки:

```python
"create_meeting": {
    # ГИПОТЕЗА (mainpart-ktalk-mcp.md:192-193, RES-003 Ф-38, не проверено живым POST):
    # путь с префиксом /api — mainpart документирует base_url = f"{space_url}/api" и
    # использует /calendar относительно него; предыдущая запись без /api была ошибкой
    # прочтения этого источника (ADR-007), не проверенным решением. Следующий боевой
    # POST под новой санкцией владельца — единственная проверка.
    AuthMode.SESSION: EndpointProfile("/api/calendar", None),
    # ФАКТ (ADR-004 п.2): api-key не проверен вовсе -> fail-closed.
    AuthMode.API_KEY: None,
},
```

## 2. Маркеры `ФАКТ`/`ГИПОТЕЗА` — область действия и формат

Обязательны в комментариях, объясняющих **происхождение** пути/scope/параметра операции
недокументированного контура (`get_room`, `get_calendar`, `create_meeting` в `auth.py`; корреляция
и мапперы в `contour_diagnostics.py`/`calendar_reader.py`/`rooms.py`). Не требуются для
комментариев о механике кода (структура, гейты, ссылки на ADR по архитектуре в целом) — маркер
привязан к утверждениям о внешнем контуре, не к любому комментарию в проекте.

Формат:

```python
# ФАКТ (Ф-NN, живой GET/POST <дата или волна>): <утверждение о контуре>
# ГИПОТЕЗА (источник, не проверено живым запросом): <утверждение о контуре>
```

Ревью-чек-лист Dev (не автоматическая проверка — `ruff`/гейты её не ловят): комментарий рядом с
записью `OPERATION_PROFILES` недокументированной операции без одного из двух маркеров — находка,
возвращается на правку. Существующие комментарии `get_room`/`get_calendar` уже фактически несут
эту информацию (ссылки на FR-17/FR-18, RES-003, ADR-004) — переразметка их маркерами делается
попутно при следующей правке этих строк, не отдельной задачей ретроактивно по всему файлу.

## 3. Диагностика: `create_meeting` → `diagnose_undocumented_failure`

`meeting_scheduling.py::create_meeting` оборачивается тем же приёмом, что
`calendar_reader._fetch_segment` (сравнить построчно при реализации):

```python
async def create_meeting(client: KTalkClient, body: dict) -> dict:
    profile = client._profile_for("create_meeting")
    try:
        response = await client._client.post(profile.path_template, json=body)
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    if response.status_code >= 400:
        logger.warning(
            "create_meeting: HTTP %s, тело: %s", response.status_code, response.text
        )
    try:
        client._classify(response, profile.required_scope)
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    return response.json()
```

Точки, важные для реализации:
- `logger.warning` — не вывод CLI/MCP-инструмента, только диагностический лог; NFR-10 не
  нарушается (тело ответа сервера на собственный запрос секретов не несёт, в отличие от
  заголовков/URL с токеном — их логировать по-прежнему нельзя, см. ADR-003 `SecretRedactor`).
- Порядок: тело логируется **до** `_classify`, потому что `_classify` может поднять исключение
  раньше, чем код успеет прочитать `response.text` — `httpx.Response.text` безопасно читать
  многократно (буферизуется), порядок не влияет на корректность, но лог до классификации
  гарантирует, что текст не потеряется на пути исключения.
- `diagnose_undocumented_failure` при успешном контрольном вызове (`list_recordings(top=1)` в
  порядке) поднимает `ContourDriftError` — этот вердикт значим только вместе с логом тела ответа:
  «путь не существует» и «объект не найден» дают разные тексты в теле 404 при живой проверке,
  вердикт корреляции сам по себе эту пару не различает (корреляция отвечает на вопрос «сеть/права
  в порядке или нет», не «путь или объект»).

## 4. Ретроактивная поправка ADR-004 spec

[ADR-004-undocumented-contour-spec.md](ADR-004-undocumented-contour-spec.md) в разделах «Механизм
детекции» и «Границы» описывал `create_meeting` как принципиально не покрытый корреляцией —
это описание больше не действует и синхронизируется этой задачей (правки в том же файле, не
дублируются здесь): строка про «POST /calendar не имеет контрольного вызова» и bullet в контракте
QA-author про «POST не покрыт корреляционной диагностикой этого документа принципиально» приводятся
в соответствие с §3 выше.

## Границы

- Не выполняет и не санкционирует новый боевой POST — проверка пути `/api/calendar` требует
  отдельной санкции владельца (задача PM), эта спека её не заменяет и не предполагает.
- Не меняет `client.py::_classify` глобально — логирование тела ограничено вызовом
  `create_meeting`, остальные операции не затронуты (см. ADR-007 «Alternatives Considered»).
- Не вводит линт-правило для маркеров `ФАКТ`/`ГИПОТЕЗА` — дисциплина ревью, не автоматика; граница
  честно зафиксирована, не выдаётся за инструментальный контроль.

## NFR Mapping

- **NFR-7** (операции живут в `OPERATION_PROFILES`, отказ до сети без записи) → не меняется,
  правка — значение существующей записи, не механизм.
- **NFR-9** (явные значения полей тела, без тихих дефолтов) → не затрагивается, тело
  `create_meeting` собирает `meeting_body.py` (ADR-005), эта задача меняет только транспортный путь.
- **NFR-10** (секреты не в логах) → §3 явно ограничивает логирование телом ответа сервера,
  исключает заголовки/URL с токеном.

## Бриф для Dev

**Архитектура:** этот файл и [ADR-007](../00-project/adr/ADR-007-create-meeting-path-correction.md).
**Реализовать:** правку `auth.py` (§1, включая маркированный комментарий), обёртку
`create_meeting` в `meeting_scheduling.py` (§3), синхронизацию `ADR-004-undocumented-contour-spec.md`
(§4).
**Порядок:** тест на новый путь в моках (`https://.../api/calendar`, не `/calendar`) → правка
`auth.py` → тест на корреляцию/лог для `create_meeting` (мок 404 + мок контроля 200 →
`ContourDriftError`; мок 404 + мок контроля 401 → исходная `KTalkNotFoundError`) → обёртка в
`meeting_scheduling.py` → синхронизация ADR-004 spec.
**Сценарии приёмки:** нет новых `#### Scenario:` в требовании — эта задача правит реализацию под
уже принятый FR-13/ADR-004, не добавляет AC. Регресс существующих тестов `create_meeting`
обязателен (моки должны бить в новый путь).

## Бриф для DevOps

**Архитектура:** этот файл.
**Подготовить:** ничего нового к runbook'у ADR-004-spec не добавляется — смоук-прогон
недокументированного контура (companion-спека ADR-004) остаётся read-only, `create_meeting` в него
не входит (создание — не неразрушающая операция).
**NFR:** без изменений (NFR-10, см. выше).

## Контракт с QA-author

**Сценарии приёмки:** нет новых — регрессия существующих unit-тестов `create_meeting` под новым
путём и новой обёрткой диагностики.

**Архитектурный контекст:** `meeting_scheduling.create_meeting`, `auth.OPERATION_PROFILES`,
`contour_diagnostics.diagnose_undocumented_failure`, `client._classify`. Только транспортный слой —
`meeting_body`/`confirmation` (ADR-005) не изменяются.

**Edge cases / boundary conditions:**
- Мок `POST /api/calendar` → 404, мок контроля `list_recordings(top=1)` → 200: ожидается
  `ContourDriftError`, не `KTalkNotFoundError`.
- Мок `POST /api/calendar` → сетевая ошибка, мок контроля → тоже ошибка: ожидается исходная
  сетевая ошибка, не `ContourDriftError` (тот же класс сбоя, не локализован в контуре).
- Мок `POST /api/calendar` → 404 с нестандартным телом: тело попадает в лог (`caplog`), не в
  исключение, пользовательское сообщение об ошибке не меняется (`KTalkNotFoundError`/
  `ContourDriftError` текст остаётся прежним — лог дополняет, не заменяет).
- Существующие фикстуры с путём `/calendar` (без `/api`) требуют обновления — иначе тест
  проверяет уже неверный путь.

**Test-pyramid рекомендация:**

| Группа | Уровень | Обоснование |
|---|---|---|
| Путь `create_meeting` == `/api/calendar` под session | unit | spy на транспорте, без сети |
| Корреляция 404×200 → `ContourDriftError`, 404×401 → исходная ошибка | unit | оба ответа мокируются, комбинаторная матрица как в ADR-004 spec |
| Лог тела ответа при 4xx | unit | `caplog`, без реального сервера |
| Фактическое поведение `/api/calendar` на боевом домене | вне пирамиды, живой прогон | требует новой санкции владельца, не автоматизируется |
