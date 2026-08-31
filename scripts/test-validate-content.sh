#!/usr/bin/env bash
# test-validate-content.sh — самопроверка гейта scripts/validate-content.py.
#
# Предмет — процесс: stdout/stderr и код возврата на СИНТЕТИЧЕСКИХ фикстурах (временный
# каталог со своим content/, своим .doc-root.yaml, своим .nauta-gates.yaml), не на дереве
# nauta. Ровно это отличие и есть смысл файла: ишью потребителей #11 (C5 инертна) и #12
# (потолок C11 не применяется) — один класс, «проверка признана работающей по признаку,
# снятому с собственного дерева». Зелёное на своём корпусе отвечало на вопрос «краснеет ли
# проверка хоть на чём-нибудь», а не «на каких входах она не исполняется вовсе». Прецедент
# ADR-025, перенесённый ADR-038 §7: «детектор, не падавший ни разу, неотличим от
# отсутствующего».
#
# ГРАНИЦА (объявлена явно, не подразумевается). Гейт несёт 19 проверок C1-C20; эта сьюта НЕ
# проверяет их все и полным покрытием не является. Она проверяет ОДИН класс — «зелёное
# означает не проверялось» — на четырёх группах входов:
#   A. гейт умеет краснеть вообще: нарушение даёт ненулевой код И названное сообщение
#      (пустой stdout поимкой не считается);
#   B. C5 на чужих формах property (ишью #11, контракт DEV-122);
#   C. потолок C11 достижим из ОБЕИХ качественных веток (ишью #12, контракт DEV-123/ADR-078);
#   D. объявленное молчание отличимо от невыполнения (форма `absent`).
# Остальные проверки покрыты pytest (tests/test_dev122_*.py, tests/test_dev123_*.py,
# tests/test_content_*_gate.py и соседи) и аудитом фальсифицируемости QA-064
# (content/60-implementation/2026-08-26-qa-064-check-falsifiability-audit.md). Дубль
# контракта здесь не нужен и не делается: pytest в дерево потребителя НЕ доставляется
# (bin/deliver.sh, PAYLOAD_FILES — только scripts/ и .githooks/), поэтому у потребителя эта
# bash-сьюта — единственный работающий детектор дефекта гейта, и она обязана быть узкой и
# быстрой, а не полной.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GATE="$REPO_ROOT/scripts/validate-content.py"

[[ -f "$GATE" ]] || { echo "ERROR: $GATE not found" >&2; exit 2; }
command -v uv >/dev/null || { echo "ERROR: uv не найден в PATH — гейт запускается тем же" \
  "раннером, что и в check.sh (uv run)" >&2; exit 2; }

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

# assert_out <описание> <вывод> <подстрока>... — все подстроки обязаны быть в выводе.
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

# refute_out <описание> <вывод> <подстрока>... — ни одной подстроки в выводе быть не должно.
refute_out() {
  local desc="$1" hay="$2"; shift 2
  local pat
  for pat in "$@"; do
    if grep -qF -- "$pat" <<<"$hay"; then
      echo "  ✗ $desc"
      echo "    неожиданно найдено в выводе: $pat"
      FAIL=$((FAIL + 1))
      return
    fi
  done
  echo "  ✓ $desc"
  PASS=$((PASS + 1))
}

# assert_caught <описание> <rc> <вывод> <подстрока>... — форма «поимка», а не «exit != 0».
# Класс провала DEV-085: ненулевой код при пустом выводе выглядит как поимка и ею не
# является — потребитель не узнаёт ни ЧТО найдено, ни ГДЕ. Три условия сразу: код ненулевой,
# вывод непустой, и в нём стоят названные слова.
assert_caught() {
  local desc="$1" rc="$2" hay="$3"; shift 3
  if [[ "$rc" -eq 0 ]]; then
    echo "  ✗ $desc"
    echo "    код возврата 0 — нарушение не поймано вовсе"
    FAIL=$((FAIL + 1))
    return
  fi
  if [[ -z "${hay//[[:space:]]/}" ]]; then
    echo "  ✗ $desc"
    echo "    код $rc при ПУСТОМ выводе — это не поимка, а молчаливый отказ (ADR-007 Д1)"
    FAIL=$((FAIL + 1))
    return
  fi
  assert_out "$desc" "$hay" "$@"
}

run_gate() {
  local dir="$1"; shift
  set +e
  OUT="$(cd "$dir" && uv run "$GATE" "${@:-content}" 2>&1)"
  RC=$?
  set -e
}

# ===== фикстуростроение =================================================================
# Дерево минимально ровно настолько, чтобы ОСТАЛЬНЫЕ 18 проверок молчали: иначе их находки
# смешались бы со счётом Errors/Warnings, который сценарии ниже читают как прибор. Проверено
# отдельным прогоном: голая фикстура даёт "OK (2 файлов проверены)" и "Errors: 0 | Warnings: 0".
mk_tree() {
  local d; d="$(mktemp -d "$TMPROOT/fixture.XXXXXX")"
  mkdir -p "$d/content"
  : > "$d/.nauta-gates.yaml"
  printf '# Fixture\n\n' > "$d/content/_index.md"
  echo "$d"
}

# doc_root <dir> <тип-property> — .doc-root.yaml со строковым values:.
doc_root() {
  cat > "$1/content/.doc-root.yaml" <<YAML
title: Fixture
properties:
  - name: Тип контента
    type: $2
    values: [Прочее, ADR]
YAML
}

# register <dir> <имя-файла> — ссылка в content/_index.md (снимает C17 и C10).
register() { printf -- '- [%s](%s)\n' "${2%.md}" "$2" >> "$1/content/_index.md"; }

# article <dir> <имя-файла> <значение "Тип контента"> — статья с frontmatter; тело читается
# со stdin. Число строк тела равно числу "\n" в теле — ровно тот прибор, которым C11 меряет T
# (_strip_leading_frontmatter(raw).count("\n")), поэтому потолки ниже задаются точно.
article() {
  local dir="$1" name="$2" type_value="$3"
  { printf -- '---\nproperties:\n  - name: Тип контента\n    value: [%s]\n---\n' "$type_value"
    cat
  } > "$dir/content/$name"
  register "$dir" "$name"
}

# body_lines <N> — N строк прозы без единого структурного признака (HAS_STRUCTURE_RE:
# таблица, <view>, <note>, заголовок уровня >= 2). Нужны и как объём T, и как run для T_S.
body_lines() {
  local i
  for ((i = 1; i <= $1; i++)); do
    echo "Строка прозы номер $i без структуры, чтобы участок не прерывался."
  done
}

# =========================================================================================
# A. Гейт умеет краснеть вообще
# =========================================================================================
echo "==> A: гейт различает чистое дерево и нарушение"

echo "--> A1: чистая фикстура — exit 0 и явное «проверено», не молчание"
A1="$(mk_tree)"; doc_root "$A1" Enum
article "$A1" article.md Прочее <<'MD'

# Статья

Текст.
MD
run_gate "$A1"
assert "A1 exit 0" "$RC" "0"
assert_out "A1 называет, что проверка выполнена и на скольких файлах" "$OUT" \
  "OK (" "файлов проверены" "Errors: 0 | Warnings: 0"

echo "--> A2: статья вне _index.md — ненулевой код И названное нарушение"
A2="$(mk_tree)"; doc_root "$A2" Enum
# Намеренно без register: предмет сценария — C17, регистрация статьи в разделе.
{ printf -- '---\nproperties:\n  - name: Тип контента\n    value: [Прочее]\n---\n'
  printf '\n# Сирота\n\nТекст.\n'
} > "$A2/content/orphan.md"
run_gate "$A2"
assert_caught "A2 поймано: код, непустой вывод и текст находки" "$RC" "$OUT" \
  "content/orphan.md" "не зарегистрирована ссылкой в content/_index.md"
assert_out "A2 находка попала в счётчик, а не только в строку вывода" "$OUT" "Errors: 1"
refute_out "A2 не рапортует «проверено, нарушений нет» одновременно с находкой" "$OUT" "OK ("

# =========================================================================================
# B. C5 на чужих формах property (ишью #11, контракт DEV-122)
# =========================================================================================
echo "==> B: C5 — объявленный values: применяется либо громко отказывает"

echo "--> B1: канон (type: Enum, values строками) — значение вне списка ловится"
B1="$(mk_tree)"; doc_root "$B1" Enum
article "$B1" bad.md Мусор <<'MD'

# Плохая

Текст.
MD
run_gate "$B1"
assert_caught "B1 значение вне enum названо вместе с файлом и допустимым множеством" \
  "$RC" "$OUT" "content/bad.md" 'property "Тип контента" имеет значение "Мусор"' \
  "не входящее в enum ['ADR', 'Прочее']"

echo "--> B2: неканоническое написание типа при непустом values: — громкая ошибка, не тишина"
B2="$(mk_tree)"; doc_root "$B2" enum
article "$B2" ok.md Прочее <<'MD'

# Статья

Текст.
MD
run_gate "$B2"
assert_caught "B2 неканонический type назван вместе с носителем и лечением" "$RC" "$OUT" \
  "content/.doc-root.yaml" "не каноническое" "не применяет ни одна проверка" \
  "использовать \`type: Enum\` со строковым массивом \`values:\`"
refute_out "B2 не выдаёт тишину за чистоту" "$OUT" "OK ("

echo "--> B3: values: списком отображений (- name: X) — TypeError недостижим, выборка живая"
B3="$(mk_tree)"
cat > "$B3/content/.doc-root.yaml" <<'YAML'
title: Fixture
properties:
  - name: Тип контента
    type: Enum
    values:
      - name: Прочее
      - name: ADR
YAML
article "$B3" ok.md Прочее <<'MD'

# Хорошая

Текст.
MD
article "$B3" bad.md Мусор <<'MD'

# Плохая

Текст.
MD
run_gate "$B3"
assert "B3 exit 1 (находка), а не 2/аварийный код интерпретатора" "$RC" "1"
refute_out "B3 форма - name: X не роняет гейт" "$OUT" "Traceback" "TypeError" "unhashable"
assert_caught "B3 отображение разобрано: нарушитель найден по имени name" "$RC" "$OUT" \
  "content/bad.md" 'имеет значение "Мусор"' "не входящее в enum ['ADR', 'Прочее']"
refute_out "B3 законное значение из той же формы не объявлено нарушением" "$OUT" \
  "content/ok.md: property"

# =========================================================================================
# C. Потолок C11 достижим из ОБЕИХ качественных веток (ишью #12, ADR-078)
# =========================================================================================
echo "==> C: грандфазер-потолок C11 — обе качественные ветки, оба исхода"

# companion-spec: тип ADR, T=10, спутника <stem>-spec.md нет. severity: block — как в живом
# каталоге; уровень находки решает потолок, не severity (ADR-078 Д3).
gates_companion() {
  cat > "$1/.nauta-gates.yaml" <<YAML
sizeBudgets:
  - type: ADR
    thresholdLines: 10
    quality: companion-spec
    severity: block
sizeBudgetGrandfathered:
  - path: content/frozen.md
    ceiling: $2
YAML
}

# longest_run_without_structure: тип Прочее, T=10, T_S=5. severity: warn НАМЕРЕННО — превышение
# потолка обязано быть error и на мягкой ступени (ADR-064 Д3, ADR-078 Д3).
gates_run() {
  cat > "$1/.nauta-gates.yaml" <<YAML
sizeBudgets:
  - type: Прочее
    thresholdLines: 10
    quality: longest_run_without_structure
    qualityThreshold: 5
    severity: warn
sizeBudgetGrandfathered:
  - path: content/frozen.md
    ceiling: $2
YAML
}

echo "--> C1: companion-spec, ровно НА потолке (20 == 20) — warning с провенансом"
C1="$(mk_tree)"; doc_root "$C1" Enum; gates_companion "$C1" 20
article "$C1" frozen.md ADR < <(body_lines 20)
run_gate "$C1"
assert "C1 exit 0 — потолок не превышен, находка не блокирует" "$RC" "0"
assert_out "C1 warning называет числа, провенанс (rel) в скобках и решение" "$OUT" \
  "грандфазер: 20 строк тела <= замороженного потолка 20" "(content/frozen.md, ADR-018 Д5)" \
  "не блокирует" "[warning]" "Errors: 0 | Warnings: 1"

echo "--> C2: companion-spec, выше потолка (20 > 15) — error"
C2="$(mk_tree)"; doc_root "$C2" Enum; gates_companion "$C2" 15
article "$C2" frozen.md ADR < <(body_lines 20)
run_gate "$C2"
assert_caught "C2 превышение потолка — error с числами и лечением" "$RC" "$OUT" \
  "грандфазер-потолок превышен: 20 строк тела > 15 (content/frozen.md)" \
  "подними ceiling явной правкой sizeBudgetGrandfathered" "[error]"

echo "--> C3: longest_run_without_structure, ровно НА потолке (20 == 20) — warning"
C3="$(mk_tree)"; doc_root "$C3" Enum; gates_run "$C3" 20
article "$C3" frozen.md Прочее < <(body_lines 20)
run_gate "$C3"
assert "C3 exit 0 — вторая ветка тоже доходит до потолка, а не мимо него" "$RC" "0"
assert_out "C3 warning несёт провенанс ветки ADR-078, а не ветки companion-spec" "$OUT" \
  "грандфазер: 20 строк тела <= замороженного потолка 20" "(content/frozen.md, ADR-078)" \
  "не блокирует" "Errors: 0 | Warnings: 1"
refute_out "C3 не печатает форму первой ветки" "$OUT" "ADR-018 Д5"

echo "--> C4: longest_run_without_structure, выше потолка (20 > 15) — error при severity: warn"
C4="$(mk_tree)"; doc_root "$C4" Enum; gates_run "$C4" 15
article "$C4" frozen.md Прочее < <(body_lines 20)
run_gate "$C4"
assert_caught "C4 превышение потолка красит и на мягкой ступени severity" "$RC" "$OUT" \
  "грандфазер-потолок превышен: 20 строк тела > 15 (content/frozen.md)" \
  "ADR-078, ADR-064 Д3" "[error]"

# =========================================================================================
# D. Объявленное молчание отличимо от невыполнения
# =========================================================================================
echo "==> D: конфигурации нет — это сказано словами, а не тишиной"

echo "--> D1: ключа sizeBudgets нет — форма absent дословно"
D1="$(mk_tree)"; doc_root "$D1" Enum
article "$D1" article.md Прочее <<'MD'

# Статья

Текст.
MD
run_gate "$D1"
assert "D1 exit 0" "$RC" "0"
# Окно сужено до ОДНОЙ записи: у гейта четыре строки провенанса (C11/C13/C14/C18), и фразовый
# ассерт по всему выводу был бы вакуумным — он бы прошёл на любой из четырёх.
assert_out "D1 запись C11 названа дословно, вместе с причиной" "$OUT" \
  "конфигурация C11 (sizeBudgets): absent (проверка не выполняется) — ключ не задан в .nauta-gates.yaml"

echo "--> D2: ключ есть — та же запись говорит configured, и absent про неё исчезает"
D2="$(mk_tree)"; doc_root "$D2" Enum; gates_run "$D2" 20
article "$D2" article.md Прочее <<'MD'

# Статья

Текст.
MD
run_gate "$D2"
assert "D2 exit 0" "$RC" "0"
assert_out "D2 C11 объявлен сконфигурированным" "$OUT" "конфигурация C11 (sizeBudgets): configured"
refute_out "D2 absent и configured не печатаются про один ключ одновременно" "$OUT" \
  "конфигурация C11 (sizeBudgets): absent"

echo ""
echo "PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]]
