---
title: "DEV-002 (волна 3, вторая половина): перенос активов в плагин ktalk"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-002 (волна 3, вторая половина): перенос активов в плагин ktalk

Перенос 11 файлов `.claude/` из vault'а `naumen-cto` (read-only источник,
`/Users/mdemyanov/Documents/naumen-cto/.claude/`) в отдельный git-репозиторий
`/Users/mdemyanov/Devel/ktalk-plugin` с депараметризацией по ADR-012 и
`ktalk-plugin-spec.md` (SA-003). Первая половина DEV-002 (сверка CLI/MCP) —
`dev-002-cli-mcp-coverage.md`, предпосылка этой задачи (использованы точные
имена и флаги новых CLI-команд). `analysis-quality.v1.md` не перенесён —
явное решение таблицы «Три дома» (ADR-012-spec): устаревший снапшот, дублирует
действующий `analysis-quality.md`.

## Дерево плагина

```
ktalk-plugin/
├── agents/
│   ├── ktalk-processor.md          (201 строка, было 436)
│   ├── ktalk-evaluator.md
│   └── references/
│       ├── two-pass-analysis.md
│       ├── protocol-template.md
│       └── vault-update-and-report.md
├── commands/
│   └── ktalk-registry.md
└── skills/
    ├── ktalk-eval/
    │   ├── SKILL.md
    │   ├── _meta.md
    │   └── references/eval-rubric.md
    └── ktalk-registry/
        ├── SKILL.md
        ├── _meta.md
        └── references/
            ├── analysis-quality.md
            └── registry-format.md
```

Отдельный git-репозиторий, локальный коммит, без remote — ADR-012 §4 (разные
циклы релиза пакета/плагина), решение о remote/публикации — за владельцем.

## Что заменено чем (было → стало)

| Было (привязка в vault'е) | Стало (источник значения в плагине) |
|---|---|
| `95_TRANSCRIPTS/{YYYY}/{date}_{type}_{title}.md` (зашито, 6 вхождений в `ktalk-processor.md` + 4 в `SKILL.md` + 4 в `registry-format.md` + 1 в `analysis-quality.md`) | `routing.transcript_archive` из `ktalk config show --json` — если ключ не объявлен, шаг явно помечает результат, не угадывает путь |
| `20_MEETINGS/committees/{id}/{date}.md`, `20_MEETINGS/standups/{date}.md` (SKILL.md, автопредложения места сохранения) | `routing.committee`/`routing.standup` из конфига хозяина; при отсутствии ключа — путь не предлагается автоматически, только ручной ввод |
| `10_PEOPLE` (grep-путь профилей, ссылки в протоколе, 8 вхождений по 4 файлам) | `directories.people` из конфига; отсутствие — отдельная явная пометка от «каталог объявлен, но не существует» |
| `30_PROJECTS/active` (поиск проекта, делегирование project-curator) | `directories.projects_active` из конфига; отсутствие — шаг делегирования пропускается с пометкой |
| `Vault: /Users/mdemyanov/Documents/naumen-cto/` (абсолютный путь, оба агента) | убрано целиком; агент инструктирован читать раскладку через `ktalk config show --json`, для `ktalk-evaluator` — пути приходят целиком во входных параметрах промта (их уже разрешил `ktalk-eval` до запуска) |
| `mcp__ktalk__ktalk_get_transcript`/`ktalk_get_summary`/`ktalk_get_recording` (MCP-вызовы) | `ktalk get-transcript <id> --chunk N --json`, `ktalk get-summary <id> --json`, `ktalk get-recording <id> --json` (CLI, ADR-012 §2а) — точные флаги взяты из `cli_content.py`, не придуманы |
| `mcp__qmd__*` (обязательный вызов, без проверки доступности) | `mcp__qmd__*` остаётся, но каждый вызов обусловлен фактической доступностью инструмента в сессии (шаг 0в ядра `ktalk-processor.md`) — опциональная интеграция по ADR-012 §5, вариант (a) |
| Шаг 7 SKILL.md — дайджест новостей, захардкоженные адресаты `amuratov`/`drubin` | не перенесён целиком — вне границы волны (ADR-012 §6) |
| `.claude/docs/vault-config.md` (ссылка в `commands/ktalk-registry.md`) | заменена на инструкцию использовать `ktalk config show --json` |
| Ссылки `_meta.md` на `.claude/agents/...`, `.mcp.json` абсолютно | относительные пути внутри плагина (`../../agents/...`) |
| CTO-специфичные хардкоды (`mdemyanov`, `ktalk:668`, `40_DECISIONS`, `00_CORE/identity/priorities.md`) в `analysis-quality.md`/шаблоне протокола | обобщены до «владелец проекта-хозяина» / «карточка приоритетов, если объявлена» — не входили в явный список запрещённых строк постановки, но такой же природы хардкода, обобщены по той же логике из соображений качества, не по прямому требованию |

## Контракт деградации — где применён буквально

Формулировка взята из `ktalk-plugin-spec.md` («Контракт деградации») без
перефразирования по существу:
- `ktalk-processor.md` шаг 0в: `qmd` и `directories.people` проверяются
  независимо, недоступность одной не останавливает шаг целиком (FR-24 AC2).
- Различение «ключ не объявлен» vs «каталог объявлен, но не существует» —
  проведено во всех трёх местах, где это применимо (`ktalk-processor.md`,
  `SKILL.md`, `analysis-quality.md`).
- `integrations.qmd = true` в конфиге — трактуется как заявленное намерение,
  не заменяет фактическую проверку доступности инструмента на старте шага.

## qmd — вариант (a), как решил владелец

Шаги сопоставления участника с профилем и поиска проекта (`ktalk-processor.md`
шаг 3, `SKILL.md` шаг 4.1) сохраняют вызовы `mcp__qmd__*`, но каждый обусловлен
проверкой из шага 0в. Инструмент объявлен в `tools:` фронтматтера агента —
это декларация доступности инструмента платформе, не гарантия его наличия в
конкретном проекте-хозяине (тот же принцип, что для MCP-сервера `ktalk` самого
плагина).

## Расхождения со спекой (с обоснованием)

- **`analysis-quality.md` Appendix — примеры анонимизированы.** Спека прямо не
  требует анонимизации примеров (они не входят в список запрещённых строк —
  `95_TRANSCRIPTS`/`20_MEETINGS`/`10_PEOPLE`/`30_PROJECTS`/абс. пути/секреты), но
  реальные имена участников встреч vault'а (`Муратов`, `Демьянов`, `Бутяйкин`,
  `Рубин`) — персональные данные конкретных людей хозяина, не относящиеся к
  контуру ktalk как продукту. Заменены на «Участник А/Б» с сохранением сути
  примеров (какие ошибки калибруют качество анализа) — решение по духу NFR-16
  (разграничение данных ktalk и артефактов хозяина), не по букве явного
  критерия приёмки.
- **README плагина не создан.** Постановка прямо выносит `plugin.json`/
  `.mcp.json`/marketplace-манифест в DEV-003; README, документирующий
  предусловие `uv tool install ktalk-mcp` (ADR-012 §2), логически относится к
  тому же пакету поставки — не создавал, чтобы не предвосхищать состав DEV-003
  до security review.
- **`references/two-pass-analysis.md`/`protocol-template.md`/
  `vault-update-and-report.md` — новое разбиение, не 1:1 со старыми номерами
  шагов.** Спека требует «ядро + reference-файлы» без фиксации конкретных имён
  файлов — разбиение по функции (алгоритм анализа / шаблон протокола / гибридное
  обновление и отчёт), не по буквальному копированию границ секций оригинала.

## Проверки (вывод команд)

### grep дерева плагина — критерий приёмки

```
$ cd /Users/mdemyanov/Devel/ktalk-plugin && grep -rn '95_TRANSCRIPTS\|20_MEETINGS\|10_PEOPLE\|30_PROJECTS\|/Users/' .
(пусто)

$ grep -rn 'mcp__qmd__' .
agents/ktalk-processor.md:13-16     (объявление в tools: фронтматтера — доступность инструмента)
agents/ktalk-processor.md:88        (проверка доступности в шаге 0в — блок деградации)
agents/ktalk-processor.md:150,155,159,162  (вызовы внутри шага 3, обусловленного шагом 0в)
skills/ktalk-registry/SKILL.md:135  (вызов внутри шага 4.1, обусловленного независимой проверкой)
skills/ktalk-registry/references/analysis-quality.md:136  (вызов, помечен "если qmd доступен")
Все вхождения — внутри опциональной интеграции (ADR-012 §5, вариант a). Не голое
требование без деградации ни в одном месте.

$ grep -rniE 'KTALK_.*(TOKEN|KEY)' .
skills/ktalk-registry/SKILL.md:83   упоминание ИМЕНИ переменной в тексте про
                                     диагностику ошибки sync ("истёк
                                     KTALK_SESSION_TOKEN") — не значение, значение
                                     секрета в плагин не попадало ни на одном шаге
                                     переноса (источник — промты vault'а, там тоже
                                     только имя переменной, не значение)

$ grep -rn 'ktalk\.ru' .
(пусто)
```

### Статус vault'а — не изменён

```
$ git -C /Users/mdemyanov/Documents/naumen-cto status --porcelain > before.txt   # снято до задачи
$ git -C /Users/mdemyanov/Documents/naumen-cto status --porcelain > after.txt    # снято после
$ diff before.txt after.txt
(пусто — идентичны, 78 строк существовавших до задачи изменений, ни одна не моя)
```

### Пакет ktalk-mcp — не сломан

```
$ uv run pytest -q
420 passed in 11.95s

$ bash scripts/check.sh --fast
Errors: 0 | Warnings: 3 (грандфазер-warnings, существовали до задачи)
```

### Размер ядра `ktalk-processor.md`

```
$ wc -l ktalk-plugin/agents/ktalk-processor.md
201 ktalk-plugin/agents/ktalk-processor.md
```

201 против исходных 436 — заметно меньше; объёмные блоки (детальный алгоритм
двухпроходного анализа, шаблон протокола, гибридное обновление/отчёт) вынесены
в `agents/references/*.md` (56–125 строк каждый), ядро содержит только
управляющую логику шагов со ссылками.

## Не покрыто этой задачей

- `plugin.json`/`.mcp.json`/marketplace-манифест плагина — DEV-003, после
  security review (прямое указание постановки).
- Живая проверка на vault'е `naumen-cto` (cutover) — операция владельца
  (OPS-001 runbook, ADR-012-spec), не автоматизируется этой задачей.
- Remote для `ktalk-plugin` — решение владельца, не выполнялось.

## Связанные статьи

- [ADR-012: границы плагина ktalk](../00-project/adr/ADR-012-plugin-boundary.md)
- [ADR-012-spec: детализация границ плагина](../40-architecture/ADR-012-plugin-boundary-spec.md) — таблица «Три дома», источник состава переноса
- [Конфигурация проекта-хозяина плагина ktalk (SA-003)](../40-architecture/ktalk-plugin-spec.md) — формат `.ktalk.toml`, контракт деградации, JSON-контракт `ktalk config show`
- [DEV-002 (волна 3, первая половина): сверка CLI/MCP](dev-002-cli-mcp-coverage.md) — источник точных CLI-флагов, использованных при депараметризации
- [DEV-001 (волна 3): конфиг хозяина и центральное хранилище](dev-001-host-config-and-store.md) — `host_config.py`/`ktalk config show`, на который опирается вся депараметризация
