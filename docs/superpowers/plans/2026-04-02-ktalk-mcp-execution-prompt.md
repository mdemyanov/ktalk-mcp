# Промт для запуска реализации KTalk MCP Server

Скопируй этот промт в новый диалог Claude Code (в директории `/Users/mdemyanov/Devel/ktalk-mcp/`):

---

## Промт

Реализуй KTalk MCP Server по плану из `docs/superpowers/plans/2026-04-02-ktalk-mcp.md`.

Используй /subagent-driven-development для параллельного выполнения задач.

### Контекст

Мы создаём локальный MCP сервер на Python (fastmcp + httpx + pydantic-settings), который даёт Claude Code доступ к записям Контур.Толк:
- Список записей (`/api/Domain/recordings/v2`)
- Детали записи (`/api/Domain/recordings/{key}`)
- Транскрипт (`/api/recordings/{key}/transcript`)
- Саммари (`/api/recordings/v2/{key}/summary`)
- Саммари по типу (`/api/recordings/{key}/summary/{type}`)

Авторизация: `Authorization: Session {token}`, токен из env `KTALK_SESSION_TOKEN`.
Два формата вывода: `raw` (JSON as-is) и `markdown` (человекочитаемый).

### Что уже есть

- `talk.public.api-api-2.json` — OpenAPI 3.0.4 спецификация KTalk API (справочник)
- `docs/superpowers/specs/2026-04-02-ktalk-mcp-design.md` — design spec
- `docs/superpowers/plans/2026-04-02-ktalk-mcp.md` — план реализации с 11 задачами

### Порядок выполнения

План содержит 11 задач (Task 1–11). Каждая задача включает пошаговые шаги с полным кодом, командами для запуска и ожидаемым выводом. Выполняй строго по плану, TDD: сначала тест → проверь что падает → реализация → проверь что проходит → коммит.

### Ключевые зависимости между задачами

```
Task 1 (scaffolding) → Task 2 (config) → Task 3 (client)
Task 1 → Task 4 (helpers) → Task 5, 6, 7, 8 (formatters, параллельно)
Task 3 + Task 8 → Task 9 (server)
Task 9 → Task 10 (README)
Task 10 → Task 11 (verification)
```

Задачи 5, 6, 7, 8 можно выполнять параллельно после задачи 4.

### Критические файлы

| Файл | Что делает |
|------|-----------|
| `pyproject.toml` | Пакет, зависимости, скрипты |
| `src/ktalk_mcp/config.py` | Settings (KTALK_BASE_URL, KTALK_SESSION_TOKEN) |
| `src/ktalk_mcp/client.py` | KTalkClient — async httpx, 5 методов, ошибки 401/404 |
| `src/ktalk_mcp/formatters.py` | 6 функций конвертации JSON → markdown |
| `src/ktalk_mcp/server.py` | FastMCP сервер, 5 tools, entry point |
| `tests/test_formatters.py` | ~20 тестов для всех форматтеров |
| `tests/test_client.py` | ~8 тестов с mock httpx |

### Верификация после завершения

```bash
uv run pytest -v                    # все тесты проходят
uv run ruff check .                 # нет ошибок линтинга
KTALK_SESSION_TOKEN=test uv run ktalk-mcp  # сервер стартует
```

Затем добавь в `~/.claude/.mcp.json` и проверь вызов `ktalk_list_recordings` с реальным токеном.
