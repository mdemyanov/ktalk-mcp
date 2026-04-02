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
git clone <repository-url>
cd ktalk-mcp
uv sync
```

## Получение session token

У KTalk нет отдельного API-ключа для пользователей. Для авторизации используется session token из cookies браузера.

1. Откройте https://naumen.ktalk.ru в браузере
2. Войдите в свой аккаунт
3. Откройте DevTools: нажмите `F12` (или `Cmd+Option+I` на Mac)
4. Перейдите во вкладку **Application** → **Cookies** → `https://naumen.ktalk.ru`
5. Найдите cookie с именем `sessionToken`
6. Скопируйте его значение

## Конфигурация

Установите переменную окружения или создайте файл `.env`:

```bash
# Обязательно
export KTALK_SESSION_TOKEN="ваш_session_token"

# Опционально (по умолчанию https://naumen.ktalk.ru)
export KTALK_BASE_URL="https://naumen.ktalk.ru"
```

Или создайте файл `.env` в корне проекта:

```env
KTALK_SESSION_TOKEN=ваш_session_token
```

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

Детали записи.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_transcript`

Транскрипт записи (диалог с таймкодами).

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_summary`

Полное саммари (краткое резюме + протокол).

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи |
| `format` | str | markdown | raw / markdown |

### `ktalk_get_summary_by_type`

Саммари конкретного типа.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи |
| `summary_type` | str | — | shortSummary / protocol |
| `format` | str | markdown | raw / markdown |

## Разработка

```bash
# Запуск тестов
uv run pytest -v

# Линтинг
uv run ruff check .

# Автоисправление
uv run ruff check . --fix

# Локальный запуск сервера
uv run ktalk-mcp
```
