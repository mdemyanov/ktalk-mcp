# ktalk-mcp

MCP сервер для доступа к записям Контур.Толк (KTalk).

## Stack
- Python 3.12+, fastmcp, httpx, pydantic-settings

## Commands
- `uv run ktalk-mcp` — запуск сервера
- `uv run pytest` — тесты
- `uv run pytest tests/test_formatters.py -v` — тесты форматтеров
- `uv run ruff check .` — линтинг
- `uv run ruff check . --fix` — автоисправление

## Architecture
Flat MCP server, 4 модуля:
- `server.py` — MCP tools (5 штук), entry point
- `client.py` — KTalkClient, async httpx обёртка над KTalk API
- `formatters.py` — JSON → markdown конвертеры для каждого типа ответа
- `config.py` — Settings из env (KTALK_BASE_URL, KTALK_SESSION_TOKEN)

## API Reference
- OpenAPI спецификация: `talk.public.api-api-2.json`
- Base URL: https://naumen.ktalk.ru
- Auth: заголовок `Authorization: Session {token}`

## Conventions
- Async everywhere (httpx, fastmcp)
- Каждый MCP tool принимает параметр `format`: "raw" (JSON as-is) или "markdown" (human-readable)
- Ошибки API → человекочитаемые сообщения на русском
- Имена пользователей: `surname firstname`, fallback: `login` → `anonymousName` → "Неизвестный"
- Длительность: секунды → "X ч Y мин" или "X мин"
