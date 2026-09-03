---
title: ktalk-mcp — документарный контур
---

Решения, требования и архитектура пакета `ktalk-mcp` (MCP-сервер к записям Контур.Толк +
CLI-реестр на SQLite). Здесь живёт ответ на вопрос «почему так»; ответ на вопрос «как
запустить» — в [README.md](../README.md), правила работы агентов — в [CLAUDE.md](../CLAUDE.md).

## Разделы

| Раздел | Что внутри | Кто пишет |
|--------|-----------|-----------|
| [00-project/](00-project/_index.md) | Roadmap, ADR | PM, SA |
| [10-domain/](10-domain/_index.md) | Исследования предметной области и API Толка | Researcher |
| [30-requirements/](30-requirements/_index.md) | Требования и acceptance-критерии | BA |
| [40-architecture/](40-architecture/_index.md) | Архитектурные спеки к ADR, контракты | SA |
| [60-implementation/](60-implementation/_index.md) | Заметки об особенностях реализации | Dev |
| [70-operations/](70-operations/_index.md) | Рунбуки эксплуатации (установка, миграция, откат) | DevOps |
| [lessons-learned.md](lessons-learned.md) | Append-only журнал уроков | все роли |

## Что сюда не кладём

- Планы и спеки в формате superpowers — они остаются в [docs/superpowers/](../docs/superpowers/).
- Операционное состояние реестра записей — оно в SQLite (`.registry.db` в vault), не в git.
- Инструкции по запуску команд — в [CLAUDE.md](../CLAUDE.md), чтобы не расходиться в двух местах.
