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
