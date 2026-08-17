---
title: "DEV-009: тело и транспорт create_meeting по снимку DevTools"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# DEV-009: тело и транспорт create_meeting по снимку DevTools

Задача DEV-009 (реализация [ADR-009](../00-project/adr/ADR-009-devtools-body-and-transport-correction.md)/
[companion-спеки](../40-architecture/ADR-009-devtools-body-and-transport-correction-spec.md)).
Нет новых `#### Scenario:` — регрессия FR-13/NFR-9 под новым составом тела и
транспортом по факту живого снимка DevTools владельца.

## Транспорт (`meeting_scheduling.py`)

Было (ADR-008): `client._client.post(..., headers={"Authorization": ...})` — заголовок
поверх `?sessionToken=` из `client._client.params` (ADR-003). Стало (ADR-009 §6):
`client._client.build_request("POST", ..., headers={"Authorization": ..., "X-Platform": "web"})`,
затем `request.url = request.url.copy_remove_param("sessionToken")`, затем
`client._client.send(request)`. Конструктор клиента не тронут — `copy_remove_param`
работает над уже построенным `httpx.Request`, специфично для этого вызова.
Регрессия закрыта тестом: read-путь (`list_recordings`) того же клиента после
`create_meeting` по-прежнему несёт `sessionToken` в query
(`test_adr009_read_paths_of_same_client_keep_session_token_in_query_after_create_meeting`).

## Тело (`meeting_body.py`)

`_REQUIRED` сократился до 8 полей (было 10) — `pinCode` и
`anonymousAccessExpirationDate` вынесены в отдельные условные правила вне общего
None-цикла:

- `pinCode`: три исхода — `pin_code=None, pin_code_explicit_none=False` →
  `MissingFieldError`; `pin_code_explicit_none=True` → `null` **независимо** от
  значения `pin_code` (побеждает при конфликте — решение зафиксировано тестом
  `test_pin_code_explicit_none_wins_over_conflicting_string_value`, спекой не
  специфицировано дословно); иначе — переданное значение.
- `anonymousAccessExpirationDate`: `allow_anonymous=True` без значения →
  `MissingFieldError`; `allow_anonymous=False` — значение (если передано) молча
  отбрасывается (поле неявляется решением вызывающего, когда доступ выключен) —
  edge case, спекой оставлен на усмотрение Dev, зафиксирован тестом.

`_FIXED` (`isRecurring`, `autoRunDeepFakeDetection`, `maskingSettings`) добавляется
`body.update(_FIXED)` в конце — не проверяется на `None`, не параметр вызывающего
(структурная невозможность, тот же приём, каким ADR-005 закрыл `isRecurring`).

`_to_utc_z` — конвертация локального ISO с оффсетом в UTC с `Z` и миллисекундами
(`datetime.fromisoformat` → `.astimezone(UTC)` → форматирование вручную, т.к.
`isoformat()` даёт `+00:00`, не `Z`, и не гарантирует три цифры миллисекунд при
`microsecond=0`).

`enableSip`/`requiredUserKeys`/`required_user_keys`-параметры удалены из сигнатуры
целиком — вызывающий код, ссылавшийся на них, ловит `TypeError` при вызове, не
рантайм-ошибку построения тела (проверено тестом с явным `pytest.raises(TypeError)`).

## CLI (`cli_meeting.py`)

`--required-user-key` → `--required-attendee-key` (`--no-required-users` →
`--no-required-attendees`) — переименование, не сохранение старого имени как
алиаса-ошибки: старый флаг даёт argparse `unrecognized arguments`, что признано
достаточно понятным (Dev-брифом допускались оба варианта). Новые флаги:
`--no-pin-code` (симметричен `--no-required-attendees`), `--anonymous-access-expiration`
(условно обязателен при `--allow-anonymous true`, без валидации условия на уровне
argparse — проверка происходит в `build_meeting_body`, единой точке валидации).

## Регрессии, затронутые составом тела

`test_meeting_body.py`, `test_meeting_scheduling.py`, `test_cli_meeting.py` —
полностью переписаны под новый allow-list (переименование `FULL_KWARGS`,
`_REQUIRED_KWARG_TO_FIELD`, ожидаемых ключей тела). Дополнительно обнаружена и
исправлена stale-фикстура в `tests/test_secret_masking.py::test_nfr10_secret_not_in_create_meeting_preview_cli_output`
(`--no-required-users`/`--enable-sip` — старые флаги CLI, найдено грепом по
`required-user-key|enable-sip` перед правкой, а не после первого прогона гейта).

## Тесты, падавшие до правки (подтверждено явным прогоном)

37 тестов красные на старом коде под новыми ожиданиями (по замыслу — контракт
меняется структурно): все 17 в `test_meeting_body.py`, 3 в `test_meeting_scheduling.py`
(`test_ac_fr13_1/2`, заголовки), 17 в `test_cli_meeting.py` — полный список сохранён
в истории прогона задачи. После правки — `uv run pytest -q` → 317 passed (было 289
на конец DEV-008, включая обе новые статьи ADR-009 в content/, не влияющие на pytest).

## Не тронуто

`ConfirmationStore`/`canonical_body_hash` (механизм) — не менялись, только состав
тела, которое они хешируют/хранят. Куда `roomName` резолвится (ADR-006), путь
`/api/calendar` (ADR-007) — не затронуты. Резолюция логина в числовой `requiredAttendees[].key`
остаётся пробелом (ADR-009 §5, §3 спеки) — оператор передаёт значение явно через
`--required-attendee-key` при исполнении.

## Боевой прогон — команда для владельца

```
uv run ktalk create-meeting-confirm \
  --subject "<тема>" \
  --start "<локальное ISO с оффсетом>" \
  --end "<локальное ISO с оффсетом>" \
  --timezone "Europe/Moscow" \
  --room-name "<новое тестовое имя, не probe-fresh-*>" \
  --required-attendee-key <KEY> \
  --enable-auto-recording true \
  --no-pin-code \
  --allow-anonymous false
```

`<KEY>` — числовой id участника, известный владельцу из первоисточника (снимок
DevTools) — не хардкодится ни в код, ни в тесты, ни в статьи (см. ADR-009-spec
«Бриф для Dev»). `--allow-anonymous false` выбран для минимального тела без
дополнительного обязательного `--anonymous-access-expiration` — при `true`
требуется добавить этот флаг явным значением (нет вычисляемого дефолта, ADR-009 §3).
Один POST, санкция владельца — не автоматизация.
