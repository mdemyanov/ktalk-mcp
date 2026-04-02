# KTalk MCP Server — Design Specification

**Date:** 2026-04-02
**Status:** Draft
**Author:** mdemyanov

## Context

Контур.Толк (KTalk) — корпоративная видеоконференц-платформа Naumen. Записи встреч, транскрипты и саммари доступны через Web UI, но нет удобного программного доступа для использования в AI-ассистентах.

**Цель**: создать локальный MCP сервер, который предоставляет Claude Code доступ к записям KTalk — списку записей, деталям, транскриптам и саммари/протоколам. Два режима вывода: raw JSON и человеко-читаемый markdown.

**Аудитория**: команда, несколько человек. Нужна документация по установке и настройке.

**Base URL**: `https://naumen.ktalk.ru`

## Architecture

### Подход: Flat MCP Server

Минимальная структура из 4 модулей без лишних абстракций. Достаточно для 5 API эндпоинтов.

### Структура проекта

```
ktalk-mcp/
├── src/ktalk_mcp/
│   ├── __init__.py          # версия, метаданные пакета
│   ├── __main__.py          # entry point: python -m ktalk_mcp
│   ├── server.py            # MCP сервер, определение 5 tools
│   ├── client.py            # KTalkClient — async httpx обёртка
│   ├── formatters.py        # raw/markdown конвертеры
│   └── config.py            # Settings (pydantic-settings)
├── tests/
│   ├── test_client.py       # mock httpx, проверка запросов
│   └── test_formatters.py   # фикстуры JSON, проверка markdown
├── pyproject.toml
├── CLAUDE.md
├── README.md
├── .gitignore
└── talk.public.api-api-2.json  # справочник API (не в пакете)
```

### Зависимости

| Пакет | Назначение |
|-------|-----------|
| `fastmcp` | MCP SDK для Python |
| `httpx` | Async HTTP клиент |
| `pydantic-settings` | Конфигурация из env/`.env` |

**Dev-зависимости**: `pytest`, `pytest-asyncio`, `ruff`

### Запуск

```bash
# Из исходников
uv run ktalk-mcp

# Через uvx (после публикации)
uvx ktalk-mcp
```

## Components

### 1. Config (`config.py`)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ktalk_base_url: str = "https://naumen.ktalk.ru"
    ktalk_session_token: str  # обязательный

    model_config = SettingsConfigDict(env_file=".env")
```

- `KTALK_SESSION_TOKEN` — обязательная переменная окружения
- `KTALK_BASE_URL` — по умолчанию `https://naumen.ktalk.ru`, можно переопределить
- Поддержка `.env` файла для удобства
- При отсутствии токена — понятная ошибка с инструкцией

### 2. HTTP Client (`client.py`)

Async-класс `KTalkClient` на базе `httpx.AsyncClient`.

**Методы** (каждый возвращает `dict` из JSON response):

| Метод | HTTP | Путь |
|-------|------|------|
| `list_recordings(**params)` | GET | `/api/Domain/recordings/v2` |
| `get_recording(key)` | GET | `/api/Domain/recordings/{key}` |
| `get_transcript(key)` | GET | `/api/recordings/{key}/transcript` |
| `get_summary(key)` | GET | `/api/recordings/v2/{key}/summary` |
| `get_summary_by_type(key, type)` | GET | `/api/recordings/{key}/summary/{type}` |

**Авторизация**: заголовок `Authorization: Session {token}` на каждый запрос.

**Обработка ошибок**:
- 401 → `"Токен сессии истёк или невалиден. Обновите KTALK_SESSION_TOKEN (см. README)"`
- 404 → `"Запись {key} не найдена"`
- Другие HTTP ошибки → описание статуса + тело ответа

**Timeout**: 30 секунд.

### 3. MCP Server (`server.py`)

5 MCP tools на базе `fastmcp`. Один экземпляр `KTalkClient`, создаётся при старте.

#### Tool: `ktalk_list_recordings`

Список доступных записей конференций.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `query` | str \| None | None | Поиск по названию, комнате, автору |
| `start_from` | str \| None | None | Начало периода (ISO 8601, напр. 2026-03-01) |
| `start_to` | str \| None | None | Конец периода |
| `top` | int | 30 | Количество записей (1–1000) |
| `order` | str | "byTimeNewFirst" | Сортировка: byTimeNewFirst, byTimeOldFirst, byTitle, bySizeBigFirst, bySizeSmallFirst |
| `page_token` | str \| None | None | Токен для следующей/предыдущей страницы |
| `format` | str | "markdown" | Формат вывода: raw / markdown |

#### Tool: `ktalk_get_recording`

Детали одной записи.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи (обязательный) |
| `format` | str | "markdown" | raw / markdown |

#### Tool: `ktalk_get_transcript`

Транскрипт записи (распознанная речь по спикерам).

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи (обязательный) |
| `format` | str | "markdown" | raw / markdown |

#### Tool: `ktalk_get_summary`

Полное саммари: протокол + краткое резюме + транскрипция (v2 endpoint).

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи (обязательный) |
| `format` | str | "markdown" | raw / markdown |

#### Tool: `ktalk_get_summary_by_type`

Саммари конкретного типа.

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `recording_key` | str | — | Ключ записи (обязательный) |
| `summary_type` | str | — | Тип: "shortSummary" или "protocol" (обязательный) |
| `format` | str | "markdown" | raw / markdown |

### 4. Formatters (`formatters.py`)

Каждая функция: `dict → str`. При `format="raw"` возвращается `json.dumps(data, ensure_ascii=False, indent=2)`.

#### `format_recordings_list(data: dict) -> str`

```markdown
# Записи KTalk

| Название | Дата | Автор | Длительность | Участники |
|----------|------|-------|-------------|-----------|
| Стендап команды | 2026-04-01 10:00 | Иванов И. | 45 мин | 5 |
| Ретро спринта | 2026-03-28 14:00 | Петрова М. | 1 ч 20 мин | 8 |

> Следующая страница: используйте `page_token: "abc123"`
```

#### `format_recording(data: dict) -> str`

```markdown
# Стендап команды

- **Ключ:** rec-abc-123
- **Дата:** 2026-04-01 10:00
- **Автор:** Иван Иванов
- **Комната:** standup-room
- **Длительность:** 45 мин
- **Участники (5):** Иван Иванов, Мария Петрова, Алексей Сидоров, ...
```

#### `format_transcript(data: dict) -> str`

```markdown
# Транскрипт: Стендап команды

**Иван Иванов** [00:00:15]: Доброе утро, давайте начнём с обсуждения задач на сегодня.

**Мария Петрова** [00:01:42]: У меня вчера было две задачи. Первую закрыла, вторая переходит на сегодня.

**Алексей Сидоров** [00:02:30]: Я занимался ревью, есть пара вопросов по архитектуре.
```

Логика: итерация по `tracks[]` → для каждого трека итерация по `chunks[]` → `speaker.userInfo.surname + firstname`, fallback на `login`, fallback на `anonymousName` → `startTimeOffsetInMillis` → `HH:MM:SS` формат.

#### `format_summary(data: dict) -> str`

Composite summary — объединяет секции:

```markdown
# Саммари: {название записи}

## Краткое резюме

{chunks из shortSummaryV2, текст}

## Протокол

{chunks из protocolV2, текст}
```

Статус обработки: если `status != "success"`, показывает текущий статус вместо контента.

#### `format_summary_by_type(data: dict, summary_type: str) -> str`

Рендерит `chunks[]` → markdown. Каждый чанк — параграф или заголовок в зависимости от `chunk.type`.

### Общие правила форматирования

- `nullable` поля с `None` — пропускаются, не показываются как "null"
- Длительность: секунды → "X ч Y мин" или "X мин" (если < 1 часа)
- Даты: ISO 8601 → `YYYY-MM-DD HH:MM` (без секунд, без timezone)
- Имена: `{surname} {firstname}`, fallback цепочка: `login` → `anonymousName` → "Неизвестный"
- Статусы обработки (транскрипт/саммари): `inProgress` → "В обработке...", `error`/`failed` → сообщение об ошибке

## Authentication Flow

### Получение токена (инструкция для пользователя)

1. Открыть https://naumen.ktalk.ru в браузере
2. Войти в свой аккаунт
3. Открыть DevTools (F12) → Application → Cookies → `https://naumen.ktalk.ru`
4. Найти cookie `sessionToken`, скопировать значение
5. Сохранить в `.env` файл или переменную окружения:

```bash
export KTALK_SESSION_TOKEN="скопированное_значение"
```

### Особенности
- Session token имеет ограниченный срок жизни (зависит от настроек KTalk)
- При истечении — MCP tool вернёт понятное сообщение с инструкцией по обновлению
- Токен привязан к конкретному пользователю, каждый член команды использует свой

## Claude Code Integration

### Конфигурация MCP сервера

В файле `~/.claude/.mcp.json` или в проектном `.mcp.json`:

```json
{
  "mcpServers": {
    "ktalk": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ktalk-mcp", "ktalk-mcp"],
      "env": {
        "KTALK_SESSION_TOKEN": "your-session-token-here"
      }
    }
  }
}
```

## Testing Strategy

### Unit тесты (`tests/test_formatters.py`)
- Фикстуры: реальные JSON-ответы из API (замоканные) для каждого эндпоинта
- Проверка markdown-вывода: наличие заголовков, правильный формат таймкодов, корректные имена
- Edge cases: пустой список записей, транскрипт в обработке, запись без участников

### Unit тесты (`tests/test_client.py`)
- Mock `httpx.AsyncClient` через `respx` или `pytest-httpx`
- Проверка: правильные URL, заголовки, параметры запроса
- Проверка обработки ошибок: 401, 404, 500

### Фреймворк
- `pytest` + `pytest-asyncio`
- `ruff` для линтинга

## Project Documentation

### CLAUDE.md
```markdown
# ktalk-mcp

MCP сервер для доступа к записям Контур.Толк.

## Stack
- Python 3.12+, fastmcp, httpx, pydantic-settings

## Commands
- `uv run ktalk-mcp` — запуск сервера
- `uv run pytest` — тесты
- `uv run ruff check .` — линтинг

## Architecture
- server.py — MCP tools
- client.py — HTTP клиент KTalk API
- formatters.py — JSON → markdown конвертеры
- config.py — Settings из env

## Conventions
- Async everywhere (httpx, fastmcp)
- Format parameter: "raw" (JSON) или "markdown"
- Ошибки API → человекочитаемые сообщения на русском
```

### README.md
1. Описание проекта
2. Установка и зависимости
3. Получение session token (пошаговая инструкция)
4. Конфигурация (env vars, `.env`)
5. Подключение к Claude Code (`.mcp.json`)
6. Доступные MCP tools с описанием параметров и примерами
7. Разработка (запуск тестов, линтинг)

## Verification Plan

1. **Unit тесты**: `uv run pytest` — все тесты проходят
2. **Линтинг**: `uv run ruff check .` — без ошибок
3. **Запуск сервера**: `uv run ktalk-mcp` — стартует без ошибок
4. **Интеграция с Claude Code**: добавить в `.mcp.json`, вызвать `ktalk_list_recordings` — получить список записей
5. **Проверка форматов**: вызвать каждый tool с `format=raw` и `format=markdown` — оба формата работают
6. **Проверка ошибок**: вызвать с невалидным токеном — получить понятное сообщение
