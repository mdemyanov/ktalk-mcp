#!/usr/bin/env bash
# check.sh — single entry-point для всех валидаций.
#
# Usage:
#   bash scripts/check.sh [--fast | --full]
#
# --fast (default): validate-content + validate-profile + check-adr-line-limit +
#         test_test_runner_ownership.py (ADR-026 Д4, TPL-77 — единственная pytest-инвокация
#         внутри --fast; владение test-раннером ловится на pre-commit, не постфактум --full)
# --full: + весь self-test harness шаблона (test-*.sh). Каждый suite обёрнут в [ -f ]-guard:
#         отсутствующий скрипт (курируемый public-снапшот шаблона его вырезает) → [INFO] skip,
#         не ошибка. В private-ветке шаблона все suite'ы на месте и реально прогоняются.

set -euo pipefail

# uv-guard: обязательная зависимость
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' не найден в PATH. Установите: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

MODE="${1:---fast}"

case "$MODE" in
  --fast|--full|-h|--help) ;;
  *)
    echo "Usage: $0 [--fast | --full]" >&2
    exit 2
    ;;
esac

if [[ "$MODE" == "-h" ]] || [[ "$MODE" == "--help" ]]; then
  cat <<EOF
Usage: $0 [--fast | --full]

Modes:
  --fast (default)  Run validators (validate-content.py + validate-profile.py +
                    check-adr-line-limit.py) + test_test_runner_ownership.py (ADR-026 Д4,
                    TPL-77). Quick gate (~1.3-1.6 sec). Suitable for pre-commit hook.
  --full            Run validators + content-classification gate + full self-test harness
                    (test-validate-content, test-validate-profile, test-resolve-agents,
                    test-publish-public, test-template, test-loud-gates, test-gate-debt,
                    test-check-status-drift, test-spdd-integration, test-repo-zone-map,
                    test-examples-sync, test-apply-overlay, test-check-backlog-closure,
                    test-backlog-cleanup, test-check-adr-line-limit,
                    test-check-content-classification, test-prompt-layer,
                    test-central-plugin-checkout, and its own regression suite).
                    Comprehensive smoke (~40 sec, +network for the central-plugin-checkout
                    suite — ADR-009 Д7 п.5, fetches a pinned commit of the public
                    tools-ai/nauta repo).
                    Suitable for CI / pre-merge gate. Missing suites (curated public
                    snapshot cuts the harness) are skipped with [INFO], not treated
                    as failures.

Exit codes:
  0  All checks passed
  1  Validator or test failed
  2  Invalid usage
EOF
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

failed=0
run_check() {
  local name="$1" cmd="$2"
  echo "▶ $name"
  if eval "$cmd"; then
    echo "  ✓ $name"
  else
    echo "  ✗ $name FAILED" >&2
    failed=1
  fi
}

# run_suite_if_present <suite-basename> — прогнать scripts/<basename>.sh, если он есть в этой
# ветке. Self-test harness шаблона (scripts/test-*.sh) вырезается из курируемого public-снапшота
# (ADR-006 §Q1). Отсутствующий suite → [INFO] skip, не ошибка (graceful degradation).
# Путь собирается из basename намеренно: литеральная строка "scripts/test-<name>.sh" в этом файле
# не появляется, поэтому cross-link gate публикации (grep по вырезанным путям) не принимает
# guarded-инвокацию runner'а за битую doc-ссылку.
run_suite_if_present() {
  # Раздельные local: `local a=$1 b=${a}` под set -u падает — ${a} раскрывается на этапе
  # аргументов local ДО присваивания a (base: unbound variable).
  local base="$1"
  local script="scripts/${base}.sh"
  local name="${base}.sh"
  if [[ -f "$script" ]]; then
    run_check "$name" "bash $script"
  else
    echo "▶ $name"
    echo "  [INFO] skip $name (нет в этой ветке)"
  fi
}

# run_gate_if_present <gate-basename> — прогнать `uv run scripts/<basename>.py`, если
# скрипт есть в этой ветке. Аналог run_suite_if_present (см. её докстроку) для гейт-скриптов
# (не test-*.sh suite), которые сами вырезаются из курируемого public-снапшота — не только
# суффиксом test-*.sh. Гейт лимита строк ADR (ADR-013) специфичен content/00-project/adr/
# САМОГО шаблона (docs/zones.yaml: "не для потомка" — до PT-EPIC-17 зона называлась
# docs/adr/, см. git-историю), поэтому вырезается сам (не каталог — .publishignore режет
# гейт точечно) вместе с соседним гейтом закрытия бэклога — без этого guard'а check.sh
# --fast в потомке падал бы на каждом коммите на отсутствующем файле. Путь собирается из
# basename намеренно: полный литеральный путь вырезаемого гейта в этом файле НИГДЕ не
# появляется (ни здесь, ни в вызове ниже) — поэтому cross-link gate публикации не
# принимает guarded-инвокацию за битую ссылку на вырезанный путь (тот же приём, что
# run_suite_if_present; литеральный путь в ЭТОМ комментарии сам был бы тем же дефектом,
# который приём призван обойти — не повторяй его при правке).
run_gate_if_present() {
  local base="$1"
  local script="scripts/${base}.py"
  local name="${base}.py"
  if [[ -f "$script" ]]; then
    run_check "$name" "uv run $script"
  else
    echo "▶ $name"
    echo "  [INFO] skip $name (нет в этой ветке)"
  fi
}

# run_pytest_file_if_present <test-basename> — прогнать `uv run --with pytest -m pytest
# scripts/tests/<basename>.py -q`, если файл есть в этой ветке (ADR-026 Д4, TPL-77). Тот же
# приём guard'а, что run_suite_if_present/run_gate_if_present (см. их докстроки) —
# отсутствующий файл (курируемый public-снапшот вырезает scripts/tests/ целиком) даёт
# [INFO] skip, не ошибку. Путь собирается из basename намеренно — литеральный путь
# scripts/tests/<файл>.py нигде не появляется в этом файле (тот же приём, что у соседних
# guard-функций — избегает cross-link gate публикации, принимающего literal-путь-в-
# вырезанной-директории за битую doc-ссылку).
run_pytest_file_if_present() {
  local base="$1"
  local file="scripts/tests/${base}.py"
  local name="${base}.py"
  if [[ -f "$file" ]]; then
    run_check "$name" "uv run --with pytest -m pytest $file -q"
  else
    echo "▶ $name"
    echo "  [INFO] skip $name (нет в этой ветке)"
  fi
}

run_check "validate-content.py" "uv run scripts/validate-content.py"
run_check "validate-profile.py" "uv run scripts/validate-profile.py"
run_gate_if_present "check-adr-line-limit"
run_pytest_file_if_present "test_test_runner_ownership"

if [[ "$MODE" == "--full" ]]; then
  # check-content-classification (ADR-016 Д7, TPL-56): второй, независимый потребитель
  # классификации путей content/ — регулярный прогон, не только момент публикации
  # (BR-003). Явно в --full, не --fast: FR-012 называет целью именно --full.
  run_gate_if_present "check-content-classification"
  for suite in test-validate-content test-validate-profile test-resolve-agents \
               test-publish-public test-template test-loud-gates test-gate-debt \
               test-check-status-drift test-spdd-integration test-repo-zone-map \
               test-examples-sync test-apply-overlay test-check-backlog-closure \
               test-backlog-cleanup test-check-adr-line-limit \
               test-check-content-classification test-prompt-layer \
               test-central-plugin-checkout; do
    run_suite_if_present "$suite"
  done
fi

if [[ "$failed" -ne 0 ]]; then
  echo "" >&2
  echo "✗ check.sh $MODE — FAILED" >&2
  exit 1
fi

echo ""
echo "✓ check.sh $MODE — passed"
