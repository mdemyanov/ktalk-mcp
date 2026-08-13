# ktalk-mcp

Пакет с двумя командами: MCP-сервер для доступа к записям Контур.Толк (KTalk)
и CLI `ktalk` — операционный реестр записей на SQLite.

## Stack
- Python 3.12+, fastmcp, httpx, pydantic-settings, stdlib sqlite3 + argparse

## Entry points
- `ktalk-mcp = ktalk_mcp.server:main` — MCP-сервер (контент: транскрипты, саммари)
- `ktalk = ktalk_mcp.cli:main` — CLI реестра (механика: sync/дедуп/статусы/экспорт)

## Commands
- `uv run ktalk-mcp` — запуск MCP-сервера
- `uv run ktalk <команда>` — CLI реестра (`sync`, `dashboard`, `list`, `show`,
  `mark-processing/done/partial/skipped`, `set-vault-id`, `export`, `migrate`)
- `uv run pytest` — тесты
- `uv run pytest tests/test_formatters.py -v` — тесты форматтеров
- `uv run ruff check .` — линтинг
- `uv run ruff check . --fix` — автоисправление
- `bash scripts/check.sh --fast` — гейты контура (тот же прогон, что на pre-commit)

## Architecture
Один пакет `ktalk_mcp`, общие `client.py`/`config.py` для MCP и CLI:
- `server.py` — MCP tools (5 штук), entry point
- `cli.py` — CLI: argparse-подкоманды, вывод (`--json` для машинного чтения)
- `registry.py` — SQLite-слой: схема (WAL), CRUD, дедуп, экспирация, миграция
  из markdown, рендер markdown-зеркала, мапперы API → строки
- `client.py` — KTalkClient, async httpx обёртка над KTalk API
- `formatters.py` — JSON → markdown конвертеры для каждого типа ответа
- `config.py` — Settings из env (KTALK_BASE_URL, KTALK_SESSION_TOKEN);
  `resolve_db_path` (KTALK_REGISTRY_DB / `--db` / дефолт `95_TRANSCRIPTS/.registry.db`)

## API Reference
- OpenAPI спецификация (справочник, есть расхождения): `talk.public.api-api-2.json`
- Base URL: https://your-domain.ktalk.ru
- Auth: query parameter `sessionToken={token}`
- Список записей: `GET /api/recordings` (поле `recordings[]`, ID в `id`)
- Детали записи: `GET /api/recordings/{id}`
- Транскрипт: `GET /api/recordings/{id}/transcript`
- Саммари (v2): `GET /api/recordings/v2/{id}/summary`
- Саммари по типу: `GET /api/recordings/{id}/summary/{type}`

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
  `30-requirements/` — требования и AC; `40-architecture/` — спеки и контракты.
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
