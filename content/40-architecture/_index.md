---
title: Архитектура
---

Архитектурные спеки, контракты интеграций и companion-спеки к ADR. Пишет `/nauta:sa`.

Соглашение об именовании: companion-спека к решению `ADR-00N-<stem>.md` называется
`ADR-00N-<stem>-spec.md` — так гейт лимита объёма ADR (C11, `quality: companion-spec`)
находит её автоматически.

| Спека | К какому решению |
|-------|------------------|
| [ADR-001-nauta-contour-spec.md](ADR-001-nauta-contour-spec.md) | Калибровка гейтов объёма для [ADR-001](../00-project/adr/ADR-001-nauta-contour.md) |

## Самостоятельные архитектурные статьи

| Статья | Тема |
|--------|------|
| [client-modules-spec.md](client-modules-spec.md) | Раскладка модулей пакета `ktalk_mcp` и карта «эндпоинт → метод клиента → MCP/CLI» для эпика «персональный API-ключ» (0.5.0) |
| [at-design-personal-api-key.md](at-design-personal-api-key.md) | Тест-дизайн и failing stubs для эпика «персональный API-ключ» (0.5.0): таблица AC → тест-функция, boundary/error cases, ручные AC |
| [security-review-personal-api-key.md](security-review-personal-api-key.md) | DevSecOps-ревью (SEC-001) эпика «персональный API-ключ» (0.5.0): NFR-5, политика записи `download.py`, находки и фиксы |
