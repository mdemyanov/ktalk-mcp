---
title: Реализация
---

Заметки Dev об особенностях реализации: что было неочевидно при переносе спеки SA в код, какие
edge case'ы покрыты, какие расхождения со спекой приняты осознанно. Пишут `/nauta:dev`.

| Статья | Тема |
|--------|------|
| [personal-api-key-dev-notes.md](personal-api-key-dev-notes.md) | Реализация ядра авторизации, диспетчера профиля эндпоинтов, диагностики и пагинации для эпика «персональный API-ключ» (0.5.0, DEV-001) |
| [rooms-calendar-dev-a-notes.md](rooms-calendar-dev-a-notes.md) | Реализация комнаты/календаря/FR-19 (эпик «Комнаты, календарь, планирование», волна 2, DEV-A) |
| [rooms-calendar-dev-b-notes.md](rooms-calendar-dev-b-notes.md) | Реализация планирования встречи FR-13 (эпик «Комнаты, календарь, планирование», волна 2, DEV-B) |
| [rooms-calendar-dev-c1-notes.md](rooms-calendar-dev-c1-notes.md) | Предпросмотр боевой встречи без сети: доказательство нуля сетевых вызовов, состава полей тела и выдачи confirmation_id (боевая приёмка 0.6.0, DEV-001) |
| [rooms-calendar-dev-c2-notes.md](rooms-calendar-dev-c2-notes.md) | Разбор боевого 404 на `create-meeting-confirm`: встреча не создана, путь `/calendar` — вероятно без `/api`, различить «нет пути»/«нет объекта» без второго POST не удалось (боевая приёмка 0.6.0, DEV-002) |
| [rooms-calendar-dev-c3-notes.md](rooms-calendar-dev-c3-notes.md) | Разбор боевого 401 на `create-meeting-confirm` после правки пути на `/api/calendar`: встреча снова не создана, GET тем же токеном тем же путём работает, `sessionToken` уходит на POST без потерь, тело 401 не сохранено, сообщение «токен истёк» ложно (боевая приёмка 0.6.0, DEV-005) |
| [rooms-calendar-dev-d1-notes.md](rooms-calendar-dev-d1-notes.md) | DEV-007: третий боевой POST дал старое сообщение вместо ADR-008 — root cause: `httpx.AsyncClient` без `cookies=` копит `Set-Cookie` между запросами одного клиента, контрольный вызов диагностики (ADR-004) наследовал cookie отказавшего POST; правка — зачистка cookie-jar response-хуком |
| [rooms-calendar-dev-d2-notes.md](rooms-calendar-dev-d2-notes.md) | DEV-008: наблюдаемость диагностики — исход контрольного вызова, когда он тоже падает (атрибут `control_probe`), пустое тело как видимый факт, HTTP-код исходного отказа виден всегда; матрица текста сообщений 401/403 × контроль ОК/упал × тело пусто/непусто |
| [rooms-calendar-dev-e-notes.md](rooms-calendar-dev-e-notes.md) | DEV-009: тело и транспорт `create_meeting` по живому снимку DevTools — заголовки вместо query на мутирующей операции (`copy_remove_param`), состав тела 14 полей (`requiredAttendees`, `_FIXED`-литералы, условный `anonymousAccessExpirationDate`, `pinCode`-развилка), переименование CLI-флагов |
| [dev-010-contacts-and-cancel.md](dev-010-contacts-and-cancel.md) | DEV-010: резолюция контактов (`search_contacts`, ADR-010) и отмена встречи (`cancel_meeting`, ADR-011) по стабам QA-author — расщепление `auth.py` в `endpoints.py` (гейт C13), опечатка счёта символов в стабе квотирования, расширение регрессии «единственная мутирующая операция» на вторую |
| [dev-001-host-config-and-store.md](dev-001-host-config-and-store.md) | DEV-001 (волна 3, плагин ktalk): discovery `.ktalk.toml` (`host_config.py`), машинный дефолт хранилища и права `0700`/`0600` через процессный `umask` (`store.py`), явная copy-then-verify миграция (`store_migration.py`), четвёртый источник приоритета `resolve_db_path`, `ktalk config show` — 42 красных стаба QA-001 закрыты, `registry.py` не тронут |
