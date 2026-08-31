#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""Shared utilities for validate-content.py and validate-profile.py."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")

try:
    import yaml  # PyYAML
except ImportError:
    yaml = None


def require_yaml() -> None:
    """Exit code 2 если PyYAML не установлен."""
    if yaml is None:
        print("ERROR: PyYAML не установлен. Установи: pip install pyyaml", file=sys.stderr)
        sys.exit(2)


@dataclass
class Issue:
    level: str  # "error" | "warning"
    path: str
    message: str
    # Непустой ключ схлопывает повторы одного факта, увиденные несколькими проходами
    # (один битый .md видят четыре rglob'а validate-content.py). Issue без ключа
    # дедупликация не трогает — прежний вывод не меняется (ADR-007 Д5).
    dedupe_key: str | None = None


class MalformedYamlError(Exception):
    """Вход существует и заявлен как YAML, но не парсится.

    Исход «не смог проверить» — отличается от «нечего проверять» (ADR-007 Д1).
    Механизм — исключение, а не sentinel: все вызывающие написаны как
    `if not fm: continue` и falsy-значение проглотили бы молча (ADR-007 Д5).

    Поля: .path — Path проблемного файла; .cause — исходное исключение PyYAML;
    .reason — причина, свёрнутая в одну строку; .message — текст для Issue.
    str(e) == f"{path}: {message}".
    """

    def __init__(self, path: Path, cause: Exception, what: str = "YAML") -> None:
        self.path = Path(path)
        self.cause = cause
        # format_issues печатает Issue одной строкой с суффиксом [error]; текст PyYAML
        # многострочен. Инвариант: "\n" not in message (NFR-002).
        self.reason = " ".join(str(cause).split())
        self.message = f"malformed {what} — {self.reason}"
        super().__init__(f"{self.path}: {self.message}")


def issue_from_yaml_error(e: MalformedYamlError) -> Issue:
    """Issue(level=error) с путём и причиной; ключ схлопывает повторы по одному файлу."""
    return Issue("error", str(e.path), e.message, dedupe_key=f"yaml:{e.path}")


def substitute_placeholders(text: str) -> str:
    """Нормализация входа перед парсингом: `{{NAME}}` → `PLACEHOLDER_NAME`.

    Правило «The placeholder precedence rule» в его действующей форме (ADR-007 Д5, редакция
    2026-07-27): подставить, затем парсить. Освобождённым остаётся ровно один класс
    входов — файл, который после подстановки парсится, то есть ломался ТОЛЬКО
    плейсхолдером. Всё, что не распарсилось после подстановки, — сломано.

    Подстановка — plain-строкой без кавычек: кавычки внутри значения с окружающим
    текстом (`title: "PLACEHOLDER" — rest`) сами ломают YAML.

    Одна реализация на оба парсера намеренно: два экземпляра одного правила — тот же
    источник расхождения, из-за которого carve-out и разъехался с `parse_yaml_file`.
    """
    return PLACEHOLDER_RE.sub(lambda m: f"PLACEHOLDER_{m.group(0)[2:-2]}", text)


def parse_frontmatter(file_path: Path) -> dict | None:
    """Извлекает YAML-frontmatter между `---` из markdown-файла.

    Плейсхолдеры подставляются ДО парсинга (`substitute_placeholders`), разбирается
    подставленный текст. Поэтому неинициализированный файл — обычный dict с
    `PLACEHOLDER_*`-значениями, а не особый исход, и любая ошибка после подстановки
    настоящая (ADR-007 Д5, редакция 2026-07-27).

    Исходы:
      dict — блок сформирован и распарсен (пустой блок → `{}`);
      None — frontmatter не заявлен. Случаев два, и оба намеренные (ADR-007 Д6):
             (1) текст не начинается с `---`;
             (2) блок открыт, но **не закрыт** вторым разделителем — блок не образован,
             парсить нечего. Это не «сломан»: `.md`, начинающийся с горизонтальной черты,
             — легальная разметка, и эвристика «черта или frontmatter» дала бы
             false-positive. Не «чинить» без нового ADR.

    Raises:
      MalformedYamlError — блок сформирован, но не парсится ПОСЛЕ подстановки.
             Файл, невалидный только из-за `{{...}}`, сюда не попадает: подстановка
             его чинит. Диагностика такого файла — warning `check_placeholders`.
    """
    require_yaml()
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    # Подстановка — по телу блока, а не по всему файлу: парсер разбирает только тело,
    # а основной текст статьи ему не принадлежит.
    body = substitute_placeholders(parts[1])
    try:
        return yaml.safe_load(body) or {}
    except yaml.YAMLError as e:
        raise MalformedYamlError(file_path, e, "YAML frontmatter") from e


def parse_yaml_file(path: Path) -> dict:
    """Читает YAML-файл, подставляя плейсхолдеры `{{...}}` перед парсингом.

    Исходы:
      {}   — файла нет (путь называет место декларации, а не саму декларацию —
             ADR-007 Д1), либо файл пуст / содержит только комментарии;
      dict — распарсен.

    Raises:
      MalformedYamlError — файл существует и не парсится **после** подстановки
             плейсхолдеров. Файл, невалидный только из-за `{{...}}`, сюда не попадает:
             подстановка идёт до парсинга, поэтому правило приоритета плейсхолдера
             (ADR-007 Д5) выполняется здесь само собой.
    """
    require_yaml()
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    # Подменяем плейсхолдеры на безопасные строки (для шаблонов до init.sh).
    substituted = substitute_placeholders(text)
    try:
        return yaml.safe_load(substituted) or {}
    except yaml.YAMLError as e:
        raise MalformedYamlError(path, e, "YAML") from e


def has_placeholder(file_path: Path) -> bool:
    """True если frontmatter содержит литерал {{...}}."""
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    return bool(PLACEHOLDER_RE.search(parts[1]))


def format_issues(issues: list[Issue]) -> str:
    """Форматирует список Issue для печати."""
    return "\n".join(
        f"{i.path}: {i.message}  [{i.level}]"
        for i in sorted(issues, key=lambda x: (x.path, x.level))
    )


#: Каноническое написание типа property со списком значений. Регистрозависимо НАМЕРЕННО:
#: Gramax резолвит `Enum` в select со списком `values:`, а строчный `enum` — ни во что
#: (ADR-047, DEV-118, ишью #9), и первое сохранение статьи через редактор пишет
#: `value: [null]`, теряя выбранное владельцем. Принять неканоническое написание молча
#: значило бы спрятать эту поломку у потребителя — поэтому оно даёт error, а не тишину.
ENUM_PROPERTY_TYPE = "Enum"
#: Лечение — дословно из схемы Gramax (скилл `gramax:writer` объявлен authoritative-источником
#: соглашений; см. докстринг `tests/test_dev118_profile_property_type_case.py`). Путь в кэше
#: плагина в сообщение НЕ кладётся: он непортативен, канон дерева — ADR-047/DEV-118.
ENUM_TREATMENT = "использовать `type: Enum` со строковым массивом `values:`"
#: Атрибуция даётся РОВНО форме `type: select` + `values: [{name: X}]` — той, которую схема
#: Gramax называет экспериментальной и не рекомендованной. На любом другом написании подсказка
#: про select была бы ложной атрибуцией, а не помощью (граница предмета DEV-119, ишью #8).
_EXPERIMENTAL_SELECT = "select"


def _noncanonical_type_message(name: str, ptype: object, raw: object) -> str:
    """Форма прецедента DEV-119: что найдено — откуда взялось — лечение дословно."""
    found = (f'property "{name}": `type: {ptype!r}` — не каноническое '
             f"`{ENUM_PROPERTY_TYPE}`, и объявленный `values:` не применяет ни одна проверка")
    mapping_values = isinstance(raw, list) and any(isinstance(i, dict) for i in raw)
    if str(ptype).strip().lower() == _EXPERIMENTAL_SELECT or mapping_values:
        origin = ("; так пишет экспериментальный синтаксис Gramax `type: select` с "
                  "`values: [{name: X}]` — схемой Gramax он объявлен не рекомендованным")
    else:
        origin = ("; Gramax резолвит в select только каноническое написание, а прочие — ни во "
                  "что, и первое сохранение статьи через редактор пишет `value: [null]`")
    return f"{found}{origin}. Лечение: {ENUM_TREATMENT} (канон дерева — ADR-047, DEV-118)"


def enum_property_values(doc_root: dict, carrier: str) -> tuple[dict[str, set[str]], list[Issue]]:
    """C5 (ишью #11): выборка property со списком значений + нормализация форм `values:`.

    Три исхода вместо прежних двух (ADR-007 Д1 — «зелёное не означает не проверялось»):
      * `type: Enum` и все элементы `values:` разобраны — property в выборке;
      * `values:` объявлен непустым, а тип не канон — error: объявленный список не
        применяет ни одна проверка, и Gramax его не резолвит (ADR-047, DEV-118);
      * форма `values:` или её элемента не разобрана — error, и property исключается из
        выборки: честное «не смог проверить» без второго, ложного класса находок.
    `values:` нет — законное молчание (`type: String`, свободный текст).

    Элемент нормализуется: строка — сама собой; отображение с ключом `name` — значение
    `name` (форма Gramax `- name: X`). Множество допустимых значений это НЕ расширяет —
    только снимает `TypeError: unhashable type: 'dict'` прежнего `set(p.get("values"))`,
    достижимый на живом каталоге потребителя.
    """
    enums: dict[str, set[str]] = {}
    issues: list[Issue] = []
    for p in doc_root.get("properties") or []:
        if not isinstance(p, dict) or "name" not in p:
            continue
        name, raw = p["name"], p.get("values")
        if not raw:
            continue
        if p.get("type") != ENUM_PROPERTY_TYPE:
            issues.append(Issue("error", carrier,
                _noncanonical_type_message(name, p.get("type"), raw)))
            continue
        if not isinstance(raw, list):
            issues.append(Issue("error", carrier,
                f'property "{name}": `values:` задан не списком, а {type(raw).__name__} — '
                "форма не разобрана, проверка значений по этому property не выполнялась "
                f"(ADR-007 Д1). Лечение: {ENUM_TREATMENT}"))
            continue
        values: set[str] = set()
        unparsed = False
        for item in raw:
            if isinstance(item, str):
                values.add(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                values.add(item["name"])
            else:
                unparsed = True
                issues.append(Issue("error", carrier,
                    f'property "{name}": элемент `values:` формы {type(item).__name__} '
                    f"({item!r}) — ни строка, ни отображение с ключом `name`; проверка "
                    f"значений по этому property не выполнялась (ADR-007 Д1). "
                    f"Лечение: {ENUM_TREATMENT}"))
        if not unparsed:
            enums[name] = values
    return enums, issues


# Забор код-блока: до 3 пробелов отступа, затем >= 3 бэктиков или тильд, затем info-строка.
_FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
# Inline-код: пробег из N бэктиков, содержимое, закрывающий пробег той же длины. Намеренно
# в пределах одной строки: непарный бэктик в прозе иначе съел бы всё до следующего бэктика
# где-то ниже по файлу и замаскировал бы настоящие ссылки между ними.
_INLINE_CODE_RE = re.compile(r'(`+)([^\n]+?)\1')


def _mask_code(text: str) -> str:
    """Заменяет код (fenced-блоки и inline) пробелами, сохраняя длину строк и их число.

    Переехала из validate-content.py в DEV-090 (NA-EPIC-29): C19
    (scripts/_conflict_markers.py) нуждается в той же маске, что C9/C10/C17
    (validate-content.py), и держать её в потребителе создало бы цикл импорта.

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


# ===== C20 — записи «намеренно» сверяются с деревом (ADR-072 Д1) =====================
#
# Предмет — носитель `.nauta-absence-records.yaml` (константа живёт в validate-content.py,
# рядом с GATES_FILENAME). Тело проверки вынесено сюда, а не написано в validate-content.py,
# по ADR-063 Д5: грандфазер-запись `scripts/validate-content.py: 1658` «обязана быть снята
# разбиением, а не продлена», а запаса до потолка там 16 строк. Модуль выбран уже
# доставляемый (PAYLOAD_FILES) и уже импортируемый читателем — состав поставки не меняется
# (ADR-072 Д5). Парсер тот же `parse_yaml_file`, второго нет.
#
# Классы error (ADR-072 Д1): не YAML, не список, чужое поле, пустое поле, ненайденный
# `detector`, `invoked-by`, не называющий обнаружителя, неразрешимый адрес решения, решение,
# замещённое чужой строкой `**Supersedes`, отрицательный `q1`/`q2`, `outcome` вне дословной
# пары контракта. Каждое сообщение называет САМ носитель: замок, меняющий только число,
# замком не является.
#
# Статус решения здесь НЕ проверяется намеренно (ADR-072, запрет 10): он живёт на рубеже MR,
# и в `--fast` красил бы рабочую ветку до sign-off — против Р1.

ABSENCE_RECORD_FIELDS = (
    "mechanism", "detector", "invoked-by", "moment", "decision",
    "uncovered", "outcome", "q1", "q2", "q3",
)
_ABSENCE_PATH_RE = re.compile(
    r"(?:scripts|tests|bin|hooks|agents|commands)/[\w./-]+|\.githooks/[\w./-]+"
)
_ABSENCE_ADR_RE = re.compile(r"ADR-\d{3}")
_ABSENCE_CLAUSE_RE = re.compile(r"Д\d+")
_ABSENCE_NEGATIVE = ("нет", "no", "false", "отрицателен", "-")
# Дословно два исхода контракта критерия сторожей (BA-056, capability-спека, строки 28-29),
# которыми механизм закрывается записью; `decision required` записью не закрывается (там же,
# строка 35), `owner` — тем более. Множество закрыто и объявлено здесь константой: читать
# спеку прибором значило бы завести новый парсер новой формы (ADR-072 Д1 в редакции SA-085).
# Slug capability здесь НЕ пишется намеренно: правило поиска носителя в замке QA-075
# (`_discover_carriers`) считает носителем любой отслеживаемый файл, называющий slug и
# несущий метку элемента, — упоминание slug тут сделало бы этот модуль ложным носителем.
_ABSENCE_OUTCOMES = ("record sufficient", "closed")
_ADR_DIR = Path("content") / "00-project" / "adr"


def _superseders(repo_root: Path, adr: str) -> list[str]:
    """ADR, чья строка-шапка `**Supersedes` называет `adr`. Конвенция дерева (ADR-030:17,
    ADR-027:16, ADR-031:18); статус замещённого при этом не читается — процедура supersede
    запрещает его трогать."""
    out = []
    for other in sorted((repo_root / _ADR_DIR).glob("ADR-*.md")):
        if other.name.startswith(adr):
            continue
        try:
            head = other.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        for line in head.splitlines():
            if line.startswith("**Supersedes") and adr in line:
                out.append(other.name)
                break
    return out


def _absence_record_issues(carrier: str, num: int, rec: dict, repo_root: Path) -> list[str]:
    """Сообщения по ОДНОЙ записи (без префикса носителя — его ставит вызывающий)."""
    msgs: list[str] = []
    for key in rec:
        if key not in ABSENCE_RECORD_FIELDS:
            msgs.append(f"чужое поле {key!r} — набор меток закрыт: {list(ABSENCE_RECORD_FIELDS)}")
    values: dict[str, str] = {}
    for field in ABSENCE_RECORD_FIELDS:
        value = rec.get(field)
        if not isinstance(value, str) or not value.strip():
            msgs.append(f"поле {field} отсутствует или пусто")
            continue
        values[field] = value.strip()

    detectors = _ABSENCE_PATH_RE.findall(values.get("detector", ""))
    if "detector" in values and not detectors:
        msgs.append(f"обнаружитель `{values['detector']}` не назван путём прогона дерева")
    for rel in detectors:
        if not (repo_root / rel).is_file():
            msgs.append(f"обнаружитель `{rel}` назван записью, но в дереве его нет")

    invokers = _ABSENCE_PATH_RE.findall(values.get("invoked-by", ""))
    if "invoked-by" in values and not invokers:
        msgs.append(f"зовущий путь `{values['invoked-by']}` не назван файлом дерева")
    for rel in invokers:
        target = repo_root / rel
        if not target.is_file():
            msgs.append(f"зовущий путь `{rel}` объявлен записью, но в дереве его нет")
            continue
        body = target.read_text(encoding="utf-8", errors="replace")
        absent = [d for d in detectors if Path(d).name not in body]
        if absent:
            msgs.append(
                f"{rel} объявлен зовущим путём, но не называет {absent} — достижимость "
                "обнаружителя утверждена, а не обеспечена"
            )

    decision = values.get("decision", "")
    # dict.fromkeys, а не set: адрес В3 называет ADR дважды (идентификатором и путём файла),
    # и без свёртки каждое сообщение о нём печаталось бы дважды — замер пробы M4 DEV-110.
    adrs = list(dict.fromkeys(_ABSENCE_ADR_RE.findall(decision)))
    if "decision" in values and not adrs:
        msgs.append(f"адрес решения `{decision}` не называет ни одного ADR-NNN")
    clause = _ABSENCE_CLAUSE_RE.search(decision)
    for adr in adrs:
        matches = sorted((repo_root / _ADR_DIR).glob(f"{adr}-*.md"))
        if not matches:
            msgs.append(f"решение {adr} в дереве не существует — адрес В3 не разрешается")
            continue
        text = matches[0].read_text(encoding="utf-8", errors="replace")
        if clause and clause.group(0) not in text:
            msgs.append(f"{matches[0].name} больше не несёт пункта {clause.group(0)}")
        for other in _superseders(repo_root, adr):
            msgs.append(f"решение {adr} замещено ({other}) — запись пережила своё решение")

    outcome = values.get("outcome", "")
    if outcome and outcome.lower() not in _ABSENCE_OUTCOMES:
        msgs.append(
            f"исход {outcome!r} не входит в пару контракта {list(_ABSENCE_OUTCOMES)} — "
            "записью закрывается только `record sufficient` или `closed`"
        )

    for field in ("q1", "q2"):
        answer = values.get(field, "").lower()
        if any(answer.startswith(tok) for tok in _ABSENCE_NEGATIVE):
            msgs.append(
                f"{field} отрицателен ({values[field]!r}) — вход с отрицательным В1/В2 "
                "записью не закрывается, он требует обнаружителя"
            )
    return [f"{carrier}[{num}]: {m}" for m in msgs]


def check_absence_records(path: Path, repo_root: Path) -> list[Issue]:
    """C20 (ADR-072 Д1): сверка записей «намеренно» с деревом. Файла нет — тихий проход
    (ADR-031 Д3): у потомка плагина записей нет, и красный на пустом дереве сделал бы
    носителя неустанавливаемым."""
    carrier = path.name
    if not path.is_file():
        return []
    try:
        data = parse_yaml_file(path)
    except MalformedYamlError as e:
        return [issue_from_yaml_error(e)]
    if not isinstance(data, dict):
        return [Issue("error", carrier,
                      f"{carrier}: корень носителя — не отображение с ключом `records:`")]
    records = data.get("records")
    if not isinstance(records, list) or not records:
        return [Issue("error", carrier,
                      f"{carrier}: ключ `records:` отсутствует или задан не непустым списком")]
    issues: list[Issue] = []
    for num, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            issues.append(Issue("error", carrier,
                                f"{carrier}[{num}]: запись задана не отображением меток"))
            continue
        issues.extend(
            Issue("error", carrier, m)
            for m in _absence_record_issues(carrier, num, rec, repo_root)
        )
    return issues


def grandfather_issue(path: str, rel: str, lines: int, ceiling: int,
                      at_ceiling: str, above_ceiling: str) -> Issue:
    """Единственный носитель формы отчёта о замороженном потолке для C11 (ADR-010 Д2).

    Обе качественные ветки `check_size_budget` зовут ЭТУ функцию: форма сообщения — контракт
    с фильтром провенанса AC-19, он ломается посимвольно, и вторая копия блока разъехалась бы
    молча. Вынос тела сюда, а не рядом с вызовом, — ADR-063 Д5: `validate-content.py` стоит
    ровно на своём грандфазер-потолке.

    Точка вызова — единственное место, где нарушитель подтверждён ОБОИМИ признаками
    (ADR-078 Д1: область грандфазера — состояние предмета, а не имя типа, вид качественного
    признака или ступень `severity`). `lines <= ceiling` -> `warning` (ADR-064 Д1),
    `lines > ceiling` -> `error` без исключений (ADR-064 Д3, ADR-078 Д3).

    `at_ceiling`/`above_ceiling` — провенанс решения, отдельный у каждой ветки: первая
    сохраняет `ADR-018 Д5` (supersede объявлен в части ОБЛАСТИ, форма записи Д5 переносится
    дословно), вторая называет `ADR-078`. Обе формы удовлетворяют регэкспу AC-19
    `\\(([^()]+?),\\s*ADR-\\d+`.
    """
    if lines <= ceiling:
        return Issue("warning", path,
                     f"грандфазер: {lines} строк тела <= замороженного потолка {ceiling} "
                     f"({rel}, {at_ceiling}) -- не блокирует")
    return Issue("error", path,
                 f"грандфазер-потолок превышен: {lines} строк тела > {ceiling} ({rel}). "
                 f"Верни рост, или подними ceiling явной правкой sizeBudgetGrandfathered "
                 f"в этом же коммите ({above_ceiling}).")
