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
| [ADR-013-central-transcript-store-spec.md](ADR-013-central-transcript-store-spec.md) | Companion-спека к [ADR-013](../00-project/adr/ADR-013-central-transcript-store.md): разрешение пути, детекция облачной синхронизации, контракт теста конкурентного доступа, контракт миграции, брифы Dev/DevOps, контракт QA-author (0.7.0) |
| [ADR-014-onboarding-spec.md](ADR-014-onboarding-spec.md) | Companion-спека к [ADR-014](../00-project/adr/ADR-014-sanctioned-onboarding.md): контракт команд и кодов возврата `ktalk-onboard.sh`, схемы `onboarding.toml`/`compat.json`, определение версии, классификация ошибок установки, врезка для промтов, брифы Dev, контракт QA (волна 4) |
| [ADR-015-cli-authority-and-write-handoff-spec.md](ADR-015-cli-authority-and-write-handoff-spec.md) | Companion-спека к [ADR-015](../00-project/adr/ADR-015-cli-authority-and-write-handoff.md): состав handoff-сообщения (предпросмотр + точная команда `*-confirm` + пояснение TTY), разбор отказов `*-preview`/`*-confirm`, NFR mapping, брифы Dev/DevOps, контракт QA-author (волна 5, SA-005) |

## Самостоятельные архитектурные статьи

| Статья | Тема |
|--------|------|
| [client-modules-spec.md](client-modules-spec.md) | Раскладка модулей пакета `ktalk_mcp` и карта «эндпоинт → метод клиента → MCP/CLI» для эпика «персональный API-ключ» (0.5.0) |
| [at-design-personal-api-key.md](at-design-personal-api-key.md) | Тест-дизайн и failing stubs для эпика «персональный API-ключ» (0.5.0): таблица AC → тест-функция, boundary/error cases, ручные AC |
| [security-review-personal-api-key.md](security-review-personal-api-key.md) | DevSecOps-ревью (SEC-001) эпика «персональный API-ключ» (0.5.0): NFR-5, политика записи `download.py`, находки и фиксы |
| [ADR-004-undocumented-contour-spec.md](ADR-004-undocumented-contour-spec.md) | Companion-спека к [ADR-004](../00-project/adr/ADR-004-undocumented-contour.md): подтверждённость путей, каталог ошибок, детекция дрейфа контура (0.6.0) |
| [ADR-005-write-operations-spec.md](ADR-005-write-operations-spec.md) | Companion-спека к [ADR-005](../00-project/adr/ADR-005-write-operations.md): протокол предпросмотра/подтверждения пишущей операции (0.6.0) |
| [rooms-calendar-spec.md](rooms-calendar-spec.md) | Раскладка реализации волны «комнаты, календарь, планирование» (0.6.0) по файлам под гейт C13: `OPERATION_PROFILES`, мапперы, сегментация, протокол подтверждения, FR-19; §4.2/4.3 — companion к [ADR-006](../00-project/adr/ADR-006-get-room-side-effect.md) (побочный эффект `get_room`) |
| [at-design-rooms-calendar.md](at-design-rooms-calendar.md) | Тест-дизайн и failing stubs для эпика «комнаты, календарь, планирование» (0.6.0): таблица AC → тест-функция, boundary/error cases, допущения для Dev |
| [security-review-write-ops.md](security-review-write-ops.md) | DevSecOps-ревью (SEC-002) первой пишущей операции `POST /calendar` (0.6.0): барьер `isatty()`, отсутствие мутирующего MCP-инструмента, NFR-9/NFR-10, `ConfirmationStore`, находки и рекомендации |
| [qa-report-rooms-calendar.md](qa-report-rooms-calendar.md) | QA-отчёт финального прогона перед релизом 0.6.0: регрессия волны 1, сверка покрытия с at-design, мутационная проверка 7 предохранителей, стабильность (TTY-буфер), рекомендация merge |
| [ADR-007-create-meeting-path-correction-spec.md](ADR-007-create-meeting-path-correction-spec.md) | Companion-спека к [ADR-007](../00-project/adr/ADR-007-create-meeting-path-correction.md): правка `auth.py`, маркеры `ФАКТ`/`ГИПОТЕЗА`, обёртка `create_meeting` в корреляционную диагностику ADR-004 (боевая приёмка 0.6.0) |
| [ADR-008-write-auth-and-error-model-spec.md](ADR-008-write-auth-and-error-model-spec.md) | Companion-спека к [ADR-008](../00-project/adr/ADR-008-write-auth-and-error-model.md): `EndpointProfile.mutating`, доп. заголовок на мутациях, `KTalkWriteAuthMismatchError`, тело 4xx как атрибут исключения (боевая приёмка 0.6.0) |
| [ADR-009-devtools-body-and-transport-correction-spec.md](ADR-009-devtools-body-and-transport-correction-spec.md) | Companion-спека к [ADR-009](../00-project/adr/ADR-009-devtools-body-and-transport-correction.md): состав тела `create_meeting` (14 полей), `X-Platform`, резолюция числового `key` участника, брифы Dev/DevOps, контракт QA-author (боевая приёмка 0.6.0) |
| [ADR-010-contacts-resolution-spec.md](ADR-010-contacts-resolution-spec.md) | Companion-спека к [ADR-010](../00-project/adr/ADR-010-contacts-resolution.md): `search_contacts`, `GET /api/contacts`, контракт 0/1/>1 совпадений, брифы Dev/DevOps, контракт QA-author (SA-010) |
| [ADR-011-meeting-cancel-update-spec.md](ADR-011-meeting-cancel-update-spec.md) | Companion-спека к [ADR-011](../00-project/adr/ADR-011-meeting-cancel-update.md): модуль `meeting_cancel.py`, профиль `cancel_meeting`, привязка подтверждения к (операция, id, reason), брифы Dev/DevOps, контракт QA-author (SA-011) |
| [at-design-contacts-and-cancel.md](at-design-contacts-and-cancel.md) | Тест-дизайн и failing stubs для QA-010: резолюция контактов (ADR-010) и отмена встречи (ADR-011) — таблица AC → тест-функция, boundary/error cases, допущения для Dev |
| [ADR-012-plugin-boundary-spec.md](ADR-012-plugin-boundary-spec.md) | Companion-спека к [ADR-012](../00-project/adr/ADR-012-plugin-boundary.md): полная таблица трёх домов (11 файлов + данные), контракт `.mcp.json`/`plugin.json`, cutover-процедура агентов, брифы Dev/DevOps, контракт QA-author (SA-001, волна 3) |
| [ktalk-plugin-spec.md](ktalk-plugin-spec.md) | Конфигурация проекта-хозяина (SA-003, волна 3): формат `.ktalk.toml`, discovery, маршрутизация артефактов как конфигурация, контракт деградации (FR-24), миграция vault'а `naumen-cto`, брифы Dev/DevOps, контракт QA-author |
| [at-design-ktalk-plugin.md](at-design-ktalk-plugin.md) | Тест-дизайн и failing stubs для волны 3 (0.7.0, QA-001): discovery `.ktalk.toml` (FR-20), приоритет разрешения пути (FR-23), работа без vault-раскладки (FR-21), машинный дефолт хранилища/облачная синхронизация/права (FR-22, NFR-14, NFR-15), миграция (NFR-12), конкурентный доступ (NFR-13), `ktalk config show` — таблица AC → тест-функция, что не покрыто автоматически и почему |
| [security-review-ktalk-plugin.md](security-review-ktalk-plugin.md) | DevSecOps-ревью (SEC-003) волны 3 перед сборкой плагина (DEV-003): режим доступа к централизованному хранилищу (NFR-15), процессная мутация `umask` в `resolve_store_root` (разбор а/б/в/г), отсутствие секретов (FR-25) в обоих деревьях, supply-chain и SAST по `host_config.py`/`store.py`/`store_migration.py`, находки и рекомендации |
| [security-review-onboarding.md](security-review-onboarding.md) | DevSecOps-ревью (SEC-004) волны 4: исполняемый `ktalk-onboard.sh` в дереве плагина — исполнение внешней команды и словосплиттинг, права и атомарность файла санкции, fail-closed чтение, TTY-барьер `grant` (NFR-18), containment записи, NFR-19 (ретрансляция вывода `uv` из окружения с секретами), FR-25 по истории обоих репозиториев, регрессия по SEC-003, находки и фиксы |
