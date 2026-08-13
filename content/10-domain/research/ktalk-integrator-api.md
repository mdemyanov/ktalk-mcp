---
title: Контракты интеграторского API Контур.Толк
properties:
  - name: Тип контента
    value: [Исследование]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

**Дата:** 2026-08-13
**Исследователь:** researcher-agent
**Запрос PM/BA:** извлечь полные контракты 14 эндпоинтов интеграторского API Контур.Толк из
OpenAPI-спеки — параметры (включая границы), схемы ответов, коды ошибок, enum'ы, security-схемы,
описание разрешений — как справочник для перехода с внутреннего session-API (`?sessionToken=`)
на официальный API с `X-Auth-Token`.
**Глубина:** standard (разбор спеки скриптом, без похода в интернет)

## TL;DR

Источник — `talk.public.api-api-2.json`, OpenAPI 3.0.4, 87 путей, из них разобраны 14 целевых.
Ни один из 14 эндпоинтов не переопределяет `security` на уровне операции — все наследуют
глобальный список из 4 схем (`apiKey`, `xAuthToken`, `userSession`, `oauth2`). Подтверждено
расхождение форм списка: `/recordings` отдаёт `{ recordings: [] }` без пагинации и помечен
`deprecated: true`, `/recordings/v2` — `{ entities: [], nextPageToken, prevPageToken }`. Подтверждена
аномалия спеки: `qualityName` в пути `/api/Recordings/{recordingKey}/file/{qualityName}` объявлен
как `in: query`. Найден кандидат на диагностику ключа для FR-11 —
`GET /api/domain/applications/access-info`, отдающий `scopes[]` (`type` + `restrictionType`) без
параметров; значения `scopes[].type` (`recording`, `reporting`, …) соответствуют строкам
`Разрешения: application.<scope>.read` в `description` каждой операции. 401 и 429 нигде не
объявлены в `responses` ни одной операции — они описаны только текстом в общем разделе
`info.description` («Коды ошибок и их значения»), как общеплатформенные, не операционные.

## Ключевые находки

1. Все 14 операций наследуют глобальный `security` (4 схемы); ни одна не задаёт override на
   уровне операции — [primary] спека, раздел `paths.*.get.security` отсутствует. [established]
2. `/api/Domain/recordings` (без `v2`) помечен `"deprecated": true`; так же деприкейтед
   `/api/recordings/{recordingKey}/summary` (без типа/таймкодов, только `TalkSummaryResult`).
   [primary] [established]
3. Форма ответа списка различается принципиально: v1 — `{ recordings: TalkDomainConferenceRecording[] }`,
   без пагинации; v2 — `{ entities: [...], nextPageToken, prevPageToken }`, с курсорной
   пагинацией через `pageTokenString`. Текущий код читает `recordings[]` + `nextPageToken` —
   это комбинация полей из **разных** версий эндпоинта. [primary] [established]
4. `qualityName` в `/api/Recordings/{recordingKey}/file/{qualityName}` объявлен `in: query`,
   хотя используется как сегмент пути — вероятный дефект генератора спеки. [primary] [established]
5. `maxParticipantCount` ограничен `[0, 10]`, default `6`, в обоих списковых эндпоинтах записей;
   в одиночном `GET /recordings/{recordingKey}` тот же параметр без `minimum`/`maximum` в схеме
   (только `default: 6`). [primary] [established]
6. `TalkUser` (поле `createdBy`) и `TalkUserBaseInfo` (поле `participants[].userInfo`) — разные
   схемы: `TalkUserBaseInfo` — подмножество `TalkUser` без `email`, `mobilePhone`, `innerPhone`,
   `features`. То есть у участников записи через `participants[]` e-mail недоступен, доступен
   только у создателя записи (`createdBy`). [primary] [established]
7. Явных 401/403 в `responses` операций почти нет (403 объявлен только у двух отчётных
   эндпоинтов `ConferenceReports/*`); при этом в `info.description` есть общая таблица
   «Коды ошибок и их значения» с 401/403/404/408/409/429, которая относится ко всему API, а не
   к конкретным операциям — коды 401 и 429 не объявлены в схеме `responses` НИ ОДНОЙ операции.
   [primary] [established]
8. Найден вероятный кандидат для «whoami»: `GET /api/domain/applications/access-info` — без
   параметров, возвращает `expiredAt` + `scopes[]` (`type`: 19 возможных `TalkScopeType`,
   `restrictionType`: `read`/`readWrite`) для ключа, которым выполнен запрос. У этой операции,
   в отличие от остальных 13 в задаче, в `description` НЕТ строки `Разрешения:` — предположительно
   доступна с любым валидным ключом независимо от выданных scope. [primary] [emerging — нужна
   проверка живым запросом, спека это не декларирует явно]
9. `TalkScopeType` (19 значений) — это те же имена, что в строке `Разрешения: application.<scope>.read`
   у каждой операции (`recording`, `reporting`, `applications`, …), с человекочитаемыми описаниями
   в `x-...`-подобном HTML-списке внутри `description` схемы. Это даёт программируемое сопоставление
   «какой scope нужен операции» ↔ «какие scope есть у ключа» через `access-info`. [primary]
   [established]
10. `GET /api/domain/applications` (список самих API-ключей пространства, НЕ то же самое, что
    `access-info`) требует явного `application.applications.read` и отдельного разрешения
    «Информация по API-ключам», включаемого для приложения в разделе «Управление». Путать с
    `access-info` не стоит — разный объём данных и разные требования к правам. [primary]
    [established]

## Security: схемы, глобальный security, наследование операциями

### securitySchemes (`components.securitySchemes`)

| Схема | type | Заголовок/механизм | Описание из спеки |
|---|---|---|---|
| `apiKey` | apiKey, `in: header`, `name: X-API-Key` | `X-API-Key` | «Ключ, используемый внутренними приложениями» |
| `xAuthToken` | apiKey, `in: header`, `name: X-Auth-Token` | `X-Auth-Token` | «Авторизация с помощью апи-ключа, выданного администратором домена» |
| `userSession` | apiKey, `in: header`, `name: Authorization` | `Authorization: Session {key}` | «Авторизация с помощью сессии пользователя. Вводить в формате "Session {key}" без кавычек» |
| `oauth2` | oauth2, flow `implicit` | `authorizationUrl: https://passport.skbkontur.ru/connect/authorize`, scope `profiles` = «Staff Profiles» | (без текстового описания) |

### Глобальный `security` (корень спеки)

```json
[
  { "apiKey": [] },
  { "xAuthToken": [] },
  { "userSession": [] },
  { "oauth2": ["profiles"] }
]
```

Это список из 4 альтернативных схем (OR, а не AND — OpenAPI трактует элементы массива `security`
как альтернативы). `X-Auth-Token` — целевая схема миграции по контексту задачи.

### Наследование на уровне операций

Проверено программно по всем 14 путям: ни у одной операции (`paths.<path>.get`) нет собственного
ключа `security` — то есть ни одна не переопределяет и не сужает глобальный список. Все 14 работают
с любой из 4 схем, в том числе с `X-Auth-Token`.

### Раздел `info.description` про API-ключ (текстовый, не в схеме)

- Заголовок передачи ключа: `X-Auth-Token` (буквально: «Чтобы выполнить запрос от имени
  приложения, передайте API-ключ в HTTP-заголовке `X-Auth-Token`»).
- Ключ показывается в интерфейсе один раз, в течение часа после создания; по истечении часа
  значение недоступно для повторного просмотра, только для изменения настроек/прав.
- Область действия (`scope`) API-ключа настраивается по 11 категориям (см. таблицу в разделе
  «Области действия и разрешения» спеки: Профили, Роли, Комнаты, Отчётность, Встречи, Создание
  встреч, Управление календарями, Записи, Статистика, Киоски, Маршрутизация), на каждую — уровень
  «только чтение» либо «чтение и изменение».

## Расхождение форм списка записей: `/recordings` vs `/recordings/v2`

| | `GET /api/Domain/recordings` (deprecated) | `GET /api/Domain/recordings/v2` |
|---|---|---|
| Схема ответа | `TalkDomainRecordingsList` | `TalkPage<TalkDomainConferenceRecording>` |
| Поле с элементами | `recordings: TalkDomainConferenceRecording[]` | `entities: TalkDomainConferenceRecording[]` |
| Пагинация | нет полей пагинации в схеме, только `skip`/`top` в запросе (offset-based, `skip` до 10000) | `nextPageToken: string`/`prevPageToken: string` (курсорная), плюс `pageTokenString` в запросе |
| Параметр курсора запроса | отсутствует | `pageTokenString` (query, string) |
| `deprecated` | `true` | не указан (актуальный) |

**Важно для миграции:** текущий код проекта (по CLAUDE.md) читает `recordings[]` +
`nextPageToken` — это смешение поля `recordings` из v1-формы с полем `nextPageToken`, которое
существует только в v2-форме (там элементы называются `entities`, не `recordings`). Ни один из
двух реальных эндпоинтов не отдаёт одновременно оба этих имени полей в одном ответе.

Элемент списка (`TalkDomainConferenceRecording`) идентичен в обеих версиях (см. раздел «Схемы
ответов» ниже).

## Аномалия: `qualityName` в query, хотя стоит в шаблоне пути

Путь: `/api/Recordings/{recordingKey}/file/{qualityName}`.

Параметры операции (как объявлено в спеке, дословно):

```json
{
  "name": "recordingKey",
  "in": "path",
  "required": true,
  "schema": { "type": "string" }
},
{
  "name": "qualityName",
  "in": "query",
  "schema": { "type": "string" },
  "description": "Качество видео. Рекомендуемое значение: `900 p`"
}
```

`qualityName` присутствует как сегмент шаблона URL (`{qualityName}`), но объявлен с `in: query`
(а не `in: path`) и без `required: true`. Подтверждено чтением JSON напрямую — это не артефакт
разворачивания `$ref`, а буквальное содержимое спеки. Зафиксировано как аномалию описания; как
физически формировать запрос (query-параметр или сегмент пути) — вопрос для SA/эксперимента с
реальным API, вне компетенции этого исследования.

## Карта разрешений (`description`) по всем 14 операциям

| # | Метод и путь | `operationId` | `deprecated` | Разрешения (из `description`) |
|---|---|---|---|---|
| 1 | `GET /api/Domain/recordings` | `DomainRecordings_Get` | true | `application.recording.read` |
| 2 | `GET /api/Domain/recordings/v2` | `DomainRecordings_GetV2` | false | `application.recording.read` |
| 3 | `GET /api/Domain/recordings/{recordingKey}` | `DomainRecordings_GetByKey` | false | `application.recording.read` |
| 4 | `GET /api/Domain/recordings/{recordingKey}/participants` | `DomainRecordings_FindParticipants` | false | `application.recording.read` |
| 5 | `GET /api/Recordings/{recordingKey}/file/{qualityName}` | `Recordings_DownloadFile` | false | `application.recording.read` |
| 6 | `GET /api/recordings/{recordingKey}/transcript` | `RecordingsTranscription_GetRecordingTranscript` | false | `application.recording.read` |
| 7 | `GET /api/recordings/v2/{recordingKey}/summary` | `RecordingsTranscription_GetRecordingTranscriptArtifacts` | false | `application.recording.read` |
| 8 | `GET /api/recordings/{recordingKey}/summary/{summarizationType}` | `RecordingsTranscription_GetRecordingTranscriptSummaryByType` | false | `application.recording.read` |
| 9 | `GET /api/recordings/{recordingKey}/summary` | `RecordingsTranscription_GetRecordingTranscriptSummary` | true | `application.recording.read` |
| 10 | `GET /api/domain/conferencesHistory` | `DomainConferencesHistory_GetDomainConferences` | false | `application.reporting.read` |
| 11 | `GET /api/ConferencesHistory/{conferenceKey}` | `ConferencesHistory_GetConferenceHistory` | false | `application.reporting.read` |
| 12 | `GET /api/ConferencesHistory/v2/{conferenceKey}` | `ConferencesHistory_GetEnrichedConferenceHistory` | false | `application.reporting.read` |
| 13 | `GET /api/ConferenceReports/{conferenceKey}/messages` | `ConferenceReports_GetConferenceChatReport` | false | `application.reporting.read` |
| 14 | `GET /api/ConferenceReports/{conferenceKey}/participants` | `ConferenceReports_GetConferenceParticipantsReport` | false | `application.reporting.read` |

Итог: весь набор из 14 эндпоинтов закрывается двумя scope — `recording` (записи, встречи 1-9) и
`reporting` (отчётность/архив встреч, 10-14), оба на уровне «только чтение». Ключу для полной
работы клиента ktalk-mcp достаточно выдать `Записи: только чтение` + `Отчётность: только чтение`
(в терминах панели администрирования — см. таблицу «Область действия» выше).

## Эндпоинты: параметры, ответы, коды

Для каждого эндпоинта: таблица параметров (только реально объявленные атрибуты — где `minimum`/
`maximum`/`default` не объявлены в спеке, ячейка пуста), плоский список полей ответа 200 (глубина
2-3 уровня, дальше — «не разворачиваем»), и коды ответов, объявленные сверх 200.

### 1. `GET /api/Domain/recordings` (deprecated)

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `startFrom` | query | string | date-time | | | | | «Дата, до которой были созданы записи» *(см. примечание ниже)* |
| `startTo` | query | string | date-time | | | | | «Дата, начиная с которой были созданы записи» *(см. примечание ниже)* |
| `skip` | query | integer | int32 | | 0 | 0 | 10000 | Пропускает заданное число элементов |
| `query` | query | string | | | | | | Фильтр по title / roomName / пользователю-создателю |
| `title` | query | string | | | | | | Название записи |
| `maxParticipantCount` | query | integer | int32 | | 6 | 0 | 10 | «Максимальное значение 10, по умолчанию 6» |
| `top` | query | integer | int32 | | 30 | 1 | 1000 | Количество элементов в выдаче |
| `orderMode` | query | enum `RecordingsOrderMode` | | | | | | Тип сортировки записей |

**Примечание про `startFrom`/`startTo`:** в v1 текст описания у `startFrom` — «до которой», у
`startTo` — «начиная с которой»; в v2 (см. ниже) те же имена параметров описаны ровно наоборот —
«начиная с которой» / «до которой». Смысл имён (`from`=начало, `to`=конец) логичнее соответствует
описанию v2. Зафиксировано дословно как есть в спеке — возможна опечатка в v1, а не смена
семантики; SA стоит перепроверить эмпирически перед тем, как полагаться на любую версию текста.

Схема ответа `TalkDomainRecordingsList`:
- `recordings`: array of `TalkDomainConferenceRecording` (поля элемента — см. раздел
  «TalkDomainConferenceRecording» ниже, общий для v1/v2/one-by-key)

Коды сверх 200: не объявлены.

### 2. `GET /api/Domain/recordings/v2`

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `startFrom` | query | string | date-time | | | | | «Дата, начиная с которой были созданы записи» |
| `startTo` | query | string | date-time | | | | | «Дата, до которой были созданы записи» |
| `pageTokenString` | query | string | | | | | | Токен пагинации |
| `query` | query | string | | | | | | Фильтр по title / roomName / пользователю-создателю |
| `title` | query | string | | | | | | Название записи |
| `maxParticipantCount` | query | integer | int32 | | 6 | 0 | 10 | «Максимальное значение 10, по умолчанию 6» |
| `top` | query | integer | int32 | | 30 | 1 | 1000 | Количество элементов в выдаче |
| `orderMode` | query | enum `RecordingsOrderMode` | | | | | | Тип сортировки записей |

Схема ответа `TalkPage<TalkDomainConferenceRecording>`:
- `entities`: array of `TalkDomainConferenceRecording`
- `nextPageToken`: string, nullable
- `prevPageToken`: string, nullable

Коды сверх 200: не объявлены.

### 3. `GET /api/Domain/recordings/{recordingKey}`

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `recordingKey` | path | string | | true | | | | Ключ записи |
| `maxParticipantCount` | query | integer | int32 | | 6 | *(не объявлены)* | *(не объявлены)* | «Максимальное число участников» |

Обратите внимание: в отличие от списковых эндпоинтов, у одиночного `GET` границы
`minimum`/`maximum` для `maxParticipantCount` в схеме не объявлены — только `default: 6`, хотя
текстовое описание короче и не упоминает границы вовсе.

Схема ответа: `TalkDomainConferenceRecording` (не список — единичный объект). Поля — см. раздел
«TalkDomainConferenceRecording» ниже.

Коды сверх 200: не объявлены.

### 4. `GET /api/Domain/recordings/{recordingKey}/participants`

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `recordingKey` | path | string | | true | | | | Ключ записи |
| `skip` | query | integer | int32 | | 0 | *(нет)* | *(нет)* | Пропускает заданное число элементов |
| `top` | query | integer | int32 | | 30 | *(нет)* | *(нет)* | «Количество элементов в выдаче запроса. Максимальное значение 100» |

`top` — текстовое описание заявляет предел 100, но в схеме `maximum` не объявлен (в отличие от
списка записей, где `top` формально ограничен `maximum: 1000` в схеме). Несовпадение текста и
формальной схемы: полагаться стоит на текст, схема границу не проверяет.

Схема ответа: массив `TalkUserBaseInfoRef[]`. Поля элемента:
- `anonymousName`: string, nullable
- `anonymousId`: string, nullable
- `userInfo`: объект `TalkUserBaseInfo` (см. общий блок ниже — усечённая версия `TalkUser`,
  без `email`/`mobilePhone`/`innerPhone`/`features`)
- `isAnonymous`: boolean

Коды сверх 200: не объявлены.

### 5. `GET /api/Recordings/{recordingKey}/file/{qualityName}`

| Параметр | in (как в спеке) | Тип | Required | Описание |
|---|---|---|---|---|
| `recordingKey` | path | string | true | Ключ записи |
| `qualityName` | **query** *(аномалия, см. раздел выше)* | string | не указан | «Качество видео. Рекомендуемое значение: `900 p`» |

Схема ответа: `200 OK` без `content`/`schema` в спеке — ответ не описан как JSON (вероятно,
бинарный поток файла записи; тип содержимого спекой не документирован).

Коды сверх 200: не объявлены.

### 6. `GET /api/recordings/{recordingKey}/transcript`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `recordingKey` | path | string | true | Ключ записи |

Схема ответа `TalkTranscript`:
- `status`: enum `TalkTranscriptionStatus` = `inProgress`, `error`, `complete`
- `statusMessage`: string, nullable
- `tracks`: array of `TalkTranscriptTrack`:
  - `trackId`: string, nullable
  - `speaker`: объект `TalkUserRef` (не разворачиваем — предел глубины; форма как у
    `TalkUserBaseInfoRef`, но с `userInfo: TalkUser`, а не `TalkUserBaseInfo`)
  - `isRenamed`: boolean
  - `diarizedSpeaker`: объект `TalkUserRef`
  - `chunks`: array of `TalkTranscriptChunk`:
    - `chunkId`: string
    - `timeOffsetInMillis`: integer (int32)
    - `startTimeOffsetInMillis`: integer (int32)
    - `endTimeOffsetInMillis`: integer (int32)
    - `text`: string
    - `words`: array of `TalkTranscriptWord` (не разворачиваем — вне заданной глубины)
    - `confidence`: number (double), nullable
    - `diarizedSpeaker`: объект `TalkUserRef` (не разворачиваем)
  - `confidence`: number (double), nullable
- `errors`: array of `TalkTranscriptionError`:
  - `startTime`: string (format `date-span`)
  - `endTime`: string (format `date-span`)
  - `message`: string
- `transcriptId`: string (uuid), nullable

Коды сверх 200: не объявлены.

### 7. `GET /api/recordings/v2/{recordingKey}/summary`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `recordingKey` | path | string | true | Ключ записи |

Схема ответа `TalkCompositeSpeechCoreResult` (композит из трёх артефактов):
- `transcriptionV2`: объект `TalkTranscriptionV2Result`:
  - `status`: enum `TalkSpeechCoreResultStatus` = `notFound`, `inProgress`, `failed`, `success`,
    `notAvailable`, `serviceError`, `recreateInProgress`
  - `statusMessage`: string
  - `tracks`: array of `TalkTranscriptTrack` (структура как в п.6, не разворачиваем повторно)
  - `errors`: array of `TalkTranscriptionError` (`startTime`, `endTime`, `message`)
  - `transcriptId`: string (uuid), nullable
- `shortSummaryV2`: объект `TalkSummaryV2Result`:
  - `summaryId`: string (uuid), nullable
  - `status`: enum `TalkSpeechCoreResultStatus` (те же 7 значений)
  - `chunks`: array of `TalkSummaryV2Chunk`: `type` (string), `timestamp` (int32),
    `version` (int32), `text` (string), `hiddenStatus` (объект, не разворачиваем — предел глубины)
  - `hidden`: boolean
  - `hiddenReason`: string, nullable
  - `hiddenBy`: объект `TalkUser` (полная форма — см. общий блок)
  - `hiddenAt`: string (date-time), nullable
- `protocolV2`: объект `TalkSummaryV2Result` (та же схема, что `shortSummaryV2`, для протокола
  встречи вместо краткого пересказа)

Коды сверх 200: не объявлены.

### 8. `GET /api/recordings/{recordingKey}/summary/{summarizationType}`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `recordingKey` | path | string | true | Ключ записи |
| `summarizationType` | path | enum `TalkSummaryType` | true | Тип суммаризации |

`TalkSummaryType` = `shortSummary`, `protocol`.

Схема ответа `TalkSummaryV2Result` (структура идентична `shortSummaryV2`/`protocolV2` из п.7):
`summaryId`, `status` (enum `TalkSpeechCoreResultStatus`), `chunks[]` (`type`, `timestamp`,
`version`, `text`, `hiddenStatus`), `hidden`, `hiddenReason`, `hiddenBy` (`TalkUser`), `hiddenAt`.

Коды сверх 200: не объявлены.

### 9. `GET /api/recordings/{recordingKey}/summary` (deprecated)

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `recordingKey` | path | string | true | Ключ записи |

Схема ответа `TalkSummaryResult` — старый формат, отличается от `TalkSummaryV2Result`:
- `status`: enum `TalkSummaryStatus` = `notFound`, `inProgress`, `failed`, `success`,
  `notAvailable`, `serviceError` (**6** значений — без `recreateInProgress`, который есть у
  `TalkSpeechCoreResultStatus` в v2/актуальных эндпоинтах)
- `summary`: объект `TalkSummary`:
  - `summaryId`: string (uuid), nullable
  - `chunks`: array of `TalkSummaryChunk`: `id` (string), `text` (string), `timestamp` (int32)
    — обратите внимание: тут `id`, а не `type`/`version`, как в `TalkSummaryV2Chunk`
  - `hidden`: boolean
  - `hiddenReason`: string, nullable
  - `hiddenBy`: объект `TalkUser`
  - `hiddenAt`: string (date-time), nullable

Коды сверх 200: не объявлены. Резюме: старая (deprecated) и новая (`v2`/`{summarizationType}`)
схемы саммари не совместимы по форме чанков (`id`+`text`+`timestamp` vs `type`+`timestamp`+
`version`+`text`+`hiddenStatus`) — не путать при миграции.

### 10. `GET /api/domain/conferencesHistory`

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `fromDate` | query | string | date-time | | | | | Начало периода |
| `toDate` | query | string | date-time | | | | | Конец периода |
| `skip` | query | integer | int32 | | *(нет)* | | | «Курсор» |
| `take` | query | integer | int32 | | *(нет в схеме, в тексте «по умолчанию 100»)* | 1 | 100 | Количество элементов в результатах |
| `roomName` | query | array of string | | | | | maxItems: 50 | Фильтр по комнатам; если пусто — все комнаты |

Схема ответа `TalkConferenceInfos`:
- `conferences`: array of `TalkConferenceInfo`:
  - `key`: string
  - `roomName`: string
  - `startTime`: string (date-time)
  - `endTime`: string (date-time), nullable
  - `title`: string, nullable
  - `isPlannedMeeting`: boolean
  - `containsDeepFakeDetections`: boolean

Коды сверх 200: **400 Bad Request** (без описания тела ошибки в схеме).

### 11. `GET /api/ConferencesHistory/{conferenceKey}`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `conferenceKey` | path | string | true | Ключ конференции |

Схема ответа `TalkConference`:
- `key`: string
- `roomName`: string
- `startTime`: string (date-time)
- `endTime`: string (date-time), nullable
- `title`: string, nullable
- `isPlannedMeeting`: boolean
- `containsDeepFakeDetections`: boolean
- `description`: string, nullable
- `artifacts`: объект `TalkConferenceArtifacts`:
  - `participants`: array of `TalkUserRef` (не разворачиваем повторно — форма как `TalkUserRef` в п.6)
  - `content`: array of `ConferenceContent`: `type` (объект `ContentType`, не разворачиваем —
    предел глубины), `id` (string) — то есть это список **ссылок** на артефакты (заметки, чаты и
    т.п.) по типу+id, а не сами данные
  - `title`: string, nullable
  - `chatChannelHasMessages`: object (dictionary), значения — boolean
- `sessionHallsArtifacts`: object (dictionary), значения — `TalkConferenceArtifacts` (для
  многозальных/session hall мероприятий)
- `eventDescription`: string, nullable
- `participantsCount`: integer (int32)

Коды сверх 200: **404 Not Found**.

### 12. `GET /api/ConferencesHistory/v2/{conferenceKey}`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `conferenceKey` | path | string | true | Ключ конференции |

Схема ответа `TalkEnrichedConference` — расширенная версия п.11, `artifacts` содержит данные
напрямую, а не список ссылок:
- `key`, `roomName`, `startTime`, `endTime` (nullable), `title` (nullable), `isPlannedMeeting`,
  `description` (nullable), `containsDeepFakeDetections`, `eventDescription` (nullable) — те же
  поля верхнего уровня, что в п.11
- `artifacts`: объект `TalkEnrichedConferenceArtifacts`:
  - `title`: string, nullable
  - `participants`: array of `TalkUserRef`
  - `recordings`: array of `TalkConferenceRecording`: `id`, `title`, `description`,
    `previewImage` (не разворачиваем), `createdDate` (date-time), `createdBy` (`TalkUser`, не
    разворачиваем — предел глубины), `duration` (int32), `progress` (int32), `status` (enum
    `VideoMediaUploadStatus`, не разворачиваем), `frameSize` (не разворачиваем),
    `allowAnonymousAccess` (boolean), `participants` (array `TalkUserRef`, не разворачиваем),
    `participantsCount` (int32), `commentsCount` (int32), `hasAudioRecord` (boolean),
    `qualities` (array `TalkVideoQuality`, не разворачиваем), `transcription` (объект
    `TalkTranscription`, не разворачиваем — предел глубины), `conferenceKey` (string, nullable),
    `notesCount` (int64, nullable), `isStream` (boolean)
  - `polls`: array of `TalkPoll`: `id`, `title`, `isAnonymous`, `isMultiSelection`,
    `isRevoteDisabled`, `isCompleted`, `isPublished`, `publishDate` (date-time, nullable),
    `created` (date-time), `createdBy` (`TalkUserRef`, не разворачиваем), `options` (array
    `TalkPollOption`, не разворачиваем), `votesCount` (int32)
  - `notes`: array of `TalkNoteInfo`: `key`, `title`, `createdBy` (`TalkUser`, не разворачиваем),
    `createdDate` (date-time), `modifiedBy` (`TalkUser`, не разворачиваем), `modifiedDate`
    (date-time), `participantsAccessEnabled` (boolean), `latestLink` (не разворачиваем)
  - `messagesByChannel`: object (dictionary), значения — `TalkChatMessageList` (не разворачиваем —
    предел глубины)
- `sessionHallsArtifacts`: object (dictionary), значения — `TalkEnrichedConferenceArtifacts`

Коды сверх 200: **404 Not Found**.

**Существенная разница v1/v2 для SA:** `ConferencesHistory/{key}` (п.11) отдаёт только список
типизированных ссылок (`content[].type` + `content[].id`) на артефакты встречи, требуя
дозапросов; `ConferencesHistory/v2/{key}` (п.12) отдаёт сами объекты (записи, опросы, заметки,
сообщения по каналам) прямо во вложенных массивах.

### 13. `GET /api/ConferenceReports/{conferenceKey}/messages`

| Параметр | in | Тип | Format | Required | Default | Min | Max | Описание |
|---|---|---|---|---|---|---|---|---|
| `conferenceKey` | path | string | | true | | | | Ключ конференции |
| `skip` | query | integer | int32 | | *(нет)* | | | «Курсор» |
| `take` | query | integer | int32 | | *(нет в схеме, в тексте «по умолчанию 100»)* | 1 | 100 | Количество элементов для получения |

Схема ответа `TalkConferenceChatReport`:
- `messages`: array of `TalkConferenceChatReportMessage`:
  - `created`: string (date-time)
  - `sender`: объект `TalkConferenceReportParticipant`: `participantId` (string),
    `participantName` (string), `isGuest` (boolean)
  - `recipient`: объект `TalkConferenceReportParticipant` (та же форма — приватные сообщения
    адресуются конкретному участнику; для сообщений в общий чат, по-видимому, `null`, спека не
    делает поле nullable явно, это стоит проверить эмпирически)
  - `isPrivate`: boolean
  - `text`: string, nullable
  - `attachments`: array of `TalkConferenceChatReportAttachment`: `downloadUrl` (string),
    `fileName` (string), `fileId` (string)

Коды сверх 200: **400 Bad Request**, **403 Forbidden**, **404 Not Found**.

### 14. `GET /api/ConferenceReports/{conferenceKey}/participants`

| Параметр | in | Тип | Required | Описание |
|---|---|---|---|---|
| `conferenceKey` | path | string | true | Ключ конференции |

Схема ответа `TalkConferenceParticipantsReport`:
- `participants`: array of `TalkConferenceReportParticipantExtendedInfo`:
  - `participantId`: string
  - `participantName`: string
  - `isGuest`: boolean
  - `connectionsInfo`: array of `TalkConferenceReportParticipantConnectionInfo`:
    - `appPlatform`: string, nullable
    - `isViaProxy`: boolean
    - `participantRealIp`: string, nullable
    - `country`: string, nullable

Коды сверх 200: **403 Forbidden**, **404 Not Found**.

## Общий блок: `TalkDomainConferenceRecording` (общий элемент для п.1-3)

Используется как единичный ответ п.3 и как элемент массива `recordings`/`entities` в п.1/п.2.

- `id`: string, nullable
- `key`: string
- `title`: string
- `createdDate`: string (date-time)
- `createdBy`: объект `TalkUser` (полная форма — см. ниже)
- `roomName`: string
- `participantsCount`: integer (int32)
- `size`: integer (int64), nullable
- `duration`: integer (int32)
- `canBeRemoved`: boolean
- `participants`: array of `TalkUserBaseInfoRef` (усечённая форма — см. ниже)
- `allowAnonymousAccess`: boolean

### `TalkUser` (полная форма — `createdBy`, `hiddenBy`, `modifiedBy` и т.п.)

`userType` (enum `TalkUserType`: `normal`, `kiosk`), `login` (nullable), `hasEmail` (boolean),
`firstname` (nullable), `surname` (nullable), `patronymic` (nullable), `department` (nullable),
`disabled` (boolean), `deletedBySelf` (boolean), `roles` (array of string), `roleInfos` (array of
`TalkRoleInfo`: `id`, `title`), `key` (string), `post` (nullable), `avatarUrl` (nullable),
`profileUrl` (nullable), `hasMobilePhone` (boolean), `hasInnerPhone` (boolean), `avatarInfo`
(объект `TalkAvatarInfo`: `width`, `height`, `face` — не разворачиваем, `contentHash`), `status`
(enum `TalkUserStatus`: `unknown`, `inMeeting`, `doNotDisturb`, `online`), `removed` (boolean),
`hidden` (boolean), **`email`** (nullable), **`features`** (array of string), **`mobilePhone`**
(nullable), **`innerPhone`** (nullable).

### `TalkUserBaseInfo` (усечённая форма — `participants[].userInfo`)

Все поля `TalkUser`, **кроме** выделенных жирным выше (`email`, `features`, `mobilePhone`,
`innerPhone`). Подтверждено дифф-сравнением по `components.schemas` напрямую: у
`TalkUserBaseInfo` этих 4 полей нет вообще, они не nullable-опущены, а физически отсутствуют в
схеме.

### `TalkUserBaseInfoRef` / `TalkUserRef`

Обёртка вокруг `TalkUser`/`TalkUserBaseInfo` для представления «участника, который может быть
анонимным»:
- `anonymousName`: string, nullable
- `anonymousId`: string, nullable
- `userInfo`: `TalkUserBaseInfo` (в `TalkUserBaseInfoRef`) либо `TalkUser` (в `TalkUserRef`, судя
  по имени схемы — не проверено разворачиванием на глубину 2, только по типу ссылки)
- `isAnonymous`: boolean

## Whoami / диагностика ключа: что есть в спеке

Явного эндпоинта с названием `whoami`/`authorize`/`session` в спеке нет. Проверены два кандидата
из тега «API-ключи»:

### `GET /api/domain/applications/access-info`

- Параметры: **нет** (ни query, ни path).
- `description`: «По запросу выводится информация обо всех доступах текущего ключа пользователя.
  Запрос выполняется в том числе для ключей с истекшим сроком действия. При успешном выполнении
  будет выведен объем доступа ключа для каждого приложения, подключенного в указанном пространстве».
- В `description` **нет** строки `Разрешения: ...` (в отличие от всех 14 целевых эндпоинтов и от
  соседнего `GET /api/domain/applications`) — формальное свидетельство, что эндпоинт не требует
  конкретного scope; подтвердить эмпирически (спека декларативно этого не пишет прямым текстом).
- Схема ответа `TalkDomainApplicationAccessInfo`:
  - `expiredAt`: string (date-time)
  - `scopes`: array of `TalkScope`:
    - `type`: enum `TalkScopeType` (19 значений — см. раздел enum'ов)
    - `restrictionType`: enum `TalkScopeRestrictionType` = `read`, `readWrite`
- Работает «в том числе для ключей с истекшим сроком действия» — то есть подходит и для
  диагностики просроченного ключа, не только валидного.
- Коды сверх 200: не объявлены.

### `GET /api/domain/applications`

- Отдельный, более тяжёлый эндпоинт — список **всех** API-ключей пространства (не только
  текущего), с полями `token`, `createdBy`, `modifiedBy`, `refreshedTokenBy`, `targetApiType`,
  `accessRestrictionWhitelist` (IP allowlist) и т.д.
- `description`: «Позволяет получить информацию об API-ключах, созданных в пространстве. Для
  использования API-запроса необходимо включить разрешение «Информация по API-ключам» для
  приложения в разделе Управление. Разрешения: `application.applications.read`» — то есть
  требует **отдельно** включённого разрешения плюс явный scope `applications`, в отличие от
  `access-info`.
- Параметры: `top` (query, int32, default 50), `start` (query, string date-time — «Дата
  сортировки»).
- Схема ответа `TalkDomainApplicationsList.applications[]` включает то же `scopes[]`
  (`TalkScope`), что и `access-info`, но в контексте каждого ключа пространства, плюс поле
  `token` (сам ключ, в открытом виде — критично: это чувствительные данные, не для журналов/логов).

**Вывод для FR-11:** `access-info` — вероятный кандидат «whoami» (не требует прав, отдаёт свои
scope + `expiredAt`), `applications` — административный листинг ключей пространства (требует
отдельного разрешения, отдаёт токены других ключей). Для диагностики собственного ключа
подходит именно `access-info`.

## Enum'ы, встретившиеся в разобранных 14 эндпоинтах и связанных схемах

| Enum | Значения | Где встречается |
|---|---|---|
| `RecordingsOrderMode` | `unknown`, `byTitle`, `byTimeNewFirst`, `byTimeOldFirst`, `bySizeBigFirst`, `bySizeSmallFirst` | параметр `orderMode` в п.1, п.2 |
| `TalkSummaryType` | `shortSummary`, `protocol` | параметр пути `summarizationType` в п.8 |
| `TalkUserType` | `normal`, `kiosk` | поле `userType` в `TalkUser`/`TalkUserBaseInfo` |
| `TalkUserStatus` | `unknown`, `inMeeting`, `doNotDisturb`, `online` | поле `status` в `TalkUser`/`TalkUserBaseInfo` |
| `TalkTranscriptionStatus` | `inProgress`, `error`, `complete` | поле `status` в `TalkTranscript` (п.6) |
| `TalkSpeechCoreResultStatus` | `notFound`, `inProgress`, `failed`, `success`, `notAvailable`, `serviceError`, `recreateInProgress` (7 значений) | `status` в `TalkTranscriptionV2Result`/`TalkSummaryV2Result` (п.7, п.8) |
| `TalkSummaryStatus` | `notFound`, `inProgress`, `failed`, `success`, `notAvailable`, `serviceError` (6 значений — без `recreateInProgress`) | `status` в устаревшем `TalkSummaryResult` (п.9) |
| `TalkScopeType` | `profiles`, `calendar`, `calendarControl`, `rooms`, `reporting`, `kiosk`, `recording`, `routing`, `onlineStats`, `applications`, `roles`, `corpTelephony`, `spectatorRegistration`, `federations`, `redirect`, `streamEvents`, `deepfakeDetection`, `surveys`, `webhooks` (19 значений) | `scopes[].type` в `access-info`/`applications` |
| `TalkScopeRestrictionType` | `read`, `readWrite` | `scopes[].restrictionType` в `access-info`/`applications` |

Значения `TalkScopeType`, релевантные для 14 целевых эндпоинтов: `recording` (Записи, п.1-9),
`reporting` (Отчётность, п.10-14).

## Коды ошибок: общая таблица из `info.description` vs объявленные в операциях

Спека содержит текстовый раздел «Коды ошибок и их значения» (не формальную JSON-схему, а
markdown внутри `info.description`), общий для всего API:

| Код | Значение (дословно из спеки) |
|---|---|
| 400 BadRequest | Неверные параметры запроса |
| 401 Unauthorized | «Убедитесь, что в запрос добавлен заголовок `X-Auth-Token` с зарегистрированным ключом. Также эта ошибка может возникать в случае проблемы при интеграции с Exchange» |
| 403 Forbidden | «Убедитесь, что ключ в заголовке `X-Auth-Token` имеет нужный уровень доступа» |
| 404 Not Found | Данные с указанными параметрами не найдены |
| 408 Request Timeout | «Отправка запроса не завершена в заданное время. Проверьте стабильность соединения» |
| 409 Conflict | «Убедитесь, что параметры запроса не повторяются» |
| 429 TooManyRequests | «Превышено ограничение по количеству запросов к API. Ограничение может быть указано в описании запроса» |

Сопоставление с формальными `responses` по 14 операциям (собрано программно):

| Код | Объявлен в скольких из 14 операций | Где именно |
|---|---|---|
| 400 | 2 | п.10 (`conferencesHistory`), п.13 (`ConferenceReports/messages`) |
| 403 | 2 | п.13, п.14 (обе `ConferenceReports/*`) |
| 404 | 4 | п.11, п.12 (`ConferencesHistory*`), п.13, п.14 |
| 401 | 0 | нигде |
| 408 | 0 | нигде среди 14 (встречается в других 87-14=73 путях спеки, не проверялось для них) |
| 409 | 0 | нигде среди 14 |
| 429 | 0 | нигде |

**Вывод:** 401 (неверный/отсутствующий ключ) и 429 (rate limit) — платформенные коды, которые
клиент обязан уметь обрабатывать для ЛЮБОГО из 14 эндпоинтов, даже там, где формальная OpenAPI-
схема их не перечисляет. Полагаться на список `responses` конкретной операции для этих двух
кодов нельзя — их нужно закладывать как общее поведение HTTP-клиента.

## Что НЕ удалось выяснить

- Реальное поведение `qualityName` (аномалия): требует ли API фактически query-параметр или
  сегмент пути, и что происходит при их одновременной/раздельной передаче — спека не дает
  ответа, нужен эмпирический запрос к реальному API или уточнение у вендора.
- Формат тела ошибок (400/403/404/…): спека не описывает JSON-схему ошибки ни для одной из 14
  операций (`responses.<code>` без `content`) — неизвестно, единый ли это формат (`{message}`,
  `{code, message}`, RFC7807 и т.п.) по всему API.
- Действительно ли `GET /api/domain/applications/access-info` не требует scope на практике
  (отсутствие строки `Разрешения:` в `description` — косвенный, не декларативный признак).
- Точные лимиты rate limiting (429) — «может быть указано в описании запроса», но ни у одной из
  14 операций явного числового лимита в `description` нет.
- Content-Type и заголовки ответа `GET /api/Recordings/{recordingKey}/file/{qualityName}`
  (бинарная выдача) — спека не описывает `content` для 200 у этой операции вовсе.
- Список допустимых значений `qualityName` (кроме рекомендованного `900 p` в тексте) — нет ни
  enum, ни ссылки на список качеств в самой операции (возможно, связано с `TalkVideoQuality` из
  `TalkConferenceRecording.qualities`, но прямой связи в спеке не заявлено).

## Рекомендации для BA/SA

- **BA:** зафиксировать в требовании к клиенту два независимых поведения — обработку 401/429 как
  общеплатформенных (не завязанных на конкретный эндпоинт) и обработку явно объявленных 400/403/404
  там, где они есть (п.10, 11, 12, 13, 14). Уточнить с продуктом/вендором формат тела ошибки, раз
  спека его не описывает.
- **BA:** при определении критериев приёмки для FR-11 (диагностика ключа) опираться на
  `GET /api/domain/applications/access-info` как первичный кандидат — единственный найденный
  эндпоинт без параметров, отдающий `scopes[]`+`expiredAt` для ключа, которым выполнен запрос, и
  явно работающий даже для истёкших ключей.
- **SA:** при проектировании клиента учесть, что `/recordings` (v1) и `/recordings/v2` — разные
  контракты ответа (`recordings[]` без пагинации vs `entities[]` + курсор `nextPageToken`/
  `pageTokenString`); текущий код, судя по CLAUDE.md, читает несовместимую комбинацию полей —
  нужно явно выбрать одну версию (вероятно, v2, так как v1 deprecated) и свести маппер к её форме.
- **SA:** аномалию `qualityName: in=query` при формировании HTTP-клиента для скачивания файла
  стоит трактовать как повод для эмпирической проверки перед фиксацией контракта клиента, а не
  слепо повторять форму из спеки.
- **SA:** учесть разницу схем `TalkUser` vs `TalkUserBaseInfo` при проектировании модели данных
  участников — e-mail недоступен через `participants[]`, только через `createdBy`/`hiddenBy` и
  аналогичные поля с полным `TalkUser`.
- **SA:** для архива встреч предпочесть `ConferencesHistory/v2/{key}` (п.12) вместо v1 (п.11) —
  v2 отдаёт данные напрямую (записи/опросы/заметки/сообщения), v1 — только список типизированных
  ссылок, требующий дополнительных запросов.
- **SA:** deprecated-эндпоинты (`/api/Domain/recordings` без v2, `/api/recordings/{key}/summary`
  без типа) не закладывать в новый клиент как основной путь — есть актуальные аналоги с иной
  формой ответа (см. таблицы выше).

## Источники

- [primary] `talk.public.api-api-2.json` (локальный файл в корне worktree,
  `/Users/mdemyanov/Devel/ktalk-mcp/.worktrees/epic-personal-api-key/talk.public.api-api-2.json`) —
  единственный источник этого исследования, OpenAPI 3.0.4, 87 путей, `info.description` содержит
  как формальные `paths`/`components.schemas`, так и текстовые markdown-разделы («Начало работы»,
  «Области действия и разрешения», «Коды ошибок и их значения», «Работа с вебхуками»), которые не
  выражены в формальной JSON-схеме и извлечены отдельно ручным чтением `info.description`.
