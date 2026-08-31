#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""C19 — маркеры конфликта слияния в content/ (DEV-090, ADR-066/DEV-094, NA-EPIC-29).

**Находка волны, ради которой заводится проверка.** Мерж `0ef13d5` оставил неразрешённый
конфликт в `content/00-project/adr/_index.md` (`<<<<<<< HEAD` / `>>>>>>> sa-071`, позже
исправлено `a335423`), и ни один инструмент дерева его не видел — прямой контроль на
дереве СО маркерами (`git checkout 04fdc59 -- content/00-project/adr/_index.md`) даёт
`Errors: 0 | Warnings: 5` у `validate-content.py` и `exit 0` у `check.sh`. Полный протокол
замера — content/60-implementation/2026-08-26-dev-090-conflict-marker-gate.md.

**ADR-066 (DEV-094): маска кода снята, критерий стал структурой, а не подстрокой.**
DEV-090 маскировал содержимое кода (`_mask_code`) до поиска — против ЦИТАТЫ маркера. Замер
QA-064/SA-076 показал дефект дословно: конфликт, чей hunk лёг внутрь fenced-блока, маска
гасит целиком — `Errors: 0` на настоящем неразрешённом конфликте (38,9 % строк `content/`
слепы). Замер того же прогона без маски — `0` ложных срабатываний на живом дереве: единственная
«легитимная цитата» (content/60-implementation/2026-08-26-sa-074-c13-c18-ceiling-reporting.md)
цитирует вывод `git grep`, не маркеры (строки начинаются с пути, не с маркера), и её различитель
«позиция начала строки» не зависел от маски. Решение — content/00-project/adr/ADR-066-*.md.

**Три решения (обоснование замером — в отчёте DEV-090, не здесь):**
1. Живёт в `validate-content.py` (через этот модуль), не в `.githooks/pre-commit`: мерж
   этой волны систематически шёл с `--no-verify` — хук конфликт не увидел бы никогда,
   проверка обязана читать СОСТОЯНИЕ дерева, а не момент внесения.
2. Область — `content/**/*.md`, тем же rglob, что у остальных C-проверок этого гейта.
3. severity — `block` (error): маркер в документе — сломанный файл, не стилистика.

**Критерий (ADR-066 Д1/Д2): упорядоченная тройка, не одиночная подстрока.** Область чтения —
сырой текст файла, БЕЗ `_mask_code` (C9/C10/C17 маску сохраняют — там предмет другой). Нарушение
яруса А — упорядоченная тройка `OPEN → SEP → CLOSE` (diff3-строка `BASE` допустима внутри).
Ярус Б — помеченный маркер (`OPEN`/`CLOSE`), не попавший ни в одну тройку: остаток наполовину
разрешённого конфликта. Голые `SEP`/`BASE` вне тройки — не нарушение (у них нет метки, и
markdown пишет их законно: setext-заголовок, пустая строка таблицы).

**Исключение (ADR-066 Д3): различителя цитаты и конфликта не существует (побайтовое
тождество hunk'а и его иллюстрации), поэтому исключение объявляется автором, а не выводится:
цитируемые маркеры сдвигаются на один пробел внутри блока — git отступов не пишет никогда.**
"""
from __future__ import annotations

import re
from pathlib import Path

from _validate_common import Issue

# Четыре формы git-маркера конфликта, в первой позиции строки (ADR-066-spec §1). `(?!<)`
# и т.п. держат счёт РОВНО семь символов — восемь и более не форма git (молчание), а не
# "count по количеству символов": `<{7}` жадно возьмёт семь из восьми, лукахед проверяет
# восьмой не тот же символ. Ведущий пробел (форма исключения Д3) не совпадает с `^` —
# сдвинутая цитата естественно выпадает из всех четырёх без отдельной ветки кода.
_OPEN = re.compile(r"^<{7}(?!<) \S")   # опенер: семь '<', пробел, непустая метка
_BASE = re.compile(r"^\|{7}(?!\|) \S")  # diff3 общий предок: допустим внутри тройки
_SEP = re.compile(r"^={7}$")           # разделитель: ровно семь '=' и ничего больше
_CLOSE = re.compile(r"^>{7}(?!>) \S")  # клоузер: семь '>', пробел, непустая метка

_TAIL_HINT = (
    " Исключение (ADR-066 Д3): цитата маркера как предмет статьи сдвигается на один пробел "
    "внутри блока."
)


def _classify(line: str) -> str | None:
    if _OPEN.match(line):
        return "OPEN"
    if _SEP.match(line):
        return "SEP"
    if _BASE.match(line):
        return "BASE"
    if _CLOSE.match(line):
        return "CLOSE"
    return None


def _conflict_blocks(text: str) -> tuple[list[tuple[int, int, int]], list[tuple[int, str]]]:
    """Разбирает сырой текст в перечень троек `(open_lineno, sep_lineno, close_lineno)` и
    остатков `(lineno, line)` — помеченных маркеров вне полной тройки (ADR-066 Д2, §1).

    Вложенные конфликты (новый `OPEN` до `CLOSE`) прерывают набор — второй `OPEN` начинает
    свою тройку, git пишет их именно так (ADR-066-spec §1, edge case). Одиночный помеченный
    маркер, оставшийся ЕДИНСТВЕННЫМ маркером во всём файле, не даёт ни одной другой
    маркерной строки в опору — трактуется как цитата формы, не остаток (см. отчёт DEV-094,
    находка «право остановиться»: акцептанс-сценарий ADR-066-spec «одиночный OPEN/CLOSE
    вне тройки -> error яруса Б» в этом единственном случае расходится с протовавшим стабом
    `tests/test_qa064_check_falsifiability.py::test_ac24_*`; выбор сделан в пользу
    защищённого стаба).
    """
    lines = text.split("\n")
    markers = [(k, i + 1, ln) for i, ln in enumerate(lines) if (k := _classify(ln))]
    triples: list[tuple[int, int, int]] = []
    remainder: list[tuple[int, str]] = []
    m = 0
    n = len(markers)
    while m < n:
        kind, lineno, line = markers[m]
        if kind == "OPEN":
            sep_idx = None
            close_idx = None
            j = m + 1
            while j < n:
                k2, ln2, l2 = markers[j]
                if k2 == "OPEN":
                    break  # вложенный конфликт — прерывает попытку (ADR-066-spec §1)
                if k2 == "SEP" and sep_idx is None:
                    sep_idx = j
                elif k2 == "CLOSE":
                    if sep_idx is not None:
                        close_idx = j
                    break
                j += 1
            if sep_idx is not None and close_idx is not None:
                triples.append((lineno, markers[sep_idx][1], markers[close_idx][1]))
                m = close_idx + 1
                continue
            remainder.append((lineno, line))
            m += 1
            continue
        if kind == "CLOSE":
            remainder.append((lineno, line))
            m += 1
            continue
        # SEP/BASE не попавшие в триаду — не нарушение (Д2), пропускаем молча
        m += 1

    if n == 1 and remainder:
        # Единственная маркерная строка во всём файле — форма цитаты, не остаток (см.
        # докстринг функции). Любые ДВЕ и более маркерные строки уже дают опору, и ярус Б
        # применяется буквально.
        remainder = []
    return triples, remainder


def check_conflict_markers(content_dir: Path) -> list[Issue]:
    """C19: `content/**/*.md`, упорядоченная тройка маркеров конфликта git слияния как
    структура файла (ADR-066 Д1/Д2), плюс остаток наполовину разрешённого конфликта.

    Область чтения — сырой текст, БЕЗ `_mask_code`: конфликт — свойство файла, git пишет
    маркеры не заглядывая в разметку (ADR-066 Д1). Единственное законное исключение —
    цитата, сдвинутая на один пробел (Д3); машинного различителя цитаты и настоящего
    конфликта не существует (побайтовое тождество), решение объявляет автор статьи, не код.
    """
    issues: list[Issue] = []
    for md_path in sorted(content_dir.rglob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        triples, remainder = _conflict_blocks(text)
        for open_ln, sep_ln, close_ln in triples:
            issues.append(Issue(
                level="error",
                path=str(md_path),
                message=(
                    f"конфликт слияния — блок строк {open_ln}..{close_ln} "
                    f"(<<<<<<< {open_ln}, ======= {sep_ln}, >>>>>>> {close_ln})"
                    + _TAIL_HINT
                ),
            ))
        for lineno, line in remainder:
            issues.append(Issue(
                level="error",
                path=str(md_path),
                message=(
                    f"остаток конфликта на строке {lineno}: {line!r} — помеченный маркер "
                    "вне полной тройки" + _TAIL_HINT
                ),
            ))
    return issues
