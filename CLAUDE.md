# ktalk-mcp

Пакет с двумя командами: MCP-сервер для доступа к записям Контур.Толк (KTalk)
и CLI `ktalk` — операционный реестр записей на SQLite.

## Стиль (безусловное правило)
Писать сухо и сжато — в ответах, коммитах, статьях `content/`, докстрингах.
Вывод, потом обоснование; без преамбул, повторов и похвалы. Нет факта — так и
сказать. Правило действует всегда и приоритетнее привычки к развёрнутости.

## Stack
- Python 3.12+, fastmcp, httpx, pydantic-settings, stdlib sqlite3 + argparse

## Entry points
- `ktalk-mcp = ktalk_mcp.server:main` — MCP-сервер (контент: транскрипты, саммари)
- `ktalk = ktalk_mcp.cli:main` — CLI реестра (механика: sync/дедуп/статусы/экспорт)

## Commands
- `uv run ktalk-mcp` — запуск MCP-сервера
- `uv run ktalk <команда>` — CLI реестра (`sync` [`--dry-run`], `auth-status`, `dashboard`,
  `list`, `show`, `mark-processing/done/partial/skipped`, `set-vault-id`, `export`, `migrate`)
  плюс планирование: `create-meeting-preview`, `create-meeting-confirm` (только TTY)
- `uv run pytest` — тесты
- `uv run pytest tests/test_formatters.py -v` — тесты форматтеров
- `uv run ruff check .` — линтинг
- `uv run ruff check . --fix` — автоисправление
- `bash scripts/check.sh --fast` — гейты контура (тот же прогон, что на pre-commit)

## Architecture
Один пакет `ktalk_mcp`, общие `client.py`/`config.py` для MCP и CLI:
- `server.py` — bootstrap FastMCP + `ktalk_auth_status`, entry point
- `tools_recordings.py` / `tools_meetings.py` / `tools_rooms.py` / `tools_scheduling.py` —
  MCP tools (13 штук). Мутирующего инструмента нет: планирование отдаёт только предпросмотр
- `rooms.py` / `calendar_reader.py` — чтение комнаты; чтение календаря с клиентской нарезкой
  окна (сервер ограничивает запрос 7 днями, потолок сегмента — 100 элементов, `skip` не работает)
- `meeting_body.py` / `confirmation.py` / `meeting_scheduling.py` / `cli_meeting.py` —
  пишущая операция (ADR-005): allow-list компоновщик тела, токен подтверждения, POST, CLI
- `contour_diagnostics.py` — корреляционная диагностика недокументированного контура (ADR-004)
- `cli.py` — CLI: argparse-подкоманды, вывод (`--json` для машинного чтения);
  `_REGISTRY_FREE_COMMANDS` — команды, не открывающие БД (`auth-status`, планирование)
- `cli_sync.py` — команды `sync` (вкл. `--dry-run`) и `auth-status`
- `registry.py` — SQLite-слой: схема (WAL), CRUD, дедуп, экспирация, миграция
  из markdown, рендер markdown-зеркала, мапперы API → строки
- `client.py` — KTalkClient, async httpx обёртка; единая точка диспетчеризации
- `auth.py` — таблица `OPERATION_PROFILES` (операция × режим → путь + scope + нормализатор),
  `AuthContext`, нормализаторы ответов, квотирование path-параметров
- `pagination.py` — единый итератор страниц + клиентское окно дат (`clip_to_window`)
- `enrichment.py` / `download.py` / `reconciliation.py` — дообогащение участников,
  потоковое скачивание, сверка идентификаторов перед первым api-key sync
- `formatters.py` — JSON → markdown конвертеры для каждого типа ответа
- `config.py` — Settings из env; `resolve_db_path`
  (KTALK_REGISTRY_DB / `--db` / дефолт `95_TRANSCRIPTS/.registry.db`)

## API Reference
- OpenAPI спецификация (справочник, **есть расхождения с реальностью**): `talk.public.api-api-2.json`
- Base URL: https://your-domain.ktalk.ru
- **Два режима авторизации** (решение — [ADR-003](content/00-project/adr/ADR-003-auth-modes.md)):
  `KTALK_PERSONAL_API_KEY` → заголовок `X-Auth-Token`; иначе `KTALK_SESSION_TOKEN` →
  query `sessionToken=`. Ключ побеждает; при обоих заданных session-токен не читается.
- **Набор путей зависит от режима** — интеграторский контур (`/api/Domain/*`, `/api/Recordings/*`,
  `/api/ConferenceReports/*`) отдаёт 401/403 по сессии, поэтому пути живут в таблице профилей
  `auth.py`, а не хардкодом в методах.
- Session-контур: `GET /api/recordings`, `/api/recordings/{id}`, `/api/conferencesHistory/{key}`
- Общее для обоих: `/api/recordings/{key}/transcript`, `/api/recordings/v2/{key}/summary`,
  `/api/recordings/{key}/summary/{type}`

### Поведение API, проверенное эмпирически (спеке здесь верить нельзя)
- `top` максимум **100**, не 1000: `400 «The field Top must be between 1 and 100»`.
- `nextPageToken` во внутреннем контуре **не существует** — пагинация только через `skip`.
- `startFrom`/`startTo` **игнорируются**: окно дат обеспечивает клиент (`clip_to_window`),
  обход прекращается на первой странице за порогом. Выдача отсортирована от новых к старым.
- `maxParticipantCount` в списке имеет максимум 10 и дефолт 6 — полный состав участников
  берётся дообогащением по каждой записи, а не из списка.
- Чат требует необъявленный в спеке параметр `channel` (рабочее значение `general`).
- **401 ≠ 403**: 401 — ключ/токен невалиден, 403 — валиден, но не хватает scope. Тело 403
  обычно пустое, диагностика строится на коде ответа и требуемом scope операции.

## Conventions
- Async everywhere (httpx, fastmcp)
- Каждый MCP tool принимает параметр `format`: "raw" (JSON as-is) или "markdown" (human-readable)
- `ktalk_get_transcript` поддерживает чанкинг: `chunk` (0=авто, 1+=номер чанка), `chunk_size` (символов, по умолчанию 30000)
- Ошибки API → человекочитаемые сообщения на русском
- Имена пользователей: `surname firstname`, fallback: `login` → `anonymousName` → "Неизвестный"
- Длительность: секунды → "X ч Y мин" или "X мин"

## CLI / реестр (registry)
- **SQLite — операционный source of truth**; `registry.md` в vault — генерируемое
  read-only зеркало (`ktalk export`), не редактировать руками.
- Статусы: `new → done|skipped|partial`, `partial → done`. Экспирация: записи
  `new` строго старше N дней (по умолчанию 7) → `skipped` при `sync`.
- Конкурентность: WAL + `busy_timeout=5000`, транзакция на операцию —
  параллельные `mark-*` из фоновых агентов безопасны.
- `--json` у всех команд печатает валидный JSON в stdout; ошибки — в stderr с
  ненулевым кодом возврата (навык/агент парсят stdout).
- Путь к БД бинарный → gitignore в vault (`.registry.db`, `-wal`, `-shm`).
- `ktalk migrate <vault>` — разовый импорт из markdown-реестров; парсер
  устойчив к 7/8-колоночным архивам и `|` внутри ячеек.

## Документарный контур (плагин nauta)
Решения живут в `content/`, не в этом файле и не в планах `docs/superpowers/`
(они остаются как есть, ретроспективно не переносятся). Решение принято —
пиши ADR; описываешь «что должно работать» — пиши требование.
- `content/00-project/` — roadmap и ADR; `10-domain/` — исследования;
  `30-requirements/` — требования и AC; `40-architecture/` — спеки и контракты;
  `60-implementation/` — заметки Dev о том, где реализация разошлась со спекой и почему.
- Каждая статья (кроме `_index.md`) обязана нести `properties: - name: Тип контента`
  в object-нотации и быть достижимой по ссылке из `_index.md` — иначе гейт даёт
  error (нет типа) или warning (сирота).
- ADR длиннее 150 строк не проходит: детализация выносится в companion-спеку
  `content/40-architecture/<stem>-spec.md`.
- Роли вызываются как `/nauta:pm decompose <фича>`, дальше `/nauta:ba`, `/nauta:sa`,
  `/nauta:dev`, `/nauta:qa`. PM декомпозирует, но не пишет код.

## Гейты (pre-commit)
`core.hooksPath=.githooks` → `scripts/check.sh --fast`. Требует `uv` в PATH.
- Пороги — в `.nauta-gates.yaml`, откалиброваны замером этого репозитория;
  обоснование и правило пересмотра: `content/40-architecture/ADR-001-nauta-contour-spec.md`.
- `src/ktalk_mcp/registry.py` заморожен грандфазером на 562 строках: рост даёт
  error. Снимается расщеплением класса `Registry`, не поднятием потолка.
- `scripts/` и `.githooks/` — payload плагина, приезжает через `/nauta:sync-scripts`
  и отслеживается по sha256 в `.nauta-scripts-basis.yaml`. Правка руками превращает
  файл в конфликт и он перестаёт обновляться; нужна своя версия — путь в `skip:`.
- Обход разовый: `git commit --no-verify`. Отключить: `git config --unset core.hooksPath`.

## Gramax (плагин gramax)
`content/` — валидный Gramax-каталог, `content/.doc-root.yaml` принадлежит Gramax,
конфигурацию гейтов туда не класть (для неё есть `.nauta-gates.yaml`).
- Новое значение свойства сначала объявляется в `.doc-root.yaml`, потом
  используется в статье; `filterProperties` правится синхронно с `properties`.
- В `_index.md` не бывает `properties` — раздел не имеет своего типа и статуса.
- Диаграммы — скиллом `mermaid`: отдельный `.mermaid`-файл рядом со статьёй,
  не inline-блок.
