---
title: "DEV-001 (волна 3): конфиг хозяина и центральное хранилище"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-001 (волна 3): конфиг хозяина и центральное хранилище

Реализация 42 красных стабов QA-001 (`content/40-architecture/at-design-ktalk-plugin.md`)
по SA-003 (`ktalk-plugin-spec.md`) и ADR-013/ADR-013-spec. Новые модули:
`host_config.py`, `store.py`, `store_migration.py`; расширения `resolve_db_path`
(`config.py`) и `cli.py` (`ktalk config show`). `registry.py` не тронут —
562 строки, как и до задачи.

## Discovery `.ktalk.toml` (`host_config.py`)

Discovery и валидация — прямое отражение алгоритма из ktalk-plugin-spec.md:
`${CLAUDE_PROJECT_DIR}`/`project_dir`-оверрайд без обхода вверх; иначе обход от
`cwd` до первого найденного файла, первого каталога с `.git` или корня ФС —
что раньше. `HostConfig` — `dataclass` с четырьмя `dict`-полями (без новой
зависимости, как и предлагала спека). Неизвестная секция/неверный тип значения —
`HostConfigError`, не тихий откат.

Неочевидное: голый обход вверх (`test_discovery_bare_cli_stops_at_filesystem_root_if_no_git_and_no_config`)
идёт по РЕАЛЬНЫМ родительским каталогам временного pytest-каталога до корня ФС —
это единственный способ покрыть контракт «не зависает, не поднимается выше
корня» без мока файловой системы. Проверено: на dev-машине и в CI это быстро
(несколько уровней) и не находит ни `.git`, ни `.ktalk.toml` по пути — но это
неявная зависимость теста от того, что реальная файловая иерархия окружения
запуска не содержит таких файлов выше `/tmp`.

## Машинный дефолт хранилища (`store.py`)

`resolve_store_root()` резолвит `${XDG_DATA_HOME:-$HOME/.local/share}/ktalk` и
**создаёт** каталог с правами `0700` при каждом вызове (идемпотентно).

**Права 0600 на `registry.db` без пост-хок `chmod` и без правки `registry.py`.**
`Registry.__init__` (заморожен) создаёт файл БД через голый
`sqlite3.connect(str(db_path))` — хук на этот момент недоступен. Решение:
`resolve_store_root()` при первом вызове меняет **процессный `umask` на
`0o077`** и не восстанавливает его. С этого момента `mkdir`/`open` этого
процесса создают каталоги `0700` и файлы `0600` единообразно — включая
`registry.db`, `-wal`/`-shm`, `transcripts/`, `eval/reports/`, не только
каталог хранилища. Это единственный способ выполнить NFR-15 («без окна между
созданием и ограничением прав») для файла, который создаёт чужой (frozen)
код, — задокументированный побочный эффект, не случайная утечка: процесс
CLI/MCP-сервера, однажды разрешивший центральный корень, до конца своего цикла
жизни создаёт файлы владелец-only. Проверено `wc -l src/ktalk_mcp/registry.py`
до/после — 562, без изменений.

`detect_sync_dir`/`warn_if_sync_dir` — сегментированная (не substring)
проверка частей пути на маркеры iCloud/Dropbox/Google Drive/OneDrive/
Nextcloud/ownCloud; `resolve_db_path` вызывает `warn_if_sync_dir` на итоговом
пути всегда (единообразно для всех четырёх источников, спека прямо это
разрешает для машинного дефолта как «регресс-барьер»).

## Приоритет источников (`config.py`, `resolve_db_path`)

`--db` > `KTALK_REGISTRY_DB` > `host_config.registry.db_path` > машинный
дефолт (`store.resolve_store_root() / "registry.db"`). Сигнатура расширена
именованным `host_config: HostConfig | None = None`, без переименования
`cli_db` — 22 существующих вызова не задеты.

### Отклонение от исходного `test_resolve_db_path_default` (обоснование)

Существующий (до волны 3) тест `test_resolve_db_path_default` проверял старое
поведение: без всех источников — относительный дефолт `95_TRANSCRIPTS/.registry.db`
(ADR-002). Новая AC (FR-22 AC-1, ADR-013 §1/§3) прямо отменяет это поведение —
дефолт обязан быть машинным, вне `cwd`. Новый стаб этой волны
(`test_resolve_db_path_none_of_the_four_sources_falls_through_to_machine_default`)
и старый тест взаимно исключают друг друга при идентичном вызове
(`resolve_db_path()` без аргументов эквивалентен `resolve_db_path(None,
host_config=None)` — сигнатура из at-design прямо фиксирует такой дефолт
параметра). Правка: `test_resolve_db_path_default` переписан на сверку с
`store.resolve_store_root() / "registry.db"` вместо удалённой константы
`DEFAULT_DB_PATH` (более не существующей — единственная точка, где она
использовалась, кроме этого теста, была сама `resolve_db_path`). Это не
стаб QA-001 (стаб — только 4 новых теста в файле, этот тест старше), поэтому
попадает под «стаб объективно неверен относительно новой спеки — править с
обоснованием», не под «не переписывать стабы».

Побочный эффект: новый стаб `test_resolve_db_path_none_of_the_four_sources_falls_through_to_machine_default`
не мокает `$HOME` (в отличие от переписанного `test_resolve_db_path_default`,
где `$HOME` теперь подменяется `tmp_path`) — при его прогоне на реальной
машине создаётся настоящий `$XDG_DATA_HOME/ktalk` (или `$HOME/.local/share/ktalk`,
если `$XDG_DATA_HOME` не задан). Не правил этот стаб (он написан QA-author,
не мой), эффект идемпотентный и безвреден (создание пустого каталога с правами
`0700`), но стоит знать при локальном запуске `uv run pytest`.

## Команда миграции (`store_migration.py`)

`migrate_to_central_store(source, target)`: если `target` уже существует —
`MigrationTargetExistsError` до какого-либо копирования (не тихая
перезапись данных другого проекта, добавленных после первой миграции);
иначе — `shutil.copy2` → построчная сверка `sqlite3.iterdump()` источник/копия
(`_dumps_match`, вынесена отдельной функцией — под неё завязан
monkeypatch-стаб `test_migration_dump_mismatch_...`) → при несовпадении
целевой файл удаляется, источник не тронут (`MigrationVerificationError`) →
при совпадении источник переименовывается в
`<имя>.pre-migration-<YYYY-MM-DD>` (backup-суффикс, не удаление). Отдельно от
`ktalk migrate <vault>` (`registry.py::migrate_from_vault`, импорт из
markdown-архивов) — не путать имена.

## `ktalk config show` (`cli.py`)

Новая подкоманда `config show` (`--json`/human-readable), в
`_REGISTRY_FREE_COMMANDS` — не открывает SQLite. `HostConfigError` при
малформенном конфиге не гасится внутри обработчика — пробрасывается в общий
`try/except` `main()`, который уже печатает `Ошибка: <текст с путём файла>` в
stderr и возвращает `1` — этого достаточно для AC
(`str(config_path) in captured.err`), отдельного перехвата в `_cmd_config` не
понадобилось.

## Не покрыто этой задачей

Депараметризация промтов skill/agent (DEV-002) — вне периметра: живёт в
отдельном git-репозитории плагина (ADR-012 §4), недостижима для `pytest` этого
пакета. См. постановку волны 3 (`docs/postanovka-wave-3-plugin.md`).

## Итог прогонов

- `uv run pytest` — 405 passed, 0 failed.
- `uv run ruff check .` — 36 существующих ошибок в `scripts/validate-profile.py`,
  не связаны с этой задачей; новые/изменённые файлы (`host_config.py`,
  `store.py`, `store_migration.py`, `config.py`, `cli.py`, `tests/test_config.py`) — чисты.
- `bash scripts/check.sh --fast` — `Errors: 0`, 3 существующих грандфазер-warning
  (`registry.py` 562/562, два скрипта nauta) — не блокируют, не новые.
- `wc -l src/ktalk_mcp/registry.py` — 562 (без изменений).
