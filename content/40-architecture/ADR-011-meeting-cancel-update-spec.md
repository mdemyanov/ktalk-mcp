---
title: "ADR-011 spec: модули отмены встречи, отложенная правка"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-011 spec: модули отмены встречи, отложенная правка

Companion-спека к [ADR-011](../00-project/adr/ADR-011-meeting-cancel-update.md). Источник фактов —
`ktalk-calendar-api.md` §5–§6 (Ф-50, Ф-51, Ф-56). Реализация — DEV-010, не эта задача.

## 1. `auth.py` — новый профиль

```python
OPERATION_PROFILES["cancel_meeting"] = {
    AuthMode.SESSION: EndpointProfile("/api/calendar/{id}/cancel", None, mutating=True),
    AuthMode.API_KEY: None,  # непроверено — fail-closed, тот же приём, что create_meeting
}
```

`OPERATION_LABELS["cancel_meeting"] = "отмена встречи"` — для единообразия диагностических
сообщений (`OperationNotAvailableError` уже читает эту таблицу для других операций).

`{id}` подставляется через `quote_path_param(id)` (Ф-56) — тот же вызов, что уже используется для
`recording_key`/`conference_key` (SEC-001); без него `+`/`/`/`=` меняют путь запроса.

## 2. Новый модуль `meeting_cancel.py` — компоновка данных отмены (без сети)

Параллель `meeting_body.py`: чистые функции, без `KTalkClient`, физическая невозможность сетевого
вызова из этого модуля.

```python
def build_cancel_confirmation_payload(*, id: str, reason: str = "") -> dict:
    """Не тело запроса (то — {"reason": reason}), а предмет хеширования подтверждения
    (ADR-011 п.2): id — часть пути, не тела, но обязан входить в хеш, иначе
    подтверждение для одной встречи матчится для любой другой. `operation` —
    дискриминатор против путаницы с будущим подтверждением update_meeting на том
    же id."""
    return {"operation": "cancel_meeting", "id": id, "reason": reason}


class CancelPreviewService:
    """Параллель PreviewService (meeting_scheduling.py) — тот же ConfirmationStore,
    та же canonical_body_hash (импорт из meeting_body.py, функция общая — не
    специфична для тела встречи)."""

    def __init__(self, store: ConfirmationStore) -> None:
        self._store = store

    def preview(self, *, id: str, reason: str = "") -> tuple[dict, str]:
        payload = build_cancel_confirmation_payload(id=id, reason=reason)
        payload_hash = canonical_body_hash(payload)
        confirmation_id = self._store.issue(payload_hash)
        return payload, confirmation_id
```

`id`/`reason` не проверяются на `None` общим циклом `_REQUIRED` (в отличие от `meeting_body.py`) —
`id` обязателен структурно (позиционный/keyword-only параметр без дефолта в CLI/MCP-обвязке, не в
этом компоновщике), `reason` — единственное поле операции с разрешённым тихим дефолтом (ADR-011
п.4, N/A на обязательность непустого значения).

## 3. `meeting_scheduling.py` (или соседний вызов из `meeting_cancel.py`) — сетевой шаг

```python
async def cancel_meeting(client: KTalkClient, *, id: str, reason: str = "") -> dict:
    """Ровно одна сетевая попытка POST .../cancel, без retry — тот же контракт,
    что create_meeting (ADR-005 п.2 «Идентификатор потребляется в момент
    фактической попытки независимо от исхода»). Транспорт (заголовки,
    отсутствие query) — тот же код, что create_meeting: profile.mutating общий
    признак, не специфичный для операции."""
    profile = client._profile_for("cancel_meeting")
    path = profile.path_template.format(id=quote_path_param(id))
    headers = (
        {"Authorization": f"Session {client._auth.credential}", "X-Platform": "web"}
        if profile.mutating else None
    )
    request = client._client.build_request(
        "POST", path, json={"reason": reason}, headers=headers
    )
    if profile.mutating:
        request.url = request.url.copy_remove_param("sessionToken")
    try:
        response = await client._client.send(request)
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "cancel_meeting", exc)
        raise
    body_text = response.text[:500] if response.status_code >= 400 else None
    try:
        client._classify(response, profile.required_scope)
    except TRANSIENT_ERRORS as exc:
        if body_text is not None:
            exc.response_body = body_text
        await diagnose_undocumented_failure(client, "cancel_meeting", exc)
        raise
    return response.json()
```

Размещение (`meeting_scheduling.py` vs. новая функция в `meeting_cancel.py`) — решение Dev по месту
(гейт C13, объём файлов); контракт функции (сигнатура, порядок try/except, диагностика) фиксирован
здесь и не меняется независимо от файла.

## 4. `cli_meeting.py` — новые подкоманды

`cancel-meeting-preview` / `cancel-meeting-confirm`, тот же паттерн, что
`create-meeting-preview`/`create-meeting-confirm`:

```python
def _add_cancel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", required=True, help="Base64 id встречи (Ф-56, из ответа "
        "create-meeting-confirm или чтения календаря); не хранится проектом")
    parser.add_argument("--reason", default="", help="Причина отмены (опционально, "
        "дефолт \"\" — единственный подтверждённый рабочий образец, Ф-50)")
```

`cancel-meeting-confirm`: TTY-барьер первым (`isatty()`), затем `CancelPreviewService.preview`,
печать предпросмотра, запрос слова подтверждения (тот же `_CONFIRM_WORD`), пересчёт хеша через
`build_cancel_confirmation_payload`+`canonical_body_hash`, `store.match`/`store.consume` до сетевой
попытки, один вызов `cancel_meeting`, вывод исхода. Обработка ошибок — тот же блок, что
`cmd_create_meeting_confirm` (`status_code`, `response_body`, `control_probe`), без изменений
контракта исключений.

## 5. MCP — только предпросмотр

`ktalk_preview_cancel_meeting` (новый инструмент, аналог `ktalk_preview_meeting`,
`tools_scheduling.py`): принимает `id`, `reason`, вызывает `CancelPreviewService.preview` — без
сети физически (тот же довод ADR-005 «Решение» п.3). Мутирующего MCP-инструмента для отмены нет и
не появится, тем же приёмом, что и для создания.

## 6. `formatters.py` — `format_cancel_preview`

```python
def format_cancel_preview(data: dict) -> str:
    payload = data.get("payload") or {}
    lines = [
        f"# Отмена встречи {payload.get('id')} (ещё не выполнена)",
        "",
        f"- Причина: {payload.get('reason') or '(пусто)'}",
        f"- confirmation_id (справочно, не межпроцессный): {data.get('confirmation_id')}",
    ]
    return "\n".join(lines)
```

Формат вывода `cancel_meeting` (успешный ответ) — существующий `render_tool_output`/CLI-принт
результата, без нового форматтера: тело ответа `POST .../cancel` не задокументировано (Ф-50
показывает только код 200, форму тела ответа не разбирает) — печатать сырой JSON, не строить
маппер по недоказанной форме.

## 7. Правка (`PUT /api/calendar/{id}`) — измерение, не проектирование

Известно (Ф-51): путь `/api/calendar/{id}`, метод `PUT`, код ответа 200. Неизвестно: форма тела
целиком (нет ни документарного аналога, ни разобранного живого образца).

**Как закрыть:** снимок DevTools живого редактирования встречи в UI Толка, тем же методом, что
ADR-009 закрыл тело создания (`docs/`, обезличенный владельцем, не в git; агент не читает сырой
файл). До снимка: `update_meeting` не входит в `OPERATION_PROFILES`, компоновщика тела нет, DEV-010
эту операцию не реализует. Отдельная задача SA (следующий номер после ADR-011) после появления
образца — не расширение этого ADR задним числом.

## Границы

- `reason` не валидируется на непустоту компоновщиком — N/A по данным (ADR-011 п.4), не решение
  «непустое не нужно никогда».
- `id` не резолвится по имени комнаты/дате/участнику — только явный ввод оператора (ADR-011 п.3).
- Отмена не отменяет отправленные ранее письма приглашения (та же оговорка, что ADR-005 «Context»
  уже сделал про создание) — из HAR-снимка не следует, что `cancel` рассылает письмо-отзыв; не
  проверялось.
- `update_meeting` вне периметра DEV-010 (см. §7) — попытка реализовать по аналогии с созданием
  запрещена ADR-011 «Alternatives Considered».

## NFR Mapping

- **NFR-9** (нет тихих дефолтов для решений вызывающего) → `id` обязателен структурно
  (`--id required=True` в CLI, keyword без дефолта в компоновщике); `reason` — единственное поле
  операции с разрешённым тихим дефолтом, симметрично `description` в `build_meeting_body`
  (ADR-009-spec §2) — оба являются полями, где отсутствие решения вызывающего не блокирует запрос
  по проектному решению, не по недосмотру.
- **NFR-10** (секреты не в логах) → заголовки `Authorization`/`X-Platform` не логируются новым
  кодом — переиспользуется код `create_meeting`, граница уже установлена ADR-008-spec.

## Контракт с QA-author

**Сценарии приёмки:** новых `#### Scenario:` в требовании нет — FR-13/NFR-9 расширяются на вторую
мутирующую операцию тем же протоколом (ADR-005), без изменения текста AC. Регрессия существующего
протокола подтверждения (`ConfirmationStore`, TTY-барьер, отсутствие MCP-мутатора) обязательна на
новом предмете хеширования.

**Архитектурный контекст:** новый модуль `meeting_cancel.py`
(`build_cancel_confirmation_payload`, `CancelPreviewService`), функция `cancel_meeting` (место —
решение Dev, §3), новый профиль `auth.py::OPERATION_PROFILES["cancel_meeting"]`, новые подкоманды
CLI (`cancel-meeting-preview`/`cancel-meeting-confirm`), новый MCP-инструмент
`ktalk_preview_cancel_meeting`, новый форматтер `format_cancel_preview`.

**Edge cases / boundary conditions:**
- Подтверждение, выданное для `id=A`, `reason="x"`, предъявленное с `id=B`, тем же `reason` —
  `store.match` обязан вернуть `False` (хеш включает `id`, п.2) — регрессионный тест именно на
  этот сценарий (голый хеш тела без `id` его бы пропустил).
- `id` с символами `+`/`/`/`=` — путь запроса содержит `%2B`/`%2F`/`%3D`, не сырые символы (тест на
  `quote_path_param`, тот же паттерн, что уже есть для `recording_key`).
- `reason=""` (дефолт) — единственная подтверждённая живым запросом конфигурация (Ф-50); тест на
  успешный путь с этим значением обязателен как регресс известного факта, не как произвольный
  выбор фикстуры.
- `reason` с непустым значением — путь не проверен живым POST; тест на построение payload/тела
  корректен, тест на реальный ответ сервера — вне периметра (нет санкции на запрос).
- `cancel_meeting` на `id` несуществующей/уже отменённой встречи — код ответа сервера не известен
  (не наблюдался), тест не должен утверждать конкретный код без факта; фиксировать как открытое
  поведение (аналог `get_room` на несуществующее имя, Ф-45, — не предполагать 404 без проверки).
- Повтор `cancel-meeting-confirm` после сетевого сбоя — тот же протокол «нет авто-retry», что
  ADR-005 п.2: `store.consume` до сетевой попытки, повтор требует нового preview/confirm.
- `update_meeting` — тест на то, что вызов операции без профиля в `OPERATION_PROFILES` даёт
  управляемый `OperationNotAvailableError`, не `KeyError`/сырое исключение (симметрично уже
  существующему поведению для отсутствующих профилей других операций).

**Test-pyramid рекомендация:**

| Группа | Уровень | Обоснование |
|---|---|---|
| `build_cancel_confirmation_payload`, `CancelPreviewService.preview` | unit | чистые функции, без сети |
| Привязка хеша к `id` (кросс-`id` подмена confirmation_id) | unit | ключевая гарантия ADR-011 п.2, чистая логика `ConfirmationStore.match` |
| `quote_path_param` на `id` с `+`/`/`/`=` | unit | регресс SEC-001 на новом типе идентификатора |
| `cancel_meeting` — заголовки/отсутствие query в исходящем запросе | unit со spy на транспорте | без сети, тот же приём, что тест `create_meeting` (ADR-009-spec) |
| CLI TTY-барьер `cancel-meeting-confirm` | unit/integration (без реального TTY, эмуляция) | тот же паттерн, что `create-meeting-confirm` |
| `OperationNotAvailableError` при отсутствии профиля (`update_meeting`) | unit | защита от случайного вызова непроектированной операции |
| Фактическое поведение сервера на боевом домене (существующий/несуществующий `id`, непустой `reason`) | вне пирамиды, живой прогон | требует новой санкции владельца |

## Бриф для Dev

**Архитектура:** этот файл и [ADR-011](../00-project/adr/ADR-011-meeting-cancel-update.md).

**Реализовать:**
1. `auth.py`: профиль `cancel_meeting` (§1), метка `OPERATION_LABELS`.
2. `meeting_cancel.py` (новый модуль): `build_cancel_confirmation_payload`,
   `CancelPreviewService` (§2).
3. Сетевой шаг `cancel_meeting` (§3) — файл на усмотрение Dev с учётом гейта C13.
4. `cli_meeting.py`: `cancel-meeting-preview`/`cancel-meeting-confirm` (§4), переиспользуют
   `_CONFIRM_WORD`, `_print_error`, обработку `status_code`/`response_body`/`control_probe`.
5. `tools_scheduling.py` (или новый `tools_meeting_cancel.py`): `ktalk_preview_cancel_meeting`
   (§5) — предпросмотр only, без мутирующего MCP-инструмента.
6. `formatters.py`: `format_cancel_preview` (§6).

**Порядок:** тест на `build_cancel_confirmation_payload`/хеш с `id` → тест на кросс-`id`
неподтверждение → правка `meeting_cancel.py` → тест на `quote_path_param` в пути отмены → тест на
заголовки/отсутствие query в `cancel_meeting` → правка сетевого шага → тест TTY-барьера CLI →
правка `cli_meeting.py` → правка `tools_scheduling.py`/`formatters.py`.

**Явно вне объёма:** `update_meeting` — не реализовывать, не добавлять профиль
(ADR-011 п.5, §7 этой спеки). Если в ходе реализации появится соблазн «заодно» спроектировать тело
`PUT` по аналогии с созданием — это прямо запрещённая альтернатива ADR-011.

**Сценарии приёмки:** нет новых `#### Scenario:` — расширение FR-13/NFR-9 на вторую мутирующую
операцию.

**Известные значения для боевого прогона.** `id`, использованный для санкционированной проверки
отмены, оператор получает из вывода `create-meeting-confirm` предыдущей боевой попытки или из
`ktalk_list_calendar` — значение не публикуется в этой (git-трекаемой) спеке (принадлежность
календаря владельца, то же правило анонимизации, что ADR-009-spec).

## Бриф для DevOps

**Архитектура:** этот файл.

**Подготовить:** ничего к runbook сверх уже существующего для `create_meeting` — отмена использует
тот же подтверждённый транспорт (ADR-009), новой инфраструктуры не требует. Следующая боевая
попытка (проверка `cancel_meeting` живым POST) требует отдельной санкции владельца, вне объёма
DEV-010. При планировании DevTools-снимка для `update_meeting` (§7) — тот же процесс, что уже
использовался для снимка создания: обезличивание владельцем до передачи агенту.

**NFR из BA:** NFR-9 (обязательность `id`, явный дефолт `reason`), NFR-10 (заголовки/секреты не
логируются) — расширение существующих требований на вторую операцию, значения не меняются.
