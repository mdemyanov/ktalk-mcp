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

    Правило приоритета плейсхолдера в его действующей форме (ADR-007 Д5, редакция
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
