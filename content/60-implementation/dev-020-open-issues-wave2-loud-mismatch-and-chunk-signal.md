---
title: "DEV-020: волна 2 открытых issue — код 3 на mismatch, сигнал вне диапазона чанка"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Approved]
---

# DEV-020: реализация по стабам QA-author волны 2 (ADR-024, Д1/Д3)

Реализация под 8 красных тестов `content/40-architecture/at-design-adr024-open-issues-wave2.md`
поверх [ADR-024](../00-project/adr/ADR-024-transcript-identity-check-hardening.md) и его
[companion-спеки](../40-architecture/ADR-024-transcript-identity-check-hardening-spec.md).
Продолжает DEV-019 (волна 1, ADR-023). Д2 (issue #8, устойчивость `anonymousId`) — код не
менялся, закрыто измерением на живом контуре (companion-спека §2), не этой задачей.

## Файлы

| Файл | Что | Строк |
|---|---|---|
| `src/ktalk_cli/formatters.py` | новая `resolve_chunk_range(data, fmt, chunk, chunk_size) -> tuple[bool, int]`; чанкинг вынесен в общий `_chunk_transcript`, переиспользуется и `render_transcript_output`, и `resolve_chunk_range` | 590 → 626 |
| `src/ktalk_cli/cli_content.py` | `cmd_get_transcript`: `resolve_chunk_range` до `_verify_transcript_identity`, `identity_check = not_checked/chunk_out_of_range` без сети на пути вне диапазона, `return 3` на `mismatch`; `_render_transcript_with_identity`: параметр `in_range`, `try/except JSONDecodeError` убран | 221 → 233 |
| `README.md` | код возврата 3 задокументирован рядом с 0/1/2, строка `get-transcript` уточнена | — |
| `pyproject.toml`/`uv.lock` | 2.0.0 → 2.1.0 (минорная — поведенческая правка контракта, не breaking по форме данных) | — |

`transcript_identity.py` не тронут (ADR-024 §Д2 не меняет код).

## Реализация — детали

- **`resolve_chunk_range`** не дублирует чанкинг: и она, и `render_transcript_output`
  вызывают общий `_chunk_transcript(data, fmt, chunk_size, full_text)`. Тривиальная ветка
  (`chunk == 0` и текст короче `chunk_size`) отдаёт `(True, 1)` без реального чанкинга — та же
  оптимизация, что была у `render_transcript_output` до правки. Отрицательный `chunk`
  (`chunk != 0`) даёт `chunk_index = chunk - 1` — отрицательный индекс, диапазон
  `0 <= chunk_index < total_chunks` ложен без специального case (не Python-семантика
  отрицательной индексации, ловится сравнением, не срезом).
- **`cmd_get_transcript`**: `fmt` вычисляется до `_fetch`, чтобы `resolve_chunk_range` был
  доступен внутри корутины на том же `data`, что и `get_transcript`, без второго сетевого
  вызова. `in_range` возвращается из `_fetch` наружу и передаётся в
  `_render_transcript_with_identity` — валидность чанка отдаётся оттуда явно, вызывающая
  сторона не гадает по форме `output_text`.
- **`_render_transcript_with_identity`**: `in_range: bool = True` — параметр со значением по
  умолчанию, чтобы не задевать другие потенциальные вызовы (по факту единственный вызывающий —
  `cmd_get_transcript`, всегда передаёт явно). Вне диапазона строится
  `{"error": output_text, "identity_check": identity_check}` явным `json.dumps`, без
  `try/except` — валидность уже известна аргументом, а не выводится из того, распарсился ли
  `output_text` как JSON.
- Код возврата 3 проверяется ПОСЛЕ печати вывода (`print(...)` уже отработал) — тело ответа не
  теряется на пути к громкому коду, как того требует ADR-024 §Д1.

## Мутационная проверка (обе точки решения, откачено без диффа)

1. `return 3` → `return 0` на mismatch: `test_nfr17_ac4_mismatch_exits_with_code_3_and_still_carries_full_body`
   упал (`assert 0 == 3`). Откат подтверждён `git diff` (пусто).
2. `if in_range:` → `if True:` (сверка всегда запускается независимо от диапазона):
   `test_nfr17_ac5_out_of_range_chunk_with_default_verify_skips_network_call_and_signals_not_checked`
   упал (`assert 1 == 0` — сетевой вызов `get_recording` произошёл). Откат подтверждён.

## Проверки

```
uv run --with pytest-xdist --with pytest pytest tests/test_nfr17_identity_verification.py -q -n 8
  → 21 passed (13 существовавших зелёных + 8 бывших красных)

uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8
  → 599 passed (591 базис QA-author + 8 закрытых стабов)

uv run --with pytest pytest tests/ -q   (последовательный, перед коммитом)
  → 599 passed

bash scripts/check.sh --full
  → PASS=22/24 (внутренние сьюты гейта), ✓ check.sh --full — passed
```

`git diff 5773e09 -- tests/test_nfr17_identity_verification.py` — пусто: ни один из восьми
стабов QA-author не изменён.

## Наблюдение, не относящееся к этой задаче

`tests/test_concurrency.py::test_nfr13_busy_timeout_exhausted_raises_recognizable_operational_error`
— один раз упал при последовательном прогоне (timing-зависимый тест на реальном
`multiprocessing`, `busy_timeout=5000`, `join(timeout=15)`); воспроизведён identично на
немодифицированном дереве (`git stash` перед прогоном) — не регрессия этой задачи. Повторный
последовательный прогон дал 599/599 без правок кода. Не входит в NFR-17/ADR-024, не трогалось.

## Что НЕ реализовывалось (по ADR-024 границам)

- Причина issue #5 (межпроцессная подмена) — не локализована, код не меняет её причину, только
  громкость отказа.
- Ключ сравнения анонимов (issue #8) — не менялся, устойчивость подтверждена измерением SA.
