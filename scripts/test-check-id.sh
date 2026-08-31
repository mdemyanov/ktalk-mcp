#!/usr/bin/env bash
# test-check-id.sh — сьюта scripts/id-check.sh (ADR-038, мутационные сценарии M1-M9 §7
# content/40-architecture/ADR-038-identifier-namespaces-and-allocation-spec.md).
#
# Предмет — процесс: stdout/stderr и код возврата на СИНТЕТИЧЕСКИХ фикстурах (временный
# каталог с собственным .nauta-ids.yaml), не на реальном дереве nauta. Полное покрытие
# сценариев приёмки живёт в tests/test_qa047_id_namespaces_allocation.py (pytest) — этот
# bash-suite самопроверка гейта (прецедент ADR-025: «детектор, не падавший ни разу,
# неотличим от отсутствующего»), не дубль контракта.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/id-check.sh"

[[ -f "$SCRIPT" ]] || { echo "ERROR: $SCRIPT not found" >&2; exit 2; }
command -v bash >/dev/null || { echo "ERROR: bash not found" >&2; exit 2; }

PASS=0
FAIL=0
TMPROOT="$(mktemp -d)"
cleanup() { rm -rf "$TMPROOT"; }
trap cleanup EXIT

assert() {
  local desc="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  ✓ $desc"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $desc"
    echo "    ожидалось: $expected"
    echo "    получено:  $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_out() {
  local desc="$1" hay="$2"; shift 2
  local pat
  for pat in "$@"; do
    if ! grep -qF -- "$pat" <<<"$hay"; then
      echo "  ✗ $desc"
      echo "    не найдено в выводе: $pat"
      echo "    вывод (первые 15 строк):"
      head -n 15 <<<"$hay" | sed 's/^/      /'
      FAIL=$((FAIL + 1))
      return
    fi
  done
  echo "  ✓ $desc"
  PASS=$((PASS + 1))
}

mk_fixture_dir() { mktemp -d "$TMPROOT/fixture.XXXXXX"; }

run_gate() {
  local dir="$1"; shift
  set +e
  OUT="$(cd "$dir" && bash "$SCRIPT" "$@" 2>&1)"
  RC=$?
  set -e
}

adr_registry() {
  cat <<'YAML'
namespaces:
  - namespace: adr
    prefix: "ADR-"
    width: 3
    home: ["content/00-project/adr/ADR-*.md"]
    definition: filename-prefix
    scope: namespace
    allocation: allocated
    populated: true
    highwater: 37
    graveyard: content/00-project/adr/_index.md
YAML
}

# ===== M1: два файла определяют ADR-041 в одном пространстве -> коллизия, оба пути ========
echo "==> M1: коллизия — два файла определяют ADR-041"
D1="$(mk_fixture_dir)"
adr_registry > "$D1/.nauta-ids.yaml"
mkdir -p "$D1/content/00-project/adr"
echo "# ADR-041 a" > "$D1/content/00-project/adr/ADR-041-a.md"
echo "# ADR-041 b" > "$D1/content/00-project/adr/ADR-041-b.md"
run_gate "$D1"
assert "M1 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M1 называет оба пути" "$OUT" "ADR-041-a.md" "ADR-041-b.md"

# ===== M2: ADR-011-revived.md при 011 в graveyard -> повторная выдача =====================
echo "==> M2: повторная выдача отменённого номера 011"
D2="$(mk_fixture_dir)"
adr_registry > "$D2/.nauta-ids.yaml"
mkdir -p "$D2/content/00-project/adr"
echo "# ADR-011" > "$D2/content/00-project/adr/ADR-011-revived.md"
echo "- ADR-011 — отменён (архив)" > "$D2/content/00-project/adr/_index.md"
run_gate "$D2"
assert "M2 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M2 называет номер и обе записи" "$OUT" "011" "ADR-011-revived.md" "_index.md"

# ===== M3: highwater: 30 при живом ADR-037-*.md -> расхождение реестра ====================
echo "==> M3: расхождение реестра (highwater 30 < corpus 37)"
D3="$(mk_fixture_dir)"
cat > "$D3/.nauta-ids.yaml" <<'YAML'
namespaces:
  - namespace: adr
    prefix: "ADR-"
    width: 3
    home: ["content/00-project/adr/ADR-*.md"]
    definition: filename-prefix
    scope: namespace
    allocation: allocated
    populated: true
    highwater: 30
    graveyard: content/00-project/adr/_index.md
YAML
mkdir -p "$D3/content/00-project/adr"
echo "# ADR-037" > "$D3/content/00-project/adr/ADR-037-live.md"
echo "- [ADR-037](ADR-037-live.md)" > "$D3/content/00-project/adr/_index.md"
run_gate "$D3"
assert "M3 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M3 называет оба числа" "$OUT" "30" "37"

# ===== M4: ADR-042-stray.md вне всех home -> не смог определить пространство имён =========
echo "==> M4: определение вне всех home"
D4="$(mk_fixture_dir)"
adr_registry > "$D4/.nauta-ids.yaml"
mkdir -p "$D4/content/00-project/adr" "$D4/docs"
echo "# ADR-036" > "$D4/content/00-project/adr/ADR-036-live.md"
echo "# ADR-042" > "$D4/docs/ADR-042-stray.md"
run_gate "$D4"
assert "M4 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M4 называет идентификатор и файл" "$OUT" "ADR-042" "docs/ADR-042-stray.md"

# ===== M5: populated: true, home указывает на пустой каталог -> не смог проверить =========
echo "==> M5: ноль определений при populated: true — не смог проверить, не «чисто»"
D5="$(mk_fixture_dir)"
adr_registry > "$D5/.nauta-ids.yaml"
mkdir -p "$D5/content/00-project/adr"
echo "не .md" > "$D5/content/00-project/adr/README.txt"
run_gate "$D5"
assert "M5 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
if grep -qi "чисто" <<<"$OUT" || grep -qi "no collisions" <<<"$OUT"; then
  echo "  ✗ M5 не должен печатать «чисто» на пустом измеренном корпусе"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M5 не печатает «чисто» на пустом измеренном корпусе"
  PASS=$((PASS + 1))
fi

# ===== M6: .nauta-ids.yaml удалён -> не смог проверить, не тихий skip =====================
echo "==> M6: реестр отсутствует — не смог проверить, не тихий skip"
D6="$(mk_fixture_dir)"
mkdir -p "$D6/content/00-project/adr"
echo "# ADR-036" > "$D6/content/00-project/adr/ADR-036-live.md"
run_gate "$D6"
assert "M6 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M6 называет путь реестра" "$OUT" ".nauta-ids.yaml"
if grep -qF "[INFO] skip" <<<"$OUT"; then
  echo "  ✗ M6 тихий skip запрещён"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M6 тихий skip отсутствует"
  PASS=$((PASS + 1))
fi

# ===== M7: реестр обрезан посреди записи -> не смог проверить =============================
echo "==> M7: реестр обрезан — не смог проверить"
D7="$(mk_fixture_dir)"
printf 'namespaces:\n  - namespace: adr\n    prefix: "ADR-"\n    width: 3\n    graveya' > "$D7/.nauta-ids.yaml"
mkdir -p "$D7/content/00-project/adr"
echo "# ADR-036" > "$D7/content/00-project/adr/ADR-036-live.md"
run_gate "$D7"
assert "M7 exit non-zero" "$([[ $RC -ne 0 ]] && echo yes || echo no)" "yes"
assert_out "M7 называет путь реестра" "$OUT" ".nauta-ids.yaml"

# ===== M8: шесть файлов, каждый определяет свой AC-001 (scope: file) -> 0, не коллизия ====
echo "==> M8: шесть AC-001 при scope: file — законно, exit 0"
D8="$(mk_fixture_dir)"
cat > "$D8/.nauta-ids.yaml" <<'YAML'
namespaces:
  - namespace: ac
    prefix: "AC-"
    width: 3
    home: ["content/30-requirements/*.md"]
    definition: list-or-row-head
    scope: file
    allocation: closed
    populated: true
YAML
mkdir -p "$D8/content/30-requirements"
for i in 1 2 3 4 5 6; do
  echo "- [ ] AC-001: собственный критерий" > "$D8/content/30-requirements/req-$i.md"
done
run_gate "$D8"
assert "M8 exit 0" "$RC" "0"
if grep -qi "коллизи" <<<"$OUT"; then
  echo "  ✗ M8 не должен упоминать коллизию"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M8 не упоминает коллизию"
  PASS=$((PASS + 1))
fi

# ===== M9: цитата RES-410/TPL-900 в прозе — не определение, 0, максимумы не сдвинуты ======
echo "==> M9: цитата чужого реестра в прозе — не определение"
D9="$(mk_fixture_dir)"
cat > "$D9/.nauta-ids.yaml" <<'YAML'
namespaces:
  - namespace: res
    prefix: "RES-"
    width: 3
    home: ["content/10-domain/research/*.md"]
    definition: h1-suffix
    scope: namespace
    allocation: allocated
    populated: true
    highwater: 44
YAML
mkdir -p "$D9/content/10-domain/research"
printf '# Инвентаризация донора (RES-044)\n\nИсточник запроса: RES-410; ср. TPL-900.\n' \
  > "$D9/content/10-domain/research/2026-08-17-a.md"
run_gate "$D9"
assert "M9 exit 0" "$RC" "0"
if grep -qF "RES-410" <<<"$OUT" || grep -qF "TPL-900" <<<"$OUT"; then
  echo "  ✗ M9 упоминание не должно попадать в отчёт как определение"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M9 упоминание не попадает в отчёт"
  PASS=$((PASS + 1))
fi

# ===== M10: однобуквенный префикс — слово на ту же букву не разбирается как токен ========
# (DEV-038, NA-EPIC-13). list-or-row-head с width:1 не должен матчить "Дата"/"Держать" как
# токен "ата"/"ержать" префикса "Д" — за префиксом должна идти цифра, иначе строка не
# кандидат вовсе (ни ERROR, ни [INFO]).
echo "==> M10: список-заголовок под однобуквенным префиксом — слово не разбирается как id"
D10="$(mk_fixture_dir)"
cat > "$D10/.nauta-ids.yaml" <<'YAML'
namespaces:
  - namespace: decision-clause
    prefix: "Д"
    width: 1
    home: ["content/00-project/adr/ADR-*.md"]
    definition: list-or-row-head
    scope: file
    allocation: derived
    populated: true
YAML
mkdir -p "$D10/content/00-project/adr"
cat > "$D10/content/00-project/adr/ADR-900-fixture.md" <<'MD'
# ADR-900: фикстура

- **Дата: 2026-08-18** — не идентификатор, просто слово на "Д"
- **Держать текущий подход** — тоже не идентификатор
- **Д1: настоящее решение А** — законный токен пространства
MD
run_gate "$D10"
assert "M10 exit 0" "$RC" "0"
if grep -qF "Дата" <<<"$OUT" || grep -qF "ержать" <<<"$OUT"; then
  echo "  ✗ M10 слово на букву префикса не должно попадать в отчёт как токен"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M10 слово на букву префикса не разбирается как токен"
  PASS=$((PASS + 1))
fi
if grep -qF "Д1" <<<"$OUT"; then
  echo "  ✗ M10 законный токен Д1 неожиданно попал в отчёт (ожидалось молчание — единственное вхождение)"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ M10 законный токен Д1 не мешает (единственное вхождение — тихо)"
  PASS=$((PASS + 1))
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]]
