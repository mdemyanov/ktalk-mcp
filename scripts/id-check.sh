#!/usr/bin/env bash
# id-check.sh — коллизии, невозврат отменённого номера, расхождение реестра
# (ADR-038, схема — content/40-architecture/ADR-038-identifier-namespaces-and-allocation-spec.md
# §4.3, §5). Реестр — .nauta-ids.yaml в корне дерева (§3 того же файла).
#
# Логика — Python (PEP 723 inline-заголовок), не bash: bash в этом дереве — 3.2, без
# ассоциативных массивов (бриф DEV-010, ADR-038-spec §8). Приём — heredoc в `uv run -`
# (единственный файл, самодостаточная доставка payload'ом, без второго .py рядом).
#
# Прогон один: перечисляются все исходы всех реестров (§4.3, «остановки на первом нет»).
# Момент вызова и обязательность здесь не назначаются (ADR-038-spec §11 — передано SA-012).
set -uo pipefail

exec uv run - "$@" <<'PYEOF'
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7.0"]
# ///
"""id-check.sh (встроенный Python) — читает .nauta-ids.yaml, индексирует определения по home
каждой записи (§4.1 форма definition), сверяет коллизии/невозврат/расхождение/популярность
(§4.3), печатает полный список исходов и завершается non-zero при любом нарушении (§5).
"""
from __future__ import annotations

import glob as globmod
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REGISTRY_PATH = Path(".nauta-ids.yaml")

_DELIMS = set(" \t:)]*|")


def _extract_token(text: str, start: int) -> str:
    """Токен идентификатора от start() до первого разделителя либо '.' — '.' отдельно,
    чтобы заголовки вида '### Д1.' не тянули точку в номер (ADR-038-spec §4.1)."""
    j = start
    n = len(text)
    while j < n and text[j] not in _DELIMS and text[j] != ".":
        j += 1
    return text[start:j]


def _match_filename_prefix(basename: str, prefix: str):
    if not prefix or not basename.startswith(prefix):
        return None
    rest = basename[len(prefix):]
    m = re.match(r"\d+", rest)
    return m.group(0) if m else None


def _match_h1_suffix(line: str, prefix: str):
    if not prefix:
        return None
    if not (line.startswith("# ") and not line.startswith("## ")):
        return None
    m = re.search(re.escape(prefix) + r"(\d+)\)\s*$", line)
    return m.group(1) if m else None


def _match_list_or_row_head(line: str, prefix: str):
    if not prefix:
        return None
    s = line.strip()
    remainder = None
    if s.startswith("- "):
        remainder = s[2:].lstrip()
        if remainder.startswith("["):
            end = remainder.find("] ")
            if end != -1:
                remainder = remainder[end + 2:]
        if remainder.startswith("**"):
            remainder = remainder[2:]
    elif s.startswith("|"):
        remainder = s[1:].split("|", 1)[0].strip()
    elif s.startswith("**"):
        remainder = s[2:]
    else:
        m = re.match(r"#+\s+(.*)", s)
        if m:
            remainder = m.group(1)
    if remainder is None or not remainder.startswith(prefix):
        return None
    token = _extract_token(remainder, len(prefix))
    # Кандидат только когда СРАЗУ за префиксом стоит цифра (ADR-038-spec §4.1: «Д1» —
    # префикс+число). Иначе однобуквенный префикс матчит любое слово, начинающееся с той же
    # буквы («Дата» → «ата», «Держать» → «ержать») — шум в [INFO], не идентификатор (DEV-038,
    # NA-EPIC-13, замер на живом дереве nauta: семь таких слов под decision-clause/"Д").
    # Легитимные нечисловые токены (AC-032-02 под prefix "AC-") ПРОХОДЯТ эту границу — их
    # первый символ уже цифра, нечисловыми их делает суффикс после дефиса, не начало.
    if not token or not token[0].isdigit():
        return None
    return token


def _match_heading_anchored(line: str, prefix: str):
    """ADR-038-spec §4.1: определение либо открывает текст заголовка любого уровня (роль
    `opens`), либо стоит в круглых скобках внутри такого заголовка (роль `parens`). Всё
    прочее вхождение в заголовке — упоминание (M11), не определение. Возвращает
    (token, role) либо None — роль нужна вызывающей стороне для приоритета §4.1b/ADR-044."""
    if not prefix:
        return None
    m = re.match(r"#{1,6}\s+(.*)", line)
    if not m:
        return None
    remainder = m.group(1)
    if remainder.startswith(prefix):
        token = _extract_token(remainder, len(prefix))
        return (token, "opens") if token else None
    needle = "(" + prefix
    idx = remainder.find(needle)
    if idx != -1:
        start = idx + len(needle)
        token = _extract_token(remainder, start)
        if token and remainder[start + len(token):start + len(token) + 1] == ")":
            return (token, "parens")
    return None


def _match_entry(path: str, definition: str, prefix: str):
    """Вернуть [(token, is_numeric, line_no, role)] для path под формой definition. `role`
    несёт смысл только для `heading-anchored` (`opens`/`parens`, §4.1b/ADR-044); прочие формы
    не имеют ролей и всегда возвращают `role=None` — вызывающая сторона не интерпретирует
    роль для них (§8b п.1: сигнатура прокидывается без интерпретации)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()

    if definition == "filename-prefix":
        token = _match_filename_prefix(os.path.basename(path), prefix)
        return [(token, token.isdigit(), 0, None)] if token else []

    if definition == "h1-suffix":
        for line in lines:
            if line.startswith("# "):
                token = _match_h1_suffix(line, prefix)
                if token:
                    return [(token, token.isdigit(), 1, None)]
                break
        return []

    if definition == "list-or-row-head":
        out = []
        for i, line in enumerate(lines, start=1):
            token = _match_list_or_row_head(line, prefix)
            if token:
                out.append((token, token.isdigit(), i, None))
        return out

    if definition == "heading-anchored":
        out = []
        for i, line in enumerate(lines, start=1):
            hit = _match_heading_anchored(line, prefix)
            if hit:
                token, role = hit
                out.append((token, token.isdigit(), i, role))
        return out

    return []


def _home_files(entry: dict) -> set[str]:
    files: set[str] = set()
    for pattern in entry.get("home") or []:
        files.update(globmod.glob(pattern))
    return files


_CANDIDATE_EXTS = (".md", ".yaml", ".yml", ".txt")


def _git_candidate_files(exts=_CANDIDATE_EXTS):
    """Корпус ступени 3 средствами git: отслеживаемые ПЛЮС неотслеживаемые, но БЕЗ
    игнорируемых. None — git недоступен (не репозиторий либо нет бинаря).

    Почему обе половины: `--cached` в одиночку ослепил бы гейт на только что созданном и ещё
    не добавленном файле (новый ADR вне home — ровно тот исход, который ступень 3 обязана
    ловить); `--others --exclude-standard` возвращает неотслеживаемые за вычетом того, что
    исключено `.gitignore`/`.git/info/exclude`/core.excludesFile. Граница сужения ровно одна
    и объявлена: игнорируемое репозиторием — не корпус репозитория.

    `-z`: пути с пробелами и не-ASCII (в этом дереве весь content/ — кириллица) git иначе
    возвращает в кавычках с escape-последовательностями, и сравнение с путями из glob()
    ломалось бы молча."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    seen = set()
    out = []
    for path in proc.stdout.split("\0"):
        if not path or not path.endswith(exts) or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _walk_candidate_files(exts=_CANDIDATE_EXTS) -> list[str]:
    """Вырожденный обход для дерева БЕЗ git. Кортеж исключений здесь принципиально неполон —
    правил игнорирования взять неоткуда; вызывающий обязан назвать это в выводе, а не
    промолчать (ADR-007 Д1)."""
    out = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in (".git", ".beads")]
        for name in files:
            if name.endswith(exts):
                out.append(os.path.normpath(os.path.join(root, name)).replace("\\", "/"))
    return out


def _candidate_files() -> tuple[list[str], str]:
    """(корпус, строка провенанса). Провенанс печатается ВСЕГДА: читатель обязан видеть, чем
    перечислен корпус, а не догадываться по составу находок."""
    files = _git_candidate_files()
    if files is not None:
        return files, (
            f"[INFO] корпус ступени 3 перечислен git ls-files --cached --others "
            f"--exclude-standard: {len(files)} файлов, игнорируемые (.gitignore) исключены."
        )
    files = _walk_candidate_files()
    return files, (
        f"[INFO] корпус ступени 3 перечислен обходом файловой системы: git недоступен — это "
        f"не git-репозиторий либо git не в PATH. Правила .gitignore не читаются, поэтому в "
        f"корпус попадают файлы игнорируемых каталогов (копии дерева: .claude/worktrees, "
        f"распакованный архив, каталог сборки) — они могут дать «определение вне home» на "
        f"файле, которого репозиторий не знает. Проверка выполнена ({len(files)} файлов), "
        f"область её знания шире корпуса репозитория — это названо здесь, а не умолчано."
    )


_HISTORY_CACHE: dict = {}


def _history_subjects():
    """Темы коммитов истории HEAD (`git log --format=%s`) либо None, если истории нет.

    Свидетель израсходованного номера — ТЕМА, не всё сообщение: тела коммитов цитируют чужие
    номера прозой, а цитата расходом не является (Д6 ADR-038 — упоминание вне предмета).
    Замер на дереве nauta (`3b9e3ec`): `--format='%B'` добавляет к множеству тем `NA-EPIC-02`,
    `NA-EPIC-09` и обломок `NA-EPIC-3`, которых ни одна волна не расходовала.

    Ref — HEAD, а не `--all`: `--all` втягивает локальные ветки соседних worktree и брошенные
    эксперименты, и вывод гейта переставал бы воспроизводиться между клонами одного дерева.
    Замер на `3b9e3ec`: множества HEAD и `--all` совпадают, поэтому цена выбора нулевая, а
    воспроизводимость — нет.
    """
    if "subjects" in _HISTORY_CACHE:
        return _HISTORY_CACHE["subjects"]
    subjects = None
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%s", "HEAD"],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            subjects = proc.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        subjects = None
    _HISTORY_CACHE["subjects"] = subjects
    return subjects


def _history_is_shallow() -> bool:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _consumed_without_home(entry: dict, found: list, retired: set):
    """ВТОРОЕ НАПРАВЛЕНИЕ расхождения (DEV-120, NA-EPIC-37) → (violations, info_lines).

    Номер израсходован волной — её коммиты стоят в истории, — а определения в доме нет
    вовсе. Проверка `corpus_max > highwater` ловит только обратный перекос (номер в доме
    есть, highwater не поднят); здесь корпус НЕ растёт, максимум не сдвигается, и краснеть
    ей нечему по построению. Замер класса (на `300ed70`, до починки данных): номера в
    истории до 36, корпус роадмапа 33, highwater 33, `bash scripts/id-check.sh` → «OK: 8
    реестров проверено, чисто», при этом `bash scripts/next-id.sh na-epic --dry-run` → 34,
    то есть аллокатор выдал бы уже израсходованный номер, и трижды подряд.

    Дискриминатор — ОБЪЯВЛЕННОЕ ПОЛЕ `definition`, приём ADR-069 Д1 (там область перевели с
    ярлыка `allocation` на объявленное поле записи). Отказ выражаем ровно у формы
    `heading-anchored`: определение там — заголовок, который человек обязан НАПИСАТЬ
    отдельным действием, и не написать его можно молча. У трёх остальных форм определением
    служит сам артефакт (файл `ADR-NNN-*.md`, заголовок статьи, строка таблицы) — «номер
    израсходован, а определения нет» там не конструируется.

    Граница спутника названа, а не обойдена: ADR-038-spec §4.3 «Границы» несёт строку «Не
    читает историю git: кладбище объявлено документом, а не восстанавливается из удалений».
    Причина в ней названа и к этому чтению не относится — здесь история не восстанавливает
    КЛАДБИЩЕ (оно по-прежнему только документ, и отменённые номера из проверки изымаются),
    а служит свидетелем РАСХОДА номера. Правка формулировки границы передана SA отчётом
    DEV-120 — сам спутник этой задачей не правится.

    ПОЧЕМУ ОТДЕЛЬНАЯ ФУНКЦИЯ (DEV-121). Тело стояло в цикле НИЖЕ раннего выхода ступени 8/7
    (`if not found: … continue`), и потому не выполнялось ровно в стартовом состоянии
    потомка: `populated: false` — то, что `/nauta:init` пишет КАЖДОМУ пространству
    (`templates/nauta-ids.yaml`, шесть записей, ни одной `populated: true`). Отказ:
    потомок объявляет своё пространство эпиков `heading-anchored`, прогоняет первую волну
    коммитом `feat(XX-EPIC-01): …`, заголовка не пишет → `found` пуст → «нечего проверять»
    → rc 0 → `next-id.sh` выдаёт `01` повторно. Замер на стенде до правки: `id-check.sh` →
    «OK: 1 реестров проверено, чисто», `next-id.sh xx-epic --dry-run` → `01`.

    Выбор формы правки — вынос в функцию с двумя точками вызова, а НЕ перестановка блока и
    не снятие `continue`. Довод: снятие `continue` включило бы на пустом корпусе ЗАОДНО и
    сканирование корпуса на повторную выдачу отменённого номера, и проверку типа поля
    `highwater` — обе читают корпус, которого нет, и обе к предмету этой задачи не
    относятся. Вынос трогает ровно одну проверку. Кладбище на второй точке вызова всё же
    читается — но как ВХОД этой проверки (изъятие отменённых номеров), и его нечитаемость
    там называется тем же «не смог проверить», а не подменяется пустым множеством.

    Пустой `prefix` отсекается: `re.escape("") + r"(\\d+)"` матчил бы КАЖДОЕ число каждой
    темы коммита. До DEV-121 эта ветка была недостижима (`_match_heading_anchored` при
    пустом префиксе не возвращает ничего, значит `found` пуст и цикл выходил раньше) —
    новая точка вызова делает её достижимой, поэтому граница объявлена здесь явно.
    """
    ns = entry["namespace"]
    prefix = entry.get("prefix") or ""
    definition = entry.get("definition")
    violations: list[str] = []
    info_lines: list[str] = []
    if definition != "heading-anchored" or not prefix:
        return violations, info_lines

    subjects = _history_subjects()
    if subjects is None:
        info_lines.append(
            f"[INFO] расход номеров пространства '{ns}' по истории git не проверен — "
            f"истории нет (не git-репозиторий либо git не в PATH). Форма "
            f"`heading-anchored` определяется заголовком, который пишут отдельным "
            f"действием, и «номер израсходован, заголовка нет» без истории "
            f"неотличимо от «номер не выдавался»: исход назван, а не проглочен "
            f"(ADR-007 Д1)."
        )
        return violations, info_lines

    if _history_is_shallow():
        info_lines.append(
            f"[INFO] история git усечена (shallow-клон) — расход номеров "
            f"пространства '{ns}' проверен по видимой части истории "
            f"({len(subjects)} коммитов), не по всей."
        )
    witness: dict = {}
    pat = re.compile(re.escape(prefix) + r"(\d+)")
    for subject in subjects:
        for m in pat.finditer(subject):
            witness.setdefault(int(m.group(1)), subject)
    defined = {int(token) for token, is_numeric, _p, _l, _role in found if is_numeric}
    for number in sorted(witness):
        if number in defined or number in retired:
            continue
        violations.append(
            f"ERROR: номер израсходован мимо дома — {prefix}{number} встречается "
            f"в теме коммита истории git («{witness[number]}»), но определения "
            f"в home {entry.get('home')} у него нет. Форма '{definition}': номер "
            f"существует для аллокатора только заголовком, и без заголовка "
            f"следующая выдача повторит уже израсходованный номер."
        )
    return violations, info_lines


def _graveyard_retired(entry: dict):
    """(retired_numbers, error_message_or_None). error non-None -> «не смог проверить»."""
    graveyard = entry.get("graveyard")
    prefix = entry.get("prefix") or ""
    if not graveyard:
        return set(), None
    path = Path(graveyard)
    if not path.is_file():
        return set(), (
            f"кладбище номеров пространства '{entry['namespace']}' объявлено как {graveyard}, "
            f"но файла в дереве нет — не смог проверить невозврат отменённого номера."
        )
    retired = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("- ") or "](" in s:
            continue
        rest = s[2:]
        if not rest.startswith(prefix):
            continue
        m = re.match(r"\d+", rest[len(prefix):])
        if m:
            retired.add(int(m.group(0)))
    return retired, None


def main(argv: list[str]) -> int:
    if not REGISTRY_PATH.is_file():
        print(
            f"ERROR: не смог проверить — реестр {REGISTRY_PATH} отсутствует. Это НЕ тихий "
            f"skip (ADR-038 Д3): без реестра граница пространств имён не объявлена.\n"
            f"  Почини: bash ${{CLAUDE_PLUGIN_ROOT}}/bin/init.sh .  — повторный `/nauta:init` "
            f"восстановит стартовый\n"
            f"  реестр из шаблона плагина (пустой корпус, populated: false у всех записей); "
            f"существующий\n"
            f"  {REGISTRY_PATH} init.sh не трогает, только заводит отсутствующий.",
            file=sys.stderr,
        )
        return 1

    try:
        raw = REGISTRY_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (yaml.YAMLError, OSError) as exc:
        # Текст PyYAML многострочен; свёртка — тот же приём, что в
        # `_validate_common.py:57` (MalformedYamlError.reason), второго диалекта не
        # заводим. Маркер и причина остаются в одной строке записи исхода.
        reason = " ".join(str(exc).split())
        print(
            f"ERROR: не смог проверить — реестр {REGISTRY_PATH} не разбирается: {reason}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(data, dict) or not isinstance(data.get("namespaces"), list):
        print(
            f"ERROR: не смог проверить — реестр {REGISTRY_PATH} повреждён: нет списка "
            f"'namespaces' верхнего уровня.",
            file=sys.stderr,
        )
        return 1

    entries = data["namespaces"]
    names = [e.get("namespace") for e in entries]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(
            f"ERROR: реестр {REGISTRY_PATH} повреждён — повторяющееся имя пространства имён: "
            f"{dupes}. Это порча самого реестра, не совпадение идентификаторов.",
            file=sys.stderr,
        )
        return 1

    for e in entries:
        e["_home_set"] = _home_files(e)

    violations: list[str] = []
    info_lines: list[str] = []
    definitions: dict[str, list[tuple[str, bool, str, int, object]]] = {}

    for e in entries:
        ns = e["namespace"]
        prefix = e.get("prefix") or ""
        definition = e.get("definition")
        found: list[tuple[str, bool, str, int, object]] = []
        for path in sorted(e["_home_set"]):
            for token, is_numeric, lineno, role in _match_entry(path, definition, prefix):
                found.append((token, is_numeric, path, lineno, role))
        definitions[ns] = found

    # Ступень 3 (§4.3 п.3): определение в форме реестра вне всех объявленных home.
    # Ограничено формой filename-prefix (единственная форма, для которой это проверено
    # сценарием AC-6/M4, ADR-038-spec §7): полнотекстовый обход дерева с формами h1-suffix/
    # list-or-row-head даёт лавину ложных совпадений на однобуквенных префиксах
    # (decision-clause: "Д" матчит "Дата:", "Для", любое слово на "Д" — замерено этой
    # задачей на живом дереве nauta, не гипотеза). Сужение — осознанная граница, не пробел:
    # расширение на остальные формы требует более строгого матчера (например, обязательного
    # требования непустого числового суффикса СРАЗУ после префикса без буквенных символов
    # между ними) и передаётся дальше как открытый пункт (см. отчёт DEV-010 / implementation
    # notes), а не решается здесь тихой эвристикой без покрывающего теста.
    #
    # Вторая объявленная граница — САМ КОРПУС: перечисляется git'ом, игнорируемое
    # репозиторием в него не входит (DEV-019). До этой правки обход был os.walk(".") с
    # кортежем исключений из двух имён, и КАЖДАЯ копия дерева внутри дерева умножала корпус:
    # замер на корне nauta с шестью worktree параллельной волны — 210 ложных ERROR, все на
    # .worktrees/, каталоге, объявленном в .gitignore и создаваемом штатным ритуалом
    # той поры. Ритуала этой формы больше нет: ручное создание копии снято с ADR-081 Д3,
    # копии кладёт платформа в `.claude/worktrees/`. Имя `.worktrees/` во второй строке НЕ
    # переписывается — это описание того, что было замерено тогда.
    all_homes: set[str] = set()
    for e in entries:
        all_homes |= e["_home_set"]
    candidate_files, corpus_provenance = _candidate_files()
    info_lines.append(corpus_provenance)
    for e in entries:
        prefix = e.get("prefix") or ""
        definition = e.get("definition")
        if not prefix or definition != "filename-prefix":
            continue
        for path in candidate_files:
            if path in e["_home_set"] or path in all_homes:
                continue
            # Санкционированный приём ADR-013 Д2: companion "-spec.md" сознательно несёт тот
            # же номер, что решение (content/40-architecture/ADR-NNN-...-spec.md рядом с
            # content/00-project/adr/ADR-NNN-....md) — не рогue-дубль. check-adr-line-limit.py
            # исключает -spec.md из ЛИМИТА той же парой файлов; здесь тот же прецедент
            # применён к «вне home»: замерено на живом дереве (id-check.sh без этой строки
            # даёт ~29 ложных ERROR на companion-файлах content/40-architecture/).
            if path.endswith("-spec.md"):
                continue
            for token, is_numeric, lineno, _role in _match_entry(path, definition, prefix):
                violations.append(
                    f"ERROR: не смог определить пространство имён — {prefix}{token} найден в "
                    f"{path}:{lineno}, вне всех объявленных home ни одной записи реестра."
                )

    for e in entries:
        ns = e["namespace"]
        prefix = e.get("prefix") or ""
        scope = e.get("scope", "namespace")
        allocation = e.get("allocation")
        populated = bool(e.get("populated"))
        definition = e.get("definition")
        found = definitions[ns]

        # §4.1a: пустой prefix ⇒ populated: false обязателен. Обратное сочетание — порча
        # самого реестра (номеров у такой записи нет по построению), не «не смог проверить»
        # (та причина держит другой факт — home пуст либо непустое пространство без
        # определений). M12, ADR-038-spec §7.
        if not prefix and populated:
            violations.append(
                f"ERROR: реестр повреждён — пространство '{ns}' объявляет пустой prefix и "
                f"populated: true одновременно (§4.1a): пустой prefix исключает populated: "
                f"true по построению (номеров у записи нет)."
            )
            continue

        # Ступень 8/7 (Д8): populated: true и ноль определений -> не смог проверить.
        if not found:
            if populated:
                violations.append(
                    f"ERROR: не смог проверить — пространство '{ns}' объявлено populated: "
                    f"true, но ноль определений найдено под home {e.get('home')}."
                )
            else:
                info_lines.append(f"[INFO] нечего проверять — пространство '{ns}' пусто по объявлению.")
            # DEV-121: пустой корпус отменяет проверки, которые ЧИТАЮТ корпус, — но не
            # проверку расхода номеров историей: там свидетель не корпус, а тема коммита,
            # и «дом пуст» для неё не отсутствие данных, а сам предмет находки. Ровно этот
            # `continue` выключал сторожа DEV-120 в стартовом состоянии потомка
            # (`populated: false` пишет `/nauta:init` каждому пространству) — то есть в
            # момент, когда отказ вероятнее всего. Оба исхода ступени 8/7 выше сохранены:
            # они про утверждение реестра о непустоте корпуса, а не про историю.
            # Дискриминатор повторён на месте вызова, а не оставлен только внутри функции:
            # кладбище ниже читается ТОЛЬКО ради этой проверки, и читать его для форм, к
            # которым проверка не применяется, значило бы завести новый красный там, где
            # предмета нет. Замер цены до этой строки: свежее дерево потомка (`deliver.sh`
            # + `/nauta:init`) краснело «кладбище номеров пространства 'adr' объявлено как
            # content/00-project/adr/_index.md, но файла в дереве нет» — четыре падения в
            # сьюте (`test_dev025_*` ×3, `test_dev030_*`), у записи формы `filename-prefix`.
            if definition == "heading-anchored" and prefix and allocation != "external":
                # `external` — тот же изъятый случай, что и ниже по циклу (Д2 ADR-069):
                # у чужого аллокатора измеримого корпуса в этом дереве нет.
                #
                # Кладбище читается ЗДЕСЬ, а не ниже (ниже до него не доходит `continue`):
                # отменённые номера — вход самой этой проверки, без них отменённая волна
                # стала бы вечным красным. Нечитаемое объявленное кладбище называется тем
                # же «не смог проверить», что и на общем пути: молча подставить пустое
                # множество значило бы выдать непроверенное за проверенное.
                retired_empty, grave_err = _graveyard_retired(e)
                if grave_err:
                    violations.append(f"ERROR: не смог проверить — {grave_err}")
                v, i = _consumed_without_home(e, [], retired_empty)
                violations.extend(v)
                info_lines.extend(i)
            continue

        # Приоритет ролей opens/parens (§4.1b/ADR-044, ADR-038-spec §7 M13/M14): отдельный
        # проход ПОСЛЕ сбора всех вхождений формы heading-anchored для пространства, ДО
        # группировки коллизий ниже (§8b п.3). Для каждого числового токена: если среди его
        # вхождений есть хотя бы одно роли `opens`, все вхождения роли `parens` того же
        # токена демотируются в упоминание — не участвуют ни в коллизии, ни в corpus_max, ни
        # в проверке кладбища. Если роли `opens` для токена нет — все `parens` остаются
        # определениями без изменений (M10 не теряется — прогнан после этой правки, §7).
        # Применяется только к `heading-anchored`: остальные три формы ролей не имеют.
        if definition == "heading-anchored":
            opens_tokens = {token for token, _n, _p, _l, role in found if role == "opens"}
            kept = []
            for item in found:
                token, is_numeric, path, lineno, role = item
                if role == "parens" and token in opens_tokens:
                    info_lines.append(
                        f"[INFO] {prefix}{token} в {path}:{lineno} — заголовок роли "
                        f"`parens`, демотирован в упоминание приоритетом ролей "
                        f"(§4.1b/ADR-044): для номера {token} уже есть определение роли "
                        f"`opens`."
                    )
                else:
                    kept.append(item)
            found = kept

        # Ступень 4: коллизия внутри объявленного пространства.
        #
        # Для формы `definition: heading-anchored` (единственный потребитель сегодня —
        # `na-epic`) группировка — по ВХОЖДЕНИЯМ (путь + строка), не по множеству путей: два
        # определения одного номера в ОДНОМ и том же файле (два заголовка heading-anchored в
        # roadmap.md, M10 ADR-038-spec §7) обязаны коллидировать наравне с определениями в
        # разных файлах — дедуп по одним лишь путям схлопывал бы такую пару в один элемент
        # и терял коллизию молча.
        #
        # Остальные три формы (`filename-prefix`, `h1-suffix`, `list-or-row-head`) НАМЕРЕННО
        # не переведены на ту же семантику этим коммитом (DEV-028, NA-EPIC-12, вне брифа §8a):
        # пробный перевод вскрыл заранее не заявленные дефекты чужих пространств имён —
        # `decision-clause` (секции «Alternatives Considered» переиспользуют текст «Д1:»,
        # «Д2:» как маркер ОТКЛОНЁННОЙ альтернативы, отдельно от «### Д1.» решения) и `tpl`
        # (второй список того же backlog повторно перечисляет уже занесённые в первую таблицу
        # номера). Оба — конфликт с уже принятым состоянием чужих пространств имён, не предмет
        # DEV-028; зафиксировано в отчёте, правка передана владельцу тех пространств.
        groups: dict = {}
        for token, is_numeric, path, lineno, _role in found:
            if definition == "heading-anchored":
                key = int(token) if is_numeric else token
                groups.setdefault(key, []).append((path, lineno))
            elif scope == "file":
                key = (path, int(token) if is_numeric else token)
                groups.setdefault(key, set()).add(path)
            else:
                key = int(token) if is_numeric else token
                groups.setdefault(key, set()).add(path)
        for key, occurrences in groups.items():
            if len(occurrences) > 1:
                if isinstance(occurrences, set):
                    places = ", ".join(sorted(occurrences))
                else:
                    places = ", ".join(f"{p}:{l}" for p, l in sorted(occurrences))
                violations.append(
                    f"ERROR: коллизия идентификаторов в пространстве '{ns}': номер "
                    f"{key[1] if isinstance(key, tuple) else key} определён в нескольких "
                    f"местах: {places}."
                )

        # Не-числовые определения — названы отдельно, не молча отброшены.
        for token, is_numeric, path, lineno, _role in found:
            if not is_numeric:
                info_lines.append(
                    f"[INFO] {prefix}{token} в {path}:{lineno} не разбирается как число — "
                    f"не участвует в арифметике highwater, назван отдельно."
                )

        # ADR-069 Д1/Д2: дискриминатор обеих проверок ниже — ОБЪЯВЛЕННОЕ ПОЛЕ записи
        # (`highwater`/`graveyard`), а не ярлык `allocation`. Прежняя строка
        # (`if allocation != "allocated": continue`) была шире любого записанного решения:
        # §4.3 п.5/п.6 ADR-038-spec квалификатора по `allocation` не несут вовсе,
        # ограничение на `allocated` есть только в §4.2 (ВЫДАЧА), где оно и уместно.
        # Цена прежней строки замерена: три состояния живого реестра `tpl` (highwater
        # 108/114/1) давали побайтово один выход и exit 0 — по этому предмету гейт был
        # неотличим от своего отсутствия (§2 часть A ADR-069-spec).
        #
        # `external` — единственное исключение, и по НАЗВАННОЙ причине (Д2): у чужого
        # аллокатора измеримого корпуса в этом дереве нет (`task`: `home: []`), сверять
        # нечего. Это не та же причина, что была у `closed` («номера не выдаются»).
        if allocation == "external":
            continue

        retired, grave_err = _graveyard_retired(e)
        if grave_err:
            violations.append(f"ERROR: не смог проверить — {grave_err}")
        else:
            for token, is_numeric, path, lineno, _role in found:
                if is_numeric and int(token) in retired:
                    violations.append(
                        f"ERROR: повторная выдача отменённого номера — {prefix}{token}: файл "
                        f"{path} переиспользует номер, отменённый записью кладбища "
                        f"{e.get('graveyard')}."
                    )

        highwater = e.get("highwater")
        if highwater is not None and (isinstance(highwater, bool)
                                      or not isinstance(highwater, int)):
            # Испорченный ввод РЕДАКТОРА реестра (ADR-069 §3, решение владельца 2026-08-26).
            # До этой ветки нечисловой `highwater` давал `TypeError: '>' not supported between
            # instances of 'int' and 'str'` и трейсбек: отказ громкий, но НЕ названный, а
            # `gate-failure-semantics` знает ровно три названных исхода. Здесь — третий из них
            # («не смог проверить»), и он называет ИМЯ записи и ИМЯ поля: вызывающий чинит
            # реестр, а не читает про сравнение int и str. Д1 расширил достижимость случая с
            # трёх `allocated`-записей на любую, куда поле впишут, — цена названа в
            # Consequences ADR-069 («цена ошибки в реестре растёт»). `bool` отсекается
            # отдельно: `True` — подкласс `int`, и `highwater: yes` сравнилось бы с корпусом
            # как единица, то есть испорченная запись прошла бы проверку МОЛЧА.
            violations.append(
                f"ERROR: не смог проверить — поле `highwater` записи '{ns}' реестра "
                f"{REGISTRY_PATH} прочитано как {highwater!r} ({type(highwater).__name__}), "
                f"а не как целое число: расхождение с корпусом не вычислимо."
            )
        elif highwater is not None:
            corpus_max = max(
                (int(token) for token, is_numeric, _p, _l, _role in found if is_numeric), default=0
            )
            if corpus_max > highwater:
                violations.append(
                    f"ERROR: расхождение реестра '{ns}' — highwater={highwater}, а максимум "
                    f"по корпусу corpus_max={corpus_max}: номер выдан в обход аллокатора."
                )

        # ВТОРОЕ НАПРАВЛЕНИЕ расхождения (DEV-120): номер израсходован волной, а
        # определения в доме нет. Тело вынесено в `_consumed_without_home` (DEV-121) —
        # точек вызова две, вторая стоит в ветке пустого корпуса ступени 8/7 выше.
        # Довод, замеры класса и границы — в докстроке функции.
        v, i = _consumed_without_home(e, found, retired)
        violations.extend(v)
        info_lines.extend(i)

    for line in info_lines:
        print(line)

    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        return 1

    print(f"OK: {len(entries)} реестров проверено, чисто.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
PYEOF
