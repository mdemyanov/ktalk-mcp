---
title: Разбор mainpart/ktalk-mcp
properties:
  - name: Тип контента
    value: [Исследование]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# Разбор mainpart/ktalk-mcp

**Дата:** 2026-08-13
**Исследователь:** researcher-agent
**Запрос PM/BA:** RES-002 — разобрать чужой публичный MCP-сервер для Контур.Толка
(mainpart/ktalk-mcp) как источник контекста для расширения нашего набора инструментов:
именование, сигнатуры, доменная модель «Комната → Встреча → Запись → Чат», механика
авторизации через Session-токен.
**Глубина:** standard (~2 ч, чтение исходников через raw.githubusercontent.com)

## TL;DR

У mainpart 9 инструментов вместо наших 5, организованных вокруг четырёх сущностей
(Room, Meeting, Recording, Chat), а не только записей. Ключевая находка для доменной
модели: сущности «Встреча» и «Запись» — отдельные объекты API с разными идентификаторами
(`conference_key` и `recording_id`), связанные полем `conferenceKey` внутри ответа
`/api/recordings/{id}`; полный список участников оба инструмента (`get_meeting`,
`get_recording`) берут из одного и того же ответа `GET /api/conferencesHistory/{conference_key}`
без дополнительных запросов. Авторизация — заголовок `Authorization: Session <token>`
(не query-параметр, как у нас), токен живёт в файле `~/.config/ktalk-mcp/token` с правами
0600, обновляется вручную через букмарклет или через сторонний `chromedb` CLI. У
mainpart нет чанкинга длинных ответов и нет саммари (`summary`) вообще — это наши
уникальные возможности. Лицензия не указана (`license: null` в метаданных GitHub),
репозиторий живой: последний коммит 31 июля 2026.

## Ключевые находки

1. У mainpart 9 инструментов без общего префикса (`create_room`, `create_meeting`,
   `list_meetings`, `get_meeting`, `list_recordings`, `get_recording`,
   `download_recording`, `get_chat_messages`, `auth_status`) — [primary, код,
   server.py], [established]. Префикс `ktalk_` был добавлен коммитом «Prefix all tools
   with ktalk_» (2026-07-20) и снят коммитом «Drop the ktalk_ prefix from all nine tool
   names» (2026-07-31) — [primary, история коммитов GitHub], [established].
2. Авторизация — заголовок `Authorization: Session <token>`, не query-параметр
   `sessionToken` — [primary, код client.py: `return {"Authorization": f"Session {token}"}`],
   [established]. Это отличается от механизма нашего проекта.
3. Базовый URL строится как `f"{self.space_url}/api"` — все пути в README
   (`/api/rooms/{slug}`, `/api/conferencesHistory/{conference_key}` и т.д.) подтверждены
   кодом, префикс `/api` не хардкожен как домен, а добавляется к переданному
   `KTALK_SPACE_URL` — [primary, код client.py], [established].
4. `get_meeting` и `get_recording` (для `has_chat`) оба обращаются к одному и тому же
   эндпоинту `GET /conferencesHistory/{conference_key}` и берут полный список участников
   из поля `artifacts.participants` этого ответа — отдельного эндпоинта «список
   участников» нет — [primary, код server.py, функции `get_meeting`/`get_recording`],
   [established].
5. `download_recording` не отдаёт файл в base64 и не возвращает ссылку — он скачивает
   файл потоково (`aiter_bytes()`, запись чанками) на диск по пути `target_path`,
   таймаут на скачивание отдельный: `httpx.Timeout(30.0, read=600.0)`. Явных лимитов на
   размер файла или прогресс-репортинга нет — [primary, код client.py/server.py],
   [established].
6. Выбор качества видео в `download_recording` — перебор массива `qualities[]` по
   полям `height`/`width`/`quality` (числовое сравнение, максимум побеждает), с
   фолбэком на `detail.fileUrl`/`detail.downloadUrl`, если `qualities` нет —
   [primary, код server.py, функция `_pick_quality_url`], [established].
7. `auth_status` не делает ни одного сетевого запроса — только читает локальный
   token_status() из файла токена и добавляет `space_url`/`receiver_port` —
   [primary, код server.py], [established]. Формулировка из README «проверяет токен» в
   этом смысле неточна: проверка чисто локальная (наличие файла + разбор `expiresAt`),
   без обращения к API за подтверждением валидности.
8. Токен обновляется двумя механизмами: (а) букмарклет, который в браузере читает
   `localStorage.session`, пытается перевыпустить токен через `/api/authorize/session` и
   POST'ит результат на `http://127.0.0.1:8765/ktalk-token` локальному HTTP-приёмнику
   (`receiver.py`) с проверкой `Origin` против `KTALK_SPACE_URL`; (б) внешняя утилита
   `chromedb` (не часть репозитория mainpart, отдельный CLI), которая читает
   незашифрованный `localStorage` из файлов профиля Chrome напрямую, без запуска
   браузера — [primary, код receiver.py + secondary, README], [established для (а),
   established для факта существования (б), но сам код `chromedb` вне репозитория и не
   проверялся].
9. У mainpart нет чанкинга длинных ответов и нет инструментов саммари — это то, что
   есть у нас и чего нет у них — [подтверждено отсутствием: полный список из 9
   инструментов не содержит ничего похожего на `summary` или `chunk`], [established].
10. Лицензия не указана нигде: ни в `pyproject.toml` (поле `license` отсутствует), ни
    отдельным файлом LICENSE, ни в метаданных GitHub API (`license: null`) —
    [primary, pyproject.toml + GitHub API], [established].

## Подтемы

### Полный список инструментов, параметры, возврат

Стек: Python ≥3.11, `fastmcp>=3.4`, `httpx` (из `pyproject.toml`, `src/ktalk_mcp/client.py`).
Все функции — `async def ... -> str`, возвращают JSON-строку (`json.dumps(...,
ensure_ascii=False)`), а не структурированный объект MCP. Ошибки — тоже JSON-строка с
полем `error` (`not_authenticated`, `api_error`, `bad_request`, `no_file_url`,
`write_failed` и т.п.).

**`create_room(title: str, slug: str | None = None, allow_anonymous: bool = False,
audio_policy: Literal["none","muted","disabled"] = "none", video_policy: ... = "none",
screen_share_policy: ... = "none", enable_lobby: bool = False, description: str = "") -> str`**
Docstring: «Create (or overwrite) a Talk room; returns {url, room_name, conference_id,
title, room}». HTTP: `PUT /rooms/{room_name}` с JSON-телом (title, enableLobby,
enableSessionHalls, audioPolicy, videoPolicy, screenSharePolicy, maxVideoQuality, и
условно anonymousAccessExpirationDate/description). [primary, код server.py]

**`create_meeting(subject: str, start: str, end: str, room_name: str | None = None,
timezone: str = "GMT+3", required_attendees: list | None = None, enable_sip: bool = True,
pin_code: str | None = None, enable_auto_recording: bool = False, is_recurring: bool =
False, description: str = "") -> str`**
HTTP: `POST /calendar` с JSON-телом. [primary, код server.py]

**`list_meetings(limit: PageLimit = 30, offset: PageOffset = 0, query: str | None = None,
start: str | None = None, end: str | None = None, fields: list[MeetingField] | None =
None, participant_fields: list[ParticipantField] | None = None) -> str`**
Где `PageLimit = Annotated[int, Field(ge=1, le=200)]`, `PageOffset = Annotated[int,
Field(ge=0)]`. HTTP: `GET /conferencesHistory/` с query-параметрами `skip` (=offset),
`top` (=limit), опционально `query`, `fromDate`/`toDate` (локальный ISO-8601 → UTC через
внутренний `_utc_bound()`, `start` без времени суток = начало дня, `end` = конец дня),
всегда `includeUnfinished=true`. Возврат: `{meetings: [...], count, has_more,
next_offset}`. [primary, код server.py]

**`get_meeting(conference_key: str, fields: list[MeetingField] | None = None,
participant_fields: list[ParticipantField] | None = None) -> str`**
HTTP: `GET /conferencesHistory/{conference_key}` — единственный запрос, полный список
участников берётся из `artifacts.participants` этого же ответа. Возможные поля
(`MeetingField`): `conference_key, room_name, title, start, end, participants_count,
participants, invited_participants, has_chat, recording_ids, session_halls_artifacts`.
[primary, код server.py]

**`list_recordings(limit: PageLimit = 30, offset: PageOffset = 0, query: str | None =
None, fields: list[RecordingField] | None = None, participant_fields:
list[ParticipantField] | None = None) -> str`**
HTTP: `GET /recordings` с `skip`, `top`, опционально `query`. Без окна по датам (в
отличие от `list_meetings`). Возврат: `{recordings: [...], count, has_more,
next_offset}`. [primary, код server.py]

**`get_recording(recording_id: str, fields: list[RecordingField] | None = None,
participant_fields: list[ParticipantField] | None = None) -> str`**
HTTP: `GET /recordings/{recording_id}`; если запрошено поле `has_chat` — дополнительно
`GET /conferencesHistory/{conf_key}` (best-effort, `conf_key` = `detail["conferenceKey"]`
из первого ответа), чтобы проверить непустой `_chat_channels(hist)`. Поля
(`RecordingField`): `recording_id, title, description, conference_key, download_url,
created_date, created_by, duration, participants_count, participants, status, has_audio,
has_chat, comments_count, frame_size, preview_image, qualities`. `download_url` строится
через `_pick_quality_url(detail)` — то же, что использует `download_recording`.
[primary, код server.py]

**`download_recording(recording_id: str, target_path: str) -> str`**
Отдаёт файл ТОЛЬКО на диск (не base64, не ссылка в ответе инструмента): 1) `GET
/recordings/{recording_id}` за метаданными, 2) выбор `fileUrl` из `qualities[]` по
максимуму `height`/`width`/`quality` с фолбэком на `fileUrl`/`downloadUrl` верхнего
уровня, 3) потоковое скачивание (`client.stream(...).aiter_bytes()`, запись чанками в
файл) с отдельным таймаутом на чтение 600 с. `target_path` — если директория (или строка
оканчивается на `os.sep`) — имя файла берётся из URL (`os.path.basename` пути, дефолт
`{recording_id}.mp4`, добавляется расширение `.mp4`, если его нет); если конкретный путь
— пишется туда, родительские директории создаются. Явных ограничений на размер файла и
прогресс-репортинга нет. Ошибки: `no_file_url` (нет ни `qualities`, ни fallback-полей),
`write_failed` (любой `OSError` при записи — права, диск заполнен и т.п.), плюс общие
`not_authenticated`/`api_error`. Возврат при успехе: `{ok: true, path, bytes, source}`.
[primary, код server.py + client.py]

**`get_chat_messages(conference_key: str | None = None, recording_id: str | None = None,
channel: str | None = None, limit: Annotated[int, Field(ge=1)] = 2000, save_path: str |
None = None) -> str`**
Если дан только `recording_id` — сначала `GET /recordings/{recording_id}` за
`conferenceKey`. Список каналов чата берётся из `GET
/conferencesHistory/{conf_key}` → поля `artifacts.chatChannelHasMessages` (словарь
id-канала → bool) плюс `sessionHallsArtifacts` для breakout-комнат. Сообщения каждого
канала — отдельный запрос `GET /conferencesHistory/{conf_key}/chat/messages?channel=
{ch}&limit={limit}`. Сообщения мержатся по `id` (дедуп через словарь `by_id`), сортируются
по `created`, каналы, вернувшие ровно `limit` сообщений, попадают в `truncated_channels`
(признак, что не всё скачано). С `save_path` пишет `.json` и `.txt` файлы вместо
возврата тела в ответе инструмента. [primary, код server.py]

**`auth_status() -> str`**
Без параметров, без сетевых запросов — читает `client.token_status()` (локальный разбор
файла токена: есть ли файл, распарсен ли `expiresAt`) и добавляет `space_url`,
`receiver_port`. [primary, код server.py]

### HTTP-эндпоинты Толка — заявлено vs подтверждено кодом

| Эндпоинт из README | Подтверждено кодом | Где именно используется |
|---|---|---|
| `PUT /rooms/{room_name}` (в README как `/api/rooms/{slug}`) | да | `create_room` |
| `POST /calendar` | не упомянут явно в README, но есть в коде | `create_meeting` |
| `GET /conferencesHistory/` (список) | да | `list_meetings` |
| `GET /conferencesHistory/{conference_key}` | да | `get_meeting`, `get_recording` (has_chat), `get_chat_messages` (список каналов) |
| `GET /conferencesHistory/{key}/chat/messages` (в README как `.../chat`) | да, но фактический путь — `/chat/messages`, не просто `/chat`, как заявлено в README | `get_chat_messages` |
| `GET /recordings` (список) | да | `list_recordings` |
| `GET /recordings/{recording_id}` | да | `get_recording`, `download_recording`, `get_chat_messages` (резолв conference_key) |
| `GET /authorize/session` (в README как `/api/authorize/session`) | НЕ найден в исследованных модулях (`server.py`, `client.py`, `receiver.py`) — упоминается только в JS-коде букмарклета, который выполняется в браузере пользователя, а не в python-коде репозитория | букмарклет (браузер, вне python-кода) |

Все пути — относительно `base_url = f"{space_url}/api"`, то есть реальный HTTP-путь
всегда с префиксом `/api`, соответствует заявленному в README. [primary, код client.py]

### Доменная модель: Комната → Встреча → Запись → Чат

- **Room** (`create_room`) — идентифицируется `room_name`/`slug`. Ключ связи со
  «Встречей» — `room_name`, передаётся при создании meeting (`create_meeting(room_name=…)`).
- **Meeting** (`list_meetings`/`get_meeting`) — идентифицируется `conference_key`. Это
  ключ, который «Толк» присваивает конкретному прошедшему/идущему совещанию (записи в
  `conferencesHistory`). Одна Room может породить много Meeting (повторяющиеся встречи в
  одной комнате).
- **Recording** (`list_recordings`/`get_recording`/`download_recording`) —
  идентифицируется своим `recording_id`, ОТДЕЛЬНЫМ от `conference_key`. Связь Meeting →
  Recording идёт как `Meeting.recording_ids` (массив id записей на одной встрече, поле
  из `MeetingField`) и в обратную сторону — `Recording.conference_key` (поле
  `detail["conferenceKey"]` в ответе `/recordings/{id}`, доступно только через сам объект
  записи, не через `list_recordings` без явного запроса поля). То есть переход
  Recording → Meeting возможен только после `get_recording` с полем `conference_key`, а
  не из списка.
- **Chat** — не самостоятельная сущность с собственным id, а срез внутри Meeting:
  каналы чата (`artifacts.chatChannelHasMessages`) и сообщения живут на `conference_key`,
  не на `recording_id`. `get_chat_messages` умеет резолвить `recording_id → conference_key`
  автоматически (один дополнительный запрос), но обратного резолва (какая запись
  породила это сообщение чата) в инструментах нет.
- Важно: `has_chat` у Recording — вычисляемое поле (best-effort секундный запрос к
  `/conferencesHistory/{conf_key}`), не хранится на самой записи. [primary, код server.py]

Итог связки: **Room --room_name--> Meeting --conference_key--> Recording**, и
параллельно **Meeting --conference_key--> Chat**. `conference_key` — центральный ключ
почти всего домена, кроме привязки к комнате. [established, код]

### Авторизация — механика целиком

1. **Заголовок.** `Authorization: Session <token>` — подтверждено кодом (`client.py`:
   `return {"Authorization": f"Session {token}"}`), комментарий в коде: «the same header
   the Talk web app sends». Отличается от нашего механизма (`?sessionToken=` в query).
   [established]
2. **Хранение.** Файл `~/.config/ktalk-mcp/token` (дефолт; переопределяется
   `KTALK_TOKEN_FILE`), права `0600` на файл, `0700` на родительскую директорию —
   создаются функцией `ensure_token_file()` при старте. Формат содержимого — либо «сырой»
   токен (regex `^[A-Za-z0-9]{16,40}$`), либо JSON `{token, expiresAt}` — парсится
   `parse_token_blob()`. [established, код client.py]
3. **Порядок разрешения источника.** Единственный источник токена — файл. Переменной
   окружения для самого значения токена НЕТ (`KTALK_TOKEN_FILE` задаёт только путь к
   файлу, не значение). Токен в файл попадает либо руками (README предлагает вставить
   через DevTools Console), либо через локальный HTTP-приёмник (receiver.py), который
   слушает `127.0.0.1:{KTALK_RECEIVER_PORT, default 8765}` и по `POST /ktalk-token`
   перезаписывает файл. Аргумента командной строки для токена нет — `__main__.py`
   сводится к `from ktalk_mcp.server import main; main()`, без своего argparse/click.
   [established, код __main__.py + server.py + receiver.py]
4. **Букмарклет.** JS выполняется в браузере пользователя на странице Толка: читает
   `localStorage.session`, пытается перевыпустить токен на полный срок через
   `/api/authorize/session` (сам этот вызов — код на стороне браузера, вне python-репозитория,
   поэтому «подтверждено кодом» относится только к README-описанию, не к
   python-исходникам), затем POST'ит результат на `http://127.0.0.1:8765/ktalk-token`.
   Сам JS-текст букмарклета не найден ни в одном исследованном .py файле — вероятно,
   лежит в README как строка для перетаскивания в закладки; дословный текст
   README-секции с этим кодом извлечь через доступный интерфейс не удалось (см. раздел
   «Что не удалось выяснить»). [secondary, README, частично established]
5. **Приёмник токена (`receiver.py`).** Слушает `127.0.0.1`, порт из
   `KTALK_RECEIVER_PORT`. Эндпоинт — `POST /ktalk-token`, принимает либо голый токен по
   regex, либо JSON `{token, expiresAt}`. Проверяет заголовок `Origin` против ожидаемого
   значения, производного от `KTALK_SPACE_URL`; при несовпадении — HTTP 403. Комментарий
   в коде поясняет механизм мьютекса: «слушающий сокет одновременно служит мьютексом:
   какой бы инстанс ktalk-mcp ни занял порт первым, тот и владеет приёмником» — то есть
   при нескольких параллельных инстансах сервера приёмник запускает только первый.
   Токен записывается через `write_token_file()` (импортируется из `client.py`), с теми
   же правами `0600`. [established, код receiver.py]
6. **`chromedb` CLI.** НЕ часть репозитория mainpart — внешняя утилита. По README
   вызывается как `chromedb -ls -p "$PROFILE" | jq -r 'select(.storage_key=="https://
   <space>.ktalk.ru" and .script_key=="session") | .value.data.token'`, то есть читает
   значения `localStorage` напрямую из файлов профиля Chrome на диске (SQLite/LevelDB
   базы профиля), без запуска браузера. README формулирует: «localStorage не зашифрован,
   пароль или связка ключей не нужны». Это утверждение README, кодом mainpart не
   проверяется (сам `chromedb` — сторонний инструмент, его исходники не смотрели).
   [secondary, README], [established как факт цитаты, contested как техническое
   утверждение о шифровании — не проверено независимо]
7. **Маскирование в логах/ошибках.** Debug-лог запроса логирует метод, URL и
   query-параметры (`self.log.debug("%s %s params=%s", method, url, params)`), но НЕ
   логирует заголовки — значит, `Authorization` в лог не попадает. Классы исключений
   `KtalkAuthError`/`KtalkAPIError` несут `payload`/`message`, не включающие сырой токен
   (токен передаётся в заголовке, а не в URL/params, поэтому он структурно не может
   попасть даже в лог URL). Явного redact-механизма (маскирующего, например, `token[:4]
   + "…"`) в коде не обнаружено — токен просто нигде не сериализуется. [established, код
   client.py]

### Сравнение: наш проект (5 инструментов) vs mainpart (9 инструментов)

| Инструмент / возможность | У нас | У mainpart | Комментарий |
|---|---|---|---|
| Список записей | `ktalk_list_recordings` | `list_recordings` | у mainpart нет окна по датам для записей (есть только у `list_meetings`) |
| Детали записи | `ktalk_get_recording` | `get_recording` | у mainpart — выбор полей через `fields`/`participant_fields`, у нас (по CLAUDE.md) — фиксированный набор |
| Транскрипт | `ktalk_get_transcript` (+ чанкинг) | — | mainpart не имеет аналога вообще; чанкинг — наша уникальная возможность |
| Саммари | `ktalk_get_summary`, `ktalk_get_summary_by_type` | — | у mainpart саммари нет вообще |
| Скачивание видео | — | `download_recording` (поток на диск, авто-выбор качества) | у нас такого инструмента нет |
| Комнаты | — | `create_room` | у нас нет сущности «комната» |
| Встречи (calendar) | — | `create_meeting`, `list_meetings`, `get_meeting` | у нас нет сущности «встреча»/`conference_key` вообще |
| Чат встречи | — | `get_chat_messages` (мульти-канал, дедуп, экспорт в файл) | у нас нет доступа к чату |
| Статус авторизации | — | `auth_status` | у нас нет явного диагностического инструмента |
| Формат ответа raw/markdown | параметр `format` у каждого tool | не найдено — везде JSON-строка | архитектурное расхождение в подходе к выводу |
| Авторизация | query `?sessionToken=` | header `Authorization: Session <token>`, файл + receiver/chromedb | принципиально разные схемы получения и хранения токена |

## Что НЕ удалось выяснить

- **Дословный текст JS-букмарклета.** Инструмент WebFetch возвращает пересказ через
  промежуточную модель, а не гарантированно полный дословный raw-текст очень длинного
  README; сама JS-строка букмарклета (обычно длинная однострочная конструкция) не
  процитирована дословно ни в одном ответе. Известно по косвенным цитатам из README,
  что делает: читает `localStorage.session`, пытается перевыпустить токен через
  `/api/authorize/session`, POST на `127.0.0.1:8765/ktalk-token`.
- **Точный путь `/api/authorize/session`.** Заявлен в README и логике букмарклета
  (браузерный JS, не python), но в python-коде репозитория (`server.py`, `client.py`,
  `receiver.py`) обращения к этому пути НЕ найдено — значит, это переиздание токена
  делает сам браузер пользователя на странице Толка, а не MCP-сервер. Не удалось
  подтвердить сам факт существования этого эндпоинта на стороне API Толка независимо от
  README.
- **Исходники внешнего `chromedb` CLI.** Не входит в репозиторий mainpart, не
  исследовался; утверждение о нешифрованности `localStorage` Chrome не проверено
  независимо от формулировки README.
- **Содержимое `.env.example`, `.mcp.json.example`, `requirements.txt`, `.gitignore`.**
  Не запрашивались отдельно — не относятся напрямую к вопросам задачи, кроме уже
  подтверждённого списка переменных окружения (взят из README + `main()` в `server.py`,
  совпадают).
- **Число звёзд/issue репозитория контекст важности:** по GitHub API — 0 звёзд, 0
  открытых issues, поле `description` в метаданных пустое (хотя `pyproject.toml`
  содержит описание «MCP server for Kontur Talk…») — репозиторий выглядит как личный
  проект автора, не набравший внешней аудитории на момент исследования.

## Рекомендации для BA/SA

- BA: обрати внимание, что у mainpart нет параметра `format` (raw/markdown) — весь
  вывод плоский JSON-строкой; если наш проект сохраняет конвенцию `format`, для новых
  инструментов (сущность «встреча», скачивание записи) потребуется явное требование по
  формату вывода, а не заимствование конвенции mainpart вслепую.
- BA: `conference_key` у mainpart — это ключ *встречи* (Meeting), не записи; при
  формулировании требований к сущности «встреча» стоит явно развести идентификатор
  встречи и идентификатор записи (`recording_id`), это два разных пространства id.
- SA: доменная связка Room → Meeting → Recording → Chat завязана в основном на один
  универсальный эндпоинт `GET /conferencesHistory/{conference_key}`, который отдаёт и
  участников, и наличие чата, и список каналов чата одним ответом — при проектировании
  своей модели стоит явно решить, где у нас будет аналогичная точка консолидации (или
  будет несколько узкоспециализированных запросов).
- SA: `download_recording` у mainpart решает вопрос больших файлов простым потоковым
  сохранением на диск с увеличенным read-таймаутом (600 с) и без прогресс-репортинга —
  это минимально достаточное решение, но не единственное; при проектировании своего
  инструмента скачивания стоит явно решить вопрос ограничения размера и обратной связи
  о прогрессе, которого у mainpart нет.
- SA: авторизация через `Authorization`-заголовок с файлом токена и локальным
  HTTP-приёмником — рабочая, но требовательная к окружению схема (нужен доступ к
  localhost из браузера пользователя и права на запись `~/.config/`); если в рамках
  эпика personal-api-key нужно другое решение (например, честный API-ключ), эту схему
  стоит рассматривать как контрпример «как делать не обязательно», а не как образец.

## Источники

- [primary] [server.py](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/src/ktalk_mcp/server.py) — определение всех 9 MCP tools, доменные проекции (`_meeting_row`, `_recording_row`), enum'ы полей, `main()`
- [primary] [client.py](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/src/ktalk_mcp/client.py) — `KtalkClient`, построение base_url, заголовок авторизации, скачивание файлов, работа с токен-файлом, исключения
- [primary] [receiver.py](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/src/ktalk_mcp/receiver.py) — локальный HTTP-приёмник токена от букмарклета, проверка Origin, мьютекс-механизм
- [primary] [__main__.py](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/src/ktalk_mcp/__main__.py) — точка входа (минимальна, делегирует в server.py)
- [primary] [pyproject.toml](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/pyproject.toml) — стек, версия, entry point, отсутствие поля license
- [secondary] [README.md](https://raw.githubusercontent.com/mainpart/ktalk-mcp/HEAD/README.md) — описание букмarклета/chromedb, таблица инструментов, таблица переменных окружения (сверено с кодом, расхождение найдено в пути чата — README говорит `/chat`, код — `/chat/messages`)
- [primary] [GitHub repo tree](https://api.github.com/repos/mainpart/ktalk-mcp/git/trees/HEAD?recursive=1) — полный список файлов репозитория
- [primary] [GitHub repo metadata](https://api.github.com/repos/mainpart/ktalk-mcp) — license: null, pushed_at: 2026-07-31, 0 stars
- [secondary] [История коммитов](https://github.com/mainpart/ktalk-mcp/commits/main) — датировка последних изменений, факт переименования инструментов (снятие префикса `ktalk_`)
