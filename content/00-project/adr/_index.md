---
title: ADR
---

Принятые решения. Один файл — одно решение; процедурная детализация выносится в
companion-спеку `<stem>-spec.md` в [40-architecture/](../../40-architecture/) (этого требует
гейт C11 при объёме ADR больше 150 строк).

| ADR | Решение | Статус |
|-----|---------|--------|
| [ADR-001](ADR-001-nauta-contour.md) | Документарный контур и гейты nauta в код-проекте | Approved |
| [ADR-002](ADR-002-sqlite-registry.md) | SQLite — операционный source of truth реестра | Approved |
| [ADR-003](ADR-003-auth-modes.md) | Режимы авторизации и профили эндпоинтов | Draft |
| [ADR-004](ADR-004-undocumented-contour.md) | Опора на недокументированный контур волны 2 и обнаружение его деградации | Draft |
| [ADR-005](ADR-005-write-operations.md) | Контракт пишущих операций: предпросмотр и привязанное подтверждение | Draft |
| [ADR-006](ADR-006-get-room-side-effect.md) | `get_room` — эмпирически мутирующий read, контракт предупреждения | Approved |
| [ADR-007](ADR-007-create-meeting-path-correction.md) | Коррекция пути `create_meeting` на `/api/calendar` и дисциплина маркировки непроверенных экстраполяций | Proposed |
| [ADR-008](ADR-008-write-auth-and-error-model.md) | Доп. заголовок `Authorization` на мутирующих операциях (гипотеза), `KTalkWriteAuthMismatchError`, тело 4xx-ответа как атрибут исключения | Draft |
| [ADR-009](ADR-009-devtools-body-and-transport-correction.md) | Коррекция тела и транспорта `create_meeting` по браузерному снимку DevTools (14 полей, `X-Platform`, `requiredAttendees`) | Draft |
| [ADR-010](ADR-010-contacts-resolution.md) | Резолюция участника встречи через справочник контактов (`GET /api/contacts`) — пересматривает ADR-009 §3 | Draft |
| [ADR-011](ADR-011-meeting-cancel-update.md) | Контракт отмены встречи (`POST /calendar/{id}/cancel`), подтверждение привязано к (операция, id, reason); правка (`PUT`) отложена до измерения тела | Draft |
| [ADR-012](ADR-012-plugin-boundary.md) | Границы плагина ktalk: три дома артефактов, плагин как тонкая обёртка над `uv tool`, cutover агентов, отдельный репозиторий | Draft |
| [ADR-013](ADR-013-central-transcript-store.md) | Централизованное машинное хранилище транскриптов: корень, раскладка, приоритет пути, конкурентный доступ, облачная синхронизация, права, миграция | Proposed |
| [ADR-014](ADR-014-sanctioned-onboarding.md) | Санкционированный онбординг пакета `ktalk-mcp`: онбординг-скрипт в дереве плагина, файл санкции, два независимых ключа, TTY на выдачу, `uv tool` как единственный менеджер, `compat.json` | Draft |
