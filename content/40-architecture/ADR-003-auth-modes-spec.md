---
title: "ADR-003 spec: режимы авторизации, профили эндпоинтов, диагностика"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-003 spec: режимы авторизации, профили эндпоинтов, диагностика

Companion-спека к [ADR-003](../00-project/adr/ADR-003-auth-modes.md). Здесь — детализация,
которую ADR сознательно не несёт: таблица профиля, псевдокод, форма нормализованного DTO, карта
«путь → scope → сообщение», сценарии деградации `auth_status`, бриф для Dev/DevOps, контракт с
QA-author. Источник требований —
[«Персональный API-ключ и расширение возможностей»](../30-requirements/personal-api-key.md)
(FR-1..FR-11, FR-14, FR-15, NFR-1..NFR-5).

## Контекст

Эпик 0.5.0 добавляет второй режим авторизации (`X-Auth-Token`) поверх существующего `sessionToken`
и операции интеграторского API, которых у клиента сегодня нет. Эмпирический зонд (session-режим —
`probe-results.md` часть 1; api-key-режим — часть 2, ключ выдан 2026-08-13 без нужных scope)
подтвердил: набор доступных путей жёстко привязан к режиму, 401/403 — устойчиво разные диагнозы,
`access-info` требует scope, который сам диагностирует. Полная аргументация — [ADR-003](../00-project/adr/ADR-003-auth-modes.md).

## Компоненты

| Компонент | Ответственность | Входы | Выходы | Зависимости |
|-----------|-----------------|-------|--------|-------------|
| `Settings` | Вычисляет `AuthMode` и активный credential по приоритету ключ→сессия→ошибка | env (`KTALK_PERSONAL_API_KEY`, `KTALK_SESSION_TOKEN`) | `AuthMode`, credential-строка | `pydantic_settings` |
| `AuthContext` | Immutable-пара (режим, credential), передаётся в клиент один раз | `Settings` | — | `Settings` |
| `OPERATION_PROFILES` | Декларативная таблица «операция × режим → путь + scope + нормализатор» | — (статические данные) | `EndpointProfile \| None` | — |
| `KTalkClient._call` | Единственная точка диспетчеризации: ищет профиль, строит запрос, классифицирует ответ, нормализует | operation, params, `AuthContext` | `NormalizedX` либо исключение | `httpx`, `OPERATION_PROFILES`, `ErrorClassifier` |
| Нормализаторы (`normalize_*`) | JSON конкретной формы → канонический DTO | сырой `dict` | `NormalizedRecording`/`NormalizedPage`/... | — |
| `PageCursor` (`SkipCursor`/`TokenCursor`) | Абстракция конца страницы по режиму | предыдущая страница | параметры следующего запроса либо `None` | — |
| `ErrorClassifier` | Код ответа + `required_scope` + `AuthMode` → человекочитаемое сообщение | `status_code`, `EndpointProfile` | `KTalkAuthError`/`KTalkScopeError`/... | `SCOPE_LABELS` |
| `AuthStatusService` | Оркестрирует `auth_status` с деградацией | `AuthContext` | `AuthStatus` DTO | `KTalkClient` |
| `SecretRedactor` | Страховочная маскировка секрета на границе CLI/MCP | необработанное исключение, значение секрета | текст без секрета | — |

## Границы

- Не парсит тело 401/403 как источник истины — формат нигде не подтверждён (401) или чаще пустой
  (403); диагностика опирается только на код ответа и заранее известный `required_scope`.
- Не реализует retry/backoff для 429 — числовые лимиты нигде не задокументированы (открытый вопрос
  BA, зондом не закрыт); 429 проходит по общему «нераспознанная ошибка API» пути FR-5 AC3.
- Не хранит секрет нигде, кроме процесса (env → `Settings` → `AuthContext` → httpx-клиент);
  никакого файла токена (явно отклонено требованием, см. «Вне рамок» в BA-артефакте).
- Не угадывает физическую форму `qualityName` (`in: query` при наличии в шаблоне пути — аномалия
  спеки, RES-001) — изолирует выбор в одной функции `build_download_url`, чтобы эмпирическая
  правка позже трогала одно место, а не все вызовы.

## Поток данных

<mermaid path="./ADR-003-dispatch-flow.mermaid" width="900px" height="560px"/>

## Таблица профиля эндпоинтов

Форма 1:1 с FR-6, дополнена `required_scope` (для 403-диагностики) и нормализатором.

| Операция | Session: путь / scope | Api-key: путь / scope | Нормализатор |
|---|---|---|---|
| `list_recordings` | `GET /api/recordings` / — | `GET /api/Domain/recordings/v2` / `recording` | `normalize_list_session` / `normalize_list_apikey` |
| `get_recording` | `GET /api/recordings/{id}` / — | `GET /api/Domain/recordings/{key}` / `recording` | `normalize_recording` (общий, разные источники) |
| `get_transcript` | `GET /api/recordings/{key}/transcript` / — | тот же путь / `recording` | `normalize_transcript` (общий) |
| `get_summary` (v2/по типу) | те же пути / — | те же пути / `recording` | `normalize_summary` (общий) |
| `get_conference` | `GET /api/conferencesHistory/{key}` / — | `GET /api/ConferencesHistory/v2/{key}` / `reporting` | `normalize_conference_v1` / `normalize_conference_v2` |
| `get_participants_full` (выделенный путь) | **None** — нет отдельного пути | `GET /api/Domain/recordings/{key}/participants` / `recording` | `normalize_participants` |
| `download_file` | из `qualities[].fileUrl` деталей записи / — | `GET /api/Recordings/{key}/file/{quality}` / `recording` | `build_download_url` + потоковая передача |
| `list_archive` | **None** — `GET /api/domain/conferencesHistory` даёт 401 под сессией | `GET /api/domain/conferencesHistory` / `reporting` | `normalize_archive_page` |
| `get_chat_messages` | `GET /api/conferencesHistory/{key}/chat/messages?channel=` / — | `GET /api/ConferenceReports/{key}/messages` / `reporting` | `normalize_chat_session` / `normalize_chat_apikey` |
| `get_participants_report` | **None** | `GET /api/ConferenceReports/{key}/participants` / `reporting` | `normalize_participants_report` |
| `auth_status` | нет прямого пути — probe (см. ниже) | `GET /api/domain/applications/access-info` / `applications` | `normalize_access_info` |

`get_participants_full(recording)` **как публичная операция FR-8** — не тождественна строке
таблицы выше: в session-режиме она реализована ДРУГИМ путём (дообогащение через
`get_recording`/`get_conference`, обе доступны сессии), не через выделенный `Domain/…/participants`.
Публичный метод сам выбирает механизм по режиму на уровне оркестрации, а не через `_call`
с единственным профилем — см. «Решение открытого вопроса: участники >10» ниже.

## Модель данных: нормализованные DTO

```python
class AuthMode(str, Enum):
    SESSION = "session"
    API_KEY = "api_key"

@dataclass(frozen=True)
class AuthContext:
    mode: AuthMode
    credential: str          # значение НИКОГДА не попадает в __repr__/логи целиком

@dataclass(frozen=True)
class EndpointProfile:
    path_template: str
    required_scope: str | None      # None = нет понятия scope (session) либо не требуется
    normalizer: Callable[[dict], Any]

@dataclass
class NormalizedRecording:
    id: str | None      # как есть из ответа; в session — единственное поле PK сегодня
    key: str | None      # есть только у api-key-контура (TalkDomainConferenceRecording.key)
    title: str
    created_by: dict
    participants: list["NormalizedParticipant"]
    participants_count: int
    duration: int
    # ... остальные поля — маппинг 1:1, без обрезки набора

@dataclass
class NormalizedParticipant:
    display_name: str          # surname firstname | anonymousName | "Неизвестный" (конвенция CLAUDE.md)
    is_anonymous: bool
    raw_ref: dict               # TalkUserBaseInfoRef как есть — для будущих полей без миграции DTO

@dataclass
class NormalizedPage:
    items: list[dict]
    cursor: "PageCursor | None"     # None = последняя страница

class PageCursor(Protocol):
    def next_params(self) -> dict: ...

@dataclass
class SkipCursor:
    skip: int
    top: int
    def next_params(self) -> dict:
        return {"skip": self.skip, "top": self.top}

@dataclass
class TokenCursor:
    token: str
    def next_params(self) -> dict:
        return {"pageTokenString": self.token}
```

`NormalizedRecording` намеренно несёт и `id`, и `key` раздельно (не схлопывает их в единый PK на
уровне DTO) — FR-15 требует сверки этих значений между контурами ДО первого боевого api-key sync;
схлопывание на этом уровне сделало бы расхождение невидимым для сверки.

## Псевдокод: селектор режима (`Settings`)

```python
class Settings(BaseSettings):
    ktalk_base_url: str = "https://your-domain.ktalk.ru"
    ktalk_session_token: str | None = None
    ktalk_personal_api_key: str | None = None

    @property
    def auth_mode(self) -> AuthMode:
        if self.ktalk_personal_api_key:
            if self.ktalk_session_token:
                logger.warning(
                    "Заданы обе переменные — используется KTALK_PERSONAL_API_KEY, "
                    "KTALK_SESSION_TOKEN игнорируется."
                )  # без значений секретов в тексте
            return AuthMode.API_KEY
        if self.ktalk_session_token:
            return AuthMode.SESSION
        raise KTalkConfigError(
            "Не задана ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN. "
            "Укажите одну из переменных (см. README)."
        )

    @property
    def auth_credential(self) -> str:
        return self.ktalk_personal_api_key or self.ktalk_session_token  # auth_mode уже проверил непустоту
```

`KTalkClient.from_settings(settings)` строит `AuthContext(settings.auth_mode, settings.auth_credential)`
и настраивает `httpx.AsyncClient` ОДИН раз при конструировании:

```python
def _build_http_client(base_url: str, auth: AuthContext) -> httpx.AsyncClient:
    if auth.mode is AuthMode.API_KEY:
        return httpx.AsyncClient(base_url=base_url, headers={"X-Auth-Token": auth.credential}, timeout=30.0)
    return httpx.AsyncClient(base_url=base_url, params={"sessionToken": auth.credential}, timeout=30.0)
```

Ни один запрос физически не может нести оба механизма — они не сосуществуют в конфигурации одного
`httpx.AsyncClient` (FR-2, инвариант из BA-артефакта).

## Псевдокод: диспетчер клиента

```python
async def _call(self, operation: str, **params) -> Any:
    profile = OPERATION_PROFILES[operation].get(self._auth.mode)
    if profile is None:
        raise OperationNotAvailableError(
            f"Операция «{OPERATION_LABELS[operation]}» доступна только в режиме "
            f"персонального ключа (переменная KTALK_PERSONAL_API_KEY)."
        )
    path = profile.path_template.format(**{k: v for k, v in params.items() if k in PATH_KEYS})
    response = await self._http.get(path, params=_query_params(params))
    self._classify(response, operation, profile.required_scope)
    return profile.normalizer(response.json())
```

Публичные методы (`list_recordings`, `get_recording`, ...) — тонкие обёртки над `_call`: сигнатуры
и имена не меняются (NFR-1), внутри — один вызов диспетчера вместо `if self._auth.mode == ...` в
каждом методе.

## Единый итератор пагинации (FR-9, FR-14)

```python
async def iter_pages(client: KTalkClient, operation: str, **kwargs) -> AsyncIterator[list[dict]]:
    cursor: PageCursor | None = None
    while True:
        page: NormalizedPage = await client._call(operation, cursor=cursor, **kwargs)
        yield page.items
        if page.cursor is None:      # конец страницы — каждый нормализатор решает по-своему
            break
        cursor = page.cursor
```

- `normalize_list_session`: `cursor = SkipCursor(skip+top, top)` если `len(items) == top`
  (полная страница — возможно есть ещё), иначе `None`. Не полагается на `nextPageToken` — его нет
  в этой форме ответа (зонд Ф-3).
- `normalize_list_apikey`: `cursor = TokenCursor(raw["nextPageToken"])` если поле непустое, иначе
  `None`.

`ktalk sync` и `list_archive` используют этот итератор напрямую — единственное различие между ними
на уровне вызывающего кода — имя операции (`list_recordings` vs `list_archive`), не наличие
отдельной ветки под `skip` и под токен.

## Карта «путь → scope → сообщение об ошибке»

| `required_scope` | Человекочитаемая метка | Операции |
|---|---|---|
| `application.recording.read` | «Записи (только чтение)» | `list_recordings`(api-key), `get_recording`(api-key), `get_transcript`, `get_summary`, `get_participants_full`, `download_file` |
| `application.reporting.read` | «Отчётность (только чтение)» | `get_conference`(v2), `list_archive`, `get_chat_messages`(api-key), `get_participants_report` |
| `application.applications.read` | «Информация по API-ключам (только чтение)» | `auth_status` → `access-info` |
| `None` (session, нет понятия scope) | — | все session-операции |

Классификатор:

```python
def _classify(self, response, operation, required_scope):
    if response.status_code == 401:
        if self._auth.mode is AuthMode.API_KEY:
            raise KTalkAuthError("Ключ авторизации истёк или невалиден. Обновите KTALK_PERSONAL_API_KEY (см. README).")
        raise KTalkAuthError("Токен сессии истёк или невалиден. Обновите KTALK_SESSION_TOKEN (см. README).")
    if response.status_code == 403:
        if self._auth.mode is AuthMode.API_KEY and required_scope:
            label = SCOPE_LABELS[required_scope]
            raise KTalkScopeError(
                f"Ключу не хватает разрешения «{label}» ({required_scope}). "
                f"Добавьте его ключу в настройках Толка (администратор домена)."
            )
        raise KTalkAuthError("Доступ запрещён. Обратитесь к администратору Толка.")
    if response.status_code == 404:
        raise KTalkNotFoundError(...)
    response.raise_for_status()   # прочие коды (400/408/409/429/5xx) — общий читаемый путь FR-5 AC3
```

Принцип: классификатор ВСЕГДА решает по (код ответа, режим, `required_scope` СВОЕЙ операции) —
никогда по коду СОСЕДНЕЙ операции. Это защищает от ловушек вида «эндпоинт валидирует параметры до
проверки авторизации и отдаёт 400 вместо 401/403» — единичный нетипичный код одной операции не
должен становиться основанием для вывода об scope всего ключа.

## Сценарии деградации `auth_status` (FR-11)

| Режим | Запрос | Результат | `alive` | `scopes` | Примечание |
|---|---|---|---|---|---|
| api-key | `access-info` → 200 | Полный отчёт | true | список | Основной путь, требует `applications.read` |
| api-key | `access-info` → 403 | Деградация | **true** | `None` | 403 = ключ валиден по определению (зонд, Ф-12); просто не хватает `applications.read` |
| api-key | `access-info` → 401 | Ключ мёртв | false | `None` | — |
| session | нет пути-аналога | Probe `list_recordings(top=1)` | true/false по коду ответа | `None` (не существует для сессии) | Закрывает открытый вопрос BA — см. ниже |

`AuthStatus.note` всегда объясняет, ПОЧЕМУ `scopes`/`expiredAt` отсутствуют, когда они `None` —
никогда молча.

## Закрытые открытые вопросы BA

**1. Механизм диагностики в session-режиме (FR-11).** BA оставил решение SA. Ответ: аналога
`access-info` у сессионного токена нет структурно (нет понятия scope у сессии, не вопрос прав).
`auth_status` в session-режиме делает реальный сетевой запрос `list_recordings(top=1, skip=0)` —
самый дешёвый уже известный рабочий session-эндпоинт — и возвращает бинарное «работает / не
работает» по коду ответа, явно указывая, что состав доступа и срок действия не проверяются
принципиально. Это удовлетворяет AC FR-11 («честный ответ… а не имитация без сетевого обращения»)
— запрос реальный, а не заглушка.

**2. Достаточно ли дообогащения для >10 участников (FR-8) в session-режиме.** BA пометил как
открытый — зонд подтвердил только случай с 8 участниками. Решение: `get_participants_full` в
session-режиме объединяет ДВА источника — `get_recording` (`participants[]`) и `get_conference`
(`artifacts.participants`) — по уникальному участнику (`userInfo.key` либо `anonymousId`), не
доверяя ни одному в отдельности. Если объединённый результат всё равно короче
`participantsCount`, клиент возвращает то, что есть, с явным флагом `incomplete: true` вместо
тихого укорачивания — деградация видна вызывающему коду и не выдаётся за полный список.
**Ручная проверка на боевом домене остаётся обязательной** (запись с >10 участников зондом не
найдена/не проверена) — если объединение не покрывает случай, это будет видно по флагу
`incomplete`, а не по молчаливо неверным данным.

## Остающиеся открытые вопросы (не закрыты этой спекой)

- **Ключ на момент проектирования не имеет `recording.read`/`reporting.read`/`applications.read`**
  (зонд, Ф-11) — ни один api-key-путь эпика не проверен эмпирически. Боевая валидация блокирована
  до перевыпуска ключа с этими тремя scope (см. бриф DevOps).
- **`qualityName: in=query`** (аномалия спеки) — реальное поведение API (путь vs query) не
  проверено; изолировано в `build_download_url`, требует эмпирической проверки при первом боевом
  скачивании под ключом.
- **Пределы 429** — нигде не задокументированы числом; общий error-путь их не различает от прочих
  нераспознанных кодов.
- **Совпадение `id` между контурами (FR-15)** — не проверяется без `recording.read`; `NormalizedRecording`
  хранит оба поля раздельно специально для этой сверки, само совпадение не гарантировано архитектурой.

## NFR Mapping

- **NFR-1** (публичный интерфейс MCP не меняется) → публичные методы клиента — тонкие обёртки над
  `_call`, сигнатуры фиксированы; новые параметры — с дефолтами, отсутствующими у старых вызовов.
- **NFR-2** (селектор задокументирован и протестирован) → `Settings.auth_mode` — единственная
  точка вычисления режима, юнит-тестируема на всех 4 комбинациях env без сети.
- **NFR-4** (README про ключ/ротацию/отличия) → вне архитектуры, бриф Dev включает пункт про README.
- **NFR-5** (ключ не логируется) → заголовок вместо query убирает секрет из URL структурно;
  `SecretRedactor` — барьер на границе CLI/MCP для случаев, которые архитектура не предвидела
  (generic exceptions, httpx repr).

## Бриф для Dev

**Архитектура:** этот файл и [ADR-003](../00-project/adr/ADR-003-auth-modes.md).
**Требование:** [personal-api-key.md](../30-requirements/personal-api-key.md).
**Фаза:** 0.5.0, первая реализация (боевая проверка api-key-путей заблокирована до перевыпуска
ключа — см. бриф DevOps).

**Реализовать (порядок — fixtures → интерфейсы → реализация → тесты):**
1. `AuthMode`, `AuthContext`, `Settings.auth_mode`/`auth_credential` — с юнит-тестами на все 4
   комбинации env (FR-1, FR-2, FR-3, NFR-2).
2. `OPERATION_PROFILES` таблица + `EndpointProfile` + `_call`/`_classify` в `client.py` —
   `OperationNotAvailableError` для операций без профиля в текущем режиме (FR-6 AC3).
3. Нормализаторы для каждой пары (операция, режим) из таблицы профиля — по одной фикстуре на
   форму ответа (используй примеры полей из `probe-results.md`/RES-001, не реальные ФИО из
   домена — Sensitive content в BA-артефакте).
4. `PageCursor`/`SkipCursor`/`TokenCursor` + `iter_pages` — переиспользуется в `ktalk sync` (FR-14)
   и `list_archive` (FR-9).
5. `build_download_url` с URL-квотированием и нормализацией имени качества (`900p`/`900 p`) —
   единая функция, FR-7 AC2.
6. `get_participants_full` — оркестрация session-режима (двойной источник + флаг `incomplete`,
   см. «Закрытые открытые вопросы»), FR-8.
7. `AuthStatusService.auth_status` — сценарии деградации из таблицы выше, FR-11.
8. `SecretRedactor` на границе `cli.py`/`server.py` — NFR-5.

**Acceptance Criteria из BA:** все AC FR-1..FR-11, FR-14, FR-15, NFR-1..NFR-5 из требования
(автоматические — реализуются и тестируются сейчас; ручные, помеченные «боевой домен» — не
блокируют мердж, но требуют прогона после перевыпуска ключа).

## Бриф для DevOps

**Архитектура:** этот файл.
**Подготовить:**
- **Перевыпуск/расширение персонального ключа** — `application.recording.read` +
  `application.reporting.read` обязательны для боевой проверки эпика; `application.applications.read`
  дополнительно для полного (не деградированного) `auth_status`. Без этого шага все ручные AC
  требования остаются неподтверждёнными (зонд, Ф-11).
- README: раздел о разнице `KTALK_PERSONAL_API_KEY` / `KTALK_SESSION_TOKEN` / `X-API-Key`
  (второй ключ пространства, вне scope эпика) — NFR-4.
- Runbook: что делать при `KTalkScopeError` (какое разрешение добавить администратору домена) —
  таблица scope→метка выше пригодна как есть.
- Обязательный ручной шаг перед первым боевым `ktalk sync` в api-key-режиме — сухой прогон сверки
  `id`/`key` (FR-15); задокументировать в README как обязательную процедуру.

**NFR из BA:** NFR-4 (README), NFR-5 (секрет не в логах/выводе — проверить на реальном CLI-выводе
после реализации, не только юнит-тестом).

## Контракт с QA-author

**AC (полный список из требования):** FR-1 (2 AC), FR-2 (2 AC), FR-3 (2 AC), FR-4 (3 AC), FR-5
(3 AC), FR-6 (3 AC), FR-7 (4 AC), FR-8 (3 AC), FR-9 (4 AC), FR-10 (4 AC), FR-11 (3 AC), FR-14
(3 AC), FR-15 (3 AC), NFR-1..NFR-5 (по 1 AC) — полный текст в
[personal-api-key.md](../30-requirements/personal-api-key.md).

**Архитектурный контекст для тестов:**
- Компоненты: `Settings` (селектор режима), `KTalkClient._call`/`_classify` (диспетчер и
  диагностика), `OPERATION_PROFILES` (данные, не код — тестируются через поведение `_call`),
  нормализаторы (чистые функции `dict → DTO`), `PageCursor` (`SkipCursor`/`TokenCursor`),
  `AuthStatusService`.
- Интеграции: KTalk API — оба контура (session query-param, api-key заголовок), мокируются httpx.
- Trust boundaries: env → `Settings` (единственная точка чтения секретов) → `AuthContext` →
  `httpx.AsyncClient` (секрет закрепляется в транспорте один раз, не передаётся дальше как
  строка) → CLI/MCP output (`SecretRedactor` — последний рубеж).

**Edge cases / boundary conditions:**
- Обе переменные окружения заданы одновременно — приоритет ключа, `sessionToken` не появляется ни
  в одном исходящем запросе (не только в первом).
- 403 на операции без `required_scope` в session-режиме — не путать с scope-диагнозом api-key.
- `access-info` возвращает 403 — должен трактоваться как «ключ жив», не как «ключ мёртв» (это
  инверсия интуиции: обычно 403 воспринимают как более серьёзную ошибку, чем 401).
- Пустая последняя страница `skip`-пагинации (0 записей) против «короче `top`, но не пустой» —
  оба случая обязаны останавливать итератор.
- `nextPageToken: null` явно в JSON против отсутствующего поля вовсе — оба варианта эквивалентны
  «последняя страница».
- Дообогащение участников: `get_recording` и `get_conference` возвращают частично пересекающиеся,
  частично разные множества (не строгое подмножество друг друга) — дедуп по ключу участника, не по
  позиции в массиве.
- Анонимный участник без `userInfo` не должен ломать дедуп-ключ (использовать `anonymousId` как
  fallback).
- `qualityName` с пробелом и без — оба должны давать одинаковый корректно закодированный URL.
- Ошибка сети/таймаут при `auth_status` — не должна маскироваться под «ключ мёртв» (это другой
  класс отказа, требует отдельного сообщения, не `alive=false`).

**Test-pyramid рекомендация:**

| AC group | Уровень | Обоснование |
|---|---|---|
| FR-1, FR-2, FR-3, NFR-2 (селектор режима) | unit | чистая функция от 4 комбинаций env, без сети |
| FR-6 AC3, диспетчер `_call`/`OperationNotAvailableError` | unit | таблица профиля — данные, не сеть |
| FR-5 (диагностика), карта scope→сообщение | unit | классификатор — чистая функция от (код, режим, scope), мок ответа httpx |
| FR-9/FR-14 (пагинация, оба курсора) | unit + integration | нормализаторы курсора — unit на фикстурах; `iter_pages` end-to-end на мок-сервере с несколькими страницами — integration |
| FR-7 (скачивание, квотирование, потоковая передача) | unit (URL) + integration (поток без буферизации целиком) |
| FR-8 (дообогащение участников, дедуп, флаг `incomplete`) | unit на фикстурах с пересекающимися/анонимными участниками |
| FR-11 (`auth_status`, все 4 сценария деградации таблицы выше) | unit — каждый сценарий детерминирован кодом ответа мок-сервера |
| FR-15 (сверка id перед первым api-key sync) | integration — требует двух наборов фикстур (session-style, api-key-style) и реальной функции сравнения множеств |
| NFR-5 (секрет не в выводе) | integration — прогон представительных сценариев ошибок через реальный CLI-вывод (stdout/stderr, включая `--json`), поиск подстроки секрета |
| Ручные AC (боевой домен, помечены в требовании явно) | вне пирамиды QA-author — не автоматизируются до перевыпуска ключа, фиксируются как ручной чеклист |
