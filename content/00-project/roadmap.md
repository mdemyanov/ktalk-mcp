---
title: Roadmap
properties:
  - name: Тип контента
    value: [Roadmap]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# Roadmap

Состояние на 2026-08-13, версия пакета — 0.4.0.

## Что уже работает

| Фаза | Результат | Где код |
|------|-----------|---------|
| PoC | MCP-сервер: 5 tools поверх KTalk API, форматтеры JSON → markdown | [server.py](../../src/ktalk_mcp/server.py), [formatters.py](../../src/ktalk_mcp/formatters.py) |
| MVP | Чанкинг транскриптов (`chunk`, `chunk_size`) — длинные записи читаются постранично | [formatters.py](../../src/ktalk_mcp/formatters.py) |
| Pilot | CLI-реестр на SQLite: `sync`, `dashboard`, `list`, `show`, `mark-*`, `export`, `migrate` | [cli.py](../../src/ktalk_mcp/cli.py), [registry.py](../../src/ktalk_mcp/registry.py) |
| Production | Реестр как операционный source of truth, markdown-зеркало в vault генерируется | [ADR-002](adr/ADR-002-sqlite-registry.md) |

Проектная документация фаз PoC–Pilot писалась в формате superpowers и осталась в
[docs/superpowers/](../../docs/superpowers/) — ретроспективно в контур она не переносится.

## Что дальше

Бэклог не зафиксирован: следующая фича начинается с `/nauta:pm decompose <описание>`, дальше
цепочка Researcher → BA → SA → Dev → QA. Кандидаты, которые уже видны из кода и обсуждений:

- **Расщепление `Registry`** — класс на 208 строк, заморожен грандфазером в
  [.nauta-gates.yaml](../../.nauta-gates.yaml); рост блокирует коммит (см. [ADR-001](adr/ADR-001-nauta-contour.md)).
- **Требования к реестру постфактум** — статусная модель и правила экспирации сегодня описаны
  только в [CLAUDE.md](../../CLAUDE.md); при следующей правке механики их место в
  [30-requirements/](../30-requirements/).

## GO-критерии следующего milestone

1. `uv run pytest` — зелёный.
2. `bash scripts/check.sh --fast` — `Errors: 0`.
3. Каждая новая фича имеет требование в `30-requirements/` и решение в `adr/`, если меняет контракт.
