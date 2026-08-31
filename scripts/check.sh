#!/usr/bin/env bash
# check.sh — single entry-point для всех валидаций.
#
# Usage:
#   bash scripts/check.sh [--fast | --full | --secret-scan-only | --delivery-composition-only]
#
# --fast (default): validate-content.py + validate-profile.py + check-adr-line-limit.py
#         (ADR-013) + check-test-subject-governs.py (ADR-070; код 1 объявлен мягким —
#         ADR-072 Д3/Д4) + check-content-actuality.py (ADR-076 Д7; код 1 объявлен мягким по
#         той же причине — цена ступени +0,14 с, замер спутника ADR-076 §6).
# --full: + check-backlog-closure.py (ADR-012 Д4) + id-check.sh (ADR-038, решение владельца
#         Р22; перевод ступени в --fast по ADR-072 Д7 ОСТАНОВЛЕН DEV-111 — см. отчёт задачи:
#         он расходится с ADR-030 Д6(2), требующим зелёный --fast у потребителя сразу после
#         payload'а, где .nauta-ids.yaml ещё не заведён) + self-test harness
#         (test-check-adr-line-limit.sh, test-check-backlog-closure.sh,
#         test-check-breaking-change-section.sh, test-check-id.sh, test-validate-content.sh —
#         две последние доставляются payload'ом; test-check-id зарегистрирована DEV-022,
#         test-validate-content заведена и зарегистрирована DEV-125 тем же коммитом).
#
# ADR-037 (content/00-project/adr/ADR-037-gate-roster-from-delivery-basis.md +
# content/40-architecture/ADR-037-gate-roster-from-delivery-basis-spec.md): перечень вызовов
# ниже — намерение («какие гейты этот раннер знает вообще»), НЕ факт обязательности. Факт —
# .nauta-scripts-basis.yaml (ADR-030 Д3), единственная запись дерева-потребителя о том, что
# ему привезли. Дерево-источник payload'а (само это дерево, опознаётся по подписи
# bin/deliver.sh) — исключение: там обязателен весь перечень целиком, найденный рядом базис
# на это не влияет (ADR-037 Д3).

set -euo pipefail

# uv-guard: обязательная зависимость
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' не найден в PATH. Установите: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

MODE="${1:---fast}"

case "$MODE" in
  --fast|--full|--secret-scan-only|--delivery-composition-only|-h|--help) ;;
  *)
    echo "Usage: $0 [--fast | --full | --secret-scan-only | --delivery-composition-only]" >&2
    exit 2
    ;;
esac

if [[ "$MODE" == "-h" ]] || [[ "$MODE" == "--help" ]]; then
  cat <<EOF
Usage: $0 [--fast | --full | --secret-scan-only | --delivery-composition-only]

Modes:
  --fast (default)  Run validators (validate-content.py + validate-profile.py +
                    check-adr-line-limit.py). Quick gate. Suitable for pre-commit hook.
  --full            Run --fast checks + check-backlog-closure.py (ADR-012 Д4 — lives in
                    --full, not --fast) + id-check.sh (ADR-038 identifier registry audit;
                    --full by owner ruling Р22) + self-test harness (test-check-adr-line-
                    limit.sh, test-check-backlog-closure.sh,
                    test-check-breaking-change-section.sh, test-check-id.sh,
                    test-validate-content.sh). Suitable for CI / pre-merge gate.
  --secret-scan-only
                    Run ONLY the secret-scan-tree gate — the same block --fast runs,
                    not a copy of it. Meant for the release path (ADR-073 Д4, spec
                    §4.3): on the filtered delivery tree the other gates have no
                    subject, and secret-scan-tree is the only applicable one.
  --delivery-composition-only
                    Run ONLY the delivery-composition guard — again the same block,
                    not a copy. Step 4 of the release procedure (ADR-073-spec §4.1)
                    needs the guard alone on the filtered tree, where --fast is red
                    for four gates that have no subject there.

Obligation (ADR-037): which of the gates above MUST exist in this tree is resolved from
.nauta-scripts-basis.yaml (delivery record), not hardcoded — see ADR-037-spec §2.

Exit codes:
  0  All checks passed
  1  Validator, gate, suite failed, or the delivery basis could not be read
  2  Invalid usage
EOF
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# ADR-037 §2 — разрешение режима обязательности. Выполняется РОВНО один раз, здесь, ДО
# первого вызова гейта — вердикт о том, обязана ли каждая позиция перечня существовать,
# принимается прежде, чем побежит хоть один шаг.
# ---------------------------------------------------------------------------
BASIS_FILE="$REPO_ROOT/.nauta-scripts-basis.yaml"
ORIGIN_INSTALLER="$REPO_ROOT/bin/deliver.sh"

# Признак источника — СОДЕРЖИМОЕ, не имя файла (ADR-037-spec §2): bin/deliver.sh — родовой
# путь, у потребителя может лежать одноимённый чужой скрипт выкладки. Подпись — литерал имени
# базиса (".nauta-scripts-basis.yaml", несущая строка BASIS_NAME= в самом bin/deliver.sh:31)
# в тексте установщика: писатель базиса обязан называть файл, который пишет.
ORIGIN=0
if [[ -f "$ORIGIN_INSTALLER" ]] && grep -Fq -- ".nauta-scripts-basis.yaml" "$ORIGIN_INSTALLER"; then
  ORIGIN=1
fi

OBLIGATION_MODE="STRICT"   # STRICT | DELIVERED
DECLARED_FILES=""          # \n-разделённый список путей files: (заполняется в DELIVERED)
SKIPPED_FILES=""           # \n-разделённый список путей skip: (заполняется в DELIVERED)
CONFLICTED_FILES=""        # \n-разделённый список путей conflicts: (ADR-079 Д1/Д2)
BASIS_NAUTA_VERSION=""
BASIS_NAUTA_REF_SHA=""
BASIS_SYNCED_AT=""
BASIS_FILES_COUNT=""

# --- §4 ADR-037-spec: читатели базиса — блочный awk, та же форма, что уже разбирает базис
#     bin/deliver.sh (секция 3 того файла): вход в блок по заголовку без отступа, выход — на
#     первой строке без отступа. Каждый читатель обязан ВСЕГДА возвращать 0 (см. заметку в
#     bin/deliver.sh про set -euo pipefail и command substitution внутри присваивания —
#     "не нашёл" не ошибка выполнения самого читателя, различие видно по ПУСТОТЕ вывода).

_basis_files_paths() {
  awk '
    /^files:[ \t]*(#.*)?$/ { infiles=1; next }
    infiles && $0 ~ /^[^ \t]/ { infiles=0 }
    infiles {
      line=$0
      sub(/^[ \t]+/, "", line)
      if (line == "" || line ~ /^#/) next
      colon = index(line, ":")
      if (colon == 0) next
      key = substr(line, 1, colon-1)
      gsub(/[ \t]+$/, "", key)
      print key
    }
  ' "$BASIS_FILE"
}

_basis_skip_paths() {
  awk '
    /^skip:[ \t]*(#.*)?$/ { inskip=1; next }
    inskip && $0 ~ /^[^ \t]/ { inskip=0 }
    inskip {
      line=$0
      sub(/^[ \t]*-[ \t]*/, "", line)
      gsub(/^[ \t]+/, "", line); gsub(/[ \t]+$/, "", line)
      if (line == "" || line ~ /^#/) next
      print line
    }
  ' "$BASIS_FILE"
}

# _basis_conflict_paths — ADR-079 Д2/§5 п.1 спутника: копия формы _basis_files_paths с
# заголовком `conflicts:`. Секция несёт ФАКТИЧЕСКИЙ sha диска на момент синка (Д1), тогда
# как `files:` — базу sha-дискриминатора ADR-030 Д4; путать их и было дефектом ишью #13.
_basis_conflict_paths() {
  awk '
    /^conflicts:[ \t]*(#.*)?$/ { inconf=1; next }
    inconf && $0 ~ /^[^ \t]/ { inconf=0 }
    inconf {
      line=$0
      sub(/^[ \t]+/, "", line)
      if (line == "" || line ~ /^#/) next
      colon = index(line, ":")
      if (colon == 0) next
      key = substr(line, 1, colon-1)
      gsub(/[ \t]+$/, "", key)
      print key
    }
  ' "$BASIS_FILE"
}

# _basis_entry_value <заголовок-блока> <путь> — значение записи внутри блочного маппинга
# (`files:` или `conflicts:`). Нужен ровно одному вызывающему — тексту шестого исхода,
# который обязан назвать ОБА sha: заявленный базисом и найденный на диске (§4 спутника).
# Хешера это не заводит: значения ЧИТАЮТСЯ из базиса, ничего не считается (Д3).
_basis_entry_value() {
  local header="$1" want="$2"
  awk -v header="$header" -v want="$want" '
    $0 ~ ("^" header ":[ \t]*(#.*)?$") { inblock=1; next }
    inblock && $0 ~ /^[^ \t]/ { inblock=0 }
    inblock {
      line=$0
      sub(/^[ \t]+/, "", line)
      if (line == "" || line ~ /^#/) next
      colon = index(line, ":")
      if (colon == 0) next
      key = substr(line, 1, colon-1)
      val = substr(line, colon+1)
      gsub(/[ \t]+$/, "", key)
      gsub(/^[ \t]+/, "", val); gsub(/[ \t]+$/, "", val)
      gsub(/^"/, "", val); gsub(/"$/, "", val)
      if (key == want) { print val; exit }
    }
  ' "$BASIS_FILE"
}

_basis_has_conflicts_block() {
  grep -qE '^conflicts:[[:space:]]*(#.*)?$' "$BASIS_FILE"
}

_basis_has_files_block() {
  grep -qE '^files:[[:space:]]*(#.*)?$' "$BASIS_FILE"
}

_basis_top_level_scalar() {
  # $1 = ключ (nauta_version|nauta_ref_sha|synced_at|files_count). Печатает значение с
  # обрезанными кавычками, либо ничего, если ключ отсутствует — awk без явного `exit 1` в
  # END всегда завершается нулём независимо от того, нашлось совпадение или нет.
  local key="$1"
  awk -v key="$key" '
    index($0, key ":") == 1 {
      line = $0
      sub("^" key ":[ \t]*", "", line)
      gsub(/[ \t]+$/, "", line)
      gsub(/^"/, "", line); gsub(/"$/, "", line)
      print line
      exit
    }
  ' "$BASIS_FILE"
}

_basis_delivery_complete() {
  # §4: терпит кавычки вокруг булева значения ("true"/"false") — единственное место, где
  # терпимость дешевле строгости (закавыченный руками true иначе дал бы неверную причину —
  # "версия до ADR-037" вместо отказа по существу). Пусто — «ключа нет», не «false»: разницу
  # между LEGACY и PARTIAL несёт ПУСТОТА против буквального "false", не отсутствие вывода.
  grep -E '^delivery_complete:[[:space:]]*"?(true|false)"?[[:space:]]*$' "$BASIS_FILE" 2>/dev/null \
    | sed -E 's/^delivery_complete:[[:space:]]*"?(true|false)"?[[:space:]]*$/\1/' \
    | head -n1 || true
}

_count_nonempty_lines() {
  # $1 = \n-разделённая строка (может быть пустой). grep -c без совпадений выходит 1 —
  # гасится здесь один раз, а не у каждого вызывающего.
  local text="$1"
  if [[ -z "$text" ]]; then
    echo 0
    return 0
  fi
  printf '%s\n' "$text" | grep -c . || true
}

_in_newline_list() {
  # $1 = искомый путь, $2 = \n-разделённый список (может быть пустой строкой).
  local needle="$1" haystack="$2"
  [[ -n "$haystack" ]] && printf '%s\n' "$haystack" | grep -Fxq -- "$needle"
}

if [[ "$ORIGIN" -eq 1 ]]; then
  # Д3/Д4: признак источника проверяется ПЕРВЫМ и только УЖЕСТОЧАЕТ — найденный рядом базис
  # обязательств дерева-источника не сужает.
  OBLIGATION_MODE="STRICT"
  if [[ -f "$BASIS_FILE" ]]; then
    echo "[INFO] в дереве-источнике payload'а найден .nauta-scripts-basis.yaml — на обязательства он не"
    echo "       влияет: здесь обязателен весь перечень гейтов (ADR-037 Д3)."
  fi
elif [[ -f "$BASIS_FILE" ]]; then
  # Порядок вердиктов обязателен (§2/§4 ADR-037-spec): завершённость — РАНЬШЕ структурных.
  # Обрыв на первой же записи даёт базис с нулём записей И complete=false — назвать его
  # "нечитаемым" значило бы соврать про причину (Д5).
  BASIS_DELIVERY_COMPLETE="$(_basis_delivery_complete)"
  if [[ -z "$BASIS_DELIVERY_COMPLETE" ]]; then
    echo "ERROR: в .nauta-scripts-basis.yaml нет ключа delivery_complete — завершённость доставки по этому" >&2
    echo "базису неизвестна. Две гипотезы, механизм их не различает: базис написан версией nauta до ADR-037" >&2
    echo "либо блок метаданных правился руками. Ни один гейт не запущен. Почини: повтори" >&2
    echo "/nauta:sync-scripts — команда перепишет базис целиком, новый несёт ключ." >&2
    exit 1
  fi
  if [[ "$BASIS_DELIVERY_COMPLETE" == "false" ]]; then
    echo "ERROR: .nauta-scripts-basis.yaml объявляет незавершённую доставку (delivery_complete: false) —" >&2
    echo "синк был прерван, дерево укомплектовано частично. Считать \"мне столько и привезли\" нельзя: гейты," >&2
    echo "отсутствующие из-за обрыва, молчали бы законно (ADR-037 Д5). Ни один гейт не запущен. Почини:" >&2
    echo "повтори /nauta:sync-scripts — доставка докопирует недостающее (ADR-030 Д7)." >&2
    exit 1
  fi
  if ! _basis_has_files_block; then
    echo "ERROR: .nauta-scripts-basis.yaml в корне дерева есть, но прочитать его не удалось: блока files: нет." >&2
    echo "check.sh не может определить, что ему доставлено, и не станет молча считать, что не доставлено" >&2
    echo "ничего (ADR-007 Д1; ADR-031 Д3: \"не смог прочитать\" ≠ \"нарушений нет\"). Ни один гейт не" >&2
    echo "запущен. Почини: повтори /nauta:sync-scripts — команда перепишет базис целиком; если файл" >&2
    echo "правился руками, верни форму из ADR-030-spec §5." >&2
    exit 1
  fi
  DECLARED_FILES="$(_basis_files_paths)"
  DECLARED_COUNT="$(_count_nonempty_lines "$DECLARED_FILES")"
  if [[ "$DECLARED_COUNT" -eq 0 ]]; then
    echo "ERROR: .nauta-scripts-basis.yaml в корне дерева есть, но прочитать его не удалось: ни одной записи" >&2
    echo "в files:. check.sh не может определить, что ему доставлено, и не станет молча считать, что не" >&2
    echo "доставлено ничего (ADR-007 Д1; ADR-031 Д3: \"не смог прочитать\" ≠ \"нарушений нет\"). Ни один" >&2
    echo "гейт не запущен. Почини: повтори /nauta:sync-scripts — команда перепишет базис целиком; если файл" >&2
    echo "правился руками, верни форму из ADR-030-spec §5." >&2
    exit 1
  fi
  BASIS_FILES_COUNT="$(_basis_top_level_scalar files_count)"
  if [[ -z "$BASIS_FILES_COUNT" ]] || [[ "$BASIS_FILES_COUNT" != "$DECLARED_COUNT" ]]; then
    echo "ERROR: .nauta-scripts-basis.yaml обрезан: files_count объявляет ${BASIS_FILES_COUNT:-<нет>} записей," >&2
    echo "разобрать удалось ${DECLARED_COUNT}. Часть заявленного пропала бы бесшумно — гейты потерянных" >&2
    echo "строк выглядели бы как недоставленные, а не как порча (ADR-037 Д5). Ни один гейт не запущен." >&2
    echo "Почини: повтори /nauta:sync-scripts — команда перепишет базис целиком." >&2
    exit 1
  fi

  # ---------------------------------------------------------------------
  # conflicts_count / conflicts: — ADR-079 Д1, §5 п.2 спутника. Место — СРАЗУ за вердиктом
  # files_count: структурные контрольные числа идут группой, до вердикта SELF-UNDECLARED.
  #
  # Пару "счётчик + блок" писатель печатает ВСЕГДА вместе, в том числе на здоровом дереве
  # (там conflicts_count: 0 и пустой блок). Поэтому отсутствие пары — не «конфликтов нет», а
  # состояние, о котором базис молчит; молчание здесь опаснее отказа: посторонний файл на
  # payload-пути исполнился бы под именем гейта nauta (ровно дефект ишью #13). Прецедент
  # формы вердикта — delivery_complete выше (ADR-037 Д5): ERROR до запуска гейтов, две
  # гипотезы названы, лечение — повторный синк.
  # ---------------------------------------------------------------------
  BASIS_CONFLICTS_COUNT="$(_basis_top_level_scalar conflicts_count)"
  _conflicts_block_present=0
  if _basis_has_conflicts_block; then _conflicts_block_present=1; fi
  if [[ -z "$BASIS_CONFLICTS_COUNT" && "$_conflicts_block_present" -eq 0 ]]; then
    echo "ERROR: в .nauta-scripts-basis.yaml нет секции conflicts: — ни ключа conflicts_count, ни блока." >&2
    echo "Заявлена ли хоть одна позиция конфликтной, по этому базису неизвестно. Две гипотезы, механизм" >&2
    echo "их не различает: базис написан версией nauta до ADR-079 либо секция удалена руками. Считать" >&2
    echo "\"конфликтов нет\" нельзя: посторонний файл на payload-пути исполнился бы под именем гейта nauta" >&2
    echo "(ADR-079 Д2; ADR-031 Д3: \"не смог прочитать\" ≠ \"нарушений нет\"). Ни один гейт не запущен." >&2
    echo "Почини: повтори /nauta:sync-scripts — команда перепишет базис целиком, новый несёт секцию." >&2
    exit 1
  fi
  if [[ -z "$BASIS_CONFLICTS_COUNT" || "$_conflicts_block_present" -eq 0 ]]; then
    if [[ -z "$BASIS_CONFLICTS_COUNT" ]]; then
      _conflicts_present_half="блок conflicts:"; _conflicts_missing_half="ключ conflicts_count"
    else
      _conflicts_present_half="ключ conflicts_count"; _conflicts_missing_half="блок conflicts:"
    fi
    echo "ERROR: .nauta-scripts-basis.yaml несёт секцию conflicts: наполовину: ${_conflicts_present_half} на месте," >&2
    echo "${_conflicts_missing_half} отсутствует. Писатель печатает счётчик и блок всегда вместе (ADR-079 Д1)," >&2
    echo "поэтому половина пары означает обрез файла или ручную правку, а не отсутствие конфликтов — а по" >&2
    echo "половине судить, занята ли позиция посторонним файлом, нельзя. Ни один гейт не запущен." >&2
    echo "Почини: повтори /nauta:sync-scripts — команда перепишет базис целиком." >&2
    exit 1
  fi
  CONFLICTED_FILES="$(_basis_conflict_paths)"
  CONFLICTED_COUNT="$(_count_nonempty_lines "$CONFLICTED_FILES")"
  # Строгий `!=`, симметрично files_count и НЕ симметрично skip_count (Д1): секцию пишет
  # ТОЛЬКО писатель ("Не редактируйте руками значения" — шапка базиса), санкционированной
  # ручной правки у неё нет, поэтому расхождение в ЛЮБУЮ сторону — порча.
  if [[ ! "$BASIS_CONFLICTS_COUNT" =~ ^[0-9]+$ ]] || [[ "$BASIS_CONFLICTS_COUNT" != "$CONFLICTED_COUNT" ]]; then
    echo "ERROR: .nauta-scripts-basis.yaml обрезан: conflicts_count объявляет ${BASIS_CONFLICTS_COUNT:-<нет>} записей," >&2
    echo "разобрать удалось ${CONFLICTED_COUNT} в conflicts:. Метка конфликта — единственное, что мешает" >&2
    echo "раннеру исполнить посторонний файл под именем гейта nauta (ADR-079 Д2); потерянная метка сняла бы" >&2
    echo "защиту бесшумно. Секцию правит только писатель, поэтому расхождение в любую сторону — порча, а не" >&2
    echo "санкционированная правка (в отличие от skip:). Ни один гейт не запущен. Почини: повтори" >&2
    echo "/nauta:sync-scripts — команда перепишет базис целиком." >&2
    exit 1
  fi
  # skip_count — контрольное число секции skip:, но НЕ симметрично files_count: files:
  # правится ТОЛЬКО писателем ("Не редактируйте руками значения" — шапка базиса), а skip:
  # явно и санкционированно правится потребителем руками (та же шапка: "секцию skip: —
  # можно"; §3 ADR-037-spec). Симметричная проверка (`!=`, как у files_count) ловила бы ОБЕ
  # стороны расхождения — и обрез (`разобрано < объявлено`, порча), и САНКЦИОНИРОВАННОЕ
  # ручное добавление строки (`разобрано > объявлено`, ожидаемое поведение) — как одну и ту
  # же ошибку, блокируя каждый прогон/коммит до повторного синка за действие, которое базис
  # сам разрешает без синка. Направленное сравнение (`-lt`) ловит ТОЛЬКО обрез: если строк
  # оказалось МЕНЬШЕ заявленного — часть заявленного пропала бы бесшумно, путь, заявленный
  # ТОЛЬКО через skip: (§3), тихо перестал бы считаться заявленным — ровно та дыра, ради
  # закрытия которой заведена сама skip-клауза правила declared.
  # Если строк оказалось БОЛЬШЕ — это ручное добавление, санкционировано, не ошибка.
  SKIPPED_FILES="$(_basis_skip_paths)"
  SKIPPED_COUNT="$(_count_nonempty_lines "$SKIPPED_FILES")"
  BASIS_SKIP_COUNT="$(_basis_top_level_scalar skip_count)"
  if [[ -z "$BASIS_SKIP_COUNT" ]] \
      || ! [[ "$BASIS_SKIP_COUNT" =~ ^[0-9]+$ ]] \
      || [[ "$SKIPPED_COUNT" -lt "$BASIS_SKIP_COUNT" ]]; then
    echo "ERROR: .nauta-scripts-basis.yaml обрезан: skip_count объявляет ${BASIS_SKIP_COUNT:-<нет>} записей," >&2
    echo "разобрать удалось ${SKIPPED_COUNT} в skip:. Часть заявленного через skip: пропала бы бесшумно —" >&2
    echo "путь, добавленный в skip: до первого синка, перестал бы считаться заявленным (§3 ADR-037-spec)," >&2
    echo "и его гейт выключился бы тихо и навсегда (ADR-037 Д5). Ни один гейт не запущен. Почини: повтори" >&2
    echo "/nauta:sync-scripts — команда перепишет базис целиком." >&2
    exit 1
  fi

  # Базис обязан заявлять САМ scripts/check.sh — раннер, которым он читается. Защита в
  # глубину поверх писателя в bin/deliver.sh: базис без этой записи, даже при непустом
  # files: и сошедшемся files_count, — признак свернувшегося состава, не полноценное
  # описание доставки (§4 ADR-037-spec: "check.sh девятая позиция payload'а, к моменту его
  # появления в дереве базис заявляет минимум девять файлов").
  if ! { _in_newline_list "scripts/check.sh" "$DECLARED_FILES" \
      || _in_newline_list "scripts/check.sh" "$SKIPPED_FILES"; }; then
    echo "ERROR: .nauta-scripts-basis.yaml не заявляет сам scripts/check.sh — раннер, которым он читается." >&2
    echo "Базис, управляющий check.sh, обязан называть check.sh в files: или в skip: (§4 ADR-037-spec:" >&2
    echo "check.sh — девятая позиция payload'а, к моменту его появления в дереве базис заявляет минимум" >&2
    echo "девять файлов). Отсутствие этой записи — признак свернувшегося базиса (например, обрыв сразу" >&2
    echo "после предварительной записи писателя, до переобработки состава), а не полноценное описание" >&2
    echo "доставки этого дерева. Ни один гейт не запущен. Почини: повтори /nauta:sync-scripts — команда" >&2
    echo "перепишет базис целиком." >&2
    exit 1
  fi

  # Раннер обязан отвергнуть САМ СЕБЯ, если базис объявил его позицию конфликтной (edge case
  # §7 спутника ADR-079). Через _run_if_declared это не выражается: scripts/check.sh — не
  # ступень ростера, он и есть исполняющийся процесс. SELF-UNDECLARED выше не срабатывает —
  # запись в files: на месте (Д1), причина другая, и вердикт печатается ровно один раз.
  # `skip:` побеждает метку той же логикой, что и в _conflicted ниже: санкционированное
  # владение потребителя метка отменить не может.
  if _in_newline_list "scripts/check.sh" "$CONFLICTED_FILES" \
      && ! _in_newline_list "scripts/check.sh" "$SKIPPED_FILES"; then
    echo "ERROR: раннер не исполняет сам себя: .nauta-scripts-basis.yaml заявляет позицию scripts/check.sh" >&2
    echo "конфликтной — на диске лежит не то, что доставлено (базис: $(_basis_entry_value files scripts/check.sh)," >&2
    echo "диск на момент синка: $(_basis_entry_value conflicts scripts/check.sh)). Продолжить значило бы" >&2
    echo "выдать чужой сценарий за прогон гейтов nauta, причём под именем этого файла (ADR-079 Д2)." >&2
    echo "Ни один гейт не запущен. Почини: разреши конфликт (bin/deliver.sh печатает варианты) и повтори" >&2
    echo "/nauta:sync-scripts." >&2
    exit 1
  fi

  BASIS_NAUTA_VERSION="$(_basis_top_level_scalar nauta_version)"
  BASIS_NAUTA_REF_SHA="$(_basis_top_level_scalar nauta_ref_sha)"
  BASIS_SYNCED_AT="$(_basis_top_level_scalar synced_at)"
  OBLIGATION_MODE="DELIVERED"
  echo "[INFO] базис доставки .nauta-scripts-basis.yaml: nauta ${BASIS_NAUTA_VERSION}, ref ${BASIS_NAUTA_REF_SHA}, синк ${BASIS_SYNCED_AT},"
  echo "       заявлено файлов: ${BASIS_FILES_COUNT}. Обязательными считаются только заявленные (ADR-037 Д1)."
else
  # Д4: строгое умолчание — отсутствие базиса не значит "ничего не доставлено". Право на
  # молчание выдаёт исключительно прочитанный и завершённый базис.
  OBLIGATION_MODE="STRICT"
fi

failed=0

# _finish — эпилог прогона: единственное место, где решается exit-код. Вынесен в функцию
# ради режима --secret-scan-only (§4.3 спутника ADR-073), который завершается раньше
# остального перечня: копия эпилога была бы вторым прибором и разошлась бы с первым.
_finish() {
  if [[ "$failed" -ne 0 ]]; then
    echo "" >&2
    echo "✗ check.sh $MODE — FAILED" >&2
    exit 1
  fi
  echo ""
  echo "✓ check.sh $MODE — passed"
  exit 0
}
# run_check <name> <cmd> [soft-codes] — третий аргумент (ADR-072 Д4) необязателен: список
# кодов, разделённых пробелом, которые для ЭТОГО вызова означают не отказ, а расхождение
# класса «soft» таксономии ADR-007 Д1. На таком коде печатается строка `⚠` и `failed` НЕ
# поднимается. Маркер ошибки (`ERROR:`/`[ERROR]`/`[error]`) в неё не входит намеренно:
# счётчик исходов ADR-042 считает маркеры, и предупреждение не смеет выглядеть отказом.
# Освобождаются ТОЛЬКО перечисленные коды — амнистия не сплошная (замок:
# tests/test_dev111_warden_detectors_on_the_path.py::test_run_check_soft_list_is_not_a_
# blanket_amnesty). Вызов без третьего аргумента ведёт себя ровно как прежде.
run_check() {
  local name="$1" cmd="$2" soft="${3:-}" rc=0
  echo "▶ $name"
  eval "$cmd" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "  ✓ $name"
  elif [[ -n "$soft" && " $soft " == *" $rc "* ]]; then
    echo "  ⚠ $name — код $rc объявлен мягким для этого вызова (расхождение класса soft,"
    echo "    ADR-007 Д1): проверка ВЫПОЛНЕНА, её исход не блокирует коммит."
  else
    echo "  ✗ $name FAILED" >&2
    failed=1
  fi
}

# _declared <rel> — §3 ADR-037-spec: позиция заявлена, если режим STRICT (весь перечень
# заявлен по умолчанию), либо путь есть в files: базиса, либо путь есть в skip: базиса —
# skip: заявляет НАРАВНЕ с files: (иначе путь, добавленный в skip: до первого синка, не
# получает записи в files: никогда, и гейт выключился бы тихо и навсегда).
_declared() {
  local rel="$1"
  [[ "$OBLIGATION_MODE" == "STRICT" ]] && return 0
  _in_newline_list "$rel" "$DECLARED_FILES" && return 0
  _in_newline_list "$rel" "$SKIPPED_FILES" && return 0
  return 1
}

# _conflicted <rel> — ADR-079 Д2: базис заявил, что на позиции лежит НЕ доставленное.
# `skip:` побеждает метку (edge case §7 спутника): путь в skip: — санкционированное владение
# потребителя ("не перезаписывай мою копию"), и метка, унаследованная от прогона ДО этой
# правки, не имеет права его отменять; писатель снимет её следующим синком (Д4).
_conflicted() {
  local rel="$1"
  [[ -n "$CONFLICTED_FILES" ]] || return 1
  _in_newline_list "$rel" "$SKIPPED_FILES" && return 1
  _in_newline_list "$rel" "$CONFLICTED_FILES"
}

# _run_if_declared <base> <ext> <runner> <kind> <kind-genitive> <func-name> — общая функция
# для гейтов (.py, uv run) и сьютов (.sh, bash); §3 ADR-037-spec: "два безусловных вызова
# идут через ту же функцию, исключений в правиле нет" — распространено на ВСЕ вызовы ниже,
# не только validate-content.py/validate-profile.py. Шесть исходов (§3 псевдокод + ADR-079 Д2):
#   conflicted && present → ERROR-CONFLICTED-PRESENT (проверяется ПЕРВЫМ, §5 п.4 ADR-079-spec)
#   present            → исполняет (присутствие исполняет, не запись)
#   declared && origin → ERROR-MISSING-AT-ORIGIN
#   declared && STRICT → ERROR-MISSING-NO-BASIS
#   rel in skip:       → ERROR-MISSING-SKIPPED
#   declared (прочее)  → ERROR-MISSING-DELIVERED
#   иначе              → INFO-NOT-DELIVERED, exit-код не меняется
_run_if_declared() {
  local base="$1" ext="$2" runner="$3" kind="$4" kind_gen="$5" func_name="$6"
  # Седьмой аргумент (ADR-072 Д4) — необязательный список мягких кодов, доезжающий до
  # run_check. Пять исходов выше НЕ меняются: мягкий код относится к исполненной проверке,
  # а не к её отсутствию — отсутствие заявленного файла остаётся ошибкой во всех четырёх
  # своих формах.
  local soft="${7:-}"
  local rel="scripts/${base}.${ext}"
  local name="${base}.${ext}"

  # Шестой исход — ПЕРЕД веткой присутствия (ADR-079 Д2). "Присутствие исполняет" (ADR-037
  # Д2) не отменяется, а сужается одним санкционированным условием: присутствие исполняет,
  # пока базис не заявил, что присутствует НЕ доставленное. Право на молчание по-прежнему
  # выдаёт только базис — здесь он выдаёт противоположное, прямой запрет.
  # Файла нет при живой метке — метка НЕ применяется, работают прежние пять исходов
  # (отсутствие заявленного остаётся ERROR по ADR-037 Д2).
  if _conflicted "$rel" && [[ -f "$rel" ]]; then
    echo "ERROR: ${kind} \"$name\" не исполнен: .nauta-scripts-basis.yaml заявляет позицию $rel" >&2
    echo "  конфликтной — на диске лежит не то, что доставлено (базис: $(_basis_entry_value files "$rel")," >&2
    echo "  диск на момент синка: $(_basis_entry_value conflicts "$rel")). Исполнить файл значило бы выдать" >&2
    echo "  чужую шкалу за проверку nauta (ADR-079 Д2; ADR-007 Д1: гейт возвращает 0, только если выполнил" >&2
    echo "  проверку и она прошла). Почини: разреши конфликт (bin/deliver.sh печатает три варианта) и" >&2
    echo "  повтори /nauta:sync-scripts." >&2
    exit 1
  fi

  if [[ -f "$rel" ]]; then
    run_check "$name" "$runner $rel" "$soft"
    return
  fi

  if _declared "$rel"; then
    if [[ "$ORIGIN" -eq 1 ]]; then
      echo "▶ $name"
      echo "  ✗ $name FAILED" >&2
      echo "  ERROR: ${kind} \"$name\" объявлен в check.sh (${func_name} \"$base\"), но файла" >&2
      echo "  $rel в этом дереве нет. Дерево опознано как источник payload'а (bin/deliver.sh" >&2
      echo "  на месте и несёт подпись установщика) — здесь обязателен весь перечень (ADR-037 Д3), сужать" >&2
      echo "  его нечем. ADR-007 Д1: гейт возвращает 0 только если выполнил проверку и она прошла. Почини:" >&2
      echo "  верни файл на место либо убери \"$base\" из вызовов в check.sh, если этого предмета здесь" >&2
      echo "  больше не должно быть." >&2
      failed=1
      return
    fi
    if [[ "$OBLIGATION_MODE" == "STRICT" ]]; then
      echo "▶ $name"
      echo "  ✗ $name FAILED" >&2
      echo "  ERROR: ${kind} \"$name\" объявлен в check.sh, файла $rel нет, и сузить обязательства" >&2
      echo "  нечем: .nauta-scripts-basis.yaml в корне дерева отсутствует. Отсутствие базиса не значит" >&2
      echo "  \"ничего не доставлено\" (ADR-037 Д4). Две гипотезы, механизм их не различает: (1) это дерево" >&2
      echo "  получило scripts/ через /nauta:sync-scripts, а базис потерян — повтори команду, она перепишет" >&2
      echo "  базис; (2) это дерево-источник с повреждённым bin/ — верни bin/deliver.sh и файл ${kind_gen}." >&2
      failed=1
      return
    fi
    if _in_newline_list "$rel" "$SKIPPED_FILES"; then
      echo "▶ $name"
      echo "  ✗ $name FAILED" >&2
      echo "  ERROR: ${kind} \"$name\" стоит в секции skip: базиса .nauta-scripts-basis.yaml, но файла" >&2
      echo "  $rel в дереве нет. skip: означает \"не перезаписывай мою копию\", а не \"у меня" >&2
      echo "  этого нет\" (ADR-030-spec §5) — заявка есть, предмета нет, и это противоречие, а не отказ." >&2
      echo "  Почини: либо верни файл (повтори /nauta:sync-scripts, предварительно убрав путь из skip:)," >&2
      echo "  либо убери путь из skip:, если этот ${kind} вам не нужен, — тогда базис перестанет его заявлять." >&2
      failed=1
      return
    fi
    echo "▶ $name"
    echo "  ✗ $name FAILED" >&2
    echo "  ERROR: ${kind} \"$name\" заявлен доставленным (.nauta-scripts-basis.yaml, files: →" >&2
    echo "  $rel, nauta ${BASIS_NAUTA_VERSION}, синк ${BASIS_SYNCED_AT}), но файла в дереве нет — доставка" >&2
    echo "  повреждена. ADR-007 Д1: \"не смог проверить\" ≠ \"нечего проверять\". Почини: повтори" >&2
    echo "  /nauta:sync-scripts — отсутствующий файл создаётся заново и конфликтом не считается" >&2
    echo "  (ADR-030 Д4)." >&2
    failed=1
    return
  fi

  # Не заявлен и отсутствует — объявленное молчание (Д2/Д6): называет источник своего права,
  # не тихий [INFO] skip (Д7 — этот токен здесь не используется вовсе).
  echo "[INFO] $name не доставлен в это дерево: базис (nauta ${BASIS_NAUTA_VERSION}, синк ${BASIS_SYNCED_AT}) его не"
  echo "       заявляет — проверка не выполняется, exit-код не меняется. Чтобы ${kind} появился: обнови"
  echo "       плагин и повтори /nauta:sync-scripts; как только ${kind} войдёт в payload, базис его заявит,"
  echo "       и с этого момента его отсутствие станет ошибкой."
}

# run_gate_if_declared <gate-basename> — прогнать `uv run scripts/<basename>.py`. Имя
# заменяет исторический остаток `run_gate_if_present`/`run_suite_if_present` («_if_present»,
# докстрока-предшественник отмечала это как остаток эпохи двух курируемых снапшотов, ADR-006
# §Q1) — неверно называл предикат: обязательность решает ЗАЯВКА базиса, не голое присутствие
# файла (ADR-037-spec §3). Имена функций не проверяются ассертами нигде (ADR-037-spec §3);
# упоминания старых имён в прозе уже закрытых артефактов (CHANGELOG.md,
# content/lessons-learned.md, content/30-requirements/**) не правятся — состояние на момент
# написания.
run_gate_if_declared() {
  _run_if_declared "$1" "py" "uv run" "гейт" "гейта" "run_gate_if_declared" "${2:-}"
}

# run_suite_if_declared <suite-basename> — прогнать scripts/<basename>.sh. Симметрична
# run_gate_if_declared (см. её докстроку).
run_suite_if_declared() {
  _run_if_declared "$1" "sh" "bash" "сьют" "сьюта" "run_suite_if_declared" "${2:-}"
}

# run_gate_sh_if_declared <gate-basename> — прогнать `bash scripts/<basename>.sh` КАК ГЕЙТ
# (Д7 ADR-040): третья обёртка _run_if_declared — runner bash (как у сьюта), но род сообщения
# "гейт" (как у .py-гейтов) — `check-hooks-path.sh` и `id-check.sh` не .sh-регрессия
# self-test harness, а содержательная проверка дерева. Протокол обязательности (пять исходов
# ADR-037) не меняется — меняется только текст рода.
run_gate_sh_if_declared() {
  _run_if_declared "$1" "sh" "bash" "гейт" "гейта" "run_gate_sh_if_declared" "${2:-}"
}

# check-hooks-path (ADR-040 Д2/Д7, ADR-040-spec §4) — маршрут хуков сверяется В --fast, ДО
# гейтов содержимого: расхождение маршрута отключает .githooks/pre-commit целиком (замер §1.2
# ADR-040-spec) — сообщить об этом раньше остального дерева, а не после.
case "$MODE" in
  --secret-scan-only|--delivery-composition-only) ;;
  *) run_gate_sh_if_declared "check-hooks-path" ;;
esac

# check-branch-discipline (ADR-081 Д2/Д7) — читатель объявления профиля дисциплины ветвления
# и сторож шва §4.4 (имя ветки рабочей копии роли — адрес задачи). Место — рядом с
# check-hooks-path: обе проверки судят не содержимое дерева, а условия, в которых дерево
# вообще проверяется, и обе обязаны сказать своё раньше гейтов содержимого. У дерева без
# объявления профиля исход — [INFO] и exit 0: молчание разрешением ни одного профиля не
# является, но и отказом на непринятую дисциплину гейт не краснеет.
case "$MODE" in
  --secret-scan-only|--delivery-composition-only) ;;
  *) run_gate_if_declared "check-branch-discipline" ;;
esac

# secret-scan-tree (ADR-040 Д1, secret-hygiene-gate) — обход РАБОЧЕГО дерева gitleaks'ом в
# --fast (симметрично --staged в .githooks/pre-commit, замер §1.4: 0.33с при 2.13с текущего
# --fast). Конфигурация: secretScan.enabled/secretScan.binary из .nauta-gates.yaml (§6),
# умолчание — включено, бинарь gitleaks. Отсутствие бинаря — громкая ошибка (uv-guard
# check.sh:23 прецедент), не тихий skip (secret-hygiene-gate: "unavailable scanner is a loud
# failure").
# Строгое значение (ADR-072 Д6, решение владельца Р3) — ВТОРОЙ читатель того же ключа:
# строгость в одном (`.githooks/pre-commit`) оставила бы этот тихим, и `check.sh --fast`,
# запускаемый из CI и вручную, продолжал бы молча пропускать скан на `True`/`yes`/`flase`.
# awk печатает строку-признак `enabled=<значение>` всегда, когда ключ НАЙДЕН: без неё
# «ключа нет» (умолчание из кода, ADR-031 Д3) и «ключ задан, значение пустое» (нечитаемо)
# неразличимы. Функция возвращает 1 на нечитаемом значении, печатая его на stdout, — разбор
# делает вызывающий код: `exit` внутри `$( )` убил бы только подоболочку.
_gates_secret_scan_enabled() {
  local gates="$REPO_ROOT/.nauta-gates.yaml" v
  [[ -f "$gates" ]] || { echo true; return 0; }
  v="$(awk '
    /^secretScan:[ \t]*(#.*)?$/ { inblk=1; next }
    inblk && $0 ~ /^[^ \t]/ { inblk=0 }
    inblk && $0 ~ /^[ \t]*enabled:/ {
      line=$0
      sub(/^[ \t]*enabled:[ \t]*/, "", line)
      gsub(/[ \t]+$/, "", line); gsub(/^"/, "", line); gsub(/"$/, "", line)
      print "enabled=" line
      exit
    }
  ' "$gates")"
  [[ -z "$v" ]] && { echo true; return 0; }
  v="${v#enabled=}"
  echo "$v"
  [[ "$v" == "true" || "$v" == "false" ]]
}
_gates_secret_scan_binary() {
  local gates="$REPO_ROOT/.nauta-gates.yaml" v
  [[ -f "$gates" ]] || { echo gitleaks; return 0; }
  v="$(awk '
    /^secretScan:[ \t]*(#.*)?$/ { inblk=1; next }
    inblk && $0 ~ /^[^ \t]/ { inblk=0 }
    inblk && $0 ~ /^[ \t]*binary:/ {
      line=$0
      sub(/^[ \t]*binary:[ \t]*/, "", line)
      gsub(/[ \t]+$/, "", line); gsub(/^"/, "", line); gsub(/"$/, "", line)
      print line
      exit
    }
  ' "$gates")"
  [[ -z "$v" ]] && v=gitleaks
  echo "$v"
}
# _secret_scan_verify_scope <scope-toml> — Д6 ADR-062: громкая сверка заявленной области
# (allowlist paths конфига) с реализованной (`git ls-files`). Отслеживаемый файл, попавший
# под вычитающий паттерн, выводится на stdout — непустой вывод means сверка провалена.
# Стоимость — сотые доли секунды против ~20 с скана (замер §1.7 ADR-062-spec).
_secret_scan_verify_scope() {
  local scope="$1" patterns combined
  patterns="$(grep -oE "'''[^']*'''" "$scope" | sed -E "s/^'''(.*)'''\$/\1/")"
  [[ -z "$patterns" ]] && return 0
  combined="$(printf '%s\n' "$patterns" | paste -sd'|' -)"
  git -C "$REPO_ROOT" ls-files 2>/dev/null | grep -E "$combined" || true
}

# run_secret_scan_tree_gate — тот же и единственный блок скана для ДВУХ режимов: --fast
# (путь коммита) и --secret-scan-only (путь релиза, §4.3 спутника ADR-073). Копии кода в
# релизном скрипте нет намеренно: копия — второй прибор, и первый же дрейф развёл бы их
# молча (У8 §7 спутника — мутация внутри этого блока обязана красить оба режима разом).
run_secret_scan_tree_gate() {
  # Присвоение стоит УСЛОВИЕМ `if !`, а не отдельной строкой: под `set -e` голое
  # `x="$(cmd)"` абортировало бы весь скрипт раньше, чем код успеет прочесть причину (тот же
  # регресс, что описан ниже у secret_scan_ok).
  if ! SECRET_SCAN_ENABLED="$(_gates_secret_scan_enabled)"; then
    # Заголовок записи исхода намеренно НЕ совпадает дословно с заголовком секции скана
    # ниже (там суффикса в скобках нет): tests/test_qa062_adr062_secret_scan_scope.py
    # ::test_d2_2_check_sh_invokes_gitleaks_with_explicit_scope_config режет файл по ПЕРВОМУ
    # вхождению того заголовка и смотрит следующие 800 символов — совпадение сдвинуло бы окно
    # на текст этого отказа и покрасило чужой замок Д2 ADR-062. По той же причине сам литерал
    # заголовка не цитируется и в этом комментарии.
    echo "▶ secret-scan-tree (чтение конфигурации)"
    echo "  ✗ secret-scan-tree FAILED" >&2
    echo "  ERROR: secretScan.enabled в .nauta-gates.yaml задан значением" >&2
    echo "  '$SECRET_SCAN_ENABLED' — признаются ровно 'true' и 'false'. Сканирование рабочего" >&2
    echo "  дерева НЕ выполнено; это не \"0 находок\" (ADR-007 Д1, ADR-072 Д6). YAML-истины" >&2
    echo "  'True'/'yes'/'on' синонимами 'true' здесь НЕ являются, а пустое значение при" >&2
    echo "  заданном ключе не даёт права на умолчание из кода — оно принадлежит только" >&2
    echo "  отсутствующему ключу. Почини: впиши 'enabled: true' либо 'enabled: false', либо" >&2
    echo "  убери ключ secretScan целиком." >&2
    exit 1
  fi
  if [[ "$SECRET_SCAN_ENABLED" == "true" ]]; then
    SECRET_SCAN_BINARY="$(_gates_secret_scan_binary)"
    echo "▶ secret-scan-tree"
    # Область — коммитируемое множество минус игнорируемый балласт (ADR-062 Д1/Д2): конфиг
    # НЕавтоподхватываемого имени передаётся явным -c "$REPO_ROOT/.gitleaks-scope.toml"
    # (У1 SEC-041, §2.1 ADR-062-spec) — автоподхват `.gitleaks.toml` разоружил бы pre-commit
    # хук тем же allowlist'ом.
    # Цель обхода — "." ПОСЛЕ cd в $REPO_ROOT (подоболочка ниже), не абсолютный $REPO_ROOT:
    # gitleaks сверяет allowlist-паттерны с путём, КАКИМ он ему передан (§1.6/§2.1
    # ADR-062-spec), и абсолютная цель делает кандидатом на совпадение весь путь целиком,
    # включая ancestor-каталоги выше $REPO_ROOT. Ролевые копии живут ПОД местом копий
    # (`.claude/worktrees/<id>` — платформа, ADR-081 Д3; `.worktrees/<имя>` — прежний ручной
    # ритуал), поэтому при абсолютной цели неякорный паттерн этого места совпал бы с
    # ПРЕФИКСОМ собственного $REPO_ROOT такой копии и молча схлопнул бы область до 0 байт
    # (поймано Д7 при реализации DEV-088). Относительная цель снимает это без правки
    # паттернов — не менять (ADR-081 §7, «что не делать»).
    SECRET_SCAN_SCOPE_CONFIG="$REPO_ROOT/.gitleaks-scope.toml"
    SECRET_SCAN_SOURCE="absent"
    [[ -f "$SECRET_SCAN_SCOPE_CONFIG" ]] && SECRET_SCAN_SOURCE="present"
    if ! command -v "$SECRET_SCAN_BINARY" >/dev/null 2>&1; then
      echo "  ✗ secret-scan-tree FAILED" >&2
      echo "  ERROR: '$SECRET_SCAN_BINARY' не найден в PATH — сканирование секретов рабочего" >&2
      echo "  дерева не выполнено (secretScan.enabled=true, .nauta-gates.yaml). Это НЕ \"0" >&2
      echo "  находок\" (ADR-007 Д1). Установи: brew install gitleaks (замер §1.1 ADR-040-spec)." >&2
      failed=1
    elif [[ "$SECRET_SCAN_SOURCE" == "present" ]] \
         && secret_scan_d6_hits="$(_secret_scan_verify_scope "$SECRET_SCAN_SCOPE_CONFIG")" \
         && [[ -n "$secret_scan_d6_hits" ]]; then
      echo "  ✗ secret-scan-tree FAILED" >&2
      echo "  ERROR: .gitleaks-scope.toml вычитает ОТСЛЕЖИВАЕМЫЕ файлы из области (Д6 ADR-062)," >&2
      echo "  а не только игнорируемые — заявленная область (git ls-files) разошлась с" >&2
      echo "  реализованной (allowlist). Файлы:" >&2
      echo "$secret_scan_d6_hits" | sed 's/^/    /' >&2
      failed=1
    else
      # bash 3.2 (macOS system bash) даёт "unbound variable" на `"${empty_array[@]}"` под
      # `set -u` — вместо опционального элемента массива два явных вызова, оба с "dir"
      # буквально рядом с $SECRET_SCAN_BINARY (регресс DEV-088: array-форма ловилась только
      # локально на bash 5, ломала fresh sibling-consumer теста ADR-030 на системном bash).
      # Каждый вызов — условие `if`, не присвоение переменной: под `set -e` присвоение вида
      # `x="$(cmd)"` абортирует скрипт целиком при ненулевом `cmd`, даже раньше чем код
      # успевает прочитать `$?` (регресс, найденный тем же прогоном).
      if [[ "$SECRET_SCAN_SOURCE" == "present" ]]; then
        secret_scan_ok=0
        (cd "$REPO_ROOT" && "$SECRET_SCAN_BINARY" dir -c "$SECRET_SCAN_SCOPE_CONFIG" --no-banner --no-color --redact -v .) >/tmp/nauta-secret-scan-tree.$$ 2>&1 || secret_scan_ok=1
      else
        secret_scan_ok=0
        (cd "$REPO_ROOT" && "$SECRET_SCAN_BINARY" dir --no-banner --no-color --redact -v .) >/tmp/nauta-secret-scan-tree.$$ 2>&1 || secret_scan_ok=1
      fi
      if [[ "$secret_scan_ok" -eq 0 ]]; then
        SECRET_SCAN_BYTES="$(grep -oE 'scanned ~[0-9]+' /tmp/nauta-secret-scan-tree.$$ | head -1 | grep -oE '[0-9]+')"
        [[ -z "$SECRET_SCAN_BYTES" ]] && SECRET_SCAN_BYTES=0
        SECRET_SCAN_SCOPE_COUNT="$( { git -C "$REPO_ROOT" ls-files 2>/dev/null || true; git -C "$REPO_ROOT" ls-files --others --exclude-standard 2>/dev/null || true; } | sort -u | wc -l | tr -d ' ')"
        if [[ "$SECRET_SCAN_BYTES" -eq 0 && "$SECRET_SCAN_SCOPE_COUNT" -gt 0 ]]; then
          echo "  ✗ secret-scan-tree FAILED" >&2
          echo "  ERROR: scanned ~0 bytes при непустом коммитируемом множестве" >&2
          echo "  ($SECRET_SCAN_SCOPE_COUNT файлов) — область скана полностью схлопнута (Д7" >&2
          echo "  ADR-062, ADR-007 Д1: это не \"0 находок\", а отсутствие проверки)." >&2
          failed=1
        else
          echo "  ✓ secret-scan-tree (scanned ~${SECRET_SCAN_BYTES} bytes, область: ${SECRET_SCAN_SCOPE_COUNT} файлов, .gitleaks-scope.toml: ${SECRET_SCAN_SOURCE})"
        fi
        rm -f /tmp/nauta-secret-scan-tree.$$
      else
        cat /tmp/nauta-secret-scan-tree.$$ >&2
        rm -f /tmp/nauta-secret-scan-tree.$$
        echo "  ✗ secret-scan-tree FAILED" >&2
        failed=1
      fi
    fi
  else
    echo "[INFO] secret-scan-tree выключен (.nauta-gates.yaml secretScan.enabled: false) — проверка не"
    echo "       выполняется, exit-код не меняется."
  fi
}


# ---------------------------------------------------------------------------
# delivery-composition (ADR-073 Д2/Д3, спутник §2/§3) — сторож ДОПОЛНЕНИЯ состава поставки.
# Правило Д3: каждая верхнеуровневая запись `git ls-files` (каталог; для корня — файл)
# принадлежит РОВНО ОДНОМУ из двух объявленных списков носителя `.nauta-delivery.yaml`;
# третьего не дано. Мощность НЕ проверяется (Д3): устаревшее исключение молчит намеренно.
# Место вызова — §3.4: после check-hooks-path и ДО secret-scan-tree, то есть на пути
# pre-commit в stable, где нарушение и вносится (RES-053, ADR-073 Д3).
# ---------------------------------------------------------------------------
DELIVERY_CARRIER_NAME=".nauta-delivery.yaml"
DELIVERY_CARRIER="$REPO_ROOT/$DELIVERY_CARRIER_NAME"

# _delivery_carrier_records — разбор носителя по схеме §2.2 в плоские записи, разделённые
# табом: `VERSION <значение>` и `ENTRY <список> <path> <есть reason> <есть provenance>`.
# Форма разбора та же блочная awk-конструкция, что уже читает базис доставки выше в этом
# файле и `.nauta-gates.yaml`: вход в блок по заголовку без отступа, выход — на первой
# строке без отступа. Наличие полей возвращается признаком, а не значением: решение
# «полон ли носитель» принимает вызывающий код, у которого есть право печатать и краснеть.
_delivery_carrier_records() {
  awk '
    function flush() {
      if (has_entry) printf "ENTRY\t%s\t%s\t%d\t%d\n", list, epath, has_reason, has_prov
      has_entry=0; epath=""; has_reason=0; has_prov=0
    }
    /^version:/ {
      flush(); list=""
      v=$0; sub(/^version:[ \t]*/, "", v)
      gsub(/[ \t]+$/, "", v); gsub(/^"/, "", v); gsub(/"$/, "", v)
      print "VERSION\t" v; next
    }
    /^excluded:[ \t]*(#.*)?$/  { flush(); list="excluded";  next }
    /^delivered:[ \t]*(#.*)?$/ { flush(); list="delivered"; next }
    /^[^ \t]/ { flush(); list=""; next }
    list != "" {
      line=$0
      sub(/^[ \t]+/, "", line)
      if (line == "" || line ~ /^#/) next
      if (line ~ /^-[ \t]*path:/) {
        flush(); has_entry=1
        p=line; sub(/^-[ \t]*path:[ \t]*/, "", p)
        gsub(/[ \t]+$/, "", p); gsub(/^"/, "", p); gsub(/"$/, "", p)
        epath=p; next
      }
      if (line ~ /^reason:[ \t]*[^ \t]/)     { has_reason=1; next }
      if (line ~ /^provenance:[ \t]*[^ \t]/) { has_prov=1;   next }
    }
    END { flush() }
  ' "$DELIVERY_CARRIER"
}

# _delivery_unreadable <причина> <строки-подробности> — единственная форма исхода «не смог
# проверить» (ADR-007 Д1): носителя нет, схема незнакома, запись неполна или её путь не той
# грануляции. Отдельной от «нарушение состава» она обязана быть потому, что лечение разное:
# там правится состав дерева или объявление, здесь — форма самого носителя.
_delivery_unreadable() {
  local why="$1" detail="${2:-}"
  echo "  ✗ delivery-composition FAILED" >&2
  echo "  ERROR: $DELIVERY_CARRIER_NAME прочитать по схеме не удалось: $why." >&2
  [[ -n "$detail" ]] && printf '%s\n' "$detail" >&2
  echo "  Состав поставки НЕ проверен — это не «нарушений нет» (ADR-007 Д1). Почини форму" >&2
  echo "  носителя по схеме ADR-073-spec §2.2: version: 1, два списка excluded: и delivered:," >&2
  echo "  у каждой записи три обязательных поля path/reason/provenance, путь — верхнеуровневый" >&2
  echo "  каталог со слэшем на конце либо корневой файл." >&2
  failed=1
}

run_delivery_composition_gate() {
  # §2.3: у потребителя сторож не зовётся ВОВСЕ — ни строки вывода, exit-код не меняется.
  # Различитель тот же, которым check.sh уже отличает два дерева (ORIGIN, строки 80-87):
  # у потребителя носителей объявления нет и быть не должно, а `--fast` обязан быть зелёным
  # сразу после payload'а (ADR-030 Д6(2), ADR-031 Д3).
  [[ "$ORIGIN" -eq 1 ]] || return 0

  # Дерево без собственной истории — НЕ нарушение границы, а отсутствие ПРЕДМЕТА, и
  # различается это тем же приёмом, что уже применён строкой выше к ORIGIN: там сторож не
  # зовётся у потребителя, здесь — не зовётся там, где источника выборки не существует.
  # Довод не в удобстве прогона, а в §3.1 спутника дословно: «Источник выборки — git
  # ls-files, то есть коммитируемое множество… поставка родится из истории». У дерева без
  # истории поставке родиться не из чего: это «нечего проверять», а не «не смог проверить»,
  # и ADR-007 Д1 различает их именно так. Случай наблюдаем не гипотетически — его дают
  # фикстуры `git archive HEAD | tar -x` (tests/test_check_sh_loud_gate_degradation.py,
  # tests/test_dev023_one_marker_per_outcome.py, tests/test_check_sh_obligation_from_basis.py):
  # плоская копия закоммиченного дерева без `.git`.
  #
  # Проверяется НЕ только «под git ли мы», но и «наш ли это корень»: материализованная копия,
  # положенная внутрь чужого репозитория, иначе получила бы выборку из ЧУЖОГО индекса и
  # судила бы состав поставки по нему. Сравнение идёт по inode (`-ef`), а не по строкам путей
  # — на macOS `pwd` и `rev-parse --show-toplevel` расходятся на `/var` против `/private/var`,
  # и строковое сравнение молча выключило бы сторож на настоящем дереве.
  #
  # Молчание ОБЪЯВЛЕННОЕ, не тихое: форма — та же строка `[INFO] … проверка не выполняется,
  # exit-код не меняется`, которой check.sh уже пользуется для недоставленного гейта и для
  # выключенного secret-scan-tree. Маркера отказа она не несёт намеренно: счётчик исходов
  # ADR-042 считает маркеры, и «нечего проверять» не смеет выглядеть отказом.
  local git_top=""
  git_top="$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -z "$git_top" ]] || ! [[ "$git_top" -ef "$REPO_ROOT" ]]; then
    echo "[INFO] delivery-composition не выполняется: у этого дерева нет своей истории git, а"
    echo "       источник выборки — git ls-files (§3.1 спутника ADR-073). Поставка родится из"
    echo "       истории, значит состава поставки здесь нет — это \"нечего проверять\", не \"не"
    echo "       смог проверить\" (ADR-007 Д1). Exit-код не меняется. Чтобы сторож заработал:"
    echo "       прогоняй его в дереве-репозитории (git init / клон), а не в плоской копии."
    return 0
  fi

  echo "▶ delivery-composition"

  if [[ ! -f "$DELIVERY_CARRIER" ]]; then
    echo "  ✗ delivery-composition FAILED" >&2
    echo "  ERROR: носитель $DELIVERY_CARRIER_NAME в корне дерева отсутствует, а дерево опознано" >&2
    echo "  как источник (bin/deliver.sh на месте и несёт подпись установщика) — здесь объявление" >&2
    echo "  границы поставки обязано быть (спутник ADR-073 §2.3). Состав поставки не проверен, и" >&2
    echo "  это не «нарушений нет» (ADR-007 Д1). Почини: заведи $DELIVERY_CARRIER_NAME по схеме" >&2
    echo "  ADR-073-spec §2.2 либо смержи ветку на коммит, где носитель уже есть." >&2
    failed=1
    return
  fi

  local records=""
  records="$(_delivery_carrier_records)" || true

  local version
  version="$(printf '%s\n' "$records" | awk -F'\t' '$1=="VERSION" {print $2; exit}')"
  if [[ "$version" != "1" ]]; then
    _delivery_unreadable "версия схемы '${version:-<ключа version нет>}' незнакома, признаётся ровно 1" \
      "  Читатель, встретивший незнакомое значение, краснеет, а не догадывается (§2.2)."
    return
  fi

  local excluded_paths="" delivered_paths="" declared_paths="" problems=""
  local kind list epath has_reason has_prov stripped
  while IFS=$'\t' read -r kind list epath has_reason has_prov; do
    [[ "$kind" == "ENTRY" ]] || continue
    if [[ -z "$epath" ]]; then
      problems+="    - запись списка $list: поле path пусто"$'\n'
      continue
    fi
    stripped="${epath%/}"
    if [[ "$epath" == ./* || "$epath" == /* || "$stripped" == */* || -z "$stripped" ]]; then
      problems+="    - '$epath' ($list): грануляция Д2 — верхнеуровневый каталог со слэшем на конце либо корневой файл; второй уровень и ведущий './' формой не являются"$'\n'
    fi
    [[ "$has_reason" == "1" ]] || problems+="    - '$epath' ($list): нет обязательного поля reason"$'\n'
    [[ "$has_prov" == "1" ]] || problems+="    - '$epath' ($list): нет обязательного поля provenance"$'\n'
    if [[ "$list" == "excluded" ]]; then
      excluded_paths+="$epath"$'\n'
    else
      delivered_paths+="$epath"$'\n'
    fi
    declared_paths+="$epath"$'\n'
  done <<< "$records"

  # §3.2 дословно: «проверяется принадлежность записи РОВНО ОДНОМУ из них». Запись в обоих
  # списках — противоречивое объявление: фильтр релиза читает только excluded (§4.1 шаг 2) и
  # выкинет её, сторож увидит её объявленной с обеих сторон и промолчит. Расхождение решается
  # автором, не механизмом.
  local both=""
  while IFS= read -r epath; do
    [[ -n "$epath" ]] || continue
    _in_newline_list "$epath" "$delivered_paths" && both+="    - '$epath'"$'\n'
  done <<< "$excluded_paths"
  if [[ -n "$both" ]]; then
    problems+="    запись названа И в excluded, И в delivered — «ровно одному» (§3.2) нарушено:"$'\n'"$both"
  fi

  if [[ -n "$problems" ]]; then
    _delivery_unreadable "объявление не по схеме" "${problems%$'\n'}"
    return
  fi

  # Выборка §3.1 — коммитируемое множество, не рабочий каталог: неотслеживаемый каталог
  # сторожа не будит, потому что поставка родится из истории. Каталог получает слэш на
  # конце, корневой файл — нет: без этого различия объявление `internal` (форма корневого
  # файла) молча закрывало бы каталог `internal/`, то есть опечатка проходила бы как
  # объявление.
  local sample entry unknown="" sample_count excluded_count
  sample="$(git -C "$REPO_ROOT" ls-files | awk -F/ '{ if (NF==1) print $0; else print $1 "/" }' | sort -u)"
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    _in_newline_list "$entry" "$declared_paths" || unknown+="$entry"$'\n'
  done <<< "$sample"

  if [[ -n "$unknown" ]]; then
    echo "  ✗ delivery-composition FAILED" >&2
    while IFS= read -r entry; do
      [[ -n "$entry" ]] || continue
      echo "  ERROR: верхнеуровневая запись '$entry' не объявлена: она не названа исключением в" >&2
      echo "  $DELIVERY_CARRIER_NAME, а значит по умолчанию уезжает на ветку delivery всему" >&2
      echo "  потребителю (ADR-073 Д2/Д3). Механизм не знает, поставка это или внутренний" >&2
      echo "  артефакт, и не станет решать за автора. Почини одним из двух — в обоих случаях" >&2
      echo "  правится $DELIVERY_CARRIER_NAME:" >&2
      echo "    1) запись — часть плагина и должна уезжать потребителю: добавь её в список" >&2
      echo "       delivered: строкой \`- path: $entry\` с полями reason и provenance;" >&2
      echo "    2) запись внутренняя и уезжать не должна: добавь её в список excluded: той же" >&2
      echo "       формой." >&2
      echo "  Схема обоих списков — ADR-073-spec §2.2." >&2
    done <<< "$unknown"
    failed=1
    return
  fi

  sample_count="$(printf '%s\n' "$sample" | grep -c . || true)"
  excluded_count="$(printf '%s\n' "$excluded_paths" | grep -c . || true)"
  echo "  ✓ delivery-composition (${sample_count} верхнеуровневых записей, ${excluded_count} объявленных исключений)"
}

if [[ "$MODE" != "--secret-scan-only" ]]; then
  run_delivery_composition_gate
fi

# Симметрично --secret-scan-only (§4.3): шаг 4 релиза (§4.1) зовёт ТОТ ЖЕ блок сторожа, а не
# свою копию правила. Отдельный режим здесь потому, что `--fast` на отфильтрованном дереве
# красен четырьмя гейтами без предмета (замер §4.3), а разбирать его вывод грепом значило бы
# завести второй, менее строгий разборщик исхода.
if [[ "$MODE" == "--delivery-composition-only" ]]; then
  _finish
fi

if [[ "$MODE" != "--delivery-composition-only" ]]; then
  run_secret_scan_tree_gate
fi

# §4.3 спутника ADR-073: режим релиза исполняет РОВНО один гейт и ничего больше — на
# отфильтрованном дереве у остальных предмета нет (замер §4.3: четыре красных из пяти).
# Выход идёт через тот же _finish, что и полный прогон: второго решателя exit-кода нет.
if [[ "$MODE" == "--secret-scan-only" ]]; then
  _finish
fi
# Два безусловных вызова (§3 ADR-037-spec: "исключений в правиле нет") — идут через ТУ ЖЕ
# функцию, что и остальной перечень: в реальном payload'е они всегда заявлены и присутствуют,
# наблюдаемое поведение не меняется; расходится только текст, если они когда-нибудь пропадут.
run_gate_if_declared "validate-content"
run_gate_if_declared "validate-profile"
run_gate_if_declared "check-adr-line-limit"

# check-test-subject-governs (ADR-070; вызов — ADR-072 Д3/Д4). До DEV-111 гейт не звался
# НИОТКУДА: `grep -rn check-test-subject-governs .githooks/pre-commit scripts/check.sh
# bin/deliver.sh .gitlab-ci.yml` на базе 11d1fd4 давал пусто (rc=1) — снятие строки
# `Governs:` не меняло вывода ни одного обязательного прогона.
#
# Код 1 объявлен МЯГКИМ (второй аргумент): по контракту ADR-070 это «неполнота охвата»
# (есть SIGNAL, нет VIOLATION) — расхождение класса soft таксономии ADR-007 Д1, а не «не
# смог проверить». Число SIGNAL меняется каждой волной (capability без объявляющего теста
# заводит BA), и блокировать по нему значило бы красить рабочую ветку чужой волной.
# Хард-блок — код 3 (VIOLATION), он мягким не объявлен и остаётся отказом.
#
# Сам гейт при этом НЕ правится: его exit-контракт (0/1/2/3) объявлен ADR-070 и заперт
# `tests/test_qa073_adr070_governs_marker_gate.py`; переоткрывать принятое решение критерий
# BA-056 запрещает. Разбирает исход раннер — здесь. Состав поставки этой волной не меняется
# (ADR-072 Д5): вызов и поставка — разные вопросы (ADR-037 Д1).
run_gate_if_declared "check-test-subject-governs" "1"

# check-content-actuality (ADR-076 Д5/Д7, DEV-118). Предмет — разрешимость ОБЪЯВЛЕННЫХ
# статьёй опор в `git ls-files`, не дата правки: соседний check-status-drift.py мерит дату и
# «Статус» (ADR-008), и ни один прибор дерева до этого не мерил соответствие статьи дереву.
#
# Ступень --fast, а не --full: замер спутника §6 — 0,14 с на всё дерево (396 файлов, три
# прогона 0.14/0.14/0.13), один `git ls-files` на прогон, не на файл. Соседний гейт того же
# класса (маркер в шапке файла по корпусу) уже стоит здесь же строкой выше.
#
# Код 1 объявлен МЯГКИМ вторым аргументом по тому же основанию, что у соседа, и оно названо
# в Д5 дословно: «сегодня без маркера весь корпус области — заявленная цена перехода, не
# авария»; корпус входит в норму волнами, и блокировать коммит по числу «неопределим»
# значило бы красить рабочую ветку чужой волной. Хард-блок — код 3 («устарел»): там суждения
# нет ни грамма, статья сама назвала путь опорой, и пути в дереве нет. Мягким он не
# объявлен и остаётся отказом.
#
# Дерево без своей истории git (плоская копия `git archive HEAD | tar -x`) гейт НЕ красит: он
# печатает объявленное молчание и возвращает 0 — та же форма и то же основание, что у
# delivery-composition выше (ADR-073 §3.1): источника разрешения (`git ls-files`) здесь нет
# вовсе, значит нет и предмета — «нечего проверять», не «не смог проверить» (ADR-007 Д1).
run_gate_if_declared "check-content-actuality" "1"


if [[ "$MODE" == "--full" ]]; then
  # check-backlog-closure (ADR-012 Д4, Ruling D задачи 8/S7-DEV-003): гейт живёт в --full,
  # не --fast — Д4 буквально: между тем, как тест Dev'а позеленел, и тем, как PM перенёс
  # пункт в «Won't», проходят коммиты; в --fast гейт бил бы по каждому из них, то есть по
  # нормальному ходу TDD внутри эпика, а не по расхождению между эпиками. Заработал только
  # после починки разбора заголовков бэклога (### и ####, scripts/check-backlog-closure.py,
  # эта же задача) — на реальном дереве даёт `OK: 0 нарушений`, не молчал раньше по причине
  # отсутствия вызова, а падал бы `ERROR: не найдены секции` до фикса.
  run_gate_if_declared "check-backlog-closure"

  # id-check (ADR-038 Д3/Д8, ADR-038-spec §4.3/§5; решение владельца Р22, roadmap 2026-08-18)
  # — коллизии, невозврат отменённого номера, расхождение реестра .nauta-ids.yaml с корпусом.
  # Живёт в --full, не в --fast, по тексту Р22 дословно: профиль назван решением. Обоснование
  # то же, что у check-backlog-closure выше, — гейт судит СОСТОЯНИЕ КОРПУСА целиком (полный
  # обход дерева), а не отдельный коммит; в --fast (вход .githooks/pre-commit) он бил бы по
  # каждому шагу TDD внутри эпика.
  #
  # ЦЕНА ПОДКЛЮЧЕНИЯ, записанная здесь, а не только в roadmap, — чтобы следующий читатель не
  # принял её за недосмотр и не «починил»: область поиска ступени 3 («определение вне всех
  # объявленных home», scripts/id-check.sh) сознательно СУЖЕНА до формы `filename-prefix` и
  # дополнительно исключает companion-файлы `-spec.md` (санкционированный прецедент ADR-013
  # Д2 — companion законно несёт номер решения). То есть гейт видит меньше, чем мог бы. Без
  # сужения однобуквенный префикс `Д` пространства decision-clause матчит обычную русскую
  # прозу («Дата», «Две», «Держать») — замер на живом дереве DEV-010: ~90 ложных ERROR, из них
  # ~29 на companion-файлах content/40-architecture/. Расширение области до честного маркера
  # определения — ОТДЕЛЬНАЯ задача (требует более строгого матчера и покрывающего теста), а не
  # условие включения этого вызова.
  #
  # `next-id.sh` в этом перечне не появляется НИКОГДА (Д5 ADR-040, подтверждено Р22):
  # аллокатор мутирует реестр, раннер обязан оставаться читателем.
  run_gate_sh_if_declared "id-check"

  # check-content-classification (Ruling C задачи 8/S7-DEV-003, ADR-033 Д2) — вызов НЕ
  # восстанавливается, это не забытый файл. Гейт требует `.publishignore`; модель «рабочая
  # ветка + производная публикуемая», для которой он писался, в nauta не существует (ADR-033
  # Д2) — семантика гейта у потомка инвертирована: он красил бы КАЖДЫЙ файл content/ как
  # неклассифицированный (живой прогон архивной копии — отчёт задачи 7). Предмета здесь нет
  # по принятому решению — громким этот вызов не делается, он просто отсутствует.

  # check-breaking-change-section (Ruling E задачи 8/S7-DEV-003, ADR-021 Д2/Д4) — гейт-
  # СКРИПТ из check.sh не вызывается: требует обязательный позиционный `<range>`,
  # несовместимый с run_gate_if_declared (зовёт без аргументов), и `.publishignore`, которого
  # тоже нет (тот же факт, что у check-content-classification выше). Неприменимость
  # документируется здесь, а не молчит — сам гейт остаётся advisory-инструментом для
  # `ba-agent.md --mode=acceptance` (диапазон эпика передаётся вручную). Его bash-СЬЮТ
  # (регрессия на синтетике, не живой прогон на `.publishignore`) при этом зарегистрирован
  # ниже — ADR-017 требует регистрацию раннера отдельно от применимости самого гейта.

  # Ruling F (задача 8/S7-DEV-003): список сьютов приведён к тому, что реально есть в
  # дереве («объявлено — значит обязано существовать», ADR-007 Д1 распространяется и на
  # self-test harness). Из 18 архивных имён остаются три — N1 (задача 7) перенёс их py/sh-
  # предметы в scripts/, задача 8 регистрирует третье (test-check-breaking-change-section
  # ранее нигде не упоминался, ADR-017). Остальные 15 удалены по ДВУМ разным причинам —
  # полная разбивка построчно в task-8-report.md, здесь — категории:
  #   (a) предмета здесь нет по принятому решению, не «не успели перенести»: test-publish-
  #       public, test-examples-sync, test-repo-zone-map (публикация/витрина examples/,
  #       ADR-033 Д2 убрал модель «рабочая ветка + производная публикуемая»); test-template
  #       (смоук rename/idempotency локальной directory-копии шаблона — ADR-009-plugin-
  #       centralization-migration-spec.md Д7 п.3: «становится бессмысленным... удалять, не
  #       переписывать», как только источник стал удалённой git-ссылкой); test-check-
  #       content-classification (Ruling C выше); test-central-plugin-checkout (ADR-009-spec
  #       п.5 — «новая тестовая поверхность БЕЗ АНАЛОГА», проверяет consumer-сторону
  #       установки nauta как ЧУЖОГО плагина; внутри самого nauta второй стороны, которую
  #       можно поставить потребителем, нет).
  #   (b) предмет здесь есть (код существует в scripts/ или agents/), но сам файл сьюта не
  #       перенесён — отложенная задача N3 роадмапа (owner-решение Р10), не код: test-
  #       validate-profile, test-resolve-agents, test-check-status-drift, test-apply-overlay
  #       (предметы — validate-profile.py, _resolve_agents.py, check-status-drift.py,
  #       apply-overlay.sh, все в scripts/). DEV-125 (NA-EPIC-38) вывел из этой категории
  #       test-validate-content: сьюта не перенесена из донора, а НАПИСАНА заново под другой
  #       предмет — самопроверку гейта на синтетических фикстурах (четыре группы входов,
  #       ишью потребителей #11/#12), не перенос ~23 сценариев донорского контракта. Она
  #       доставляется payload'ом и зарегистрирована в перечне ниже;
  #       test-loud-gates (_validate_common.py/_drift_check.py); test-gate-debt (debt-батч
  #       PT-EPIC-13, большей частью тот же _drift_check.py/apply-overlay.sh); test-spdd-
  #       integration (two-way sync CLAUDE.md, PM-review drift-check, manifest drift_pairs —
  #       все три живут в этом дереве); test-backlog-cleanup (ownership-бухгалтерия PT-EPIC-16
  #       поверх check-backlog-closure.py/check-adr-line-limit.py); test-prompt-layer
  #       (ADR-016 промт-слой 11 ролей — agents/*.md, собственный домен nauta; 5 из 8
  #       исходных предметов уже переехали сюда напрямую вне этой задачи).
  #
  # test-check-id (DEV-022, NA-EPIC-11) — регистрируется тем же механизмом, что три соседа
  # выше, и это ЧЕТВЁРТОЕ имя перечня, а не исключение. Основание — то же правило ADR-017,
  # уже записанное абзацем выше про test-check-breaking-change-section: регистрация раннера
  # решается отдельно от применимости самого гейта. Разница с соседями по перечню одна и
  # ничего в протоколе не меняет: `scripts/test-check-id.sh` входит в PAYLOAD_FILES
  # (bin/deliver.sh) — то есть доставляется каждому потребителю, — тогда как три соседних
  # сьюты живут только здесь. Именно поэтому её отсутствие в перечне было вакуумом, а не
  # безобидным упущением: 19 мутационных проверок M1–M9 ехали в каждое дерево и не бежали ни
  # в одном профиле (находка DEV-019, «Осознанные границы» его отчёта).
  #
  # Обязательность НЕ ужесточается регистрацией: run_suite_if_declared соблюдает те же пять
  # исходов ADR-037, что и остальной перечень. У потребителя, синкнувшегося payload'ом БЕЗ
  # этой позиции, базис её не заявляет — он получит объявленное молчание (INFO-NOT-DELIVERED)
  # и exit 0, а не ложный красный. Красным она станет ровно тогда, когда базис её заявит.
  # test-validate-content (DEV-125, NA-EPIC-38) — ПЯТОЕ имя перечня, на том же основании и по
  # тому же протоколу, что и четвёртое. Отличие от соседей — только в предмете: это
  # самопроверка `validate-content.py` (самого большого гейта поставки, 19 проверок), которой
  # не было ни одной, тогда как у четырёх меньших гейтов она есть с ADR-025. Профилактика
  # ровно того класса, что дали ишью #11/#12: проверка признавалась работающей по признаку,
  # снятому с СОБСТВЕННОГО дерева. Сьюта входит в PAYLOAD_FILES — без регистрации здесь она
  # ехала бы к каждому потребителю и не бежала ни в одном профиле (вакуум DEV-019/DEV-022).
  for suite in test-check-adr-line-limit test-check-backlog-closure \
               test-check-breaking-change-section test-check-id \
               test-validate-content; do
    run_suite_if_declared "$suite"
  done
fi

# ---------------------------------------------------------------------------
# projectGates (ADR-077) — точка подключения ПРОЕКТНОГО гейта: проверки, которую написал
# потребитель доставки и которой в ростере выше нет и не будет.
#
# Носитель объявления — ключ `projectGates` в `.nauta-gates.yaml`, и выбран он по ВЛАДЕНИЮ
# файлом (Д1), не по удобству: это единственный из трёх кандидатов ВНЕ PAYLOAD_FILES
# (bin/deliver.sh), то есть единственный, который доставщик не перезаписывает каноном. Сам
# этот файл и `.githooks/pre-commit` заморожены per-file sha256 (ADR-030 Д3/Д4) — правка
# любого из них у потребителя даёт конфликт синка либо запись в skip:.
#
# Обязательность проектного гейта решает ЕГО ОБЪЯВЛЕНИЕ, не базис доставки (Д2): базис
# отвечает на вопрос «что мне привезли» и по построению не может ответить о непривезённом
# (`files:` пишется циклом ровно по PAYLOAD_FILES). Множества путей не пересекаются, поэтому
# приоритета между двумя источниками обязательности не требуется — но каждое сообщение
# обязано называть СВОЙ носитель дословно, иначе чинящего отправят не в тот файл (§4 спутника
# ADR-077; тот же класс дефекта, что закрывает ADR-037 Д5 пятью раздельными сообщениями).
# ---------------------------------------------------------------------------

# _project_gates_records — разбор ключа в плоские записи, разделённые табом: `KEY` (ключ
# найден; печатается ВСЕГДА при входе в блок, иначе «ключа нет» и «ключ есть, списки пусты»
# были бы неразличимы — тот же приём, что у признака `enabled=` в _gates_secret_scan_enabled)
# и `<fast|full>\t<путь>`. Форма — та же блочная awk-идиома, которой этот файл уже читает
# secretScan и носитель поставки: вход в блок по заголовку без отступа, выход — на первой
# строке без отступа. Отличие одно: значение подключа — список `- <путь>`, а не скаляр.
_project_gates_records() {
  local gates="$REPO_ROOT/.nauta-gates.yaml"
  [[ -f "$gates" ]] || return 0
  awk '
    /^projectGates:[ \t]*(#.*)?$/ { inblk=1; lst=""; print "KEY"; next }
    inblk && $0 ~ /^[^ \t]/ { inblk=0 }
    inblk {
      line=$0
      sub(/^[ \t]+/, "", line); gsub(/[ \t]+$/, "", line)
      if (line == "" || line ~ /^#/) next
      if (line ~ /^fast:[ \t]*(#.*)?$/) { lst="fast"; next }
      if (line ~ /^full:[ \t]*(#.*)?$/) { lst="full"; next }
      if (lst != "" && line ~ /^-[ \t]*/) {
        p=line
        sub(/^-[ \t]*/, "", p)
        gsub(/^"/, "", p); gsub(/"$/, "", p)
        if (p != "") print lst "\t" p
      }
    }
  ' "$gates"
}

# run_project_gates <fast|full> — шесть исходов Д3 ADR-077, ни одного тихого. Два молчания
# ОБЪЯВЛЕННЫЕ (ADR-040 Д8: у потребителя отсутствие конфигурации законно и громкой ошибкой не
# делается) и exit-кода не меняют; четыре отказа — ERROR и failed=1. Мягкие коды проектным
# гейтам НЕ выдаются (Д8): выдача была бы дырой — потребитель объявил бы мягким собственный
# отказ. Таймаут чужому гейту не вводится: времени прогона проектных гейтов не измерено ни в
# одном дереве, порог был бы выдуманным числом (Consequences ADR-077, приём ADR-037 Д6).
run_project_gates() {
  local profile="$1" records lst rel runner paths="" passes="$1" pass n
  records="$(_project_gates_records)"
  if [[ -z "$records" ]]; then
    echo "[INFO] projectGates: absent (.nauta-gates.yaml) — проверка не выполняется, exit-код не"
    echo "       меняется (ADR-077 Д3, ADR-040 Д8). Точка подключения СВОЕГО гейта существует:"
    echo "       заведи ключ projectGates с подсписками fast:/full: — объявленные пути будут"
    echo "       исполнены здесь, в хвосте прогона (fast: в обоих режимах, full: только в --full)."
    return 0
  fi

  # Порядок §4 спутника: сначала список профиля, затем fast: (он идёт в обоих режимах, Д5).
  # Дубль исполняется РОВНО один раз: путь, объявленный и в fast:, и в full:, в --full не
  # должен бежать дважды (граничное условие §10 спутника).
  if [[ "$profile" == "full" ]]; then passes="full fast"; fi
  for pass in $passes; do
    while IFS=$'\t' read -r lst rel; do
      [[ "$lst" == "$pass" && -n "$rel" ]] || continue
      _in_newline_list "$rel" "$paths" && continue
      paths+="$rel"$'\n'
    done <<< "$records"
  done

  n="$(printf '%s' "$paths" | grep -c . || true)"
  echo "[INFO] projectGates: configured (${n} позиций) — носитель объявления .nauta-gates.yaml,"
  echo "       профиль ${profile}. Источник обязательности этих гейтов — их объявление в ключе,"
  echo "       а не базис доставки (ADR-077 Д2): базис заявляет только привезённое."
  # `return 0`, а не голый `return`: голый вернул бы статус ПОСЛЕДНЕЙ команды — то есть 1 от
  # самого `[[ -n "$paths" ]]`, — и под `set -e` инертный ключ ронял бы весь прогон ещё до
  # _finish. Поймано красным `test_d3_row2_present_but_empty_key_is_configured_zero`.
  [[ -n "$paths" ]] || return 0

  while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue

    # Путь вне дерева отвергается ДО запуска. Проверка грубая намеренно: любое вхождение ".."
    # достаточно, чтобы отказать — механизм не разрешает символические ссылки и не считает
    # уровни, а объявление о собственном гейте таких форм не требует.
    if [[ "$rel" == /* || "$rel" == *".."* ]]; then
      echo "▶ $rel"
      echo "  ✗ $rel FAILED" >&2
      echo "  ERROR: путь \"$rel\" объявлен в projectGates (.nauta-gates.yaml) абсолютным либо содержит \"..\"" >&2
      echo "  — объявление не даёт права исполнить код вне дерева (ADR-077 Д3), гейт НЕ запускался." >&2
      echo "  Почини: назови путь от корня репозитория либо убери его из projectGates." >&2
      failed=1
      continue
    fi

    # Д4: раннер выводится из расширения, бит x не спрашивается (git переносит его одной
    # единственной сущностью и в носители объявления не годится).
    case "$rel" in
      *.sh) runner="bash" ;;
      *.py) runner="uv run" ;;
      *)
        echo "▶ $rel"
        echo "  ✗ $rel FAILED" >&2
        echo "  ERROR: гейт \"$rel\" объявлен в projectGates (.nauta-gates.yaml), а раннер не выводится из пути:" >&2
        echo "  признаются ровно два расширения — .sh (bash) и .py (uv run), ADR-077 Д4. Гейт НЕ" >&2
        echo "  запускался. Почини: дай файлу одно из двух расширений либо убери путь из projectGates." >&2
        failed=1
        continue
        ;;
    esac

    # Граница, ради которой существует решение: «заявлен и отсутствует» — противоречие, а не
    # отказ от проверки. Сообщение называет ИМЕННО projectGates: базис доставки этот путь не
    # заявляет и заявить не может, и посылать чинящего в .nauta-scripts-basis.yaml значило бы
    # отправить его не в тот файл.
    if [[ ! -f "$rel" ]]; then
      echo "▶ $rel"
      echo "  ✗ $rel FAILED" >&2
      echo "  ERROR: гейт объявлен в projectGates (.nauta-gates.yaml), но файла $rel в дереве нет —" >&2
      echo "  заявка есть, предмета нет. ADR-007 Д1: \"не смог проверить\" ≠ \"нечего проверять\"," >&2
      echo "  и источник обязательности здесь — объявление в ключе, не доставка (ADR-077 Д2)." >&2
      echo "  Почини: верни файл либо убери путь из projectGates." >&2
      failed=1
      continue
    fi

    run_check "$rel" "$runner $rel"
  done <<< "$paths"
}

# Место вызова — хвост прогона (Д6): после всего доставленного ростера и до _finish, чтобы
# красный ДОСТАВЛЕННЫЙ гейт был виден раньше чужого. Односьютные режимы (--secret-scan-only,
# --delivery-composition-only) сюда не доезжают — они завершаются своим _finish выше, и это
# то же правило «режим релиза исполняет РОВНО один гейт и ничего больше» (§4.3 спутника
# ADR-073). Признак дерева-источника (ORIGIN) здесь не спрашивается: у проектных гейтов
# перечня по умолчанию нет, объявление всегда явное, и поведение в дереве-источнике и у
# потребителя одинаково (Д7).
if [[ "$MODE" == "--full" ]]; then
  run_project_gates "full"
else
  run_project_gates "fast"
fi

_finish
