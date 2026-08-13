#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""validate-content.py — валидатор структуры Gramax-каталога.

Проверяет content/ на соответствие правилам Gramax (см. CLAUDE.md / spec).
Exit codes: 0 — clean; 1 — есть errors; 2 — pyyaml не установлен или плохой путь.

C9/C10 (ADR-014, TPL-37а) — ссылочная целостность: битые ссылки (error) и статьи-сироты
(warning). Архитектура: ADR-014 (Decision Д1-Д5) и её companion-спека (§1 паттерн-таблица,
§2 алгоритм) — путь не приводится литералом здесь намеренно (docs/adr/ вырезается из
public-снапшота публикацией; литеральный путь в этом keep-файле ловится cross-link
гейтом publish-public.sh — тот же класс осторожности, что у run_gate_if_present в
check.sh).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import (
    Issue, MalformedYamlError, issue_from_yaml_error,
    parse_frontmatter, parse_yaml_file, has_placeholder, PLACEHOLDER_RE, require_yaml,
)


def check_property_names(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C4: имена property в frontmatter объявлены в .doc-root.yaml."""
    declared = {p["name"] for p in doc_root.get("properties", []) if isinstance(p, dict) and "name" in p}
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm or not isinstance(fm["properties"], list):
            continue
        for p in fm["properties"]:
            if not isinstance(p, dict) or "name" not in p:
                continue
            name = p["name"]
            if name not in declared:
                issues.append(Issue("error", str(md_path),
                    f"property \"{name}\" не объявлен в .doc-root.yaml"))
    return issues


def check_property_values(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C5: значения property из frontmatter входят в values: (для type: Enum)."""
    enums = {
        p["name"]: set(p.get("values") or [])
        for p in doc_root.get("properties", [])
        if isinstance(p, dict) and p.get("type") == "Enum" and "name" in p
    }
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm or not isinstance(fm["properties"], list):
            continue
        for p in fm["properties"]:
            if not isinstance(p, dict) or "name" not in p or "value" not in p:
                continue
            name = p["name"]
            if name not in enums:
                continue
            values = p["value"] if isinstance(p["value"], list) else [p["value"]]
            for v in values:
                if v not in enums[name]:
                    allowed = sorted(enums[name])
                    issues.append(Issue("error", str(md_path),
                        f"property \"{name}\" имеет значение \"{v}\", не входящее в enum {allowed}"))
    return issues


def check_filter_coverage(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C6: статья объявляет хотя бы один property из filterProperties (warning)."""
    filter_names = set(doc_root.get("filterProperties") or [])
    if not filter_names:
        return []
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm:
            continue
        props = fm.get("properties") or []
        if not isinstance(props, list):
            continue
        declared = {p["name"] for p in props if isinstance(p, dict) and "name" in p}
        if not (declared & filter_names):
            issues.append(Issue("warning", str(md_path),
                f"не объявляет ни одного property из filterProperties {sorted(filter_names)} — фильтр в Gramax не сработает"))
    return issues


def check_placeholders(content_dir: Path) -> list[Issue]:
    """C7: warning про плейсхолдеры в frontmatter."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if has_placeholder(md_path):
            issues.append(Issue("warning", str(md_path),
                "frontmatter содержит плейсхолдер {{...}}; ожидается замена через init.sh"))
    return issues


def check_doc_root_placeholders(content_dir: Path) -> list[Issue]:
    """C7-doc-root: warning, если .doc-root.yaml содержит плейсхолдеры {{...}}."""
    path = content_dir / ".doc-root.yaml"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if PLACEHOLDER_RE.search(text):
        return [Issue("warning", str(path),
            "содержит плейсхолдер {{...}}; ожидается замена через init.sh")]
    return []


def check_index_no_properties(content_dir: Path) -> list[Issue]:
    """C2: _index.md не должен содержать properties:."""
    issues = []
    for index_path in content_dir.rglob("_index.md"):
        try:
            fm = parse_frontmatter(index_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if fm and "properties" in fm:
            issues.append(Issue(
                level="error",
                path=str(index_path),
                message="_index.md не должен иметь properties (раздел не имеет своего типа/статуса)",
            ))
    return issues


def check_object_notation(content_dir: Path) -> list[Issue]:
    """C3: properties в статьях — список dict-ов с ключами name+value."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if not fm or "properties" not in fm:
            continue
        props = fm["properties"]
        if not isinstance(props, list):
            issues.append(Issue("error", str(md_path),
                "properties должен быть списком (получено: " + type(props).__name__ + ")"))
            continue
        for p in props:
            if not isinstance(p, dict):
                issues.append(Issue("error", str(md_path),
                    "элемент properties должен быть dict-ом (получено: " + type(p).__name__ + ")"))
                continue
            keys = set(p.keys())
            if keys != {"name", "value"}:
                # Если ровно один ключ — это плоская нотация.
                if len(keys) == 1:
                    issues.append(Issue("error", str(md_path),
                        f"использует плоскую frontmatter-нотацию ({list(keys)[0]}: ...); требуется object-нотация (- name: X / value: [Y])"))
                else:
                    issues.append(Issue("error", str(md_path),
                        f"элемент properties должен иметь ровно ключи name+value (получено: {sorted(keys)})"))
    return issues


def check_indexes(content_dir: Path) -> list[Issue]:
    """C1: каждая подпапка с .md или вложенными .md содержит _index.md."""
    issues = []
    for d in [content_dir, *sorted(p for p in content_dir.rglob("*") if p.is_dir())]:
        # Пропускаем подпапки без .md (рекурсивно)
        has_md = any(d.rglob("*.md"))
        if not has_md:
            continue
        index_path = d / "_index.md"
        if not index_path.exists():
            issues.append(Issue(
                level="error",
                path=f"{d}/",
                message="missing _index.md (Gramax не покажет раздел в навигации)",
            ))
    return issues


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


# Модульный уровень, рядом с остальными компилированными паттернами файла (например
# _LINK_PATTERNS). Единственное определение "структурной строки" -- C8 и C11 (§3.4) читают
# ОДНУ константу, не два независимых regex (ADR-010 Д2). Известный дефект (TPL-67 -- слеп к
# блочному Gramax {% table %}, код-fence, юникод-рамкам) НЕ чинится этим ADR -- T_S откалиброван
# RES-026 на этом же regex; правка сдвинула бы run-распределение без данных на замену.
HAS_STRUCTURE_RE = re.compile(r"(?m)^\s*\||<view|<note|^#{2,}\s")


def check_bloat(content_dir: Path, threshold: int = 40) -> list[Issue]:
    """C8 -- логика не меняется, только ссылка на модульную HAS_STRUCTURE_RE вместо
    локальной переменной."""
    issues = []
    for index_path in content_dir.rglob("_index.md"):
        body = _strip_frontmatter(index_path.read_text(encoding="utf-8"))
        has_structure = bool(HAS_STRUCTURE_RE.search(body))
        prose = [ln for ln in body.splitlines()
                 if ln.strip() and not ln.lstrip()[:1] in {"#", "|", "-", "*", ">", "<"}]
        if len(prose) > threshold and not has_structure:
            issues.append(Issue("warning", str(index_path),
                f"_index раздут ({len(prose)} строк прозы) без структуры "
                f"(таблиц/<view>/заголовков); добавьте навигацию или сократите"))
    return issues


# ===== C9/C10: ссылочная целостность (ADR-014, spec §1-§2) ==========================

# Паттерн-таблица §1 — данные, не управляющая логика (новый Gramax-тег = новая строка).
# kind: "path" — резолв относительно source.parent; "snippet_id" — резолв в
# <content_dir>/.gramax/snippets/<raw_target>.md (спец-случай, §2 шаг7).
_LINK_PATTERNS: list[tuple[str, re.Pattern]] = [
    # #1/#2: markdown link/image. Классы отрицают \n намеренно: без этого на
    # несбалансированной скобке (markdown-таблица, пример кода) матч убегает через
    # несколько строк и подставляет мусор в сообщение об ошибке.
    ("path", re.compile(r'!?\[[^\]\n]*\]\(([^)\n]+)\)')),      # #1/#2: markdown link/image
    ("path", re.compile(r'<mermaid\s+[^>]*?path="([^"]+)"')),   # #3
    ("path", re.compile(r'<image\s+[^>]*?src="([^"]+)"')),      # #4
    ("path", re.compile(r'<openapi\s+[^>]*?src="([^"]+)"')),    # #5
    ("snippet_id", re.compile(r'<snippet\s+[^>]*?id="([^"]+)"')),  # #6
    ("path", re.compile(r'\[drawio:([^:\]]+):[^\]]*\]')),       # #7 (bracket); #8 legacy — покрыт #1
]

# Внешние цели (http/https/mailto/tel/protocol-relative //) — не сканируются, сети нет
# (ADR-014 Д1/Д5, спека §1).
_EXTERNAL_RE = re.compile(r'^(?:[a-z][a-z0-9+.\-]*:|//)', re.IGNORECASE)

# Забор код-блока: до 3 пробелов отступа, затем >= 3 бэктиков или тильд, затем info-строка.
_FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
# Inline-код: пробег из N бэктиков, содержимое, закрывающий пробег той же длины. Намеренно
# в пределах одной строки: непарный бэктик в прозе иначе съел бы всё до следующего бэктика
# где-то ниже по файлу и замаскировал бы настоящие ссылки между ними.
_INLINE_CODE_RE = re.compile(r'(`+)([^\n]+?)\1')


def _mask_code(text: str) -> str:
    """Заменяет код (fenced-блоки и inline) пробелами, сохраняя длину строк и их число.

    Статья, документирующая синтаксис Gramax-тега, содержит примеры вида
    `<mermaid path="./file.mermaid"/>` как иллюстрации, а не как ссылки. Без этой маски
    C9 требует существования файла из примера (ложный error), а C10 засчитывает пример
    markdown-ссылки входящей ссылкой и «отбеливает» настоящую статью-сироту.

    Маскирование заменой, не вырезанием: смещения в тексте сохраняются, поэтому соседний
    с блоком настоящий линк находится там же, где и до маски.
    """
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in text.split("\n"):
        m = _FENCE_RE.match(line)
        if fence_char is None:
            if m:
                fence_char, fence_len = m.group(1)[0], len(m.group(1))
                out.append(" " * len(line))
            else:
                out.append(line)
            continue
        # Внутри блока: закрывает только забор того же символа, не короче открывающего и
        # без info-строки. Вложенный забор короче внешнего остаётся содержимым.
        if m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len \
                and not m.group(2).strip():
            fence_char, fence_len = None, 0
        out.append(" " * len(line))
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), "\n".join(out))


@dataclass
class Reference:
    source: Path        # файл, где найдена ссылка
    raw_target: str     # текст внутри скобок/атрибута, как в файле (до fragment/<>-очистки)
    kind: str           # "path" | "snippet_id"
    resolved: Path | None  # None — не должно случаться (обе ветки §2 шаг6/7 его строят)


def _collect_references(content_dir: Path) -> list[Reference]:
    """§2: единый проход по content_dir.rglob("*.md"), даёт список Reference для C9 и C10.

    Guard Д2: файлы с has_placeholder() == True пропускаются целиком — их исходящие
    ссылки не проверяются вовсе (ни error, ни warning). Файл остаётся видимым в C1-C8 и
    как ЦЕЛЬ входящих ссылок (C10) — guard касается только его СОБСТВЕННЫХ исходящих.

    Код в тексте маскируется до применения паттернов (_mask_code): пример синтаксиса —
    не ссылка ни для C9, ни для C10.
    """
    refs: list[Reference] = []
    for md_path in sorted(content_dir.rglob("*.md")):
        if has_placeholder(md_path):
            continue
        text = _mask_code(md_path.read_text(encoding="utf-8"))
        for kind, pattern in _LINK_PATTERNS:
            for m in pattern.finditer(text):
                raw_target = m.group(1)
                # §2 шаг4: сначала #fragment, потом обёртка <...> — в этом порядке.
                target = raw_target.split("#", 1)[0]
                target = target.strip("<>")
                if not target:
                    continue  # самоссылка на якорь — уже отфильтровано
                if _EXTERNAL_RE.match(target):
                    continue
                if kind == "path":
                    resolved = (md_path.parent / target).resolve()
                else:  # "snippet_id" — резолв по raw_target (§2 шаг7), не по target
                    resolved = (content_dir / ".gramax" / "snippets" / f"{raw_target}.md").resolve()
                refs.append(Reference(md_path, raw_target, kind, resolved))
    return refs


def check_broken_links(content_dir: Path) -> list[Issue]:
    """C9: ссылка, не резолвящаяся на диске, — error (факт, не суждение)."""
    issues = []
    for ref in _collect_references(content_dir):
        if ref.resolved is not None and not ref.resolved.exists():
            issues.append(Issue("error", str(ref.source),
                f"битая ссылка на \"{ref.raw_target}\" — {ref.resolved} не существует"))
    return issues


def check_orphans(content_dir: Path) -> list[Issue]:
    """C10: .md-статья (не _index.md) с нулевой входящей степенью — warning.

    In-degree, не BFS от корня (Д3). Self-ссылка не засчитывается как входящая (не
    "отбеливает" орфана), но и не отнимается — инициализация нулём на файл, не декремент.
    Сравнение путей — обе стороны через .resolve() (ловушка прототипа SA, ADR-014 spec §5):
    сравнение resolved-absolute с ключами относительных путей ложно помечало бы всё
    orphan.
    """
    incoming: dict[Path, int] = {}
    display: dict[Path, Path] = {}
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        key = md_path.resolve()
        incoming[key] = 0
        display[key] = md_path

    for ref in _collect_references(content_dir):
        if ref.resolved is None:
            continue
        if ref.resolved == ref.source.resolve():
            continue  # self-ссылка не засчитывается как входящая
        if ref.resolved in incoming:
            incoming[ref.resolved] += 1

    return [
        Issue("warning", str(display[key]),
              "статья без входящих ссылок из каталога — проверьте, что путь к ней "
              "передаётся явно (PM/pm-review), иначе она не будет найдена")
        for key, count in incoming.items() if count == 0
    ]


# ===== C11/C12: детектор объём+структура content/ (ADR-018, PT-EPIC-20) ==============

def _strip_leading_frontmatter(content: str) -> str:
    """Дословная копия check-adr-line-limit.py::_strip_leading_frontmatter (ADR-013 Д3).
    Дублируется здесь (не импортируется): check-adr-line-limit.py НЕ в поставке потомку
    (.publishignore) -- validate-content.py обязан работать независимо от него.
    Используется ТОЛЬКО для T (body_lines, количественный признак) -- RES-025-B/BA-каталог
    калибровали T именно этой функцией, не _strip_frontmatter ниже."""
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    return content[end + 5:]


# _strip_frontmatter(text) -- уже существует выше (используется C8). Используется для T_S
# (longest_run_without_structure) -- BA-определение дословно говорит "_strip_frontmatter из
# check_bloat", не _strip_leading_frontmatter. Не заменять один на другой в C11 -- разные
# функции срезают по-разному на файлах с "---" внутри тела (RES-026 калибровала T_S на
# _strip_frontmatter конкретно).


def _longest_run_without_structure(body: str) -> int:
    """RES-026 определение: самый длинный участок ПОДРЯД идущих строк тела, ни одна из
    которых не матчит HAS_STRUCTURE_RE ПОСТРОЧНО (не re.search по всему телу разом --
    иначе один заголовок в конце файла "обелил" бы всё тело, как C8 уже делает для generic
    случая -- этот признак намеренно другой, RES-026/BA-027b)."""
    longest = current = 0
    for line in body.splitlines():
        if HAS_STRUCTURE_RE.search(line):
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _type_content_value(fm: dict | None) -> str | None:
    """Первое значение property "Тип контента" (object-нотация, value: [X] или value: X),
    либо None -- отсутствие frontmatter/properties/самого property/пустого value трактуются
    одинаково. Общий хелпер C11 и C12."""
    if not fm:
        return None
    props = fm.get("properties")
    if not isinstance(props, list):
        return None
    for p in props:
        if isinstance(p, dict) and p.get("name") == "Тип контента":
            v = p.get("value")
            if isinstance(v, list):
                return v[0] if v else None
            return v or None
    return None


def _repo_relative(md_path: Path, content_dir: Path) -> str:
    """Repo-root-relative, "/"-separated путь для сравнения с sizeBudgetGrandfathered ("path:").
    ВНИМАНИЕ (edge case для QA, §9): опирается на то, что content_dir называется буквально
    "content" в реальном дереве; тестовая фикстура вольна называть свой content_dir иначе --
    тогда путь в фикстурном sizeBudgetGrandfathered обязан использовать ТОТ ЖЕ leaf-компонент,
    не литерал "content/..."."""
    return content_dir.name + "/" + str(md_path.relative_to(content_dir)).replace("\\", "/")


def check_size_budget(content_dir: Path, doc_root: dict) -> list[Issue]:
    """C11 (ADR-018): сигнал -- только при совместном срабатывании (BR-004)."""
    entries = {
        b["type"]: b
        for b in (doc_root.get("sizeBudgets") or [])
        if isinstance(b, dict) and b.get("type") and b.get("thresholdLines") is not None
    }
    if not entries:
        return []
    grandfathered = {
        g["path"]: g["ceiling"]
        for g in (doc_root.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3 (issue_from_yaml_error) -- не дублируем
        type_value = _type_content_value(fm)
        if type_value not in entries:
            continue
        budget = entries[type_value]
        threshold = budget["thresholdLines"]
        raw = md_path.read_text(encoding="utf-8")
        lines = _strip_leading_frontmatter(raw).count("\n")
        if lines <= threshold:
            continue  # BR-004: количественный не сработал -- тихий проход
        rel = _repo_relative(md_path, content_dir)
        ceiling = grandfathered.get(rel)
        quality = budget.get("quality")
        severity = budget.get("severity", "warn")
        level = "error" if severity == "block" else "warning"

        if quality == "companion-spec":
            if any(content_dir.rglob(f"{md_path.stem}-spec.md")):
                continue  # качественный признак не провален -- тихий проход
            if ceiling is not None:
                if lines <= ceiling:
                    issues.append(Issue("warning", str(md_path),
                        f"грандфазер: {lines} строк тела <= замороженного потолка {ceiling} "
                        f"({rel}, ADR-018 Д5) -- не блокирует"))
                else:
                    issues.append(Issue("error", str(md_path),
                        f"грандфазер-потолок превышен: {lines} строк тела > {ceiling} ({rel}). "
                        f"Верни рост, или подними ceiling явной правкой sizeBudgetGrandfathered "
                        f"в этом же коммите (ADR-018 Д5, прецедент GRANDFATHERED, ADR-013 Д1)."))
                continue
            issues.append(Issue(level, str(md_path),
                f"тело {lines} строк > T={threshold} (Тип контента: {type_value}); "
                f"companion-спека {md_path.stem}-spec.md не найдена. "
                f"P1: расщепи decision/деталь -- вынеси процедурную детализацию в "
                f"{md_path.stem}-spec.md (kind: reference, без лимита строк) -- ADR-013 Д2, ADR-018."))
            continue

        # quality == "longest_run_without_structure"
        run = _longest_run_without_structure(_strip_frontmatter(raw))
        quality_threshold = budget.get("qualityThreshold")
        if quality_threshold is None or run < quality_threshold:
            continue  # тихий проход
        issues.append(Issue(level, str(md_path),
            f"тело {lines} строк > T={threshold} (Тип контента: {type_value}), и самый длинный "
            f"участок без структуры (заголовок/таблица/<view>/<note>) -- {run} строк >= "
            f"T_S={quality_threshold}. P3: сократи содержание (не разметку); "
            f"P4: добавь структуру -- ADR-018."))
    return issues


GATES_FILENAME = ".nauta-gates.yaml"


def _load_gates(content_dir: Path) -> tuple[dict, list[Issue]]:
    """ADR-031: конфигурация гейтов шаблона из корня проекта.

    Корень — родитель `content_dir`. Отсутствие файла и его нечитаемость
    различаются явно, как в блоке чтения `.doc-root.yaml` (ADR-007 Д5):
    нет файла -> ({}, []) — конфигурации нет, потребители законно тривиальны;
    малформенный -> ({}, [error]) — «не смог прочитать» != «нарушений нет».
    """
    path = content_dir.parent / GATES_FILENAME
    if not path.is_file():
        return {}, []
    try:
        return parse_yaml_file(path) or {}, []
    except MalformedYamlError as e:
        return {}, [issue_from_yaml_error(e)]


def check_type_content_declared(content_dir: Path) -> list[Issue]:
    """C12 (ADR-018 Д6, TPL-68): каждая не-_index.md статья обязана нести непустое свойство
    "Тип контента". Ловит класс, невидимый C3-C6: parse_frontmatter -> None для файла без
    ведущего "---" блока вовсе (ADR-007 Д6 -- None не значит "сломан", но и не значит "ОК")."""
    issues = []
    for md_path in content_dir.rglob("*.md"):
        if md_path.name == "_index.md":
            continue
        if has_placeholder(md_path):
            continue
        try:
            fm = parse_frontmatter(md_path)
        except MalformedYamlError:
            continue  # уже отражено C3
        if _type_content_value(fm) is None:
            issues.append(Issue("error", str(md_path),
                'статья не объявляет непустое свойство "Тип контента" '
                '(properties: - name: Тип контента / value: [...]) -- TPL-68, ADR-018 Д6'))
    return issues


# ===== C13/C14: гейт объёма кода (.py/.groovy) и корневого промт-слоя (ADR-032, PT-EPIC-27) ====

GIT_OK, GIT_NO_BINARY, GIT_NO_REPO = "ok", "no-binary", "no-repo"


class _GitUnavailable(Exception):
    """git отсутствует в PATH -- поднимается `_git_ls_files`, перехватывается
    `check_code_size_budget` и превращается в громкий Issue(error) (ADR-007 Д1: "не
    смог проверить" != "0 нарушений"), не в тихий []."""


def _git_probe(repo_root: Path) -> str:
    """ADR-032-spec §3.1, симметрично `check-status-drift.py::_git_probe`. Три исхода:
    GIT_OK -- рабочее дерево git; GIT_NO_REPO -- команда завершилась ошибкой (не рабочее
    дерево, напр. SNAP_DIR publish-public.sh, `git archive | tar -x`, без `.git`);
    GIT_NO_BINARY -- сам `git` не найден в PATH."""
    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        return GIT_NO_BINARY
    except subprocess.CalledProcessError:
        return GIT_NO_REPO
    return GIT_OK


def _git_ls_files(repo_root: Path, patterns: list[str]) -> list[str] | None:
    """`git ls-files`, не `Path.rglob` (Д3 ADR-032 -- та же tracked-популяция, что
    измеряла RES-030; `.gitignore`-исключения наследуются даром). None -- GIT_NO_REPO,
    легитимный тихий skip (тот же посадочный принцип, что `_load_gates` на отсутствующем
    `.nauta-gates.yaml`, ADR-031 Д3). GIT_NO_BINARY поднимается как исключение --
    вызывающая сторона решает, во что его превратить (не «0 нарушений»)."""
    probe = _git_probe(repo_root)
    if probe == GIT_NO_REPO:
        return None
    if probe == GIT_NO_BINARY:
        raise _GitUnavailable()
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--"] + patterns,
        capture_output=True, text=True, check=True,
    )
    return [ln for ln in r.stdout.splitlines() if ln]


# RES-030 §B буквально, с исправлением (ADR-032 §7): FR-002 BA-048 транскрипционно
# потеряла пятую альтернативу Groovy `^public class ` при переносе из RES-030 -- её
# потеря сливает соседние сегменты в один длиннее (риск в сторону БЛОКА, не тихого
# прохода), не наоборот.
PY_DECL_RE = re.compile(r'^(?:class |def |async def )')
GROOVY_DECL_RE = re.compile(r'^(?:class |abstract class |final class |public class |def )')


def _longest_declaration_or_file(body: str, decl_re: re.Pattern) -> int:
    """FR-002 BA-048: анкеры -- строки без отступа, начинающиеся с шаблона декларации.
    Длина самого длинного сегмента между соседними анкерами (и от последнего анкера до
    EOF). Ноль анкеров (script-style, 42% Groovy-корпуса RES-030) -- декларация := длина
    файла целиком: "класс и файл -- один и тот же объект" (FR-002, AC-003)."""
    lines = body.splitlines()
    anchors = [i for i, ln in enumerate(lines) if decl_re.match(ln)]
    if not anchors:
        return len(lines)
    anchors.append(len(lines))
    return max(b - a for a, b in zip(anchors, anchors[1:]))


# FR-004 BA-048, буквально -- `tests`/`test`-сегмент пути ИЛИ имя матчит один из 4
# суффиксных паттернов (`*Spec.*` -- Spock-конвенция Groovy).
_TEST_NAME_RE = (
    re.compile(r'^test_'),         # test_*
    re.compile(r'_test\.[^.]+$'),  # *_test.ext
    re.compile(r'Test\.[^.]+$'),   # *Test.ext
    re.compile(r'Spec\.[^.]+$'),   # *Spec.ext (Spock, Groovy)
)


def _is_test_file(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    if any(seg in ("tests", "test") for seg in parts[:-1]):
        return True
    name = parts[-1]
    return any(p.search(name) for p in _TEST_NAME_RE)


def check_code_size_budget(repo_root: Path, gates: dict) -> list[Issue]:
    """C13 (ADR-032): пара "строки файла + длиннейшая top-level декларация" для
    `.py`/`.groovy`, тот же контракт BR-004, что уже несёт C11 для content/. Перечисление
    файлов -- `git ls-files` (Д3), не `Path.rglob`. Отсутствие `codeSizeBudgets` в
    конфигурации -- легитимный тихий skip (симметрично C11)."""
    entries = {
        (b["extension"], b["kind"]): b
        for b in (gates.get("codeSizeBudgets") or [])
        if isinstance(b, dict) and b.get("extension") and b.get("kind")
           and b.get("thresholdLines") is not None
    }
    if not entries:
        return []
    extensions = sorted({ext for ext, _ in entries})
    try:
        files = _git_ls_files(repo_root, [f"*{e}" for e in extensions])
    except _GitUnavailable:
        return [Issue("error", str(repo_root),
            "git недоступен в PATH -- код-гейт (C13) не проверен, это НЕ \"0 нарушений\" "
            "(ADR-007 Д1)")]
    if files is None:  # GIT_NO_REPO -- напр. SNAP_DIR publish-public.sh (git archive, без .git)
        return []
    grandfathered = {
        g["path"]: g["ceiling"] for g in (gates.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    issues = []
    for rel in files:
        ext = "." + rel.rsplit(".", 1)[-1] if "." in rel else ""
        kind = "test" if _is_test_file(rel) else "prod"
        budget = entries.get((ext, kind))
        if budget is None:
            continue  # расширение/kind без записи -- не гейтится (FR-006, напр. .sh)
        path = repo_root / rel
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # нечитаемый файл -- тихий skip, не выдумываем сигнал (Д4 ADR-032)
        lines = raw.count("\n")
        threshold = budget["thresholdLines"]
        if lines <= threshold:
            continue  # BR-003/BR-004: количественный признак не сработал
        decl_re = PY_DECL_RE if ext == ".py" else GROOVY_DECL_RE
        decl_len = _longest_declaration_or_file(raw, decl_re)
        decl_threshold = budget["qualityThreshold"]
        if decl_len < decl_threshold:
            continue  # тихий проход -- контейнер (BR-003, пример: validate-profile.py)
        ceiling = grandfathered.get(rel)
        severity = budget.get("severity", "block")
        level = "error" if severity == "block" else "warning"
        if ceiling is not None:
            if lines <= ceiling:
                issues.append(Issue("warning", str(path),
                    f"грандфазер: {lines} строк <= замороженного потолка {ceiling} "
                    f"({rel}, ADR-032 Д7, ADR-018 Д5) -- не блокирует"))
            else:
                issues.append(Issue("error", str(path),
                    f"грандфазер-потолок превышен: {lines} строк > {ceiling} ({rel}). "
                    f"Разбей декларацию, верни рост, или подними ceiling явной правкой "
                    f"sizeBudgetGrandfathered в этом же коммите (ADR-032 Д7, ADR-018 Д5)."))
            continue
        issues.append(Issue(level, str(path),
            f"{rel}: {lines} строк ({kind}) > T={threshold}, самая длинная top-level "
            f"декларация -- {decl_len} строк >= T_S={decl_threshold}. Разбей декларацию на "
            f"части, либо заведи sizeBudgetGrandfathered-запись (path: \"{rel}\") тем же "
            f"коммитом (ADR-032, ADR-018 Д5)."))
    return issues


PROMPT_LAYER_GRANDFATHER_KEY = "CLAUDE.md+AGENTS.md"
PROMPT_LAYER_FILES = ("CLAUDE.md", "AGENTS.md")


def check_prompt_layer_size_budget(repo_root: Path, gates: dict) -> list[Issue]:
    """C14 (ADR-032): корневой промт-слой -- СУММА строк `CLAUDE.md`+`AGENTS.md`, один
    количественный признак без пары (FR-008 -- контекстное окно тратится на длину
    независимо от структуры, второй признак здесь нечего страховать). Отсутствующий файл
    пары даёт 0 к сумме (FR-007), не ошибку. Не читает git вовсе (Д8 ADR-032) -- ловит
    рост промт-слоя и на снапшоте `publish-public.sh` без `.git`."""
    budget = gates.get("promptLayerSizeBudget")
    if not isinstance(budget, dict) or budget.get("thresholdLines") is None:
        return []
    counts = {}
    for name in PROMPT_LAYER_FILES:
        p = repo_root / name
        try:
            counts[name] = p.read_text(encoding="utf-8").count("\n") if p.is_file() else 0
        except (OSError, UnicodeDecodeError):
            counts[name] = 0  # нечитаемый -- 0 к сумме, симметрично отсутствующему (FR-007)
    total = sum(counts.values())
    threshold = budget["thresholdLines"]
    if total <= threshold:
        return []
    grandfathered = {
        g["path"]: g["ceiling"] for g in (gates.get("sizeBudgetGrandfathered") or [])
        if isinstance(g, dict) and "path" in g and "ceiling" in g
    }
    ceiling = grandfathered.get(PROMPT_LAYER_GRANDFATHER_KEY)
    severity = budget.get("severity", "block")
    level = "error" if severity == "block" else "warning"
    detail = "+".join(f"{n}={c}" for n, c in counts.items())
    if ceiling is not None:
        if total <= ceiling:
            return [Issue("warning", PROMPT_LAYER_GRANDFATHER_KEY,
                f"грандфазер: сумма {total} ({detail}) <= замороженного потолка {ceiling} "
                f"(ADR-032 Д7) -- не блокирует")]
        return [Issue("error", PROMPT_LAYER_GRANDFATHER_KEY,
            f"грандфазер-потолок превышен: сумма {total} ({detail}) > {ceiling}. Сократи "
            f"объём одного из файлов, верни рост, или подними ceiling явной правкой "
            f"sizeBudgetGrandfathered (path: \"{PROMPT_LAYER_GRANDFATHER_KEY}\") тем же "
            f"коммитом (ADR-032 Д7).")]
    return [Issue(level, PROMPT_LAYER_GRANDFATHER_KEY,
        f"сумма строк {detail} = {total} > T={threshold} (корневой промт-слой, FR-008). "
        f"Сократи объём одного из файлов, либо заведи sizeBudgetGrandfathered-запись "
        f"(path: \"{PROMPT_LAYER_GRANDFATHER_KEY}\") тем же коммитом (ADR-032).")]


def main(argv: list[str]) -> int:
    require_yaml()
    parser = argparse.ArgumentParser(description="Validate Gramax content/ structure")
    parser.add_argument("content_dir", nargs="?", default="content",
                        help="Path to content directory (default: content)")
    args = parser.parse_args(argv)

    content_dir = Path(args.content_dir)
    if not content_dir.is_dir():
        print(f"ERROR: not a directory: {content_dir}", file=sys.stderr)
        return 2

    issues = []
    issues.extend(check_indexes(content_dir))
    issues.extend(check_bloat(content_dir))
    issues.extend(check_broken_links(content_dir))  # C9 (ADR-014)
    issues.extend(check_orphans(content_dir))        # C10 (ADR-014)
    issues.extend(check_index_no_properties(content_dir))
    issues.extend(check_object_notation(content_dir))
    # Три проверки ниже читают декларацию из .doc-root.yaml. Исходы «файла нет» ({} —
    # декларации нет, проверки законно тривиальны) и «файл нечитаем» (error) различаются
    # явно: прежнее `or {}` их схлопывало, и прогон на пустом словаре либо рапортовал
    # «чисто», либо заливал вывод ложными «property не объявлен» (ADR-007 Д5, AC-01-11).
    try:
        doc_root = parse_yaml_file(content_dir / ".doc-root.yaml")
    except MalformedYamlError as e:
        issues.append(issue_from_yaml_error(e))
        doc_root = None
    if doc_root is not None:
        issues.extend(check_property_names(content_dir, doc_root))
        issues.extend(check_property_values(content_dir, doc_root))
        issues.extend(check_filter_coverage(content_dir, doc_root))
    # C11 (ADR-018) переехал на собственный носитель (ADR-031): .doc-root.yaml
    # принадлежит Gramax и конфигурацию шаблона больше не несёт.
    gates, gates_issues = _load_gates(content_dir)
    issues.extend(gates_issues)
    issues.extend(check_size_budget(content_dir, gates))
    # repo_root -- уже установленная конвенция _load_gates (ADR-031 Д1), C13/C14
    # переиспользуют тот же якорь, не вводят второй способ найти корень (ADR-032 §5).
    repo_root = content_dir.parent
    issues.extend(check_code_size_budget(repo_root, gates))          # C13, новое (ADR-032)
    issues.extend(check_prompt_layer_size_budget(repo_root, gates))  # C14, новое (ADR-032)
    issues.extend(check_placeholders(content_dir))
    issues.extend(check_doc_root_placeholders(content_dir))
    issues.extend(check_type_content_declared(content_dir))          # C12, новое (ADR-018 Д6)

    # Один битый файл видят несколько независимых rglob-проходов. Схлопываем ДО подсчёта:
    # `Errors: N` считается из списка, а не на печати (ADR-007 Д5).
    seen: set[str] = set()
    deduped: list[Issue] = []
    for issue in issues:
        if issue.dedupe_key:
            if issue.dedupe_key in seen:
                continue
            seen.add(issue.dedupe_key)
        deduped.append(issue)
    issues = deduped

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    for issue in sorted(issues, key=lambda i: (i.path, i.level)):
        print(f"{issue.path}: {issue.message}  [{issue.level}]")

    md_count = sum(1 for _ in content_dir.rglob("*.md"))
    if not issues:
        print(f"{content_dir}/: OK ({md_count} файлов проверены)")

    print(f"\nErrors: {len(errors)} | Warnings: {len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
