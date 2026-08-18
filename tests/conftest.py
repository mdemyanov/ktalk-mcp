"""Shared test fixtures for ktalk-mcp."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_xdg_dirs(tmp_path, monkeypatch):
    """QA-007 (ADR-016): санкция записи живёт в `$XDG_CONFIG_HOME/ktalk`, подтверждения
    и журнал — в `$XDG_STATE_HOME/ktalk`. Без этой изоляции прогон писал бы их в
    настоящий `$HOME` пользователя и выдавал бы санкцию машине из-под тестов.
    Тест, которому нужен свой путь, перекрывает переменную своим `monkeypatch`.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
