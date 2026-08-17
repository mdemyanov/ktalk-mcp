---
title: "Заметки реализации: комната/календарь/FR-19 (DEV-A, волна 2)"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# Заметки реализации: комната/календарь/FR-19 (DEV-A, волна 2)

Реализована читающая часть эпика «Комнаты, календарь, планирование» по
[rooms-calendar-spec.md](../40-architecture/rooms-calendar-spec.md): `contour_diagnostics.py`,
FR-17 (`rooms.py`/`tools_rooms.py`), FR-18 (`calendar_reader.py`/расширение `tools_meetings.py`),
FR-19 (`cli.py::main`). FR-13 (планирование встречи: `meeting_body.py`, `confirmation.py`,
`meeting_scheduling.py`, `cli_meeting.py`, `tools_scheduling.py`, профиль `create_meeting`) —
следующий агент, вне объёма этой заметки.

## Расхождения со спекой (с обоснованием)

1. **`split_window` с `start > end`.** Спека фиксирует edge cases для `start == end` и
   ширину >7 дней, но не для перевёрнутого окна (`start > end`, тест
   `test_fetch_segment_known_400_text_gives_plain_error_without_correlation` вызывает
   `get_calendar_window(client, date(8,7), date(8,1))`, ожидая известный 400 «Дата окончания
   должна быть больше даты начала» от сервера). Естественная реализация цикла `while seg_start
   <= end` для перевёрнутого диапазона даёт **ноль сегментов** — ни одного сетевого вызова, тест
   падает молча (нет исключения вовсе). Решение: `split_window` при `start > end` возвращает один
   сегмент `(start, end)` как есть, не нормализуя — валидацию берёт на себя сервер (по решающей
   таблице §5.5), не клиент. Не пересматривает контракт `split_window` для нормального случая
   (`start <= end`), только явно определяет ранее неспецифицированную ветку.

2. **`_fetch_segment` — decision-table реализована тремя `try/except`, не одним.** Первая версия
   собрала весь путь под общий `except TRANSIENT_ERRORS`, что приводило к тому, что
   `ContourDriftError`/перевыброшенная исходная ошибка от `diagnose_undocumented_failure` (сами —
   подклассы `KTalkError` ⊂ `TRANSIENT_ERRORS`) ловились этим же `except` повторно, вызывая
   диагностику дважды. Разбито на: (а) сетевая ошибка при самом запросе, (б) явная ветка 400 до
   `_classify` (известный/неизвестный текст), (в) `_classify` (401/403/404) отдельным
   `try/except`. Решающая таблица §5.5 реализована как задумано, но не «прямым if/except» одним
   блоком, как формулировка спеки предполагала буквально — три коротких блока вместо одного.

3. **Английская фраза в докстроке `ktalk_list_calendar`.** Черновик докстроки содержал `"your
   calendar"` для объяснения решения AC-7 на английском — сам тест
   (`test_ac_fr18_7_calendar_tool_docstring_does_not_claim_personal_calendar`) запрещает эту
   строку в описании инструмента, что корректно поймало непреднамеренное нарушение AC-7 в
   формулировке. Переформулировано без запрещённых фраз.

## Не тронуто по объёму (не моё)

`_REGISTRY_FREE_COMMANDS` в `cli.py` содержит сегодня только `"auth-status"` — спека §7.1
перечисляет также `create-meeting-preview`/`create-meeting-confirm`, но эти подкоманды не
зарегистрированы в `build_parser()` этим агентом (FR-13, следующий Dev). Следующий агент
дополняет множество при добавлении `cli_meeting.py`, не переопределяет решение целиком.

## Находка для QA-author: `test_secret_masking.py` — 2 стаба с несовместимой предпосылкой

`test_nfr10_secret_not_in_get_room_error_message` и
`test_nfr10_secret_not_in_calendar_error_message` создают `KTalkClient(personal_api_key=SECRET)`
и мокируют сетевой `401`, ожидая `pytest.raises(KTalkAuthError)` из `get_room`/
`get_calendar_window`. Обе операции по ADR-004 п.2/rooms-calendar-spec §2 **fail-closed под
api-key** (`AuthMode.API_KEY: None` — нет подтверждённого профиля, FR-17 AC3/NFR-7): вызов
поднимает `OperationNotAvailableError` **до** сети, мокированный `401` не запрашивается вовсе.

Секрет при этом нигде не утекает (`OperationNotAvailableError` не строит текст из credential) —
содержательная цель NFR-10 не нарушена, но тип исключения не совпадает с ожиданием стаба, и тест
падает. Похоже на перенос паттерна из `test_secret_not_in_auth_error_message` (где
`list_recordings` действительно доступен под api-key) без учёта того, что `get_room`/
`get_calendar` — session-only операции этой волны. Не переписывал тест — по роли Dev не трогает
QA-author stubs; тесты остаются red до решения QA-author (варианты: сменить фикстуру на
`session_token`, чтобы дойти до сети, либо расширить assertion на `OperationNotAvailableError`).
