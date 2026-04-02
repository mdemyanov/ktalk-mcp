# ktalk-mcp

MCP сервер для доступа к записям [Контур.Толк](https://ktalk.ru) (KTalk) из Claude Code.

Предоставляет доступ к:
- Списку записей конференций
- Деталям записи
- Транскриптам (распознанная речь по спикерам)
- Саммари и протоколам встреч

## Установка

Требуется Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mdemyanov/ktalk-mcp.git
cd ktalk-mcp
uv sync
```

## Получение session token

KTalk использует session token для авторизации API-запросов. Токен передаётся как query parameter.

1. Откройте https://your-domain.ktalk.ru в браузере
2. Войдите в свой аккаунт
3. Откройте DevTools: нажмите `F12` (или `Cmd+Option+I` на Mac)
4. Перейдите во вкладку **Application** → **Cookies** → `https://your-domain.ktalk.ru`
5. Найдите cookie с именем `sessionToken`
6. Скопируйте его значение

> **Важно:** session token имеет ограниченный срок жизни. Если MCP tool возвращает ошибку авторизации, получите новый токен по инструкции выше.

## Подключение к Claude Code

Добавьте в файл `~/.claude/.mcp.json` (глобально) или `.mcp.json` (в проекте):

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ktalk-mcp", "ktalk-mcp"],
      "env": {
        "KTALK_SESSION_TOKEN": "ваш_session_token"
      }
    }
  }
}
```

Замените `/path/to/ktalk-mcp` на реальный путь к директории проекта.

### Альтернативная конфигурация

Вместо `.mcp.json` можно задать переменную окружения или создать файл `.env` в корне проекта:

```bash
export KTALK_SESSION_TOKEN="ваш_session_token"

# Опционально (по умолчанию https://your-domain.ktalk.ru)
export KTALK_BASE_URL="https://your-domain.ktalk.ru"
```

## Доступные MCP Tools

### `ktalk_list_recordings`

Список записей конференций.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `query` | str | — | Поиск по названию, комнате, автору |
| `start_from` | str | — | Начало периода (ISO 8601) |
| `start_to` | str | — | Конец периода |
| `top` | int | 30 | Количество записей (1–1000) |
| `order` | str | byTimeNewFirst | Сортировка |
| `page_token` | str | — | Токен пагинации |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_recording`

Детали одной записи — автор, дата, длительность, список участников.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ (ID) записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_transcript`

Транскрипт записи — распознанная речь по спикерам с таймкодами.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ (ID) записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_summary`

Полное саммари записи (краткое резюме + протокол).

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ (ID) записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_summary_by_type`

Саммари конкретного типа.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ (ID) записи |
| `summary_type` | str | — | `shortSummary` / `protocol` |
| `format` | str | markdown | raw / markdown |

## API

Сервер работает с KTalk Web API. Авторизация — через `sessionToken` query parameter.

| Эндпоинт | Описание |
|----------|----------|
| `GET /api/recordings` | Список записей |
| `GET /api/recordings/{id}` | Детали записи |
| `GET /api/recordings/{id}/transcript` | Транскрипт |
| `GET /api/recordings/v2/{id}/summary` | Полное саммари (v2) |
| `GET /api/recordings/{id}/summary/{type}` | Саммари по типу |

> OpenAPI спецификация `talk.public.api-api-2.json` включена как справочник, но содержит расхождения с реальным API (пути, формат авторизации, структура ответов).

## Разработка

```bash
# Запуск тестов
uv run pytest -v

# Линтинг
uv run ruff check .

# Автоисправление
uv run ruff check . --fix

# Локальный запуск сервера
KTALK_SESSION_TOKEN=... uv run ktalk-mcp
```

## Лицензия

MIT
