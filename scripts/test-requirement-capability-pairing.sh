#!/usr/bin/env bash
# Тест-дизайн QA-001/QA-002 (ktalk-plugin-56l.17/.23): наблюдаемые исходы ADR-021 — пара
# «требование → openspec/specs/<capability>/spec.md» в дереве пакета ktalk-mcp.
# Прогон ручной: bash scripts/test-requirement-capability-pairing.sh
#
# QA-002 (ревизия): два решения, по которым писался первый раунд, не выдержали исполнения
# и были исправлены — стаб приведён следом, не ослаблен до тавтологии:
#   1) Переезд четырёх требований переносит СОДЕРЖАНИЕ, не путь: на старых путях остаются
#      файлы-указатели (Тип контента: Прочее, без каркаса FR/NFR, с адресом нового файла) —
#      удаление оригиналов давало 34 битые ссылки в 22 документах (5 ADR, roadmap.md).
#      PAIR-2 проверяет отличие указателя от требования, не факт «файла нет».
#   2) `.nauta-ids.yaml`: `scenario.populated` — ПОСТОЯННЫЙ `false`, не флаг «до первой
#      спеки»: пустой `prefix` + `allocation: derived` делает `populated: true` порчей
#      реестра (`id-check.sh:527-533`), не «корпус пуст». PAIR-5 проверяет инвариант
#      независимо от числа спек, не переключение по их наличию.
#
# Источник контракта: content/00-project/adr/ADR-021-requirement-capability-pairing.md,
# content/40-architecture/ADR-021-requirement-capability-pairing-spec.md §1-4.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0

check_true() { # check_true <условие 0/1> <название>
  if [ "$1" = "0" ]; then PASS=$((PASS+1)); printf 'ok   %s\n' "$2"
  else FAIL=$((FAIL+1)); printf 'FAIL %s\n' "$2"; fi
}

check_eq() { # check_eq <ожидание> <факт> <название>
  if [ "$1" = "$2" ]; then PASS=$((PASS+1)); printf 'ok   %s\n' "$3"
  else FAIL=$((FAIL+1)); printf 'FAIL %s: ожидалось "%s", получено "%s"\n' "$3" "$1" "$2"; fi
}

# check_capability_line <файл> <csv ожидаемых slug'ов, через запятую> <тест-имя>
# Покрывает все 4 исхода check_capability_link (validate-content.py:954-1000):
#   A) строки нет вовсе; B) строка есть, путей не называет; C) путь не той формы
#   (openspec/specs/<slug>/spec.md); D) путь той формы, но файла нет.
check_capability_line() {
  local file="$1" expected_csv="$2" name="$3"
  if [ ! -f "$file" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL %s: файла требования ещё нет (%s)\n' "$name" "$file"; return
  fi
  local line
  line="$(grep -m1 '\*\*Capability:\*\*' "$file" || true)"
  if [ -z "$line" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL %s: строки **Capability:** нет [исход A]\n' "$name"; return
  fi
  local paths
  paths="$(printf '%s\n' "$line" | grep -oE 'openspec/specs/[^`, ]+' || true)"
  if [ -z "$paths" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL %s: строка есть, ни одного пути [исход B]\n' "$name"; return
  fi
  local p bad_form=0 dangling=0
  for p in $paths; do
    if ! [[ "$p" =~ ^openspec/specs/[a-z0-9-]+/spec\.md$ ]]; then bad_form=1; fi
    if [ ! -f "$ROOT/$p" ]; then dangling=1; fi
  done
  check_true "$bad_form" "$name: все пути формы openspec/specs/<slug>/spec.md [исход C]"
  check_true "$dangling" "$name: все объявленные спеки существуют на диске [исход D]"
  local got
  got="$(printf '%s\n' $paths | sed -E 's#openspec/specs/([a-z0-9-]+)/spec\.md#\1#' | sort | paste -sd, -)"
  local want
  want="$(printf '%s\n' "$expected_csv" | tr ',' '\n' | sort | paste -sd, -)"
  check_eq "$want" "$got" "$name: набор capability совпадает с ADR-021-spec §1"
}

# check_pointer <старый файл> <подстрока-адрес нового файла> <имя проверки>
# Различает файл-указатель от требования, которое "воскресло" на старом пути (QA-002:
# переезд переносит содержание, не путь — удаление оригиналов давало 34 битые ссылки в 22
# документах, включая 5 ADR и roadmap.md). Три независимых признака указателя:
#   (а) Тип контента остаётся Прочее, не Требование;
#   (б) нет каркаса FR/NFR (содержание не вернулось);
#   (в) файл называет адрес нового расположения.
check_pointer() {
  local file="$1" new_path_substr="$2" name="$3"
  if [ ! -f "$file" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL %s: файла-указателя нет — исторические ссылки на этот путь сломаны
' "$name"; return
  fi
  local type_line
  type_line="$(awk '/name: Тип контента/{getline; print; exit}' "$file" | tr -d ' ')"
  check_eq "value:[Прочее]" "$type_line" "$name: Тип контента остаётся Прочее (не воскресло как Требование)"
  local scaffold
  scaffold="$(grep -cE '^#{2,4} +(FR|NFR)-[0-9]' "$file" || true)"
  check_eq "0" "$scaffold" "$name: нет каркаса FR/NFR (содержание не вернулось на старый путь)"
  if grep -qF "$new_path_substr" "$file"; then
    PASS=$((PASS+1)); printf 'ok   %s: называет адрес нового файла (%s)\n' "$name" "$new_path_substr"
  else
    FAIL=$((FAIL+1)); printf 'FAIL %s: не называет адрес нового файла %s\n' "$name" "$new_path_substr"
  fi
}

echo "== PAIR-1: check.sh --fast -> Errors: 0 (итоговое состояние эпика) =="
FAST_OUT="$("$ROOT/scripts/check.sh" --fast 2>&1)"
FAST_ERR_LINE="$(printf '%s\n' "$FAST_OUT" | grep -E '^Errors: ' | tail -1)"
FAST_ERR_COUNT="$(printf '%s\n' "$FAST_ERR_LINE" | grep -oE 'Errors: [0-9]+' | grep -oE '[0-9]+')"
check_eq "0" "${FAST_ERR_COUNT:-unknown}" \
  "PAIR-1 validate-content.py: 0 ошибок (переезд+спеки+строки Capability закрыты)"

echo "== PAIR-2: четыре старых пути — файлы-указатели, не воскресшие требования =="
check_pointer "$ROOT/content/30-requirements/ktalk-plugin-meetings.md" \
  "2026-08-18-meetings-prompt-surface.md" "PAIR-2 ktalk-plugin-meetings.md"
check_pointer "$ROOT/content/30-requirements/ktalk-plugin-onboarding.md" \
  "2026-08-18-onboarding-sanctioned-install.md" "PAIR-2 ktalk-plugin-onboarding.md"
check_pointer "$ROOT/content/30-requirements/ktalk-plugin-analysis-calibration.md" \
  "2026-08-19-analysis-quality-calibration.md" "PAIR-2 ktalk-plugin-analysis-calibration.md"
check_pointer "$ROOT/content/30-requirements/ktalk-prompt-defect-channel.md" \
  "2026-08-19-prompt-defect-channel.md" "PAIR-2 ktalk-prompt-defect-channel.md"

echo "== PAIR-3: три оставшихся требования несут строки Capability (все 4 исхода) =="
check_capability_line "$ROOT/content/30-requirements/personal-api-key.md" \
  "talk-api-auth-modes,recording-data-access,registry-sync-window" "PAIR-3 personal-api-key.md"
check_capability_line "$ROOT/content/30-requirements/rooms-calendar-scheduling.md" \
  "room-diagnostics,calendar-window-reading,meeting-scheduling" "PAIR-3 rooms-calendar-scheduling.md"
check_capability_line "$ROOT/content/30-requirements/ktalk-plugin.md" \
  "host-project-config-discovery,centralized-machine-storage" "PAIR-3 ktalk-plugin.md"

echo "== PAIR-4: восемь файлов openspec/specs/<capability>/spec.md существуют =="
for c in talk-api-auth-modes recording-data-access registry-sync-window \
         room-diagnostics calendar-window-reading meeting-scheduling \
         host-project-config-discovery centralized-machine-storage; do
  if [ -f "$ROOT/openspec/specs/$c/spec.md" ]; then
    PASS=$((PASS+1)); printf 'ok   PAIR-4 %s\n' "$c"
  else
    FAIL=$((FAIL+1)); printf 'FAIL PAIR-4 openspec/specs/%s/spec.md отсутствует\n' "$c"
  fi
done

echo "== PAIR-5 (инвариант, ADR-021 п.4 после ревизии): scenario.populated ВСЕГДА false =="
SPEC_COUNT="$(find "$ROOT/openspec/specs" -mindepth 2 -name spec.md 2>/dev/null | wc -l | tr -d ' ')"
POPULATED_LINE="$(awk '/namespace: scenario/{f=1} f&&/populated:/{print; exit}' "$ROOT/.nauta-ids.yaml")"
NORM="$(printf '%s' "$POPULATED_LINE" | tr -d ' ')"
check_eq "populated:false" "$NORM" \
  "PAIR-5 scenario.populated остаётся false независимо от числа спек (сейчас: $SPEC_COUNT) — пустой prefix + allocation: derived делает populated: true порчей реестра, id-check.sh:527-533"

echo "== PAIR-6: указатели зарегистрированы в _index.md (иначе — сирота, C10/C17) =="
IDX="$ROOT/content/30-requirements/_index.md"
for f in ktalk-plugin-meetings.md ktalk-plugin-onboarding.md \
         ktalk-plugin-analysis-calibration.md ktalk-prompt-defect-channel.md; do
  if [ ! -f "$ROOT/content/30-requirements/$f" ]; then
    FAIL=$((FAIL+1)); printf 'FAIL PAIR-6 %s: файла-указателя нет (см. PAIR-2)\n' "$f"
  elif grep -q "($f)" "$IDX"; then
    PASS=$((PASS+1)); printf 'ok   PAIR-6 %s: зарегистрирован в _index.md\n' "$f"
  else
    FAIL=$((FAIL+1)); printf 'FAIL PAIR-6 %s: файл есть, но не зарегистрирован в _index.md — сирота (C10)\n' "$f"
  fi
done

echo "== PAIR-7: FR-19 auth-status слит в talk-api-auth-modes, не своя capability =="
if [ -d "$ROOT/openspec/specs/auth-status" ]; then
  FAIL=$((FAIL+1)); printf 'FAIL PAIR-7 openspec/specs/auth-status/ существует — FR-19 обязан жить внутри talk-api-auth-modes (ADR-021-spec §1), не отдельной capability\n'
elif [ -f "$ROOT/openspec/specs/talk-api-auth-modes/spec.md" ] && \
     grep -qi 'auth-status\|auth_status' "$ROOT/openspec/specs/talk-api-auth-modes/spec.md"; then
  PASS=$((PASS+1)); printf 'ok   PAIR-7 auth-status покрыт внутри talk-api-auth-modes\n'
else
  FAIL=$((FAIL+1)); printf 'FAIL PAIR-7 talk-api-auth-modes/spec.md ещё не несёт сценария auth-status (или спеки ещё нет)\n'
fi

echo "== PAIR-8: check.sh --full -> exit 0 (после PAIR-1..7) =="
"$ROOT/scripts/check.sh" --full >/tmp/pair8-full.log 2>&1
check_eq "0" "$?" "PAIR-8 check.sh --full завершается кодом 0"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
