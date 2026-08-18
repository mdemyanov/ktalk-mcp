# ktalk-mcp — API Контур.Толк

Справочник вынесен из корневого `CLAUDE.md`: грузится только при работе под `src/`.

## Контракт API
- OpenAPI спецификация (справочник, **есть расхождения с реальностью**): `talk.public.api-api-2.json`
- Base URL: https://your-domain.ktalk.ru
- **Два режима авторизации** (решение — [ADR-003](content/00-project/adr/ADR-003-auth-modes.md)):
  `KTALK_PERSONAL_API_KEY` → заголовок `X-Auth-Token`; иначе `KTALK_SESSION_TOKEN` →
  query `sessionToken=`. Ключ побеждает; при обоих заданных session-токен не читается.
- **Набор путей зависит от режима** — интеграторский контур (`/api/Domain/*`, `/api/Recordings/*`,
  `/api/ConferenceReports/*`) отдаёт 401/403 по сессии, поэтому пути живут в таблице профилей
  `auth.py`, а не хардкодом в методах.
- Session-контур: `GET /api/recordings`, `/api/recordings/{id}`, `/api/conferencesHistory/{key}`
- Общее для обоих: `/api/recordings/{key}/transcript`, `/api/recordings/v2/{key}/summary`,
  `/api/recordings/{key}/summary/{type}`

### Поведение API, проверенное эмпирически (спеке здесь верить нельзя)
- `top` максимум **100**, не 1000: `400 «The field Top must be between 1 and 100»`.
- `nextPageToken` во внутреннем контуре **не существует** — пагинация только через `skip`.
- `startFrom`/`startTo` **игнорируются**: окно дат обеспечивает клиент (`clip_to_window`),
  обход прекращается на первой странице за порогом. Выдача отсортирована от новых к старым.
- `maxParticipantCount` в списке имеет максимум 10 и дефолт 6 — полный состав участников
  берётся дообогащением по каждой записи, а не из списка.
- Чат требует необъявленный в спеке параметр `channel` (рабочее значение `general`).
- **401 ≠ 403**: 401 — ключ/токен невалиден, 403 — валиден, но не хватает scope. Тело 403
  обычно пустое, диагностика строится на коде ответа и требуемом scope операции.
