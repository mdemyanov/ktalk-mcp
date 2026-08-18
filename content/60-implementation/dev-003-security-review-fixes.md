---
title: "DEV-003 (волна 3): закрытие замечаний security review перед сборкой плагина"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-003 (волна 3): закрытие замечаний security review перед сборкой плагина

TDD-закрытие [security-review-ktalk-plugin.md](../40-architecture/security-review-ktalk-plugin.md)
(SEC-003) перед сборкой плагина ktalk (DEV-003). Изменены `store.py`, `store_migration.py`,
`cli.py`; новый модуль `cli_store.py`. `registry.py` не тронут — 562 строки, как до задачи.
Все находки закрыты собственными тестами (не стабы QA-author — на это замечание пайплайн
qa-author не запускался, метод — классический TDD: тест до реализации).

## BLOCK-01 — миграция не проставляла NFR-15-права на цель

`store_migration.py::migrate_to_central_store`: `shutil.copy2` заменён на явное
`os.open(target, O_CREAT|O_EXCL|O_WRONLY, 0o600)` + `shutil.copyfileobj` + `os.chmod(target,
0o600)` + `os.chmod(target.parent, 0o700)`. Права цели больше не зависят ни от прав источника,
ни от того, вызывался ли где-то раньше в процессе `resolve_store_root()`. Заодно закрывает
MIN-01 (см. ниже) — `O_EXCL` делает проверку-и-создание одной атомарной операцией ОС вместо
`target.exists()` + `copy2`.

Тест: `tests/test_store_migration.py::test_block01_target_gets_owner_only_permissions_regardless_of_source_mode`
— воспроизведение ровно по отчёту (ambient umask `0o022`, источник `0644`/`0755`, `os.umask`
замокан на ambient, чтобы исключить случайный эффект `resolve_store_root()` из другого теста).
Эмпирическая перепроверка тем же способом, каким находку воспроизвёл ревьюер (реальные
`stat().st_mode` на временных файлах, не намерение кода) — см. итоговый прогон ниже.

## MAJ-01 — `.ktalk.toml` → `resolve_db_path` не был подключён в `main()`

`cli.py::main()`: перед резолвингом пути реестра теперь вызывается `discover_host_config()`,
результат передаётся в `resolve_db_path(args.db, host_config=host_config)`. Вызов — только в
ветке, открывающей `Registry` (не для `_REGISTRY_FREE_COMMANDS`), чтобы discovery не задевал
команды, которые вообще не должны знать о БД.

Тесты: `tests/test_cli_host_config_wiring.py` — приоритет `.ktalk.toml` реально подхватывается
(`list --json` видит запись из БД, адресованной `registry.db_path`), явный `--db` по-прежнему
побеждает, malformed `.ktalk.toml` не ломает `_REGISTRY_FREE_COMMANDS`-команду (`auth-status`).

## MAJ-02 — мутация `umask` в `resolve_store_root()` не восстанавливалась

`store.py::resolve_store_root()` не тронута (сохраняет мутацию `umask(0o077)` без
восстановления — обратная совместимость для вызывающих, не оборачивающих вызов сами, как и
было задокументировано dev-001). Реальное сужение окна — в `cli.py::main()`: `os.umask(0o077)`
/ `try/finally` вокруг **конструктора** `Registry(db_path)`, восстановление `os.umask(old)`
сразу после открытия соединения, **до** вызова хендлера.

**Отклонение от буквального кода в отчёте.** Рекомендация ревью оборачивала в `try/finally` весь
блок `with Registry(...) as reg: return handler(reg, args)` — то есть restore происходил бы
только после завершения хендлера, а не «сразу после открытия БД», как сказано в комментарии
самого фрагмента (текст описания и код там разошлись). Хендлеры (`_cmd_export` и будущие) пишут
файлы вне хранилища тем же процессом — с буквальным кодом отчёта эти файлы всё равно
унаследовали бы `0600` по построению. Сделано иначе: `Registry(db_path)` конструируется в
`try`, `with reg:` и вызов хендлера — уже снаружи, после `finally`. Это даёт то самое
«без окна между созданием и ограничением прав» для `registry.db`/`-wal`/`-shm` (создаются в
`Registry.__init__`, `journal_mode=WAL` выставляется там же) и одновременно не протекает в код
хендлера. Проверено эмпирически: `ktalk --db <path> export` под ambient umask `0o022` пишет
`registry.md` с режимом `0o644`, не `0o600` (см. прогон ниже).

Тесты: `tests/test_cli_host_config_wiring.py::test_maj02_umask_restored_after_registry_command_returns`,
`::test_maj02_file_written_after_registry_closes_uses_ambient_umask_not_0o077`;
`tests/test_store.py::test_maj02_resolve_store_root_umask_mutation_documented_not_restored_by_itself`
фиксирует контракт `store.py` явно (сама функция umask не восстанавливает — это ответственность
вызывающей стороны).

## MAJ-03 — существующий корень хранилища со слабыми правами не чинился

`store.py::resolve_store_root()`: после `mkdir(parents=True, exist_ok=True)` добавлен
безусловный `os.chmod(root, 0o700)` — не только при первом создании каталога.

Тест: `tests/test_store.py::test_maj03_existing_root_with_weak_permissions_is_tightened_to_0700`
— каталог создан заранее с `0o755`, после вызова режим приведён к `0o700`.

## MAJ-04 — нет CLI-команды для `migrate_to_central_store`

Новый модуль `cli_store.py` (по конвенции репозитория — `register_subparsers`/`cmd_*`, как
`cli_meetings_read.py`): подкоманда `ktalk migrate-to-central-store <source> [--target PATH]
[--json]`. `--target` по умолчанию — `store.resolve_store_root() / "registry.db"`. Имя
намеренно не пересекается с `ktalk migrate <vault>` (импорт markdown-архивов, ADR-002).

**Отклонение от буквальной формулировки отчёта.** Рекомендация MAJ-04 говорит «в
`_REGISTRY_FREE_COMMANDS` не добавлять». Технически это не может быть верно: если команда не
входит в `_REGISTRY_FREE_COMMANDS`, `main()` перед вызовом хендлера сам открывает
`Registry(resolve_db_path(args.db))` — то есть создаёт/открывает ПОСТОРОННИЙ реестр по
машинному дефолту как побочный эффект простого запуска команды миграции. Это прямо противоречит
NFR-12 («миграция — явный шаг, без скрытых побочных эффектов») — ровно тому требованию, которое
MAJ-04 закрывает. Добавлено в `_REGISTRY_FREE_COMMANDS` с явным обоснованием в комментарии кода
и в тесте. Считаю формулировку отчёта опиской/инверсией, не сознательным намерением — команда
сама управляет и путём-источником, и путём-целью, поэтому не должна тем более косвенно открывать
третий, никак не относящийся к делу файл БД.

Тесты: `tests/test_cli_migrate_to_central_store.py` — перенос данных + backup-переименование
источника, отказ при уже существующей цели (source не тронут), права цели `0o600` даже через
CLI-путь (BLOCK-01 закрыт и на уровне команды, не только модуля), дефолтный `--target`.

## MIN-01 — TOCTOU между проверкой существования и копированием

Закрыт тем же изменением, что и BLOCK-01: `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)`
объединяет проверку-и-создание в одну атомарную операцию ОС, отдельного окна `target.exists()`
→ `copy2` больше нет. Гонки двух параллельных процессов намеренно не воспроизводились тестом
(флаки по конструкции любого timing-based теста этого класса) — атомарность гарантируется
семантикой `O_EXCL`, не таймингом теста; наблюдаемый эффект («второй вызов не портит уже
смигрированные данные») уже покрыт регрессионно (`test_migration_repeated_call_does_not_...`,
`test_min01_target_creation_is_atomic_not_check_then_act`).

## MIN-02 — прерывание между сверкой дампа и `rename` источника (принятый остаточный риск)

**Не закрыт кодом, зафиксирован явно как принятый остаточный риск** (пропорциональность: explicit
редкая административная команда, не сетевой endpoint, требует kill/сбой машины ровно в узком
окне между успешной построчной сверкой и `source.rename(backup)`). Повторный запуск после такого
прерывания сегодня получает `MigrationTargetExistsError` и не восстанавливается сам — требуется
ручное вмешательство (переименовать `source` вручную или удалить `target` и мигрировать заново).
Решение по отчёту — зафиксировать в runbook DevOps (OPS-001), не блокирует сборку плагина. Шаг
не входит в объём DEV-003 (за пределами кода, ответственность DevOps).

## INFO-01 / INFO-02 — принятые остаточные риски, код не менялся

- **INFO-01** (`host_config.py::_validate_string_map`, схема `.ktalk.toml` не рассчитана на
  секреты, контент-проверки нет): принято как есть — значения используются только для локальной
  сборки путей/вывода `ktalk config show`, не уходят в сеть; blue-sky soft-warning на
  высокоэнтропийные значения не реализован (не находка, требующая фикса, по формулировке
  отчёта).
- **INFO-02** (несанитизированный `{title}` в будущей маршрутизации, `ktalk-plugin/skills/
  ktalk-registry/`): вне периметра кода этого пакета (промты плагина, отдельный репозиторий).
  Зафиксировано как открытый вопрос для SA/BA перед реализацией маршрутизации как рабочей фичи,
  не для DEV-003.

## Итог прогонов

- `uv run pytest` — 433 passed, 0 failed (было 420 на момент ревью, +13 новых тестов на
  замечания этой задачи).
- `uv run ruff check .` — 36 ошибок, все в `scripts/validate-profile.py` (не мои, базовая
  линия), новые/изменённые файлы (`store.py`, `store_migration.py`, `cli.py`, `cli_store.py`,
  `tests/test_store.py`, `tests/test_store_migration.py`, `tests/test_cli_host_config_wiring.py`,
  `tests/test_cli_migrate_to_central_store.py`) — чисты.
- `bash scripts/check.sh --fast` — `Errors: 0`, 3 существующих грандфазер-warning
  (`registry.py` 562/562 и два скрипта nauta) — не блокируют, не новые.
- `wc -l src/ktalk_mcp/registry.py` — 562 (без изменений).
- Эмпирическая перепроверка тем же способом, каким находки воспроизвёл ревьюер (реальные права
  на файлах во временных каталогах, не намерение кода):
  - BLOCK-01: ambient umask `0o022`, обычный (0644/0755) источник → цель `0o600`, родитель `0o700`.
  - MAJ-03: заранее созданный корень `0o755` → после `resolve_store_root()` `0o700`.
  - MAJ-02: `ktalk --db <path> export` под ambient umask `0o022` — umask процесса после команды
    равен umask до неё (не утекает), `registry.md` получает `0o644` (ambient), не `0o600`.
