---
title: "ADR-008 spec: заголовок на мутациях, KTalkWriteAuthMismatchError, тело ответа в исключении"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-008 spec: заголовок на мутациях, KTalkWriteAuthMismatchError, тело ответа в исключении

Companion-спека к [ADR-008](../00-project/adr/ADR-008-write-auth-and-error-model.md). Источник
фактов — [rooms-calendar-dev-c3-notes.md](../60-implementation/rooms-calendar-dev-c3-notes.md).

## 1. `EndpointProfile.mutating` и дополнительный заголовок

`auth.py`:

```python
@dataclass(frozen=True)
class EndpointProfile:
    path_template: str
    required_scope: str | None
    mutating: bool = False  # ADR-008: session-режим шлёт доп. Authorization-заголовок
```

`OPERATION_PROFILES["create_meeting"][AuthMode.SESSION]` получает `mutating=True`; все
остальные записи не меняются (дефолт `False`, обратная совместимость по умолчанию —
`EndpointProfile(...)` без третьего позиционного аргумента продолжает работать).

Комментарий над записью дополняется, не заменяется (маркер ADR-007 п.2 сохраняется):

```python
"create_meeting": {
    # ГИПОТЕЗА (mainpart-ktalk-mcp.md:192-193, RES-003 Ф-38, не проверено живым POST):
    # путь с префиксом /api — ...(текст ADR-007 без изменений)...
    # ГИПОТЕЗА (ADR-008, DEV-005 §5, не проверено живым POST): запись в session-режиме
    # может требовать доп. заголовок Authorization: Session <token> — mutating=True
    # добавляет его поверх query, не вместо. Следующий боевой POST — единственная проверка.
    AuthMode.SESSION: EndpointProfile("/api/calendar", None, mutating=True),
    AuthMode.API_KEY: None,
},
```

Точка отправки заголовка — не в `client.py::__init__` (там собирается только базовый
транспорт, ADR-003 инвариант не трогается), а в вызывающем коде операции, у которого уже есть
`client._auth.credential` и `profile`:

```python
# meeting_scheduling.py::create_meeting, перед POST
headers = {"Authorization": f"Session {client._auth.credential}"} if profile.mutating else None
response = await client._client.post(profile.path_template, json=body, headers=headers)
```

`headers=None` в httpx не переопределяет client-level заголовков — `params={"sessionToken": ...}`
уходит как обычно вместе с новым заголовком (аддитивно, ADR-008 «Decision» п.1). Api-key-режим
не подключает `mutating` вовсе: `create_meeting[AuthMode.API_KEY]` остаётся `None` (fail-closed,
ADR-004 п.2) — условие `profile.mutating` физически недостижимо для этого режима, пока профиль
`None`.

## 2. `KTalkWriteAuthMismatchError` и правка `diagnose_undocumented_failure`

`client.py`, рядом с `KTalkScopeError`:

```python
class KTalkWriteAuthMismatchError(KTalkAuthError):
    """401/403 на операции, чей credential в ту же секунду подтверждён рабочим
    независимой проверкой (ADR-008). Обновление токена не решает проблему —
    причина в том, как эта конкретная операция принимает credential, не в его
    валидности."""
```

`contour_diagnostics.py::diagnose_undocumented_failure`:

```python
async def diagnose_undocumented_failure(
    client: KTalkClient, operation: str, error: Exception
) -> None:
    try:
        await client.list_recordings(top=1)
    except TRANSIENT_ERRORS:
        raise error from None
    if isinstance(error, KTalkAuthError) and not isinstance(error, KTalkScopeError):
        raise KTalkWriteAuthMismatchError(
            f"Операция «{operation}» вернула {_status_hint(error)}, хотя тот же credential "
            "подтверждён рабочим независимой проверкой (list_recordings) в ту же секунду. "
            "Обновлять токен/ключ не нужно — причина в том, как именно эта операция "
            "принимает credential (см. ADR-008), не в его валидности."
        ) from error
    raise ContourDriftError(operation, str(error)) from error
```

`KTalkScopeError` (403 в api-key-режиме, конкретный недостающий scope) исключается из новой
ветки — там причина уже названа точно (`SCOPE_LABELS`), контроль `list_recordings` её не
уточняет и не опровергает, `ContourDriftError`/`KTalkWriteAuthMismatchError` для этого случая
были бы информационным шагом назад. `_status_hint` — вспомогательная функция, читает код ответа
из текста существующих сообщений `KTalkAuthError` («401» либо «403»), либо (проще при
реализации) `_classify` передаёт код ответа отдельным полем при конструировании исключения —
конкретный способ извлечения кода решает Dev, снаружи виден только текст сообщения.

Обратная совместимость: `except KTalkAuthError` в существующем коде (`_auth_status_session`,
`client.py:322`) продолжает ловить `KTalkWriteAuthMismatchError` — это подкласс, не параллельная
иерархия.

## 3. Тело ответа на исключении

`meeting_scheduling.py::create_meeting`:

```python
async def create_meeting(client: KTalkClient, body: dict) -> dict:
    profile = client._profile_for("create_meeting")
    headers = (
        {"Authorization": f"Session {client._auth.credential}"} if profile.mutating else None
    )
    try:
        response = await client._client.post(profile.path_template, json=body, headers=headers)
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо

    body_text = response.text[:500] if response.status_code >= 400 else None
    if body_text:
        logger.warning("create_meeting: HTTP %s, тело: %s", response.status_code, body_text)

    try:
        client._classify(response, profile.required_scope)
    except TRANSIENT_ERRORS as exc:
        if body_text:
            exc.response_body = body_text  # атрибут читает CLI/MCP на границе вывода
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    return response.json()
```

`response_body` — обычный атрибут экземпляра исключения (Python допускает произвольные атрибуты
на исключениях без объявления в `__init__`), не новый параметр конструктора — минимизирует
изменение сигнатур существующих классов ошибок. `diagnose_undocumented_failure` перевыбрасывает
`error`/поднимает новую ошибку `from error` — атрибут `response_body`, если он был прикреплён
до вызова, не переносится автоматически на `KTalkWriteAuthMismatchError`/`ContourDriftError`;
перенос (`new_exc.response_body = getattr(error, "response_body", None)`) — часть правки
`diagnose_undocumented_failure`, чтобы тело не терялось на пути через корреляцию.

Вывод на границе CLI не меняется структурно — `cli_meeting.py::_print_error` уже вызывает
`redact_secrets(str(message))`; `message` строится вызывающей стороной
(`cmd_create_meeting_confirm`) как `f"{exc}"` сегодня. Правка — включить тело, если оно есть:

```python
def _print_error(message: str, response_body: str | None = None) -> None:
    text = message if not response_body else f"{message}\nТело ответа сервера: {response_body}"
    print(f"Ошибка: {redact_secrets(text)}", file=sys.stderr)
```

Вызов в `cmd_create_meeting_confirm` передаёт `getattr(exc, "response_body", None)`.
`redact_secrets` применяется к объединённому тексту одним проходом — новой точки маскирования не
вводится, существующий барьер расширяет область действия автоматически (см. ADR-003
«Маскирование ключа», `config.py::redact_secrets`).

## Границы

- Заголовок добавляется только для `mutating=True`-профилей session-режима; api-key-режим
  (`X-Auth-Token`) не затрагивается ни этим, ни последующими пунктами.
- `KTalkWriteAuthMismatchError` не заменяет `KTalkAuthError`/`KTalkScopeError` — это третья ветка
  в `diagnose_undocumented_failure`, не правка `client.py::_classify` (которая продолжает поднимать
  обычный `KTalkAuthError`; корреляция уточняет диагноз только там, где контрольный вызов возможен
  — сегодня только вокруг `create_meeting`).
- `response_body` — диагностический текст для человека, обрезан до 500 символов, не
  структурируется и не парсится программно; более длинное тело усекается без индикатора «обрезано»
  — граница честно называется, не решается (следующая задача при необходимости).
- Не выполняет и не санкционирует новый боевой POST — гипотеза заголовка проверяется отдельной
  задачей PM с новой санкцией владельца.

## NFR Mapping

- **NFR-9** (нет тихих дефолтов у полей тела) → не затрагивается, эта задача не меняет
  `meeting_body.py`/`build_meeting_body`.
- **NFR-10 / SEC-001** (секреты не в логах/выводе) → `response_body` проходит через
  `redact_secrets` на границе CLI тем же вызовом, что и остальной текст ошибки; `logger.warning`
  логирует тело ответа сервера на собственный запрос — секретов не несёт (ADR-007 §3,
  довод не меняется); заголовок `Authorization: Session <token>` не логируется и не появляется в
  тексте исключения ни в одной из веток — только в `httpx`-запросе.

## Бриф для Dev

**Архитектура:** этот файл и [ADR-008](../00-project/adr/ADR-008-write-auth-and-error-model.md).
**Реализовать:**
1. `EndpointProfile.mutating: bool = False` (`auth.py`), `mutating=True` на
   `create_meeting[AuthMode.SESSION]`, комментарий по маркеру `ГИПОТЕЗА` (§1).
2. `KTalkWriteAuthMismatchError(KTalkAuthError)` в `client.py`.
3. Правка `diagnose_undocumented_failure` (`contour_diagnostics.py`): ветка на
   `isinstance(error, KTalkAuthError) and not isinstance(error, KTalkScopeError)`, перенос
   `response_body` на новое исключение (§2–3).
4. `create_meeting`: заголовок при `profile.mutating`, `response.text[:500]` до `_classify`,
   прикрепление `response_body` к перехваченному исключению (§3).
5. `cli_meeting.py::_print_error` — второй параметр `response_body`, вызов из
   `cmd_create_meeting_confirm` с `getattr(exc, "response_body", None)`.

**Порядок:** тест на `mutating=True` → заголовок присутствует в запросе (spy на транспорте) →
тест `diagnose_undocumented_failure` (матрица: 401×контроль-200 → `KTalkWriteAuthMismatchError`;
403-scope×контроль-200 → по-прежнему без новой ветки, если существующий тест уже покрывает
api-key/`KTalkScopeError`; 404×контроль-200 → `ContourDriftError`, регресс ADR-007) → тест
переноса `response_body` через `diagnose_undocumented_failure` → тест `_print_error` с телом →
интеграция в `create_meeting` → регресс NFR-10 (секрет ключа/токена не появляется даже при
включённом теле ответа, параметризованный мок с телом, содержащим случайно похожую на секрет
строку).

**Сценарии приёмки:** новых `#### Scenario:` в требовании нет — задача правит модель ошибок и
транспорт под уже принятый FR-13/NFR-10, не добавляет AC. Регресс существующих тестов
`create_meeting`/`diagnose_undocumented_failure` обязателен.

## Бриф для DevOps

**Архитектура:** этот файл.
**Подготовить:** ничего нового к runbook — смоук-прогон недокументированного контура (ADR-004
companion) остаётся read-only, `create_meeting` в него не входит.
**NFR:** без изменений (NFR-10, см. выше); секрет по-прежнему не покидает `httpx`-заголовок/query
в текстовом виде.

## Контракт с QA-author

**Сценарии приёмки:** нет новых — регрессия существующих unit-тестов `create_meeting`,
`diagnose_undocumented_failure`, `_print_error` под новыми ветками.

**Архитектурный контекст:** `meeting_scheduling.create_meeting`, `auth.EndpointProfile.mutating`,
`contour_diagnostics.diagnose_undocumented_failure`, `client.KTalkWriteAuthMismatchError`,
`cli_meeting._print_error`. Транспортный и диагностический слой — `meeting_body`/`confirmation`
(ADR-005) не изменяются.

**Edge cases / boundary conditions:**
- Мок `POST /api/calendar` → 401, мок контроля `list_recordings(top=1)` → 200: ожидается
  `KTalkWriteAuthMismatchError`, текст не содержит «обновите токен»/«обновите ключ».
- Мок `POST /api/calendar` → 403 (session, нет scope-контекста), мок контроля → 200: та же ветка
  (`KTalkWriteAuthMismatchError`) — session-403 не является `KTalkScopeError` (это подкласс только
  для api-key-режима, см. `client.py::_classify`).
- Мок `POST /api/calendar` → 403 (api-key, `KTalkScopeError` с конкретным scope), мок контроля →
  200: ветка не срабатывает — `KTalkScopeError` исключён явно, `ContourDriftError` тоже не
  поднимается (существующее поведение api-key/403 вне рамок `create_meeting`, где api-key
  fail-closed — тест на уровне `diagnose_undocumented_failure` как модуля, не на живом
  `create_meeting`).
- Мок `POST /api/calendar` → 404, мок контроля → 200: по-прежнему `ContourDriftError` (регресс
  ADR-007, ветка не должна была измениться).
- Мок `POST /api/calendar` → 401, мок контроля → тоже 401/сетевая ошибка: перевыбрасывается
  исходный `KTalkAuthError`, не `KTalkWriteAuthMismatchError` — корреляция не подтвердилась.
- Тело ответа 401 с строкой, случайно похожей на переменную окружения секрета (тест с
  синтетическим значением `KTALK_SESSION_TOKEN`, подставленным в мок-тело) — `redact_secrets`
  маскирует её в итоговом выводе `_print_error`, как маскирует остальной текст.
- `EndpointProfile` без `mutating` (все существующие записи) — заголовок не отправляется,
  регресс существующих `get_room`/`get_calendar`/`list_recordings` не создаёт новых заголовков.

**Test-pyramid рекомендация:**

| Группа | Уровень | Обоснование |
|---|---|---|
| `mutating=True` → доп. заголовок в запросе | unit | spy на транспорте, без сети |
| `diagnose_undocumented_failure`: матрица (401/403-session/403-scope/404) × (контроль ок/не ок) | unit | комбинаторика на моках, как ADR-004/ADR-007 spec |
| Перенос `response_body` через корреляцию | unit | атрибут исключения, без сети |
| `_print_error` с/без `response_body`, включая маскирование | unit | `redact_secrets`, синтетический секрет |
| Фактическое поведение заголовка на боевом домене | вне пирамиды, живой прогон | требует новой санкции владельца, не автоматизируется |
