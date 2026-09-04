---
title: "AT-design: волна 2 открытых issue — громкий отказ, сигнал вне диапазона чанка"
properties:
  - name: Тип контента
    value: [Test Design]
  - name: Фаза
    value: [Production]
  - name: Статус
    value: [Draft]
---

# AT-design: волна 2 открытых issue (NFR-17 — Д1/Д3 ADR-024)

Тест-дизайн и красные тесты QA-author к [ADR-024](../00-project/adr/ADR-024-transcript-identity-check-hardening.md)
и его [companion-спеке](ADR-024-transcript-identity-check-hardening-spec.md). Источник AC —
[transcript-identity-observability.md](../30-requirements/transcript-identity-observability.md)
(NFR-17, тот же документ, что и волна 1); капабилити-спека —
[recording-data-access/spec.md](../../openspec/specs/recording-data-access/spec.md), два новых
`#### Scenario:` этого раздела. Продолжает
[at-design-adr023-open-issues.md](at-design-adr023-open-issues.md) — не дублирует таблицу волны 1
(NFR17-AC1…AC3, FR-41, issue #3), только AC4/AC5.

Красная линия роли: код реализации не пишется (`formatters.py::resolve_chunk_range`,
`cli_content.py::cmd_get_transcript`/`_render_transcript_with_identity` — Dev). Тесты живут в
существующей сьюте `tests/test_nfr17_identity_verification.py` (не новый файл — тот же предмет,
NFR-17, только новый ADR поверх него), красные ветки падают на `AssertionError`/`ImportError`
(последний — только на `resolve_chunk_range`, функции ещё нет; импорт внутри тела теста, файл
собирается целиком).

Д2 (issue #8, устойчивость `anonymousId`) не меняет код — companion-спека §2 фиксирует измерение
на живом контуре, не тест. Здесь нет отдельной строки: уже существующий
`test_nfr17_boundary_anonymous_participants_identified_by_anonymous_id` (волна 1) остаётся
зелёным guard'ом на тот же ключ сравнения, регресса не вносит.

## Покрытие AC — NFR17-AC4 (Д1, issue #5)

| AC ID | `#### Scenario:` капабилити-спеки | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR17-AC4 | «A detected mismatch fails loudly, not silently» | `mismatch` -> `rc == 3`, `rc not in (0,1,2)`, `out["transcript"]` не пуст | integration | `test_nfr17_ac4_mismatch_exits_with_code_3_and_still_carries_full_body` | red — сегодня `rc == 0` |
| NFR17-AC4 (испорченный ввод) | N/A, явно | опечатанный `recording_key` не воспроизводит `mismatch` (даёт согласованный `match` на чужом составе, или `not_checked` через 404 — уже покрыто волной 1) — причина issue #5 не локализована, нет воспроизводимого клиентского триггера | — | — | N/A (обоснование в докстринге теста и `content/00-project/adr/ADR-024-…md` §Д1) |
| NFR17-AC4 (замаскированный отказ) | то же — это сам предмет решения | до правки `mismatch` тонул в `rc == 0`; тест проверяет явно, что маска снята | integration | тот же тест, тот же assert | red |

## Покрытие AC — NFR17-AC5 (Д3, issue #9)

| AC ID | `#### Scenario:` капабилити-спеки | Assertion outline | Тип | Тест-функция | Статус |
|---|---|---|---|---|---|
| NFR17-AC5 | «An out-of-range chunk request does not silently drop the verification signal» | `--chunk` вне диапазона -> 0 вызовов `get_recording` (счётчик по URL, не общий счётчик запросов), валидный JSON, `identity_check.result == "not_checked"`, `reason == "chunk_out_of_range"` | integration | `test_nfr17_ac5_out_of_range_chunk_with_default_verify_skips_network_call_and_signals_not_checked` | red — сегодня 1 сетевой вызов на сверку, JSON невалиден |
| NFR17-AC5 (валидность/`total_chunks`) | то же, на уровне компонента | `resolve_chunk_range`: чанк в середине/на границе/за границей/`0`→первый чанк | unit | `test_nfr17_ac5_resolve_chunk_range_reports_in_range_for_a_middle_chunk`, `…_boundary_last_valid_chunk_is_in_range`, `…_one_past_last_chunk_is_out_of_range`, `…_auto_chunk_zero_maps_to_first_chunk` | red — `ImportError`, функции нет |
| NFR17-AC5 (испорченный ввод) | то же | `--chunk -1` (структурно бессмысленный ввод, не просто «больше диапазона») -> тот же `not_checked`/`chunk_out_of_range`, 0 вызовов `get_recording` | integration + unit | `test_nfr17_malformed_negative_chunk_index_also_skips_network_call_and_signals_not_checked`, `test_nfr17_malformed_resolve_chunk_range_negative_chunk_is_out_of_range` | red |
| NFR17-AC5 (замаскированный отказ) | то же — это сам предмет решения | до правки сверка ВЫПОЛНЯЛАСЬ (сетевой вызов оплачивался), но результат тихо терялся `JSONDecodeError`-веткой сборки `--json` — неотличимо от «сверка прошла» на уровне формы ответа | integration | тот же `test_nfr17_ac5_out_of_range_chunk_with_default_verify_skips_network_call_and_signals_not_checked` — проверяет и нулевой вызов, и структурированный `reason` | red |
| — (регресс, `--no-verify-identity` + чанк вне диапазона) | границы решения, companion-спека «Edge cases»: поведение не меняется | 0 вызовов, `identity_check` отсутствует, текстовое сообщение доходит как есть | integration | `test_nfr17_out_of_range_chunk_with_no_verify_identity_is_unaffected_by_hardening` | green (guard) — уже верно сегодня; мутационно проверено (временная порча `--no-verify-identity` на игнорирование флага дала явный `AssertionError` на этом тесте, откачена без диффа) |

## Правки существующих тестов волны 1 (не регресс — смена контракта)

| Тест | Старое утверждение | Новое утверждение | Причина |
|---|---|---|---|
| `test_nfr17_ac1_mismatch_surfaced_in_default_on_json_response` → переименован в `test_nfr17_ac4_mismatch_exits_with_code_3_and_still_carries_full_body` | `assert rc == 0` (закреплял тихий код на `mismatch`) | `assert rc == 3`, `assert rc not in (0,1,2)`, `assert out.get("transcript") is not None` | ADR-024 §Д1 отменяет ровно это старое поведение («отказ становится громким», не «гонка устранена») |
| `test_nfr17_out_of_range_chunk_with_default_verify_does_not_crash_on_json_parse` → переименован в `test_nfr17_ac5_out_of_range_chunk_with_default_verify_skips_network_call_and_signals_not_checked` | `assert len(httpx_mock.get_requests()) == 2` (сверка обязана произойти дважды), `assert "не существует" in raw` (нестрого-JSON текст как есть) | `assert _count_recording_calls(httpx_mock, key) == 0`, `out = json.loads(raw)` (обязан быть валиден), `identity_check.result == "not_checked"`, `reason == "chunk_out_of_range"` | ADR-024 §Д3: сверка на этой ветке не должна запускаться вовсе; issue #9 называет прежнее поведение (тихая потеря результата в нестрого-JSON тексте) недостаточным |

Обе правки — предмет прямого указания companion-спеки ADR-024 («Контракт с QA-author», «Бриф для
Dev», раздел «Порядок»), не находка этой роли постфактум.

## Обязательные классы покрытия (волна 2)

### Испорченный/опечатанный ввод

- **NFR17-AC4**: N/A, обоснованно — `mismatch` есть сигнатура серверной кросс-контаминации
  (RES-006), не клиентской опечатки; опечатанный `recording_key`, для которого сервер отвечает
  СОГЛАСОВАННО на обоих путях, даёт `match` на чужом составе (не `mismatch`), а несогласованный
  (404 на `get_recording`) уже даёт `not_checked` — покрыто волной 1
  (`test_nfr17_malformed_mistyped_recording_key_get_recording_404_yields_not_checked`), не
  дублируется здесь.
- **NFR17-AC5**: `--chunk -1` — структурно бессмысленный (не просто «больше диапазона») ввод,
  которым пользователь мог опечататься; два теста (integration + unit на `resolve_chunk_range`)
  проверяют одинаковый исход с положительным значением вне диапазона.

### Замаскированный отказ

- **NFR17-AC4**: сам предмет решения — код 0 маскировал обнаруженный `mismatch` от
  потребителей, читающих только код возврата, не тело ответа.
- **NFR17-AC5**: сам предмет решения — до правки сверка выполнялась (сетевая цена
  оплачивалась), а её результат тихо терялся сборкой `--json` (`JSONDecodeError` → печать как
  есть). Тест проверяет не только «результат не пуст», но что сверка вовсе НЕ запускается (иначе
  утечка оплаченного, но не нужного вызова осталась бы незамеченной регрессией).

## Базис прогона

`uv run --with pytest-xdist --with pytest pytest tests/ -q -n 8` на момент написания: **591
passed, 8 failed** (было 592 passed/0 failed до этой задачи — расхождение на единицу: два
теста волны 1 переименованы и стали красными, шесть новых тестов добавлены). Каждый красный тест
падает на `AssertionError` со значением по обе стороны сравнения либо на `ImportError` внутри
тела теста (`resolve_chunk_range` — функции ещё нет, `formatters.py` не тронут); ни один — на
ошибке коллекции файла. Мутационная проверка единственного green-guard теста волны 2
(`test_nfr17_out_of_range_chunk_with_no_verify_identity_is_unaffected_by_hardening`) —
временная порча `cmd_get_transcript` (игнорирование `--no-verify-identity`) дала `AssertionError`
на этом и на смежном тесте волны 1 (`test_nfr17_no_verify_identity_flag_skips_second_call_entirely`),
откат без диффа подтверждён `git status --short`/`git diff --stat`.

## Не покрыто (out of scope)

- Причина исходной подмены (issue #5) — не локализована ADR-024 §Д1, тест на неё не
  проектируется (нет воспроизводимого триггера).
- Живое измерение устойчивости `anonymousId` (issue #8, Д2) — выполнено вручную SA на живом
  контуре (companion-спека §2), не автоматизируется этим тест-дизайном; санкции на повторный
  живой прогон у роли QA-author нет и не запрашивалась.
- Мониторинг кода 3 как сигнала инцидента у плагина-обёртки — вне пакета `ktalk-cli` (бриф
  DevOps companion-спеки).
