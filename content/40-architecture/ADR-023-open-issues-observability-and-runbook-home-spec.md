---
title: "ADR-023 spec: детализация трёх решений волны открытых issue"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-023 spec: обнаружимость подмены транскрипта, момент синхронизации, дом OPS-001

Companion-спека к [ADR-023](../00-project/adr/ADR-023-open-issues-observability-and-runbook-home.md).
Решения — в ADR; здесь — компоненты, алгоритмы, брифы Dev/DevOps, контракт QA-author.

## Контекст

Реализует [NFR-17](../30-requirements/transcript-identity-observability.md) (issue #5),
[FR-41](../30-requirements/registry-sync-observability.md) (issue #6), issue #7 (дом OPS-001).
Issue #3 (баг `.get("id", fallback)` в `formatters.py:126`/`:165`) сюда не входит — дефект
возвращает существующее поведение, не архитектурное решение.

## Компоненты — NFR-17

| Компонент | Ответственность | Входы | Выходы | Зависимости |
|---|---|---|---|---|
| `transcript_identity.py` (новый модуль) | Извлечение идентификаторов спикеров/участников, сравнение | `TalkTranscript`, `TalkConferenceRecording` (оба — сырой JSON API) | `dict` результата сверки | нет (чистые функции) |
| `cli_content.py::cmd_get_transcript` | Флаг `--no-verify-identity` (сверка включена по умолчанию), оркестрация второго вызова, сборка envelope | `args.no_verify_identity`, результат `client.get_transcript`, `client.get_recording` | текст ответа (markdown/JSON) с/без `identity_check` | `KTalkClient.get_recording`, `transcript_identity` |

### `transcript_identity.py`

```
_identity_key(user_ref: dict | None) -> str | None
    # userInfo.key или userInfo.login (именованный); anonymousId или anonymousName (аноним);
    # None, если user_ref пуст — та же приоритетность, что _format_user_name(with_id=True)
    # в formatters.py, здесь возвращается сырой токен, не строка для вывода.

speaker_identities(transcript: dict) -> set[str]
    # обход tracks[]: speaker, при отсутствии — diarizedSpeaker; None отбрасываются.

participant_identities(recording: dict) -> set[str]
    # обход recording["participants"] (TalkUserRef[]); None отбрасываются.

check_identity(transcript: dict, recording: dict) -> dict
    # ts = speaker_identities(transcript); rp = participant_identities(recording)
    # not ts or not rp        -> {"result": "inconclusive"}
    # ts & rp                 -> {"result": "match", "transcript_speakers": sorted(ts),
    #                              "recording_participants": sorted(rp)}
    # иначе                   -> {"result": "mismatch", тот же набор полей}
```

`not_checked` не формируется этой функцией — это исход на уровне `cmd_get_transcript`, когда сам
вызов `client.get_recording` бросает исключение (сеть/авторизация/4xx), до вызова `check_identity`.

### Оркестрация в `cmd_get_transcript`

1. Как сегодня: `data = await client.get_transcript(recording_key)`. Ошибка здесь — как сегодня,
   отказ команды целиком (не относится к NFR-17).
2. Если `--no-verify-identity` НЕ передан (умолчание — сверка включена, ADR-023 §1): отдельный
   `try` вокруг `await client.get_recording(recording_key)`. Успех → `check_identity(data,
   recording)`. Исключение → `{"result": "not_checked", "reason": redact_secrets(str(exc))}` (та
   же функция маскирования, что уже применяется к ошибке основного вызова, NFR-5). Основной
   результат транскрипта возвращается в любом случае (AC3).
3. При `--no-verify-identity`: шаг 2 не выполняется, `identity_check` не формируется, второй
   сетевой вызов не происходит — нулевая цена только при явном отказе.
4. Сборка вывода:
   - markdown (`--json` не передан): `print(output_text)`, затем при наличии `identity_check` —
     одна строка `f"[identity-check] {identity_check['result']}"` (+ `reason`, если есть).
   - JSON (`--json`): `output_text = render_transcript_output(...)` не меняется; если
     `identity_check` есть — `parsed = json.loads(output_text)` (успех гарантирован кроме одного
     edge-case ниже), печать `{"transcript": parsed, "identity_check": identity_check}`.
   - Edge case: `render_transcript_output` при `--chunk N` вне диапазона возвращает
     нестрого-JSON текст (`"Чанк N не существует..."`) — `json.loads` в этом случае бросит
     исключение; при неудаче парсинга `identity_check` в вывод не добавляется, печатается
     `output_text` как есть (сверять нечего — чанка, содержимого которого касалась бы сверка, нет).

## Границы — NFR-17

- Не чинит причину подмены (контур/сеть) — RES-006 её не локализовал, ADR-023 её не проектирует.
- Не кэширует и не переиспользует результат `get_recording` между вызовами — каждый вызов, где
  сверка включена (умолчание), платит своей ценой заново; простота важнее экономии.
- Не проверяет анонимных участников со сменным `anonymousId` — известное ограничение (ADR-023
  Consequences), не проверено живым тестом.

## Компоненты — FR-41

| Компонент | Ответственность | Входы | Выходы | Зависимости |
|---|---|---|---|---|
| `cli.py::_cmd_dashboard` | Добавляет `last_synced` в JSON-ответ верхнего уровня | `reg.get_meta("last_synced")` | `{"new": …, "stats": …, "last_synced": str \| None}` | `Registry.get_meta` (registry.py:378, без изменений) |

Изменение — одна строка в существующей функции: `payload["last_synced"] =
reg.get_meta("last_synced")` перед `_print_json`. `registry.py` не растёт (потолок 562 строки).
Markdown-вывод (`else`-ветка `_cmd_dashboard`) не меняется — FR-41 требует машиночитаемый
`--json`, не текстовый дашборд.

## Дом OPS-001 — структура раздела

```
content/70-operations/
└── _index.md          # кладбище-таблица по образцу content/00-project/adr/_index.md
```

`content/_index.md` (корневой) получает строку в таблице разделов — раздел «70-operations/»,
рунбуки DevOps. `CLAUDE.md` — строку в списке путей документарного контура. Файл
`OPS-001-registry-migration-rollback.md` (рабочее имя, уточняет DevOps) заводится задачей DevOps
отдельным коммитом вместе с подъёмом `populated: true`/`highwater: 1` в `.nauta-ids.yaml`
(§3 ADR-023) — не этой задачей.

## NFR Mapping

- `### Requirement: NFR-17` → сверка по умолчанию (`--no-verify-identity` отключает) +
  `transcript_identity.py`: `match`/`mismatch`/
  `inconclusive`/`not_checked` — различает «сверено, совпадает» от «не сверено» (AC3), не
  ложноположит на консистентном ответе за счёт требования непустого пересечения, а не полного
  совпадения множеств (AC2).
- `### Requirement: FR-41` → `last_synced` в `dashboard --json`, `null` при отсутствии
  синхронизации (AC1/AC2), чтение не мутирует реестр — `get_meta` не пишет (AC3).

## Бриф для Dev

**Архитектура:** этот документ + [ADR-023](../00-project/adr/ADR-023-open-issues-observability-and-runbook-home.md)
**Требование:** NFR-17, FR-41
**Фаза:** Production

**Реализовать:**
- Новый модуль `transcript_identity.py`: `_identity_key`, `speaker_identities`,
  `participant_identities`, `check_identity` — функции выше, без побочных эффектов.
- `cli_content.py::cmd_get_transcript`: флаг `--no-verify-identity` (`action="store_true"`,
  умолчание сверки — включена), оркестрация шагов 1-4 выше.
- `cli.py::_cmd_dashboard`: строка `last_synced` в JSON-ответе.

**Порядок:** fixtures (консистентный транскрипт+recording; расходящийся; recording-вызов падает;
свежий реестр без sync) → интерфейсы (`transcript_identity.py`) → реализация → тесты.

**Сценарии приёмки:** `#### Scenario:` из капабилити-спек, объявленных требованиями (пути —
`openspec/specs/recording-data-access/spec.md`, `openspec/specs/registry-sync-window/spec.md`).

## Бриф для DevOps

**Архитектура:** этот документ + ADR-023
**Подготовить:**
- Раздел `content/70-operations/` (пустой каркас — `_index.md`, эта задача) → DevOps материализует
  `OPS-001-registry-migration-rollback.md` по контракту отката из
  [ADR-013-spec](ADR-013-central-transcript-store-spec.md) §«Контракт команды миграции»,
  поднимает `populated`/`highwater` в `.nauta-ids.yaml` тем же коммитом.
- Мониторинг: нет рантайм-метрик (CLI, не сервис) — `identity_check.result == "mismatch"` в логах
  вызывающей стороны (плагина) как сигнал инцидента, не метрика пакета.

**NFR из BA:** NFR-17 (обнаружимость подмены — включена по умолчанию, цена на каждом вызове
`get-transcript` кроме явного `--no-verify-identity`), FR-41 (наблюдаемость момента синхронизации
без мутации).

## Контракт с QA-author

**Сценарии приёмки (полный список из капабилити-спек):**
- `openspec/specs/recording-data-access/spec.md` — сценарии NFR-17 (мэтч/мисмэтч/недоступность
  источника).
- `openspec/specs/registry-sync-window/spec.md` — сценарии FR-41 (значение после sync/отсутствие
  sync/отсутствие мутации при повторных чтениях).

**Архитектурный контекст для тестов:**
- Компоненты: `transcript_identity.py` (чистые функции — unit), `cmd_get_transcript` (оркестрация
  двух вызовов клиента — integration с моком транспорта), `_cmd_dashboard` (чтение `meta` —
  integration с реальной/тестовой SQLite).
- Границы доверия: `KTalkClient` → API контура (мокается на границе HTTP, не выше).

**Edge cases / граничные условия:**
- Оба множества (спикеры/участники) пусты одновременно — `inconclusive`, не `match` и не
  `mismatch` (не путать «нечего сравнивать» с «совпало»).
- `get_recording` возвращает 4xx/5xx/таймаут при включённой по умолчанию сверке — `not_checked`,
  основной транскрипт всё равно печатается, код возврата команды остаётся 0.
- `--chunk N` вне диапазона + сверка по умолчанию + `--json` — `identity_check` не добавляется
  (edge case парсинга, см. «Оркестрация» выше), regression-тест на этот путь отдельно от
  основного JSON-envelope теста.
- `--no-verify-identity` передан явно — второй сетевой вызов не происходит вовсе (regression-тест
  на отсутствие вызова `get_recording`, не только на отсутствие поля в выводе).
- `dashboard --json` на свежей БД без единого `sync` — `last_synced: null`, не отсутствие ключа.
- Серия вызовов `dashboard --json` подряд — статусы записей реестра не меняются (регрессия
  побочного эффекта, AC3 FR-41).

**Рекомендация по пирамиде тестов:**

| Группа AC | Уровень | Обоснование |
|---|---|---|
| NFR-17 match/mismatch/inconclusive | unit | чистые функции `transcript_identity.py`, входы — фикстуры JSON |
| NFR-17 not_checked (отказ `get_recording`) | integration | мок транспорта `KTalkClient`, оркестрация двух вызовов |
| FR-41 значение/отсутствие/немутирующее чтение | integration | реальная тестовая SQLite через `Registry` |
