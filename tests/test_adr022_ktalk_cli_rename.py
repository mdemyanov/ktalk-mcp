"""Failing stubs for ADR-022 (ktalk-mcp -> ktalk-cli rename, MCP layer removal).

Companion: content/40-architecture/ADR-022-ktalk-cli-rename-spec.md (§7 order of work,
§8 literal inventory, "Contract with QA-author"). QA-author task ktalk-plugin-foz.17/QA-001.

Scope of this file: the two outcomes of that contract that are executable *today*, before
Dev's three-commit rename lands — (1) the printed package identity must be read from
installed metadata, not a hard-coded string literal (SA-001 finding, ADR-022 §7); (2) the
module/dist-name rename is either complete or incomplete, counted, not eyeballed (ADR-022-
ktalk-cli-rename-spec.md §8, exactly 12 `ktalk-mcp` literals today, 8 legitimate survivors
after the rename, 4 that must move to a dynamic read).

Deliberately NOT covered here (documented, not silently skipped — QA-author contract):
- The `ktalk-mcp==0.11.0` deprecation-pointer package's own behaviour (nonzero exit code,
  stderr notice, DeprecationWarning, no `ktalk` entry point). Its `src/ktalk_mcp/__init__.py`
  does not coexist with the renamed `src/ktalk_cli/` in one working tree — it is cut from a
  separate historical commit/branch (§7 п.3) after the rename already happened here. A stub
  importing `ktalk_mcp` in *this* tree would break on ImportError, not on an assertion, once
  step 2 of §7 lands — exactly the "fails on compile/import, not on assert" defect the
  QA-author contract forbids. Left as a design-only outcome (see at-design.md), to be
  authored against that separate release artifact when DevOps cuts it (§7 п.3 / Brief for
  DevOps).
"""

from __future__ import annotations

import collections
import email.message
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def test_ac_printed_identity_tracks_installed_metadata_not_a_hardcoded_literal(monkeypatch, capsys):
    """SA-001 (ADR-022 §7/§8): `ktalk --version` prints `f"ktalk-mcp {__version__}"` — the
    distribution name is a bare string literal in cli.py, not read from the installed
    package's metadata. The exact same defect class already hit the *version* half of this
    same print statement once (0.8.0, `tests/test_cli.py::test_version_matches_pyproject`);
    there has never been an equivalent guard for the *name* half.

    A test that only compares the printed name against `pyproject.toml`'s `[project].name`
    (the literal mirror of `test_version_matches_pyproject`) would be vacuous here: today
    the hard-coded literal "ktalk-mcp" and pyproject.toml's name happen to be equal by
    coincidence, so that comparison passes right now for the wrong reason, and it would
    keep passing if Dev "fixed" this by editing the literal to "ktalk-cli" by hand instead
    of reading metadata — reproducing exactly the class of bug this ADR exists to close,
    just with a new string. Instead we mutate what `importlib.metadata` actually reports
    for this package's name and observe whether the printed identity follows it (must,
    per ADR-022 §7) or stays frozen (today's bug).
    """
    fake_name = "zz-test-distribution-name-not-a-real-package"

    def fake_metadata(name):
        msg = email.message.Message()
        msg["Name"] = fake_name
        return msg

    monkeypatch.setattr(importlib.metadata, "metadata", fake_metadata)

    # __version__/identity resolution runs once, at package import time (same pattern the
    # 0.8.0 __version__ fix already uses) — force a fresh import under the patched metadata,
    # restoring the previous module objects afterwards so later tests are unaffected.
    #
    # Module identifier below is "ktalk_cli", not the "ktalk_mcp" named throughout this
    # file's prose: the mechanical rename (ADR-022 §7 п.2, companion §8) renames the
    # functional identifier here too — this is completion of that same rename, not a
    # rewrite of the stub's assertions/intent (Dev instructions: extend, never replace).
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name == "ktalk_cli" or name.startswith("ktalk_cli.")
    }
    for name in list(saved):
        del sys.modules[name]
    try:
        cli_module = importlib.import_module("ktalk_cli.cli")
        code = cli_module.main(["--version"])
        out = capsys.readouterr().out
    finally:
        for name in list(sys.modules):
            if name == "ktalk_cli" or name.startswith("ktalk_cli."):
                del sys.modules[name]
        sys.modules.update(saved)

    assert code == 0
    printed_name = out.split()[0]
    assert printed_name == fake_name, (
        f"printed identity {printed_name!r} did not follow the patched installed-metadata "
        f"name ({fake_name!r}) — the distribution name printed by `ktalk --version` is "
        f"still a hard-coded literal in cli.py, the exact defect class ADR-022 §7 requires "
        f"closed (symmetric to test_version_matches_pyproject, which already closed it for "
        f"the version half after the 0.8.0 incident)"
    )


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".md"}:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def test_ac_module_rename_literal_budget_is_exactly_eight_legitimate_survivors():
    """ADR-022-ktalk-cli-rename-spec.md §8: exactly 12 `ktalk-mcp` (hyphen) literals exist in
    `src/` today, in 6 files. 4 are code that must start reading identity dynamically
    (`__init__.py`, `cli.py` x2, `CLAUDE.md` header) — closed by the previous test plus a
    human/Dev diff review of the header. 8 are legitimate, permanent survivors: 6 reference
    the never-renamed config path `~/.config/ktalk-mcp/token` (ADR-022 п.5), 2 reference an
    unrelated third-party product from RES-002 (`token_file.py:26`, `endpoints.py:120`).

    This is a two-sided budget, not a one-sided "no more than N" ceiling: it fails equally
    if the rename is incomplete (too many hits, today's state) *and* if a future
    find-replace overreaches into the six protected config-path occurrences or the two
    foreign-product references (too few hits, or hits in the wrong files) — both are named,
    reviewed classes of risk in the companion spec ("Точка правки" / "Edge cases").
    """
    per_file: collections.Counter = collections.Counter()
    for path, text in _iter_text_files(SRC):
        count = text.count("ktalk-mcp")
        if count:
            per_file[path.name] += count

    expected = {
        "config.py": 1,
        "token_file.py": 5,
        "endpoints.py": 1,
        "CLAUDE.md": 1,
    }
    assert dict(per_file) == expected, (
        "'ktalk-mcp' literal budget in src/ has drifted from the post-rename target "
        "(ADR-022-ktalk-cli-rename-spec.md §8: 6 config-path + 2 foreign-product refs "
        f"survive verbatim, everything else reads identity dynamically). Found: {dict(per_file)!r}, "
        f"expected exactly: {expected!r}"
    )


def test_ac_module_identifier_ktalk_mcp_fully_renamed_in_src_and_tests():
    """ADR-022 п.4 / companion §7 п.2: the Python module identifier `ktalk_mcp` (underscore
    — import paths, package name) is renamed to `ktalk_cli` everywhere in `src/` and
    `tests/`, without exception (unlike the hyphenated `ktalk-mcp` literal above, which has
    8 legitimate, permanent survivors). A partial mechanical rename — some files still
    importing `ktalk_mcp.*` — is exactly the risk the companion spec names under
    "Edge cases / граничные условия" (§ Contract with QA-author).
    """
    hits = []
    for base in (SRC, ROOT / "tests"):
        for path, text in _iter_text_files(base):
            if path == Path(__file__):
                continue  # this test's own docstrings name "ktalk_mcp" — not a src hit
            if "ktalk_mcp" in text:
                hits.append(str(path.relative_to(ROOT)))

    assert not hits, (
        "module identifier 'ktalk_mcp' (underscore) still present after the rename in: "
        + ", ".join(sorted(hits))
    )
