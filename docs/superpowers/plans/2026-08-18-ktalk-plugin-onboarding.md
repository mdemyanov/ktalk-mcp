# Онбординг плагина ktalk (волна 4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Плагин `ktalk` обнаруживает отсутствие или устаревание пакета `ktalk-mcp`, показывает
готовые к выполнению команды установки и инструкцию по токену, а при явной санкции пользователя
выполняет установку сам.

**Architecture:** Исполнитель — bash-скрипт `scripts/ktalk-onboard.sh` в дереве плагина (прецедент:
`scripts/check-plugin-composition.sh`, dev-004); хука в плагине нет и не появляется. Промты (2 навыка
+ 2 агента) получают врезку «перед первой командой `ktalk` в сессии вызови скрипт», длинные тексты
живут в `references/onboarding.md`. Факт санкции — файл `${XDG_CONFIG_HOME:-$HOME/.config}/ktalk/onboarding.toml`
на машине пользователя, fail-closed. Пакет получает `ktalk --version` и номер 0.7.0; минимально
совместимая версия объявлена машинночитаемым `compat.json` в дереве плагина.

**Tech Stack:** bash (POSIX-совместимый вызов, без jq и без sort -V), Python 3.12+ / argparse
(правка `cli.py`), pytest, ruff, гейты `scripts/check.sh --fast`, документарный контур Gramax.

**Spec:** `content/30-requirements/ktalk-plugin-onboarding.md` (FR-26…FR-30, NFR-17…NFR-19).
Решения волны, принятые владельцем 2026-08-18, перечислены в Global Constraints и обязательны
дословно — Task 2 их документирует, а не переизобретает.

## Global Constraints

- **Два репозитория.** Пакет и документы — `/Users/mdemyanov/Devel/ktalk-mcp`; плагин —
  `/Users/mdemyanov/Devel/ktalk-plugin` (отдельный git, remote публичный). Коммиты — в обоих,
  **push — операция владельца, не выполнять**.
- **Стиль текста** (CLAUDE.md): сухо и сжато, вывод раньше обоснования, без преамбул. Все
  пользовательские тексты — на русском.
- `src/ktalk_mcp/registry.py` заморожен на 562 строках. Не трогать. Пороги `.nauta-gates.yaml`
  не поднимать.
- ADR не длиннее **150 строк**; детализация — в companion-спеке `content/40-architecture/`.
- Каждая новая статья `content/` несёт `properties: - name: Тип контента` в object-нотации и
  достижима ссылкой из `_index.md` своего раздела.
- Секреты (`KTALK_SESSION_TOKEN`, `KTALK_PERSONAL_API_KEY`, `KTALK_BASE_URL`) и значения токенов
  не попадают ни в дерево плагина, ни в вывод скрипта, ни в тесты (FR-25, NFR-19). Фикстуры —
  синтетические.
- **Решения волны (принято владельцем, менять нельзя):**
  - форма решения — новый ADR-014 + точечная правка «Негативных последствий» ADR-012;
  - исполнитель — `scripts/ktalk-onboard.sh` в дереве плагина, хука нет;
  - файл санкции — `${XDG_CONFIG_HOME:-$HOME/.config}/ktalk/onboarding.toml`, каталог `0700`,
    файл `0600`, fail-closed (нет файла или ключа — санкции нет);
  - два независимых ключа `allow_install` и `allow_update`, область — машина;
  - файл санкции пишет скрипт **только** по подкоманде `grant`, запущенной в терминале;
    без TTY `grant` отказывает (exit 33). Установка (`install`) TTY не требует;
  - менеджер пакетов — только `uv tool install ktalk-mcp`; при отсутствии `uv` скрипт называет
    отсутствующим `uv` и ничего не ставит;
  - версия установленного пакета читается `ktalk --version`, fallback — `uv tool list`;
  - `compat.json` = `{"ktalk_mcp_min_version": "0.7.0"}`; устаревшая версия — предупреждение,
    не блокировка;
  - ретрай — одна повторная попытка через 3 секунды и только на сетевом классе ошибок;
  - `ktalk doctor` и CI репозитория плагина — вне волны;
  - публикация 0.7.0 в PyPI — операция владельца, не выполнять.
- **Контракт скрипта (обязателен дословно, Task 2 его документирует, Tasks 4–6 реализуют):**

  | Команда | Назначение |
  |---|---|
  | `check` | диагностика: PATH, `uv`, версия |
  | `install` | установка/обновление по санкции |
  | `grant install\|update` | выдать санкцию (только TTY) |
  | `revoke install\|update` | отозвать санкцию |
  | `status` | состояние санкций |

  Флаг `--json` у `check`, `install`, `status` печатает один JSON-объект в stdout.

  | Код | Значение |
  |---|---|
  | 0 | всё в порядке / операция успешна |
  | 10 | `ktalk` не найден в PATH |
  | 11 | версия ниже минимально совместимой (или неопределима) |
  | 12 | `uv` не найден в PATH |
  | 20 | внутренняя ошибка (нет/битый `compat.json`, неверный аргумент) |
  | 30 | нет санкции на установку |
  | 31 | установка провалилась |
  | 32 | нужно обновление, нет санкции на обновление |
  | 33 | `grant` вызван без TTY |

- Гейты перед сдачей (репозиторий пакета): `uv run pytest` зелёный, `uv run ruff check .` без
  новых ошибок (36 существующих в `scripts/validate-profile.py` — не наши),
  `bash scripts/check.sh --fast` → `Errors: 0`.

---

## File Structure

**Репозиторий `ktalk-mcp`:**

- `content/30-requirements/ktalk-plugin-onboarding.md` — **modify**: FR-26 AC3 переадресовать на
  `compat.json`; добавить AC ретрая (FR-30) и AC предпосылки релиза.
- `content/00-project/adr/ADR-014-sanctioned-onboarding.md` — **create**: решение (≤150 строк).
- `content/40-architecture/ADR-014-onboarding-spec.md` — **create**: контракт скрипта, схемы
  `onboarding.toml`/`compat.json`, текст врезки, брифы Dev/QA.
- `content/00-project/adr/ADR-012-plugin-boundary.md` — **modify**: одна фраза в «Негативных
  последствиях» + ссылка на ADR-014 в «Связанных статьях».
- `content/00-project/adr/_index.md`, `content/40-architecture/_index.md` — **modify**: ссылки на
  новые статьи (иначе гейт даёт warning «сирота»).
- `src/ktalk_mcp/cli.py` — **modify**: флаг `--version`.
- `pyproject.toml`, `src/ktalk_mcp/__init__.py` — **modify**: версия 0.7.0.
- `tests/test_cli.py` — **modify**: тест `--version`.
- `content/60-implementation/dev-005-onboarding.md` — **create**: дев-заметка обеих частей.
- `content/40-architecture/security-review-onboarding.md` — **create**: SEC-004.

**Репозиторий `ktalk-plugin`:**

- `compat.json` — **create**.
- `scripts/ktalk-onboard.sh` — **create**: весь исполняемый онбординг.
- `scripts/test-onboard.sh` — **create**: bash-suite (прогон ручной, CI вне волны).
- `references/onboarding.md` — **create**: тексты FR-27/FR-28 (установка, проверка, токен).
- `skills/ktalk-registry/SKILL.md`, `skills/ktalk-eval/SKILL.md`, `agents/ktalk-processor.md`,
  `agents/ktalk-evaluator.md` — **modify**: врезка (4 строки, идентична во всех четырёх).
- `README.md` — **modify**: раздел про санкцию, отзыв, минимальную версию.

---

### Task 1: Правка требования под принятые решения

**Files:**
- Modify: `content/30-requirements/ktalk-plugin-onboarding.md`

**Interfaces:**
- Produces: формулировки AC, на которые опираются Tasks 2 и 4–6 (`compat.json` как источник
  минимальной версии; ретрай; предпосылка публикации).

- [ ] **Step 1: Переписать FR-26 AC3**

Заменить в третьем AC FR-26 фрагмент «объявленной в README (ADR-012 §4)» на:

```
объявленной машинночитаемым файлом `compat.json` в дереве плагина (README цитирует этот файл,
не наоборот)
```

- [ ] **Step 2: Добавить AC ретрая в FR-30**

Добавить четвёртым AC в FR-30:

```
- Given автоматическая установка провалилась с ошибкой сетевого класса (недоступность индекса,
  таймаут, отказ DNS), When плагин обрабатывает ошибку, Then он делает ровно одну повторную
  попытку той же командой; ошибки прав, конфликта версий и отсутствия пакета в индексе не
  повторяются никогда — автоматическая проверка (стаб `uv`, возвращающий сетевой и несетевой
  текст ошибки).
```

- [ ] **Step 3: Добавить FR-31 — предпосылка релиза**

Добавить после FR-30 новый раздел:

```markdown
### FR-31 — Установка приводит к работоспособному контуру

Команда установки, которую плагин показывает (FR-27) и выполняет (FR-29), обязана давать версию
пакета не ниже минимально совместимой. На 2026-08-18 в индексе опубликована 0.4.0, в репозитории
пакета — 0.6.0; ни одна из них не несёт конфиг-слоя волны 3 в объявленном виде.

**AC:**
- Given пакет установлен показанной командой из публичного индекса, When выполняется `check`
  (FR-26), Then результат — «версия соответствует минимальной», не «ниже минимальной»; расхождение
  означает, что релиз не выпущен, и фиксируется как открытый пункт, а не как успех онбординга —
  ручная проверка владельцем после публикации.
```

- [ ] **Step 4: Прогнать гейты**

Run: `bash scripts/check.sh --fast`
Expected: `Errors: 0`, число warnings не выросло (было 3 — грандфазеры).

- [ ] **Step 5: Commit**

```bash
git add content/30-requirements/ktalk-plugin-onboarding.md
git commit -m "docs(ba): требование онбординга — compat.json, ретрай, FR-31"
```

---

### Task 2: ADR-014, companion-спека, правка ADR-012

**Files:**
- Create: `content/00-project/adr/ADR-014-sanctioned-onboarding.md`
- Create: `content/40-architecture/ADR-014-onboarding-spec.md`
- Modify: `content/00-project/adr/ADR-012-plugin-boundary.md`
- Modify: `content/00-project/adr/_index.md`, `content/40-architecture/_index.md`

**Interfaces:**
- Consumes: AC из Task 1.
- Produces: письменный контракт, на который ссылаются Tasks 4–7 и SEC-004 (Task 9). Контракт
  скрипта и коды возврата — из Global Constraints этого плана, дословно.

- [ ] **Step 1: Написать ADR-014**

Файл `content/00-project/adr/ADR-014-sanctioned-onboarding.md`, frontmatter как у ADR-013
(`Тип контента: [ADR]`, `Фаза: [Pilot]`, `Статус: [Draft]`), тело — не более 150 строк, разделы:

- **Контекст** — ADR-012 §2 запретил плагину чинить зависимость; FR-26…FR-30 это отменяют в части
  «не чинит» и «не проверяет». Установленного пакета в момент обнаружения нет, поэтому подкоманда
  пакета исполнителем быть не может.
- **Решение**, шесть пронумерованных пунктов:
  1. Исполнитель — `scripts/ktalk-onboard.sh` в дереве плагина; хук не вводится. Отклонённая
     ADR-012 альтернатива («install-хук не имеет санкции на запись вне своего дерева») не
     воскрешается: скрипт исполняется только по явному вызову промта или пользователя.
  2. Санкция — файл `${XDG_CONFIG_HOME:-$HOME/.config}/ktalk/onboarding.toml`, каталог `0700`,
     файл `0600`, fail-closed. Не в централизованном хранилище (ADR-013 — данные пакета) и не в
     `.ktalk.toml` (файл коммитится в репозиторий проекта: санкцию можно было бы получить клоном).
  3. Два независимых ключа `allow_install`, `allow_update`; область — машина, потому что эффект
     `uv tool install` машинный. Санкция на установку не расширяется на обновление (FR-30 AC2).
  4. Отличие от TTY-барьера ADR-005: там подтверждение берётся в моменте для одной боевой
     операции, здесь — заранее и персистентно. Поэтому TTY требуется для `grant` (выдача
     санкции), но не для `install` (её применение). Инвариант NFR-18 сохраняется: невозможность
     спросить никогда не трактуется как согласие.
  5. Менеджер — только `uv tool`; при отсутствии `uv` скрипт называет отсутствующим `uv` и не
     ставит его (FR-27 AC3).
  6. Минимально совместимая версия — `compat.json` в дереве плагина, не `dependencies`
     манифеста (ADR-012 §4 остаётся в силе) и не проза README. Рассогласование — предупреждение,
     не блокировка.
- **Последствия** (позитивные / негативные / смягчения) — в негативных явно: в дереве плагина
  появляется второй исполняемый файл, и он умеет менять состояние машины; смягчение — fail-closed
  санкция, TTY на `grant`, security review SEC-004.
- **Альтернативы**: хук плагина (отклонён — исполняется без диалога, конфликт с NFR-18);
  чисто промптовый онбординг (отклонён — ни один AC не проверяем автоматически); ключ санкции в
  `.ktalk.toml` (отклонён — приезжает клоном); `pipx`/`pip --user` (отклонены — ни один FR их не
  требует, три пути ломают идемпотентность FR-30).
- **Связанные статьи**: требование, ADR-012, ADR-013, ADR-005, companion-спека.

- [ ] **Step 2: Проверить длину ADR**

Run: `wc -l content/00-project/adr/ADR-014-sanctioned-onboarding.md`
Expected: не больше 150.

- [ ] **Step 3: Написать companion-спеку**

Файл `content/40-architecture/ADR-014-onboarding-spec.md` (`Тип контента: [Архитектура]`), разделы:

1. **Контракт `ktalk-onboard.sh`** — таблицы команд и кодов возврата из Global Constraints этого
   плана, скопированные дословно.
2. **Схема `onboarding.toml`**:

```toml
allow_install = true
allow_update = false
granted_at = "2026-08-18"
```

   Санкция считается выданной только при точном совпадении строки
   `^allow_(install|update)[[:space:]]*=[[:space:]]*true[[:space:]]*$`. Любое иное содержимое —
   санкции нет (fail-closed). `granted_at` — информационное поле, на решение не влияет.
3. **Схема `compat.json`**: `{"ktalk_mcp_min_version": "0.7.0"}`; читается grep+sed, без `jq`
   (наличие `jq` не гарантировано).
4. **Определение версии**: `ktalk --version` → `ktalk-mcp X.Y.Z`; fallback `uv tool list` →
   строка `ktalk-mcp vX.Y.Z`; обе не сработали → «версия неопределима», трактуется как устаревшая
   (код 11). Сравнение версий — покомпонентное на bash, не `sort -V` (на macOS его поведение не
   гарантировано).
5. **Классификация ошибок установки**: сетевой класс — регистронезависимое совпадение вывода `uv`
   с `failed to fetch|connection|timed out|timeout|temporary failure in name resolution|network|could not resolve`;
   всё остальное не повторяется.
6. **Текст врезки для промтов** — дословно, как в Task 7 Step 1.
7. **Бриф для Dev** — задачи 3–7 этого плана.
8. **Контракт с QA** — что проверяет bash-suite, что остаётся ручной проверкой владельца
   (ветка записи `grant` в TTY; живая установка; FR-31 после публикации). Явно: тесты **не**
   эмулируют TTY через `script`/pty — это обошло бы барьер, который сами и проверяют.

- [ ] **Step 4: Правка ADR-012**

В разделе «Последствия», абзац «Негативные», заменить фрагмент
«плагин не проверяет и не чинит это автоматически» на:

```
плагин не проверяет и не чинит это автоматически — снято [ADR-014](ADR-014-sanctioned-onboarding.md):
обнаружение стало обязанностью плагина, установка — по явной санкции пользователя
```

В «Связанных статьях» добавить строку со ссылкой на ADR-014 и его спеку.

- [ ] **Step 5: Ссылки в `_index.md`**

Добавить ADR-014 в `content/00-project/adr/_index.md` и спеку в `content/40-architecture/_index.md`
в том же формате, что соседние строки.

- [ ] **Step 6: Прогнать гейты**

Run: `bash scripts/check.sh --fast`
Expected: `Errors: 0`, Warnings не больше 3 (только грандфазеры; «сирота» и «нет типа» — ошибка
оформления, чинить в этом же шаге).

- [ ] **Step 7: Commit**

```bash
git add content/00-project/adr content/40-architecture
git commit -m "docs(sa): ADR-014 санкционированный онбординг + спека, правка ADR-012"
```

---

### Task 3: `ktalk --version` и бамп пакета до 0.7.0

**Files:**
- Modify: `src/ktalk_mcp/cli.py`
- Modify: `pyproject.toml`, `src/ktalk_mcp/__init__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `ktalk --version` печатает в stdout `ktalk-mcp X.Y.Z` и выходит с кодом 0. Формат
  потребляется `installed_version()` из Task 4.

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_cli.py`:

```python
def test_version_flag(capsys):
    from ktalk_mcp.cli import main

    code = main(["--version"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("ktalk-mcp ")
    assert out.split()[1].count(".") == 2
```

Если существующие тесты `test_cli.py` вызывают `main` иначе (например, через `SystemExit`) —
повторить их конвенцию, но проверять те же три утверждения.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/test_cli.py::test_version_flag -v`
Expected: FAIL (argparse завершает процесс с кодом 2 — неизвестный аргумент).

- [ ] **Step 3: Реализовать флаг**

В `src/ktalk_mcp/cli.py`, в функции построения парсера, рядом с `--db`:

```python
    parser.add_argument(
        "--version",
        action="store_true",
        help="Версия пакета ktalk-mcp",
    )
```

В `main()`, до диспетчеризации подкоманд и до открытия реестра:

```python
    if getattr(args, "version", False):
        from ktalk_mcp import __version__

        print(f"ktalk-mcp {__version__}")
        return 0
```

Если подкоманда обязательна (`sub.required = True`), снять обязательность или обработать
`--version` до `parse_args` — тест обязан проходить при вызове без подкоманды.

- [ ] **Step 4: Проверить, что тест проходит**

Run: `uv run pytest tests/test_cli.py::test_version_flag -v`
Expected: PASS

- [ ] **Step 5: Бамп версии**

`pyproject.toml`: `version = "0.7.0"`. `src/ktalk_mcp/__init__.py`: `__version__ = "0.7.0"`
(если переменной нет — добавить; если версия читается из метаданных пакета, оставить как есть и
поправить только `pyproject.toml`).

- [ ] **Step 6: Полный прогон**

Run: `uv run pytest -q && uv run ruff check . && bash scripts/check.sh --fast`
Expected: все тесты зелёные, ruff — без новых ошибок, `Errors: 0`.

- [ ] **Step 7: Commit**

```bash
git add src/ktalk_mcp pyproject.toml tests/test_cli.py
git commit -m "feat(cli): ktalk --version, версия пакета 0.7.0"
```

---

### Task 4: Каркас скрипта, `compat.json`, команда `check`

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-plugin`

**Files:**
- Create: `compat.json`, `scripts/ktalk-onboard.sh`, `scripts/test-onboard.sh`

**Interfaces:**
- Produces: `check` с кодами 0/10/11/12/20 и `--json`; функции `min_version`,
  `installed_version`, `version_ge`, `emit` — используются Tasks 5–6.

- [ ] **Step 1: Написать падающий тест-харнесс**

Создать `scripts/test-onboard.sh`:

```bash
#!/usr/bin/env bash
# Тесты онбординг-скрипта. Прогон ручной: bash scripts/test-onboard.sh
# Ветка записи `grant` в TTY здесь НЕ проверяется — эмуляция pty обошла бы барьер,
# который тест и должен защищать (проверка владельцем вручную, ADR-014-onboarding-spec §8).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/ktalk-onboard.sh"
PASS=0; FAIL=0

check_eq() { # check_eq <ожидание> <факт> <название>
  if [ "$1" = "$2" ]; then PASS=$((PASS+1)); printf 'ok   %s\n' "$3"
  else FAIL=$((FAIL+1)); printf 'FAIL %s: ожидалось "%s", получено "%s"\n' "$3" "$1" "$2"; fi
}

make_env() { # make_env <каталог> — временный PATH и XDG_CONFIG_HOME
  TMP="$(mktemp -d)"; mkdir -p "$TMP/bin" "$TMP/config"
  export XDG_CONFIG_HOME="$TMP/config"
  export PATH="$TMP/bin:/usr/bin:/bin:/usr/sbin:/sbin"
}

stub() { # stub <имя> <код> <stdout>
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "%s"\nexit %s\n' "$3" "$2" > "$TMP/bin/$1"
  chmod +x "$TMP/bin/$1"
}

# 1. ktalk отсутствует, uv есть → 10
make_env; stub uv 0 ""
"$SCRIPT" check >/dev/null 2>&1; check_eq 10 $? "check: нет ktalk, есть uv → 10"

# 2. ни ktalk, ни uv → 12
make_env
"$SCRIPT" check >/dev/null 2>&1; check_eq 12 $? "check: нет uv → 12"

# 3. версия ниже минимальной → 11
make_env; stub uv 0 ""; stub ktalk 0 "ktalk-mcp 0.4.0"
"$SCRIPT" check >/dev/null 2>&1; check_eq 11 $? "check: 0.4.0 < 0.7.0 → 11"

# 4. версия достаточна → 0
make_env; stub uv 0 ""; stub ktalk 0 "ktalk-mcp 0.7.0"
"$SCRIPT" check >/dev/null 2>&1; check_eq 0 $? "check: 0.7.0 → 0"

# 5. версия выше минимальной → 0
make_env; stub uv 0 ""; stub ktalk 0 "ktalk-mcp 1.2.3"
"$SCRIPT" check >/dev/null 2>&1; check_eq 0 $? "check: 1.2.3 → 0"

# 6. --version не поддержан, версия берётся из uv tool list
make_env
printf '#!/usr/bin/env bash\nexit 2\n' > "$TMP/bin/ktalk"; chmod +x "$TMP/bin/ktalk"
stub uv 0 "ktalk-mcp v0.7.0"
"$SCRIPT" check >/dev/null 2>&1; check_eq 0 $? "check: fallback на uv tool list"

# 7. --json печатает валидный JSON
make_env; stub uv 0 ""; stub ktalk 0 "ktalk-mcp 0.7.0"
OUT="$("$SCRIPT" check --json 2>/dev/null)"
printf '%s' "$OUT" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null
check_eq 0 $? "check --json: валидный JSON"

printf '\nPASS: %s  FAIL: %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `bash scripts/test-onboard.sh`
Expected: все проверки FAIL (файла `scripts/ktalk-onboard.sh` ещё нет).

- [ ] **Step 3: Создать `compat.json`**

```json
{
  "ktalk_mcp_min_version": "0.7.0"
}
```

- [ ] **Step 4: Реализовать каркас и `check`**

Создать `scripts/ktalk-onboard.sh` (`chmod +x`):

```bash
#!/usr/bin/env bash
# Онбординг плагина ktalk: обнаружение пакета, санкция, установка.
# Контракт — ADR-014-onboarding-spec.md в репозитории пакета ktalk-mcp.
set -uo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPAT_FILE="$PLUGIN_ROOT/compat.json"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ktalk"
SANCTION_FILE="$CONFIG_DIR/onboarding.toml"
INSTALL_CMD=(uv tool install ktalk-mcp)
INSTALL_CMD_TEXT="uv tool install ktalk-mcp"

E_OK=0; E_MISSING_CLI=10; E_OUTDATED=11; E_MISSING_UV=12; E_INTERNAL=20
E_NO_SANCTION=30; E_INSTALL_FAILED=31; E_NO_UPDATE_SANCTION=32; E_NO_TTY=33

JSON=0

min_version() {
  local raw
  raw="$(grep -Eo '"ktalk_mcp_min_version"[[:space:]]*:[[:space:]]*"[^"]+"' "$COMPAT_FILE" 2>/dev/null \
        | head -1 | sed -E 's/.*"([^"]+)"[[:space:]]*$/\1/')"
  [ -n "$raw" ] || return 1
  printf '%s\n' "$raw"
}

installed_version() {
  local out
  if out="$(ktalk --version 2>/dev/null)"; then
    out="$(printf '%s' "$out" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -n "$out" ]; then printf '%s\n' "$out"; return 0; fi
  fi
  if command -v uv >/dev/null 2>&1; then
    out="$(uv tool list 2>/dev/null | grep -E '^ktalk-mcp[[:space:]]' | head -1 \
          | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -n "$out" ]; then printf '%s\n' "$out"; return 0; fi
  fi
  return 1
}

version_ge() { # version_ge A B → 0, если A >= B
  local a b x y i
  IFS=. read -r -a a <<< "${1%%[-+]*}"
  IFS=. read -r -a b <<< "${2%%[-+]*}"
  for i in 0 1 2; do
    x="${a[i]:-0}"; y="${b[i]:-0}"
    x="${x//[!0-9]/}"; y="${y//[!0-9]/}"
    x="${x:-0}"; y="${y:-0}"
    if [ "$((10#$x))" -gt "$((10#$y))" ]; then return 0; fi
    if [ "$((10#$x))" -lt "$((10#$y))" ]; then return 1; fi
  done
  return 0
}

report() { # report <status> <installed> <min> <message>
  if [ "$JSON" -eq 1 ]; then
    printf '{"status":"%s","installed_version":"%s","min_version":"%s","install_command":"%s","message":"%s"}\n' \
      "$1" "$2" "$3" "$INSTALL_CMD_TEXT" "$4"
  else
    printf '%s\n' "$4"
  fi
}

cmd_check() {
  local min installed
  if ! min="$(min_version)"; then
    report error "" "" "Не прочитан compat.json плагина — переустановите плагин."
    return "$E_INTERNAL"
  fi
  if ! command -v ktalk >/dev/null 2>&1; then
    if ! command -v uv >/dev/null 2>&1; then
      report missing_uv "" "$min" "Не найден uv. Установите uv, затем: $INSTALL_CMD_TEXT"
      return "$E_MISSING_UV"
    fi
    report missing_cli "" "$min" "Пакет ktalk-mcp не установлен. Команда установки: $INSTALL_CMD_TEXT"
    return "$E_MISSING_CLI"
  fi
  installed="$(installed_version)" || installed=""
  if [ -z "$installed" ] || ! version_ge "$installed" "$min"; then
    report outdated "$installed" "$min" \
      "Версия пакета (${installed:-неопределима}) ниже минимально совместимой $min. Обновление: uv tool upgrade ktalk-mcp"
    return "$E_OUTDATED"
  fi
  report ok "$installed" "$min" "Пакет ktalk-mcp $installed установлен, версия совместима."
  return "$E_OK"
}

main() {
  local cmd="${1:-}"; shift || true
  local rest=()
  for arg in "$@"; do
    case "$arg" in
      --json) JSON=1 ;;
      *) rest+=("$arg") ;;
    esac
  done
  case "$cmd" in
    check) cmd_check ;;
    *)
      printf 'Использование: ktalk-onboard.sh {check|install|grant|revoke|status} [--json]\n' >&2
      return "$E_INTERNAL" ;;
  esac
}

main "$@"
```

- [ ] **Step 5: Проверить, что тесты проходят**

Run: `bash scripts/test-onboard.sh`
Expected: `PASS: 7  FAIL: 0`

- [ ] **Step 6: Проверка состава плагина**

Run: `bash scripts/check-plugin-composition.sh`
Expected: `Проверка состава плагина: OK`, код возврата 0.

- [ ] **Step 7: Commit** (в репозитории плагина, без push)

```bash
git add compat.json scripts/ktalk-onboard.sh scripts/test-onboard.sh
git commit -m "feat(onboard): compat.json и команда check"
```

---

### Task 5: Санкция — `status`, `grant`, `revoke`

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-plugin`

**Files:**
- Modify: `scripts/ktalk-onboard.sh`, `scripts/test-onboard.sh`

**Interfaces:**
- Consumes: `report`, коды возврата, `CONFIG_DIR`/`SANCTION_FILE` из Task 4.
- Produces: `sanction_granted <install|update>` (0 — санкция есть) — используется Task 6.

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `scripts/test-onboard.sh` перед итоговой печатью:

```bash
# 8. нет файла санкции → status сообщает отсутствие, код 0
make_env
OUT="$("$SCRIPT" status --json 2>/dev/null)"; check_eq 0 $? "status: без файла код 0"
printf '%s' "$OUT" | grep -q '"install":false' ; check_eq 0 $? "status: install=false без файла"

# 9. корректный файл → санкция видна
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
"$SCRIPT" status --json 2>/dev/null | grep -q '"install":true'
check_eq 0 $? "status: allow_install = true распознан"

# 10. мусор в файле → fail-closed
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install=maybe\nallow_install : true\n<<<\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
"$SCRIPT" status --json 2>/dev/null | grep -q '"install":false'
check_eq 0 $? "status: битый файл → санкции нет"

# 11. grant без TTY → 33 и файл не создан
make_env
"$SCRIPT" grant install >/dev/null 2>&1; check_eq 33 $? "grant без TTY → 33"
[ -f "$XDG_CONFIG_HOME/ktalk/onboarding.toml" ]; check_eq 1 $? "grant без TTY не создал файл"

# 12. revoke снимает ключ без TTY
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
"$SCRIPT" revoke install >/dev/null 2>&1; check_eq 0 $? "revoke: код 0"
"$SCRIPT" status --json 2>/dev/null | grep -q '"install":false'
check_eq 0 $? "revoke: санкция снята"

# 13. неизвестный ключ санкции → 20
make_env
"$SCRIPT" grant everything >/dev/null 2>&1; check_eq 20 $? "grant с неверным ключом → 20"
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `bash scripts/test-onboard.sh`
Expected: проверки 1–7 проходят, 8–13 — FAIL.

- [ ] **Step 3: Реализовать санкцию**

Добавить в `scripts/ktalk-onboard.sh` перед `main()`:

```bash
sanction_granted() { # sanction_granted install|update
  [ -f "$SANCTION_FILE" ] || return 1
  grep -Eq "^allow_$1[[:space:]]*=[[:space:]]*true[[:space:]]*\$" "$SANCTION_FILE"
}

sanction_json() {
  local i u
  sanction_granted install && i=true || i=false
  sanction_granted update && u=true || u=false
  printf '{"install":%s,"update":%s}' "$i" "$u"
}

cmd_status() {
  if [ "$JSON" -eq 1 ]; then
    printf '{"status":"ok","sanction":%s,"sanction_file":"%s"}\n' "$(sanction_json)" "$SANCTION_FILE"
  else
    local i u
    sanction_granted install && i="есть" || i="нет"
    sanction_granted update && u="есть" || u="нет"
    printf 'Санкция на установку: %s\nСанкция на обновление: %s\nФайл: %s\n' "$i" "$u" "$SANCTION_FILE"
  fi
  return "$E_OK"
}

set_key() { # set_key <install|update> <true|false>
  local tmp
  mkdir -p "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR" || return "$E_INTERNAL"
  tmp="$(mktemp "$CONFIG_DIR/.onboarding.XXXXXX")" || return "$E_INTERNAL"
  {
    grep -Ev "^allow_$1[[:space:]]*=" "$SANCTION_FILE" 2>/dev/null
    printf 'allow_%s = %s\n' "$1" "$2"
  } > "$tmp"
  chmod 600 "$tmp" && mv "$tmp" "$SANCTION_FILE" || return "$E_INTERNAL"
  return "$E_OK"
}

cmd_grant() {
  case "${1:-}" in
    install|update) ;;
    *) printf 'Укажите, что разрешаете: grant install | grant update\n' >&2; return "$E_INTERNAL" ;;
  esac
  if [ ! -t 0 ]; then
    printf 'Санкция выдаётся только в терминале. Запустите вручную:\n  bash %s grant %s\n' \
      "${BASH_SOURCE[0]}" "$1" >&2
    return "$E_NO_TTY"
  fi
  set_key "$1" true || return "$E_INTERNAL"
  printf 'Санкция "%s" выдана. Файл: %s\nОтзыв: bash %s revoke %s\n' \
    "$1" "$SANCTION_FILE" "${BASH_SOURCE[0]}" "$1"
  return "$E_OK"
}

cmd_revoke() {
  case "${1:-}" in
    install|update) ;;
    *) printf 'Укажите, что отзываете: revoke install | revoke update\n' >&2; return "$E_INTERNAL" ;;
  esac
  [ -f "$SANCTION_FILE" ] || return "$E_OK"
  set_key "$1" false || return "$E_INTERNAL"
  printf 'Санкция "%s" отозвана.\n' "$1"
  return "$E_OK"
}
```

В `main()` расширить `case`:

```bash
    check) cmd_check ;;
    status) cmd_status ;;
    grant) cmd_grant "${rest[0]:-}" ;;
    revoke) cmd_revoke "${rest[0]:-}" ;;
```

- [ ] **Step 4: Проверить, что тесты проходят**

Run: `bash scripts/test-onboard.sh`
Expected: `FAIL: 0`.

- [ ] **Step 5: Проверить права файла вручную**

Run:
```bash
XDG_CONFIG_HOME=/tmp/ktalk-onb-check bash -c 'mkdir -p /tmp/ktalk-onb-check/ktalk; printf "allow_install = true\n" > /tmp/ktalk-onb-check/ktalk/onboarding.toml; bash scripts/ktalk-onboard.sh revoke install >/dev/null; stat -f "%Lp %N" /tmp/ktalk-onb-check/ktalk/onboarding.toml /tmp/ktalk-onb-check/ktalk'
```
Expected: `600` у файла, `700` у каталога. После проверки: `rm -rf /tmp/ktalk-onb-check`.

- [ ] **Step 6: Commit**

```bash
git add scripts/ktalk-onboard.sh scripts/test-onboard.sh
git commit -m "feat(onboard): санкция — status/grant/revoke, fail-closed, TTY на grant"
```

---

### Task 6: Установка — `install`, идемпотентность, ретрай

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-plugin`

**Files:**
- Modify: `scripts/ktalk-onboard.sh`, `scripts/test-onboard.sh`

**Interfaces:**
- Consumes: `sanction_granted`, `installed_version`, `version_ge`, `min_version`, коды возврата.
- Produces: `install` с кодами 0/12/30/31/32 и печатью вывода `uv` (FR-29 AC4).

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `scripts/test-onboard.sh`:

```bash
# 14. нет санкции → 30, uv не вызывался
make_env
printf '#!/usr/bin/env bash\ntouch "%s/uv-was-called"\nexit 0\n' "$TMP" > "$TMP/bin/uv"; chmod +x "$TMP/bin/uv"
"$SCRIPT" install >/dev/null 2>&1; check_eq 30 $? "install: без санкции → 30"
[ -f "$TMP/uv-was-called" ]; check_eq 1 $? "install: без санкции uv не вызывался"

# 15. санкция есть, установка успешна → 0
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
printf '#!/usr/bin/env bash\necho "Installed 1 executable: ktalk"\nexit 0\n' > "$TMP/bin/uv"; chmod +x "$TMP/bin/uv"
"$SCRIPT" install >/dev/null 2>&1; check_eq 0 $? "install: с санкцией → 0"

# 16. пакет уже свежий → 0 и uv не вызывался (идемпотентность)
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\nallow_update = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
stub ktalk 0 "ktalk-mcp 0.7.0"
printf '#!/usr/bin/env bash\ntouch "%s/uv-was-called"\nexit 0\n' "$TMP" > "$TMP/bin/uv"; chmod +x "$TMP/bin/uv"
"$SCRIPT" install >/dev/null 2>&1; check_eq 0 $? "install: уже установлен → 0"
[ -f "$TMP/uv-was-called" ]; check_eq 1 $? "install: уже установлен — uv не вызывался"

# 17. устаревшая версия без санкции на обновление → 32
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
stub ktalk 0 "ktalk-mcp 0.4.0"; stub uv 0 ""
"$SCRIPT" install >/dev/null 2>&1; check_eq 32 $? "install: устарел, нет allow_update → 32"

# 18. сетевая ошибка → ровно две попытки, код 31
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
printf '#!/usr/bin/env bash\necho attempt >> "%s/attempts"\necho "error: Failed to fetch" >&2\nexit 1\n' \
  "$TMP" > "$TMP/bin/uv"; chmod +x "$TMP/bin/uv"
"$SCRIPT" install >/dev/null 2>&1; check_eq 31 $? "install: сетевой сбой → 31"
check_eq 2 "$(wc -l < "$TMP/attempts" | tr -d ' ')" "install: сетевой сбой — ровно 2 попытки"

# 19. несетевая ошибка → одна попытка, код 31
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
printf '#!/usr/bin/env bash\necho attempt >> "%s/attempts"\necho "error: Permission denied" >&2\nexit 1\n' \
  "$TMP" > "$TMP/bin/uv"; chmod +x "$TMP/bin/uv"
"$SCRIPT" install >/dev/null 2>&1; check_eq 31 $? "install: отказ прав → 31"
check_eq 1 "$(wc -l < "$TMP/attempts" | tr -d ' ')" "install: отказ прав — одна попытка"

# 20. нет uv → 12
make_env; mkdir -p "$XDG_CONFIG_HOME/ktalk"
printf 'allow_install = true\n' > "$XDG_CONFIG_HOME/ktalk/onboarding.toml"
"$SCRIPT" install >/dev/null 2>&1; check_eq 12 $? "install: нет uv → 12"
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `bash scripts/test-onboard.sh`
Expected: проверки 1–13 проходят, 14–20 — FAIL.

- [ ] **Step 3: Реализовать `install`**

Добавить в `scripts/ktalk-onboard.sh` перед `main()`:

```bash
RETRY_DELAY="${KTALK_ONBOARD_RETRY_DELAY:-3}"

is_network_error() {
  printf '%s' "$1" | grep -Eqi \
    'failed to fetch|connection|timed out|timeout|temporary failure in name resolution|network|could not resolve'
}

run_install() {
  local out rc
  out="$("${INSTALL_CMD[@]}" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ] && is_network_error "$out"; then
    printf 'Сетевая ошибка, повтор через %s с.\n' "$RETRY_DELAY"
    sleep "$RETRY_DELAY"
    out="$("${INSTALL_CMD[@]}" 2>&1)"; rc=$?
  fi
  printf '%s\n' "$out"
  printf 'Команда: %s\nКод возврата: %s\n' "$INSTALL_CMD_TEXT" "$rc"
  [ "$rc" -eq 0 ] || return "$E_INSTALL_FAILED"
  return "$E_OK"
}

cmd_install() {
  local min installed
  if ! min="$(min_version)"; then
    report error "" "" "Не прочитан compat.json плагина — переустановите плагин."
    return "$E_INTERNAL"
  fi
  if ! command -v uv >/dev/null 2>&1; then
    report missing_uv "" "$min" "Не найден uv. Установите uv, затем: $INSTALL_CMD_TEXT"
    return "$E_MISSING_UV"
  fi
  if command -v ktalk >/dev/null 2>&1; then
    installed="$(installed_version)" || installed=""
    if [ -n "$installed" ] && version_ge "$installed" "$min"; then
      report ok "$installed" "$min" "Пакет ktalk-mcp $installed уже установлен — установка не требуется."
      return "$E_OK"
    fi
    if ! sanction_granted update; then
      report no_update_sanction "$installed" "$min" \
        "Версия ${installed:-неопределима} ниже $min. Обновление требует отдельной санкции: bash ${BASH_SOURCE[0]} grant update"
      return "$E_NO_UPDATE_SANCTION"
    fi
  elif ! sanction_granted install; then
    report no_sanction "" "$min" \
      "Санкции на автоматическую установку нет. Установите сами: $INSTALL_CMD_TEXT — или выдайте санкцию: bash ${BASH_SOURCE[0]} grant install"
    return "$E_NO_SANCTION"
  fi
  run_install
}
```

В `main()` добавить ветку `install) cmd_install ;;`.

- [ ] **Step 4: Проверить, что тесты проходят**

Run: `KTALK_ONBOARD_RETRY_DELAY=0 bash scripts/test-onboard.sh`
Expected: `FAIL: 0`.

Примечание: `KTALK_ONBOARD_RETRY_DELAY` существует ради времени прогона тестов; по умолчанию
3 секунды. Задокументировать это в спеке (Task 2 §5) — если Task 2 уже закоммичена, дописать
одной строкой в этой задаче.

- [ ] **Step 5: Проверка состава плагина**

Run: `bash scripts/check-plugin-composition.sh`
Expected: код возврата 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/ktalk-onboard.sh scripts/test-onboard.sh
git commit -m "feat(onboard): install — санкция, идемпотентность, ретрай сетевых сбоев"
```

---

### Task 7: Тексты онбординга, врезки в промты, README

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-plugin`

**Files:**
- Create: `references/onboarding.md`
- Modify: `skills/ktalk-registry/SKILL.md`, `skills/ktalk-eval/SKILL.md`,
  `agents/ktalk-processor.md`, `agents/ktalk-evaluator.md`, `README.md`

**Interfaces:**
- Consumes: коды возврата `check` из Task 4, тексты команд из Tasks 5–6.

- [ ] **Step 1: Написать `references/onboarding.md`**

```markdown
# Онбординг: пакет ktalk-mcp

Файл читается, когда `scripts/ktalk-onboard.sh check` вернул ненулевой код. Значения токенов
здесь не запрашиваются, не печатаются и не записываются никуда — проверяется только факт
настройки.

## Код 10 — пакет не установлен

Покажи пользователю команду дословно и **не выполняй её сам**:

    uv tool install ktalk-mcp

Проверка после установки: `which ktalk-mcp` или `ktalk --help`.

Если пользователь готов доверить установку плагину — санкция выдаётся им самим в терминале:

    bash ${CLAUDE_PLUGIN_ROOT}/scripts/ktalk-onboard.sh grant install

Эту команду выполняет пользователь. Агент её не запускает: без терминала она откажет (код 33).
После выдачи санкции установку выполняет `bash ${CLAUDE_PLUGIN_ROOT}/scripts/ktalk-onboard.sh install`.

## Код 12 — нет uv

Отсутствует `uv`, а не `ktalk-mcp`. Плагин `uv` не устанавливает. Сообщи, что нужно поставить
`uv` (https://docs.astral.sh/uv/), и повтори проверку.

## Код 11 — версия ниже минимальной

Сообщи установленную и минимальную версии. Обновление — отдельная санкция:

    bash ${CLAUDE_PLUGIN_ROOT}/scripts/ktalk-onboard.sh grant update
    bash ${CLAUDE_PLUGIN_ROOT}/scripts/ktalk-onboard.sh install

Работу можно продолжать: несовместимость версии — предупреждение, не блокировка. Часть сценариев
при этом может не работать.

## Авторизация

Поддерживаются два режима, значение хранит окружение, не плагин:

- `KTALK_PERSONAL_API_KEY` — личный API-ключ, передаётся заголовком `X-Auth-Token`;
- `KTALK_SESSION_TOKEN` — сессионный токен, передаётся параметром `sessionToken`.

Если заданы оба, побеждает `KTALK_PERSONAL_API_KEY`, сессионный токен не читается.

Где взять: личный API-ключ — в профиле пользователя в интерфейсе Толка; сессионный токен —
из активной сессии веб-клиента. Куда положить: переменная окружения процесса Claude Code либо
`.mcp.json`/`settings.json` проекта-хозяина. **Не** в файл внутри дерева плагина и не в
`.ktalk.toml`.

Проверка режима: `ktalk auth-status --json` — печатает выбранный режим, не значение секрета.
Никогда не проси прислать значение токена в чат и не печатай его.
```

- [ ] **Step 2: Вставить врезку в четыре промта**

Добавить в начало каждого из четырёх файлов (`skills/ktalk-registry/SKILL.md`,
`skills/ktalk-eval/SKILL.md`, `agents/ktalk-processor.md`, `agents/ktalk-evaluator.md`),
сразу после frontmatter и заголовка, идентичный блок:

```markdown
## Предусловие: пакет ktalk-mcp

Перед первой командой `ktalk` в сессии выполни:

    bash ${CLAUDE_PLUGIN_ROOT}/scripts/ktalk-onboard.sh check --json

Код 0 — работай дальше. Ненулевой код — прочитай `${CLAUDE_PLUGIN_ROOT}/references/onboarding.md`
и действуй по нему; не пропускай шаг молча и не выдумывай результат. Команды установки и выдачи
санкции сам не выполняешь: `install` — только после того как санкция уже выдана пользователем,
`grant` — никогда.
```

- [ ] **Step 3: Дополнить README**

В разделе «Предусловие: пакет `ktalk-mcp`» заменить абзац «Плагин не устанавливает и не обновляет
пакет сам…» на:

```markdown
Плагин обнаруживает отсутствие или устаревание пакета сам (ADR-014) и показывает команду
установки. Выполнить установку за вас он может только по явной санкции:

    bash <путь к плагину>/scripts/ktalk-onboard.sh grant install    # выдать санкцию (только в терминале)
    bash <путь к плагину>/scripts/ktalk-onboard.sh status           # проверить состояние
    bash <путь к плагину>/scripts/ktalk-onboard.sh revoke install   # отозвать

Санкция хранится в `${XDG_CONFIG_HOME:-$HOME/.config}/ktalk/onboarding.toml` (права 0600) и
действует на всю машину. Санкция на установку не разрешает обновление — для него нужна отдельная
`grant update`. Нет файла или ключа — санкции нет.

Минимально совместимая версия пакета объявлена в `compat.json` этого плагина. Версия ниже —
предупреждение, не блокировка.
```

- [ ] **Step 4: Проверить состав и отсутствие секретов**

Run: `bash scripts/check-plugin-composition.sh && grep -rn "KTALK_SESSION_TOKEN\|KTALK_PERSONAL_API_KEY" --exclude-dir=.git . | grep -v "scripts/check-plugin-composition.sh"`
Expected: код 0 у первой команды; во второй — только упоминания имён переменных в
`references/onboarding.md`, `README.md`, `skills/ktalk-registry/SKILL.md`; ни одного значения.

- [ ] **Step 5: Прогнать тесты скрипта повторно**

Run: `KTALK_ONBOARD_RETRY_DELAY=0 bash scripts/test-onboard.sh`
Expected: `FAIL: 0`.

- [ ] **Step 6: Commit**

```bash
git add references/onboarding.md skills agents README.md
git commit -m "docs(plugin): врезка предусловия в 4 промта, тексты онбординга, README"
```

---

### Task 8: Дев-заметка и сводка гейтов

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-mcp`

**Files:**
- Create: `content/60-implementation/dev-005-onboarding.md`
- Modify: `content/60-implementation/_index.md`

**Interfaces:**
- Consumes: фактический результат Tasks 3–7.

- [ ] **Step 1: Написать дев-заметку**

Файл `content/60-implementation/dev-005-onboarding.md` (`Тип контента: [Прочее]`), разделы:
состав изменений в обоих репозиториях; расхождения со спекой ADR-014 с причиной (если их нет —
написать «расхождений нет», не выдумывать); переменная `KTALK_ONBOARD_RETRY_DELAY` и зачем она;
что **не** покрыто (публикация 0.7.0 в PyPI, апгрейд установленного `uv tool`, живая проверка на
vault'е, push репозитория плагина, ветка записи `grant` в TTY — ручная проверка владельца);
вывод команд проверок из шага 2.

- [ ] **Step 2: Собрать вывод проверок**

Run (пакет):
```bash
uv run pytest -q; uv run ruff check . | tail -3; bash scripts/check.sh --fast | tail -3
```
Run (плагин):
```bash
cd /Users/mdemyanov/Devel/ktalk-plugin && KTALK_ONBOARD_RETRY_DELAY=0 bash scripts/test-onboard.sh | tail -2 && bash scripts/check-plugin-composition.sh
```
Expected: pytest зелёный; ruff — 36 существующих ошибок в `scripts/validate-profile.py` и ни одной
новой; `Errors: 0`; `FAIL: 0`; проверка состава OK. Вставить фактический вывод в заметку дословно.

- [ ] **Step 3: Ссылка в `_index.md`**

Добавить строку на `dev-005-onboarding.md` в `content/60-implementation/_index.md`.

- [ ] **Step 4: Гейты**

Run: `bash scripts/check.sh --fast`
Expected: `Errors: 0`.

- [ ] **Step 5: Commit**

```bash
git add content/60-implementation
git commit -m "docs(dev): дев-заметка DEV-005 — онбординг плагина"
```

---

### Task 9: Security review SEC-004

**Репозиторий:** `/Users/mdemyanov/Devel/ktalk-mcp`

**Files:**
- Create: `content/40-architecture/security-review-onboarding.md`
- Modify: `content/40-architecture/_index.md`

**Interfaces:**
- Consumes: всё, что сделали Tasks 3–7.

- [ ] **Step 1: Провести ревью**

Дispatch `/nauta:devsecops` (агент `nauta:devsecops-agent`) со скоупом:

- `scripts/ktalk-onboard.sh` — исполнение внешней команды, кавычки и словосплиттинг, `PATH`-
  зависимость, права и атомарность записи файла санкции, fail-closed при повреждённом файле,
  невозможность выдать санкцию без TTY, отсутствие путей записи вне `$CONFIG_DIR`;
- врезка в промты — не подталкивает ли агента выполнить `grant`;
- NFR-19 — grep вывода всех команд скрипта на значение синтетического токена;
- FR-25 — секретов в дереве плагина и в git-истории обоих репозиториев нет;
- неотмена закрытых находок SEC-003 (BLOCK-01, MAJ-01…04) — регрессии нет;
- `ktalk --version` — не печатает ничего, кроме имени и версии.

- [ ] **Step 2: Записать отчёт**

Файл `content/40-architecture/security-review-onboarding.md` в формате SEC-003
(`Тип контента: [Прочее]`): вердикт, таблица находок с severity, разбор каждой, остаточные риски.

- [ ] **Step 3: Закрыть находки уровня Block/Major**

Каждая находка Block или Major закрывается кодом в том же цикле; Minor и Info — в отчёт с
пометкой «принято». После правок повторить прогоны Task 8 Step 2.

- [ ] **Step 4: Ссылка в `_index.md` и коммит**

```bash
git add content/40-architecture
git commit -m "docs(sec): SEC-004 — ревью онбординга плагина"
```

---

## Что остаётся владельцу (не выполнять)

1. `git push` в обоих репозиториях.
2. Публикация 0.7.0 в PyPI (в индексе сейчас 0.4.0 — до публикации `check` будет честно сообщать
   «версия ниже минимальной»).
3. `uv tool upgrade ktalk-mcp` на своей машине (сейчас стоит 0.4.0 в directory-режиме из
   `/Users/mdemyanov/Devel/ktalk-mcp`).
4. Живая проверка на `/Users/mdemyanov/Documents/naumen-cto` и ветка записи `grant` в терминале.
