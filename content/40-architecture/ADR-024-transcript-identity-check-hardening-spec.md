---
title: "ADR-024 spec: детализация ужесточения сверки идентичности транскрипта"
properties:
  - name: Тип контента
    value: [Архитектура]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# ADR-024 spec: громкий отказ, устойчивость anonymousId, сигнал на границе чанка

Companion-спека к [ADR-024](../00-project/adr/ADR-024-transcript-identity-check-hardening.md).
Решения — в ADR; здесь — методика перепроверки, компоненты, брифы Dev/DevOps, контракт
QA-author. Реализует [NFR-17](../30-requirements/transcript-identity-observability.md).

## §1 — Причинный анализ issue #5 (методика перепроверки)

Команды, выполненные заново в этой задаче (не перенесены из RES-006 без проверки):

| Утверждение | Команда | Результат |
|---|---|---|
| Клиентского кэша нет | `grep -rn "cache\|lru_cache\|_cache" src/ktalk_cli/` | пусто |
| Клиент строится заново на вызов | чтение `cli_content.py:163` (`_fetch`, `cmd_get_transcript`) | `async with KTalkClient.from_settings(Settings()) as client:` внутри корутины, вызываемой один раз на процесс |
| `_shared_client` не используется | `grep -rn "get_shared_client" src/ tests/` | одно вхождение — само определение (`client.py:343`), ни одного вызывающего |
| Cookie-jar не даёт sticky-сессии | чтение `client.py:81-88` | `_forget_response_cookies` — hook на `response`, `self._client.cookies.clear()` после каждого ответа |
| Прокси не задан в коде | `grep -rn "proxy\|trust_env\|HTTP_PROXY\|HTTPS_PROXY" src/` | пусто |

Структурный довод, добавленный этой задачей поверх RES-006: инцидент — четыре ОТДЕЛЬНЫХ
ОС-процесса, каждый с одним вызовом `get-transcript`. Python не делит объекты модуля между
процессами; поэтому ЛЮБОЙ кэш, будь он реализован, был бы кэшем **одного** процесса и
структурно не мог бы отдать чужому процессу чужой результат — гипотеза «перепутанный кэш»,
как она сформулирована в issue («ключевать кэш по `recording_id`»), не совместима с топологией
инцидента независимо от того, есть кэш в коде или нет. Единственный ресурс, разделяемый
параллельными процессами ОДНОГО оператора, — файл session-токена/переменная окружения
(`token_file.py`, `config.py`) — это карта наблюдения (RES-006, Г1), не подтверждённая причина:
локализация требует живого теста с двумя разными токенами на одном наборе `recording_id`,
санкции на который эта задача не имеет и не запрашивает.

## §2 — Методика измерения issue #8

`ktalk auth-status --json` вернул `{"alive": true}` — контур доступен, замер выполнен, не
принята консервативная ветка по умолчанию. Метод:

1. `ktalk list --json` → список `recording_id` реестра оператора (только идентификаторы, без
   имён встреч в дальнейшей обработке).
2. Для каждого — `KTalkClient.get_recording(rid)`, отбор записей с `participants[].isAnonymous`.
3. Для отобранных — `KTalkClient.get_transcript(rid)`, извлечение `tracks[].speaker`/
   `diarizedSpeaker` с `isAnonymous`.
4. Сравнение `(anonymousId, anonymousName)` между двумя источниками — булево равенство, значения
   в вывод не печатались (только SHA-256-префиксы для собственной проверки в ходе задачи).

Выборка: из записей реестра оператора на 2026-09-04 часть несла анонимных участников; из них
часть анонимов реально говорила (появилась в `tracks[]`) — только эти пригодны для сравнения
(не говоривший аноним есть в `participants`, но ни в одном треке, сравнивать не с чем — это
`inconclusive`-по-построению случай, не сигнал о нестабильности). У всех пригодных для сравнения
анонимов — точное совпадение `anonymousId` и `anonymousName` между `get_recording.participants` и
`tracks[].speaker`. Выборка мала (единицы пар в единицах встреч) — измерение подтверждает
устойчивость для наблюдавшегося случая, не для всех топологий контура (например, вебинар с
одновременно множеством анонимных гостей не наблюдался).

## §3 — Компоненты, issue #9

Перепроверено при подготовке ADR: `get_recording` на пути `--chunk N` вне диапазона сегодня
ДЕЙСТВИТЕЛЬНО вызывается, несмотря на комментарий «сверять нечего» — `cmd_get_transcript`
вызывает `_verify_transcript_identity` до вызова `render_transcript_output`, порядок вызовов не
зависит от чанка; только СБОРКА вывода (`_render_transcript_with_identity`) отбрасывает
`identity_check`, ловя `JSONDecodeError` при разборе уже отрендеренного текста.

| Компонент | Ответственность | Входы | Выходы | Зависимости |
|---|---|---|---|---|
| `formatters.py` (новая функция, рабочее имя `resolve_chunk_range`) | Определяет валидность `--chunk` и `total_chunks` из уже полученных данных, без сети | `data` (транскрипт), `fmt`, `chunk`, `chunk_size` | `(in_range: bool, total_chunks: int)` | нет (чистая функция, переиспользует внутренности `chunk_transcript_raw`/`chunk_transcript_markdown`) |
| `cli_content.py::cmd_get_transcript` | Порядок: сначала определить валидность чанка, затем решать о сверке | `resolve_chunk_range(...)` | пропуск `_verify_transcript_identity` при `in_range is False` | `formatters.resolve_chunk_range` |
| `cli_content.py::_render_transcript_with_identity` | Сборка `--json`-конверта без `try/except JSONDecodeError` на этом пути — валидность уже установлена заранее | `output_text`, `identity_check`, `json_flag` | `{"transcript" \| "error": …, "identity_check": …}` | — |

### Оркестрация (заменяет шаг 4 companion-спеки ADR-023)

1. `data = await client.get_transcript(recording_key)` — без изменений.
2. `in_range, total_chunks = resolve_chunk_range(data, fmt, args.chunk, args.chunk_size)` — новый
   шаг, локальный, без сети.
3. Если `not in_range`: `identity_check = {"result": "not_checked", "reason":
   "chunk_out_of_range"}`, `_verify_transcript_identity` НЕ вызывается.
4. Если `in_range` и не передан `--no-verify-identity`: сверка выполняется как сегодня (ADR-023
   §1, шаг 2).
5. Сборка вывода:
   - markdown: без изменений — `identity_check["reason"]` уже печатается хвостом
     (`_render_transcript_with_identity`, ветка `not json_flag`).
   - `--json`, `in_range`: без изменений — `{"transcript": parsed, "identity_check": …}`.
   - `--json`, `not in_range`: `{"error": f"Чанк {chunk} не существует. Всего чанков:
     {total_chunks}", "identity_check": identity_check}` — валидный JSON, без `try/except`.

## Границы

- Не чинит причину подмены (issue #5) — RES-006 и §1 этой спеки её не локализуют, только
  ужесточают наблюдаемость отказа кодом возврата.
- Не меняет ключ сравнения анонимов (issue #8) — измерение не показало основания.
- Не кэширует `get_recording` между вызовами `get-transcript` — каждый вызов, где сверка
  выполняется, платит сетевой ценой заново (ADR-023 Границы, не пересматривается).

## Data flow

`get_transcript` → `resolve_chunk_range` (локально, без сети) → ветвление: вне диапазона →
`identity_check = not_checked/chunk_out_of_range`, без сети; в диапазоне → `get_recording` →
`check_identity` → `match`/`mismatch`/`inconclusive` → код возврата (3 только на `mismatch`) →
сборка вывода (markdown-хвост или `--json`-конверт). Порядок вызовов детализирован в §3
«Оркестрация» выше; отдельная диаграмма не заводится — последовательность линейна, без
разветвлений, требующих визуализации сверх таблицы шагов.

## NFR Mapping

- `### Requirement: A transcript response's recording identity is independently verifiable`
  (openspec `recording-data-access`) → §1: код возврата 3 на `mismatch` делает расхождение
  наблюдаемым на уровне процесса, не только тела ответа (новый `#### Scenario:` ниже).
- Тот же Requirement → §3: `not_checked` с `reason: chunk_out_of_range` сохраняет различение
  «сверено»/«не сверено»/«сверка не запускалась» и на границе чанка, не роняя команду.

### Дополнение капабилити-спеки

`openspec/specs/recording-data-access/spec.md`, раздел «A transcript response's recording
identity is independently verifiable…», получает два новых сценария (текст — задача этого SA,
элаборация уже принятого NFR-17, не новое требование):

```
#### Scenario: A detected mismatch fails loudly, not silently

- WHEN identity verification reports `mismatch` for a `get-transcript` response
- THEN the command SHALL exit with a nonzero status code distinct from a usage error and from a
  hard fetch failure, in addition to carrying `identity_check.result == "mismatch"` in its output

#### Scenario: An out-of-range chunk request does not silently drop the verification signal

- WHEN `get-transcript` is called with a chunk index outside the valid range
- THEN identity verification SHALL NOT be attempted over the network, and the response SHALL
  still carry an explicit `identity_check.result == "not_checked"` naming the chunk as the reason
```

## Контракт с QA-author

**Сценарии приёмки (полный список из капабилити-спеки):**
`openspec/specs/recording-data-access/spec.md`, раздел «A transcript response's recording
identity is independently verifiable, not assumed from a successful call» — все пять сценариев
(три существующих + два новых выше).

**Архитектурный контекст:**
- Компоненты: `transcript_identity.py` (не меняется), `formatters.py::resolve_chunk_range`
  (новая чистая функция), `cli_content.py::cmd_get_transcript`/`_render_transcript_with_identity`
  (реордер вызовов + envelope без `try/except`).
- Границы доверия: `KTalkClient` → API контура, мокается на границе HTTP.
- Причина issue #5 не локализована — тесты на неё не проектируются (нет воспроизводимого
  триггера), только на наблюдаемый эффект (код 3 на mismatch).

**Edge cases / граничные условия:**
- `mismatch` → код возврата 3, тело ответа (`transcript`+`identity_check`) печатается полностью
  (не пусто).
- `not_checked`/`inconclusive`/`match` → код 0, без изменений.
- `--chunk` вне диапазона + умолчание-сверка + `--json` → **ноль** вызовов `get_recording`
  (regression на снятие лишнего сетевого вызова, было — два), валидный JSON с `error` и
  `identity_check.result == "not_checked"`, `reason == "chunk_out_of_range"`.
- `--chunk` вне диапазона + `--no-verify-identity` → поведение не меняется (без `identity_check`
  вовсе, как и сегодня).
- `--chunk` в диапазоне — путь §3 не активируется, поведение ADR-023 без изменений.
- Anonymous-only встреча (issue #8) — тест на `check_identity` с обоими множествами, целиком
  состоящими из одинаковых `anonymousId`/`anonymousName` — должен остаться `match` (уже
  покрыто `test_nfr17_boundary_anonymous_participants_identified_by_anonymous_id`, регресса не
  вносит).

**Рекомендация по пирамиде тестов:**

| Группа AC | Уровень | Обоснование |
|---|---|---|
| Код 3 на `mismatch`, код 0 на прочих исходах | integration | оркестрация `cmd_get_transcript`, мок транспорта |
| `resolve_chunk_range` (валидность/total_chunks) | unit | чистая функция, фикстуры JSON |
| Ноль сетевых вызовов на `--chunk` вне диапазона | integration | мок транспорта `KTalkClient`, проверка числа запросов |
| `--json` envelope на `not_checked`/`chunk_out_of_range` | integration | тот же мок, разбор итогового JSON |

## Бриф для Dev

**Архитектура:** этот документ + [ADR-024](../00-project/adr/ADR-024-transcript-identity-check-hardening.md)
**Требование:** NFR-17
**Фаза:** Production

**Реализовать:**
- `formatters.py`: `resolve_chunk_range(data, fmt, chunk, chunk_size) -> tuple[bool, int]` —
  вынести вычисление `total_chunks`/`chunk_index` из `render_transcript_output` в переиспользуемую
  форму (или переиспользовать существующую внутреннюю логику без дублирования кода чанкинга).
- `cli_content.py::cmd_get_transcript`: реордер — `resolve_chunk_range` до
  `_verify_transcript_identity`; при `not in_range` — `identity_check` формируется локально
  (`not_checked`/`chunk_out_of_range`), сеть на сверку не идёт; при `mismatch` — `return 3` вместо
  `return 0` в конце функции (остальные исходы — `return 0`, как сегодня).
- `cli_content.py::_render_transcript_with_identity`: убрать `try/except JSONDecodeError` на пути
  вне диапазона — валидность уже известна вызывающей стороне, формировать `{"error": …,
  "identity_check": …}` явно.
- `README.md`/справочник кодов возврата — добавить код 3 рядом с 1/2.
- Версия пакета — минимум минорная (ломает закреплённый тестом `rc == 0` на `mismatch` и форму
  `--json` на `--chunk` вне диапазона, обе — не breaking change контракта данных, но
  поведенческие правки, заслуживающие видимости в CHANGELOG).

**Порядок:** fixtures (mismatch; чанк вне диапазона с умолчанием-сверкой; чанк вне диапазона с
`--no-verify-identity`) → `resolve_chunk_range` → реордер `cmd_get_transcript` → тесты (правка
существующего `test_nfr17_ac1_mismatch_surfaced_in_default_on_json_response`, дописывающего
`assert rc == 0`, на `assert rc == 3`; правка
`test_nfr17_out_of_range_chunk_with_default_verify_does_not_crash_on_json_parse` на ноль сетевых
вызовов вместо двух).

**Acceptance scenarios:** `#### Scenario: A detected mismatch fails loudly, not silently`,
`#### Scenario: An out-of-range chunk request does not silently drop the verification signal` —
`openspec/specs/recording-data-access/spec.md`.

## Бриф для DevOps

Изменение не затрагивает инфраструктуру — CLI без рантайм-сервиса. Единственный операционный
эффект: код возврата 3 у `get-transcript` — если `ktalk-registry` плагина-обёртки или любой
внешний оркестратор трактует ЛЮБОЙ ненулевой код как фатальный сбой конвейера, ему нужно отдельно
обработать код 3 (мисматч идентичности) не как отказ инфраструктуры, а как сигнал требуемого
ручного разбора записи. Рунбука не требуется — не production incident response, а контракт
интеграции, брифуется потребителю (репозиторий `ktalk-plugin`) отдельной задачей той стороны.

**NFR из BA:** NFR-17 (обнаружимость подмены — теперь на уровне процесса, не только тела ответа).
