#!/usr/bin/env bash
# check-readiness.sh [<целевой каталог>] — предполётная проверка окружения одной командой
# (DEV-065/DEV-067, NA-EPIC-20, openspec/specs/colleague-readiness/spec.md, Requirement
# «Предполётная проверка сводит пять мест в один вердикт»).
#
# Usage: bash check-readiness.sh [<целевой каталог>]
#   Без аргумента целевой каталог — pwd (та же форма, что `bin/deliver.sh`: `DEST_ARG="${1:-.}"`;
#   решение DEV-067, п.1 брифа PM: "берёт pwd или отказывается" — берёт pwd, но НЕ молча —
#   разрешённый абсолютный путь печатается ПЕРВОЙ строкой вывода, ADR-007 Д1).
#
# Два РАЗНЫХ дерева — не одно (находка PM, DEV-067, `content/40-architecture/
# 2026-08-13-circuit-interface-design.md:293`, "фиксированный cwd… явные флаги"):
#   PLUGIN_ROOT — где физически лежит этот скрипт (BASH_SOURCE) — источник поставки плагина.
#   TARGET_ROOT — целевой каталог: аргумент, иначе pwd — проект коллеги, который проверяется.
# До DEV-067 все пять предпосылок читались из PLUGIN_ROOT независимо от того, откуда скрипт
# позвали — коллега в пустом проекте получал ложное "готово" по чужому дереву (плагину). Замер
# воспроизведения (тот же, что в отчёте PM):
#   $ cd /tmp && rm -rf pre && mkdir pre && cd pre && git init -q .
#   $ PATH="/usr/bin:/bin" bash <plugin>/scripts/check-readiness.sh
#   ✓ версия плагина / ✓ маршрут git-хуков / ✓ конфигурация гейтов — все три о ПЛАГИНЕ, не о
#   /tmp/pre; единственная причина non-zero (bd не в PATH) — предпосылка №2, независимая от
#   каталога вовсе.
#
# Пять предпосылок первого цикла:
#   1. версия плагина     — три случая, найдено tech-writer'ом (DEV-068): скрипт живёт либо в
#      ИСХОДНИКЕ плагина (рядом .claude-plugin/plugin.json — читаем "version" оттуда), либо в
#      ДОСТАВЛЕННОЙ копии у коллеги (.claude-plugin/plugin.json в PAYLOAD_FILES не входит и не
#      доставляется — рядом его нет НИКОГДА; источник правды тогда — nauta_version из
#      .nauta-scripts-basis.yaml ЦЕЛЕВОГО проекта, TARGET_ROOT, провенанс поставки,
#      bin/deliver.sh:286). Названо явно: это версия ПОСТАВКИ (когда синхронизирована),
#      не обязательно версия установленного плагина — коллега мог обновить плагин и не
#      пересинхронизировать. Ни того ни другого — громкий отказ с обеими проверенными
#      позициями в сообщении.
#   2. бинарь bd           — bin/init.sh:177, "Установите: brew install beads" (не зависит от
#      каталога — свойство PATH процесса)
#   3. носитель контура И  — `bd where`, cwd = корень основного дерева ЦЕЛЕВОГО проекта
#      (TARGET_ROOT), тот же приём, что bin/init.sh шаг 6
#   4. маршрут git-хуков   — делегируется scripts/check-hooks-path.sh, исполняется с cwd =
#      TARGET_ROOT (не дублируется; сама логика сравнения core.hooksPath — одно место)
#   5. конфигурация гейтов — .nauta-gates.yaml в корне ЦЕЛЕВОГО проекта (читается
#      scripts/check.sh; сам check.sh трактует отсутствие файла как молчаливое умолчание
#      true — здесь это предпосылка, отсутствие которой громко, ADR-034 Д3 / ADR-007 Д1)
#
# Форма отказа — ADR-034 Д3 / ADR-007 Д1: ненулевой код возврата, имя отсутствующей
# предпосылки и инструкция её устранения, а не тихая деградация. Одна непройденная
# предпосылка — одна строка с маркером `ERROR:` (симметрично Д3 ADR-042,
# openspec/specs/gate-failure-semantics/spec.md): счёт `ERROR:` в выводе считает исходы, не
# строки. Исключение — предпосылка №3 (носитель), когда её собственная зависимость (bd)
# уже провалена предпосылкой №2: вторичный маркер по тому же корню задвоил бы находку, поэтому
# она репортится как непройденная БЕЗ второго ERROR:, со ссылкой на находку выше.
set -uo pipefail  # без -e: все пять проверок обязаны отработать, даже если одна упала

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

TARGET_ARG="${1:-.}"
if [[ ! -d "$TARGET_ARG" ]]; then
  echo "ERROR: целевой каталог $TARGET_ARG не существует — проверять нечего." >&2
  echo "  Usage: bash check-readiness.sh [<целевой каталог>] (без аргумента — pwd)." >&2
  exit 1
fi
TARGET_ROOT="$(cd "$TARGET_ARG" && pwd -P)"

echo "Плагин (источник):     $PLUGIN_ROOT"
echo "Целевой проект (цель): $TARGET_ROOT"
echo

FAILED=0
MISSING=()

report_ok() {
  echo "  ✓ $1: $2"
}

# report_fail <name> <marker-line> [continuation-lines...] — печатает ✗-заголовок в stdout и
# ровно ОДНУ строку с маркером ERROR: в stderr (плюс необязательные строки-продолжения без
# маркера).
report_fail() {
  local name="$1"; shift
  local marker_line="$1"; shift
  echo "  ✗ $name FAILED"
  echo "  ERROR: $marker_line" >&2
  for cont in "$@"; do
    echo "    $cont" >&2
  done
  MISSING+=("$name")
  FAILED=1
}

# report_skipped <name> <reason> — предпосылка не выполнена, но её собственная проверка не
# может быть исполнена из-за уже названной находкой предпосылки выше (не дублирует ERROR:).
report_skipped() {
  echo "  ✗ $1 FAILED (не проверено: $2)"
  MISSING+=("$1")
  FAILED=1
}

# --- 1. версия плагина — исходник (PLUGIN_ROOT) ИЛИ доставленная копия (TARGET_ROOT) --------
# _basis_scalar <ключ> <файл> — тот же awk-приём, что scripts/check.sh::_basis_top_level_scalar
# (верхнеуровневый скаляр .nauta-scripts-basis.yaml, кавычки обрезаны). Второй диалект YAML-
# чтения не заводится — приём переиспользован буквально.
_basis_scalar() {
  local key="$1" file="$2"
  awk -v key="$key" '
    index($0, key ":") == 1 {
      line = $0
      sub("^" key ":[ \t]*", "", line)
      gsub(/[ \t]+$/, "", line)
      gsub(/^"/, "", line); gsub(/"$/, "", line)
      print line
      exit
    }
  ' "$file"
}

PLUGIN_JSON="$PLUGIN_ROOT/.claude-plugin/plugin.json"
TARGET_BASIS="$TARGET_ROOT/.nauta-scripts-basis.yaml"
echo "▶ версия плагина"
if [[ -f "$PLUGIN_JSON" ]]; then
  VERSION="$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$PLUGIN_JSON" | head -1)"
  if [[ -z "$VERSION" ]]; then
    report_fail "версия плагина" \
      "ключ \"version\" не найден в $PLUGIN_JSON — версия плагина не определена."
  else
    report_ok "версия плагина" "$VERSION (исходник плагина, $PLUGIN_JSON)"
  fi
elif [[ -f "$TARGET_BASIS" ]]; then
  BASIS_VERSION="$(_basis_scalar nauta_version "$TARGET_BASIS")"
  BASIS_SYNCED_AT="$(_basis_scalar synced_at "$TARGET_BASIS")"
  if [[ -z "$BASIS_VERSION" ]]; then
    report_fail "версия плагина" \
      "ключ nauta_version не найден в $TARGET_BASIS — версия поставки не определена."
  else
    report_ok "версия плагина" \
      "поставка $BASIS_VERSION, синхронизирована ${BASIS_SYNCED_AT:-<дата не записана>} (НЕ обязательно версия установленного плагина — $TARGET_BASIS)"
  fi
else
  report_fail "версия плагина" \
    "ни $PLUGIN_JSON (исходник плагина), ни $TARGET_BASIS (провенанс доставленной копии)" \
    "не найдены — версия не определена ни одним из двух источников." \
    "Почини: исходник — восстанови .claude-plugin/plugin.json из поставки плагина;" \
    "доставленная копия — повтори /nauta:sync-scripts (bin/deliver.sh), он пишет .nauta-scripts-basis.yaml."
fi

# --- 2. бинарь bd (свойство PATH процесса, не зависит от каталога) --------------------------
echo "▶ бинарь bd (PATH)"
BD_PRESENT=0
if command -v bd >/dev/null 2>&1; then
  BD_PRESENT=1
  report_ok "бинарь bd" "$(command -v bd)"
else
  report_fail "бинарь bd" \
    "бинарь bd не найден в PATH. Установите: brew install beads"
fi

# --- 3. носитель контура И (целевой проект — TARGET_ROOT) -----------------------------------
echo "▶ носитель контура И (целевой проект: $TARGET_ROOT)"
if [[ "$BD_PRESENT" -ne 1 ]]; then
  report_skipped "носитель контура И" "требует бинарь bd, см. предпосылку выше"
elif ! command -v git >/dev/null 2>&1; then
  report_fail "носитель контура И" \
    "git не найден в PATH — носитель не может быть проверен (это НЕ \"нет носителя\", ADR-007 Д1)."
else
  GIT_COMMON_DIR_RAW="$(git -C "$TARGET_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -z "$GIT_COMMON_DIR_RAW" ]]; then
    report_fail "носитель контура И" \
      "$TARGET_ROOT не является git-репозиторием — носитель контура И не может быть определён."
  else
    case "$GIT_COMMON_DIR_RAW" in
      /*) BD_ROOT="$(dirname "$GIT_COMMON_DIR_RAW")" ;;
      *)  BD_ROOT="$(cd "$TARGET_ROOT/$(dirname "$GIT_COMMON_DIR_RAW")" && pwd -P)" ;;
    esac
    if ( cd "$BD_ROOT" && bd where >/dev/null 2>&1 ); then
      report_ok "носитель контура И" "инициализирован в $BD_ROOT"
    else
      report_fail "носитель контура И" \
        "носитель контура И не инициализирован в $BD_ROOT." \
        "Почини: bin/init.sh (шаг 6, bd init --stealth --skip-agents --skip-hooks --non-interactive)."
    fi
  fi
fi

# --- 4. маршрут git-хуков (делегируется, cwd = целевой проект) ------------------------------
echo "▶ маршрут git-хуков (целевой проект: $TARGET_ROOT)"
HOOKS_SCRIPT="$SCRIPT_DIR/check-hooks-path.sh"
if [[ ! -f "$HOOKS_SCRIPT" ]]; then
  report_fail "маршрут git-хуков" \
    "$HOOKS_SCRIPT отсутствует — проверка маршрута хуков не может быть выполнена."
else
  HOOKS_OUT="$(cd "$TARGET_ROOT" && bash "$HOOKS_SCRIPT" 2>&1)"
  HOOKS_RC=$?
  if [[ "$HOOKS_RC" -eq 0 ]]; then
    echo "  ✓ маршрут git-хуков"
    echo "$HOOKS_OUT" | sed 's/^/    /'
  else
    echo "  ✗ маршрут git-хуков FAILED"
    echo "$HOOKS_OUT" | sed 's/^/    /' >&2
    MISSING+=("маршрут git-хуков")
    FAILED=1
  fi
fi

# --- 5. конфигурация гейтов (целевой проект — TARGET_ROOT) -----------------------------------
echo "▶ конфигурация гейтов (целевой проект: $TARGET_ROOT)"
GATES_FILE="$TARGET_ROOT/.nauta-gates.yaml"
if [[ ! -f "$GATES_FILE" ]]; then
  report_fail "конфигурация гейтов" \
    "$GATES_FILE отсутствует — гейты (secretScan, sizeBudgets, ...) читают умолчания" \
    "вслепую, ни одна норма не названа явно. Почини: скопируй .nauta-gates.yaml из поставки" \
    "плагина (templates/nauta-gates.yaml либо bin/deliver.sh) в корень проекта."
else
  report_ok "конфигурация гейтов" "$GATES_FILE"
fi

# --- вердикт ---------------------------------------------------------------------------------
echo
if [[ "$FAILED" -eq 0 ]]; then
  echo "✓ готово: все пять предпосылок первого цикла выполнены ($TARGET_ROOT)."
  exit 0
fi
echo "✗ не готово: ${#MISSING[@]} из 5 предпосылок не выполнены ($TARGET_ROOT): ${MISSING[*]}"
exit 1
