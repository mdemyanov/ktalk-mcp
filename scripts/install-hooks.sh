#!/usr/bin/env bash
# install-hooks.sh — активирует git hooks из .githooks/.
#
# Usage: bash scripts/install-hooks.sh
#
# Disable: git config --unset core.hooksPath

set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repository" >&2
  exit 1
fi

if [[ ! -d .githooks ]]; then
  echo "ERROR: .githooks/ не найдена. Запусти из корня репо." >&2
  exit 1
fi

git config core.hooksPath .githooks
echo "✓ Pre-commit hook активирован (core.hooksPath = .githooks)"
echo "  Bypass: git commit --no-verify"
echo "  Disable: git config --unset core.hooksPath"
