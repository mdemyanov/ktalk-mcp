# ktalk-cli

CLI `ktalk` для доступа к записям Контур.Толк (KTalk) и операционного реестра
записей на SQLite. MCP-слой снят ADR-022 целиком (был во фризе с ADR-015) —
единственная поверхность пакета сегодня — CLI.

## Стиль (безусловное правило)
Писать сухо и сжато — в ответах, коммитах, статьях `content/`, докстрингах.
Вывод, потом обоснование; без преамбул, повторов и похвалы. Нет факта — так и
сказать. Правило действует всегда и приоритетнее привычки к развёрнутости.

## Entry points
- `ktalk = ktalk_cli.cli:main` — единственная точка входа (реестр + чтение/запись контура)

## Commands
- `bash scripts/check.sh --fast` — гейты контура (тот же прогон, что на pre-commit)

## Architecture
Один пакет `ktalk_cli`, единая точка входа CLI.
- Планирование отдаёт только предпросмотр (`create-meeting-preview`), создание —
  отдельная подтверждаемая команда (ADR-005/ADR-016)
- Пути API живут в таблице `OPERATION_PROFILES` (`auth.py`), не хардкодом в методах —
  набор путей зависит от режима авторизации
- `calendar_reader.py`: окно календаря режется клиентом (сервер лимитирует 7 днями,
  потолок сегмента 100, `skip` не работает)
- `cli.py`: `_REGISTRY_FREE_COMMANDS` — команды, не открывающие БД
- `contour_diagnostics.py` — диагностика недокументированного контура (ADR-004)

## API Reference
Контракты, режимы авторизации и эмпирика поведения API (спеке верить нельзя) —
в `src/ktalk_cli/CLAUDE.md`, грузится при работе с файлами под `src/`.

## Conventions
- Async everywhere (httpx) — `fastmcp` снят ADR-022 вместе с MCP-слоем
- `ktalk get-transcript` поддерживает чанкинг: `--chunk` (0=авто, 1+=номер чанка), `--chunk-size` (символов, по умолчанию 30000)
- Ошибки API → человекочитаемые сообщения на русском
- Имена пользователей: `surname firstname`, fallback: `login` → `anonymousName` → "Неизвестный"
- Длительность: секунды → "X ч Y мин" или "X мин"

## CLI / реестр (registry)
- **SQLite — операционный source of truth**; `registry.md` в vault — генерируемое
  read-only зеркало (`ktalk export`), не редактировать руками.
- Статусы: `new → done|skipped|partial`, `partial → done`. Экспирация: записи
  `new` строго старше N дней (по умолчанию 7) → `skipped` при `sync`.
- Конкурентность: WAL + `busy_timeout=5000`, транзакция на операцию —
  параллельные `mark-*` из фоновых агентов безопасны.
- `--json` у всех команд печатает валидный JSON в stdout; ошибки — в stderr с
  ненулевым кодом возврата (навык/агент парсят stdout).
- Путь к БД бинарный → gitignore в vault (`.registry.db`, `-wal`, `-shm`).
- `ktalk migrate <vault>` — разовый импорт из markdown-реестров; парсер
  устойчив к 7/8-колоночным архивам и `|` внутри ячеек.

## Документарный контур (плагин nauta)
Решения живут в `content/`, не в этом файле и не в планах `docs/superpowers/`
(они остаются как есть, ретроспективно не переносятся). Решение принято —
пиши ADR; описываешь «что должно работать» — пиши требование.
- `content/00-project/` — roadmap и ADR; `10-domain/` — исследования;
  `30-requirements/` — требования и AC; `40-architecture/` — спеки и контракты;
  `60-implementation/` — заметки Dev о том, где реализация разошлась со спекой и почему;
  `70-operations/` — рунбуки DevOps (установка, миграция, откат; ADR-023 §3).
- Каждая статья (кроме `_index.md`) обязана нести `properties: - name: Тип контента`
  в object-нотации и быть достижимой по ссылке из `_index.md` — иначе гейт даёт
  error (нет типа) или warning (сирота).
- ADR длиннее 150 строк не проходит: детализация выносится в companion-спеку
  `content/40-architecture/<stem>-spec.md`.
- Роли вызываются как `/nauta:pm decompose <фича>`, дальше `/nauta:ba`, `/nauta:sa`,
  `/nauta:dev`, `/nauta:qa`. PM декомпозирует, но не пишет код.

## Пара «требование → контракт» (openspec/, ADR-021)
Требование из `30-requirements/` обязано нести строку `**Capability:**
openspec/specs/<capability>/spec.md` — путь к машинно-проверяемому контракту поведения
(`#### Scenario:`). Гейт nauta 0.26.0 (C15/C16) проверяет форму пути раньше его
существования: строка на несуществующую спеку красит дерево громче отсутствия строки — не
пиши её, пока файла спеки нет.
- `content/` несёт обоснование и решения, переживает эпик. `openspec/specs/…/spec.md` несёт
  контракт поведения, тоже переживает эпик, но отдельно от обоснования. Стор задач несёт
  состояние эпика (очередь, раунды, test-report) и никогда не попадает в `content/`.
- Другое «три дома», чем ADR-012 §1 (плагин/проект-хозяин/пакет Python) — совпадение слова,
  не предмета.
- `openspec/specs/` не заводится пустым каркасом — материализуется файл-за-файлом вместе с
  первой спекой (`.nauta-ids.yaml`, пространство `scenario`), тем же принципом, что и
  `content/00-project/adr/`.
- Восемь capability пакета, их граница и порядок написания спек — [ADR-021](content/00-project/adr/ADR-021-requirement-capability-pairing.md)
  и его companion-спека.

## Гейты (pre-commit)
`core.hooksPath=.githooks` → `scripts/check.sh --fast`. Требует `uv` в PATH.
- Пороги — в `.nauta-gates.yaml`, откалиброваны замером этого репозитория;
  обоснование и правило пересмотра: `content/40-architecture/ADR-001-nauta-contour-spec.md`.
- `src/ktalk_cli/registry.py` заморожен грандфазером на 562 строках: рост даёт
  error. Снимается расщеплением класса `Registry`, не поднятием потолка.
- `scripts/` и `.githooks/` — payload плагина, приезжает через `/nauta:sync-scripts`
  и отслеживается по sha256 в `.nauta-scripts-basis.yaml`. Правка руками превращает
  файл в конфликт и он перестаёт обновляться; нужна своя версия — путь в `skip:`.
- Обход разовый: `git commit --no-verify`. Отключить: `git config --unset core.hooksPath`.

## Gramax (плагин gramax)
`content/` — валидный Gramax-каталог, `content/.doc-root.yaml` принадлежит Gramax,
конфигурацию гейтов туда не класть (для неё есть `.nauta-gates.yaml`).
- Новое значение свойства сначала объявляется в `.doc-root.yaml`, потом
  используется в статье; `filterProperties` правится синхронно с `properties`.
- В `_index.md` не бывает `properties` — раздел не имеет своего типа и статуса.
- Диаграммы — скиллом `mermaid`: отдельный `.mermaid`-файл рядом со статьёй,
  не inline-блок.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
