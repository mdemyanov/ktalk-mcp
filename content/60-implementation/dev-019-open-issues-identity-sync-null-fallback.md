---
title: "DEV-019: сверка идентичности транскрипта, last_synced, регресс null-id"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-019: реализация по стабам QA-013 (ADR-023, ред. 2a2f6e3)

Реализация под 22 красных стаба QA-013 (`content/40-architecture/at-design-adr023-open-issues.md`):
NFR-17 (сверка идентичности транскрипта, включена по умолчанию), FR-41 (`last_synced` в
`dashboard --json`), issue #3 (`.get(id, fallback)` не срабатывает на явном `null`).

## Файлы

| Файл | Что | Строк |
|---|---|---|
| `src/ktalk_cli/transcript_identity.py` (новый) | `_identity_key`, `speaker_identities`, `participant_identities`, `check_identity` — чистые функции NFR-17 | 69 |
| `src/ktalk_cli/cli_content.py` | `--no-verify-identity`, `_verify_transcript_identity`, `_render_transcript_with_identity`, `cmd_get_transcript` переписан | 167 → 221 |
| `src/ktalk_cli/cli.py` | `_cmd_dashboard`: одна строка `"last_synced": reg.get_meta("last_synced")` | 445 (без изменений в строках) |
| `src/ktalk_cli/formatters.py` | `format_recording`/`format_recordings_list`: `.get(k, fallback)` → `.get(k) or fallback` (issue #3) | 589 (без изменений в строках) |
| `tests/test_cli_content.py` | 2 существующих теста получили `--no-verify-identity` (см. ниже) | — |

`src/ktalk_cli/registry.py` не тронут (грандфазер 562 строки).

## Расхождение со спекой: два существующих теста потребовали правки

Companion-спека и at-design описывают только новые стабы; они не предупреждают о коллизии с
двумя ДОЕЗДА-002 тестами (`tests/test_cli_content.py`):
`test_get_transcript_json_default_returns_raw_json` и `test_get_transcript_markdown_default`.
Оба вызывали `get-transcript` без флага и ожидали ровно один сетевой вызов / плоский JSON
(`out["status"]`) — это была форма ДО ADR-023 §1. После того, как сверка стала умолчанием,
оба теста по своему прежнему тексту требовали бы второй мок (`get_recording`) и обёрнутый
`{"transcript": ...}` ответ — то есть фактически тестировали бы NFR-17 у пробела покрытия,
не относящегося к их предмету (форма raw/markdown вывода).

Правка: добавлен `--no-verify-identity` в оба вызова `main([...])`, поведение и ассерты не
менялись. Это не ослабление теста — предмет теста (форма вывода get-transcript) остался
проверен буквально тем же ассертом; сверка идентичности по умолчанию отдельно и полно
покрыта `tests/test_nfr17_identity_verification.py` (14 тестов, включая явный тест
умолчания-включено `test_nfr17_default_on_no_flag_calls_get_recording_and_adds_identity_check`).
Альтернатива (переписать оба теста на мок `get_recording` и распаковку `out["transcript"]`)
дублировала бы уже существующее покрытие NFR-17 без нового сигнала.

## Реализация NFR-17 — детали

- `_identity_key` повторяет приоритет `_format_user_name(with_id=True)` (`formatters.py`), но
  возвращает сырой токен: `userInfo.key or .login` для именованных, `anonymousId or
  anonymousName` для `isAnonymous: true`, `None` для пустой ссылки.
- `speaker_identities`/`participant_identities` — `set[str]`, `None` не подмешивается.
- `check_identity` — 3 исхода (`inconclusive`/`match`/`mismatch`); `not_checked` — уровень
  оркестрации `_verify_transcript_identity` (`try/except` вокруг `client.get_recording`,
  маскирование `redact_secrets`, тот же барьер NFR-5, что у основной ошибки команды).
- `_render_transcript_with_identity` — отдельная чистая функция сборки вывода (markdown-строка
  vs JSON-обёртка), вынесена из `cmd_get_transcript`, чтобы не приближаться к порогу 100 строк
  на функцию (C13). `json.loads` на `output_text` при `--chunk` вне диапазона кидает
  исключение — перехвачено, `identity_check` в этом случае не добавляется, текст об
  отсутствующем чанке печатается как есть (edge case companion-спеки).

## Проверки

```
uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
```
→ **592 passed, 0 failed** (`f18e1c6` — базис, все узлы зелёные).

Расхождение с целью брифа «587 passed» (арифметика брифа: базис 565 + 22 закрытых стаба =
587). Фактический базис прогона (`at-design-adr023-open-issues.md`, «Базис прогона») —
**570 passed / 22 failed** = 592 неудалённых теста (565 исходных + 5 green-guard стабов,
уже проходивших на момент коммита стабов, + 22 red). 570 + 22 = 592, не 587 — итоговые 592
согласуются с зафиксированным QA-author базисом, не с числом в брифе; расхождение
арифметическое (в брифе), не результат добавленных/удалённых тестов с моей стороны (единственная
правка существующих тестов — `--no-verify-identity` в двух местах, без изменения числа тестов).

```
bash scripts/check.sh --fast   → Errors: 0 | Warnings: 4 (все — грандфазеры, не задеты)
bash scripts/check.sh --full   → PASS=22/24 (обе внутренние сьюты гейта), Errors: 0
```

## Что НЕ реализовывалось (по companion-спеке)

- Дом OPS-001 (issue #7) — задача DevOps, не входит в бриф Dev.
- Живое конкурентное воспроизведение подмены (RES-006) — вне автоматизации, нет санкции.
