#!/usr/bin/env bash
# check-hooks-path.sh — сверка эффективного каталога git hooks с доставленным значением
# (ADR-040-spec §4, Д2/Д7 ADR-040).
#
# Три различимых исхода §4 (внутри git-репозитория):
#   ok            эффективный каталог == <toplevel>/<expected>          -> exit 0
#   не установлен эффективный каталог == умолчание git (<git-common-dir>/hooks),
#                 core.hooksPath не задан вовсе                          -> exit 1
#   переставлено  эффективный каталог -- любой третий путь               -> exit 1
#
# Сравниваются РАЗРЕШЁННЫЕ пути (realpath/pwd -P), не строки (замер §1.2: `bd init`
# переставляет core.hooksPath безусловно и в АБСОЛЮТНОЙ форме — сравнение сырых строк дало бы
# ложный "переставлено" на семантически идентичном пути).
#
# worktree: `git rev-parse --git-path hooks` уже учитывает core.hooksPath общего конфига и
# отдаёт путь ГЛАВНОГО дерева по умолчанию (не ./.git/hooks самого worktree) — второго кода
# для этого случая не заводим.
#
# Нулевой исход, ДО трёх выше: предмет проверки — core.hooksPath, свойство git-репозитория.
# Дерево без `.git` вовсе (доставленный снапшот, `git archive HEAD | tar -x` — та же
# популяция, что GIT_NO_REPO у `scripts/validate-content.py::_git_probe`/`_git_ls_files`,
# и `SNAP_DIR` publish-public.sh) не является git-репозиторием СТРУКТУРНО — предмета
# сравнения (core.hooksPath) в нём нет и быть не может, это не "не смог проверить" (broken/
# unreadable input), а "нечего проверять", объявленное самим деревом (gate-failure-semantics,
# Requirement "Three gate outcomes": "nothing to check" -- silent, INFO, 0). Различается от
# отсутствия САМОГО git-бинаря (тоже громкая ошибка -- "could not check", симметрично
# GIT_NO_BINARY/_GitUnavailable того же файла): здесь есть чем проверить, но нечего.
set -euo pipefail

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: 'git' не найден в PATH -- маршрут хуков не проверен (это НЕ \"хук в порядке\"," >&2
  echo "ADR-007 Д1: \"не смог проверить\" != \"нечего проверять\")." >&2
  exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "OK: маршрут хуков не проверяется — это дерево не является git-репозиторием (нет .git);"
  echo "  core.hooksPath -- свойство git-репозитория, предмета проверки здесь нет (gate-failure-"
  echo "  semantics: \"nothing to check\", симметрично GIT_NO_REPO validate-content.py)."
  exit 0
fi

TOPLEVEL="$(git rev-parse --show-toplevel)"

# --- ожидаемый путь: hooksPath.expected из .nauta-gates.yaml, умолчание .githooks (§6). -----
# Провенанс значения (У-5, ADR-043 Д3, прецедент `limit_source: default` ADR-036 Д3): гейт,
# работающий по умолчанию из КОДА, обязан назвать и значение, и его происхождение — иначе
# "проверено по объявленной норме" неотличимо от "проверено по числу, которого никто не
# объявлял". Ключа `hooksPath:` в templates/nauta-gates.yaml нет вовсе, и это законно
# (ADR-043 Д3); здесь заводится не ключ, а называние происхождения.
EXPECTED_REL=".githooks"
EXPECTED_SOURCE="default (умолчание в коде scripts/check-hooks-path.sh; ключ hooksPath.expected в .nauta-gates.yaml не задан)"
GATES_FILE="$TOPLEVEL/.nauta-gates.yaml"
if [[ -f "$GATES_FILE" ]]; then
  _v="$(awk '
    /^hooksPath:[ \t]*(#.*)?$/ { inblk=1; next }
    inblk && $0 ~ /^[^ \t]/ { inblk=0 }
    inblk && $0 ~ /^[ \t]*expected:/ {
      line=$0
      sub(/^[ \t]*expected:[ \t]*/, "", line)
      gsub(/[ \t]+$/, "", line)
      gsub(/^"/, "", line); gsub(/"$/, "", line)
      print line
      exit
    }
  ' "$GATES_FILE")"
  if [[ -n "$_v" ]]; then
    EXPECTED_REL="$_v"
    EXPECTED_SOURCE="configured (.nauta-gates.yaml, ключ hooksPath.expected)"
  fi
fi

# Разрешённый (realpath) ожидаемый каталог. mkdir -p не требуется -- .githooks доставлен
# payload'ом и физически существует у источника; у потребителя без него это отдельная
# аномалия (отсутствие carrier'а), не предмет этой проверки.
if [[ -d "$TOPLEVEL/$EXPECTED_REL" ]]; then
  EXPECTED_RESOLVED="$(cd "$TOPLEVEL/$EXPECTED_REL" && pwd -P)"
else
  EXPECTED_RESOLVED="$TOPLEVEL/$EXPECTED_REL"
fi

# --- эффективный каталог хуков: git сам учитывает core.hooksPath и worktree (общий конфиг). -
EFFECTIVE_RAW="$(git rev-parse --git-path hooks)"
case "$EFFECTIVE_RAW" in
  /*) EFFECTIVE_ABS="$EFFECTIVE_RAW" ;;
  *)  EFFECTIVE_ABS="$TOPLEVEL/$EFFECTIVE_RAW" ;;
esac
if [[ -d "$EFFECTIVE_ABS" ]]; then
  EFFECTIVE_RESOLVED="$(cd "$EFFECTIVE_ABS" && pwd -P)"
else
  EFFECTIVE_RESOLVED="$EFFECTIVE_ABS"
fi

# --- умолчание git (то, что было бы эффективным каталогом, если core.hooksPath не задан) ----
GIT_COMMON_DIR_RAW="$(git rev-parse --git-common-dir)"
case "$GIT_COMMON_DIR_RAW" in
  /*) GIT_COMMON_DIR_ABS="$GIT_COMMON_DIR_RAW" ;;
  *)  GIT_COMMON_DIR_ABS="$TOPLEVEL/$GIT_COMMON_DIR_RAW" ;;
esac
if [[ -d "$GIT_COMMON_DIR_ABS/hooks" ]]; then
  DEFAULT_RESOLVED="$(cd "$GIT_COMMON_DIR_ABS/hooks" && pwd -P)"
else
  DEFAULT_RESOLVED="$GIT_COMMON_DIR_ABS/hooks"
fi

HOOKS_PATH_SET="$(git config --get core.hooksPath || true)"

if [[ "$EFFECTIVE_RESOLVED" == "$EXPECTED_RESOLVED" ]]; then
  # --- сторож формы значения (ADR-081 Д7 / SA-097 §3.7). ------------------------------------
  # В ГЛАВНОМ дереве абсолютная форма core.hooksPath разрешается в тот же каталог, что и
  # относительная, и сравнение выше даёт OK. Но ключ — свойство ОБЩЕГО конфига репозитория
  # (`git rev-parse --git-common-dir` один на все рабочие копии), а $TOPLEVEL у каждой копии
  # свой: при абсолютной форме всякая изолированная копия получает каталог хуков ГЛАВНОГО
  # дерева — исполняет ЧУЖОЙ хук и краснеет на этой же проверке. Провенанс формы: `bd init`
  # переставляет ключ безусловно и абсолютно (§1.2 ADR-040-spec), то есть абсолютизация
  # повторяема и наступает после всякой переустановки bd. Исход — предупреждение, не отказ:
  # в главном дереве маршрут ВЕРЕН, чинить нечего, но молчать о цене нельзя.
  # Чего сторож НЕ ловит: смену значения ПОСЛЕ своего прогона (конфиг общий и правится извне
  # посреди чужого прогона), и абсолютную форму, указывающую в третий каталог, — это уже
  # исход «переставлен» ниже.
  if [[ "$HOOKS_PATH_SET" == /* ]]; then
    echo "WARNING: core.hooksPath задан в АБСОЛЮТНОЙ форме ($HOOKS_PATH_SET)."
    echo "  В этом дереве маршрут верен, но ключ общий на все рабочие копии репозитория:"
    echo "  всякая изолированная копия (.claude/worktrees/<id>) исполнит хук ГЛАВНОГО дерева"
    echo "  и получит красный вердикт этой же проверки (ADR-081 Д7, SA-097 §3.7)."
    echo "  Почини: bash scripts/install-hooks.sh (переустановка в относительной форме)."
  fi
  echo "OK: маршрут хуков ($EFFECTIVE_RESOLVED) сверено с ожидаемым значением ($EXPECTED_REL)."
  echo "  норма hooksPath.expected: $EXPECTED_SOURCE"
  exit 0
fi

if [[ -z "$HOOKS_PATH_SET" ]] && [[ "$EFFECTIVE_RESOLVED" == "$DEFAULT_RESOLVED" ]]; then
  echo "ERROR: хук не установлен — core.hooksPath не задан, git использует умолчание" >&2
  echo "  ($EFFECTIVE_RESOLVED), а доставленный хук лежит в $EXPECTED_RESOLVED ($EXPECTED_REL)." >&2
  echo "  норма hooksPath.expected: $EXPECTED_SOURCE" >&2
  echo "  Ни сканирование секретов, ни остальные проверки pre-commit сейчас не выполняются ни" >&2
  echo "  при одном коммите. Почини: bash scripts/install-hooks.sh" >&2
  exit 1
fi

echo "ERROR: core.hooksPath переставлен сторонним инструментом" >&2
echo "  ожидалось: $EXPECTED_RESOLVED ($EXPECTED_REL)" >&2
echo "  норма hooksPath.expected: $EXPECTED_SOURCE" >&2
echo "  фактически: $EFFECTIVE_RESOLVED (core.hooksPath=${HOOKS_PATH_SET:-<не задан>})" >&2
echo "  Сканирование секретов сейчас не выполняется ни при одном коммите — наш" >&2
echo "  .githooks/pre-commit по этому пути не исполняется (замер §1.2 ADR-040-spec)." >&2
echo "  Ремонт — расследование, кто переставил core.hooksPath, а не переустановка вслепую." >&2
exit 1
