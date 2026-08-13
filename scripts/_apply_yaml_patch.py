#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""_apply_yaml_patch.py — addressee-key resolution for overlay YAML patches (ADR-022, TPL-70).

`append_block_yaml` (`scripts/apply-overlay.sh`) used to append the overlay patch to the end
of the target file unconditionally — worked only by accident, when the target file happened to
end with the open block-sequence the patch was meant to extend. This helper finds the list the
patch actually addresses (its own top-level key, ADR-022 Д1) and splices the patch body into
that list's block-sequence — textual splice, not a full `yaml.safe_load`+`dump` round-trip
(ADR-022 Д2 — preserves load-bearing comments, e.g. the ADR-018 ordering warning in
`content/.doc-root.yaml`).

See: ADR-022 (Д1-Д5) and ADR-022-spec §1-§2 (формат патча, алгоритм — этот файл реализует
псевдокод §2 дословно). Цитируется по короткому имени, не полным путём content/ — этот файл
KEEP_EXACT (ships to descendants), а ADR-022/ADR-022-spec — per-file cut шаблона (topology B,
DEV-033); полный путь здесь абортил бы cross-link gate публикации (тот же приём, что
scripts/apply-overlay.sh уже использует для той же пары ADR).

CLI:
    python3 scripts/_apply_yaml_patch.py <target-file> <patch-file> <mark-start> <mark-end>

Exit codes:
    0 — patch applied, target file overwritten in place
    1 — malformed patch OR addressee list not found in target — target file left untouched
        (ADR-022 Д3: loud refusal, no partial write, not a silent fallback to append-at-EOF)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


class PatchError(Exception):
    """Patch malformed or addressee not found — caller must NOT write the target file."""


def find_addressee_key(patch_text: str) -> str:
    """ADR-022-spec §2/§1: the patch must be standalone YAML with exactly one top-level key,
    whose value is a list — that key names the list in the target file the patch extends."""
    try:
        doc = yaml.safe_load(patch_text)
    except yaml.YAMLError as exc:
        raise PatchError(f"malformed overlay patch: not valid YAML — {exc}") from exc
    if not isinstance(doc, dict) or len(doc) != 1:
        raise PatchError(
            f"malformed overlay patch: expected exactly one top-level key, got {doc!r}"
        )
    ((key, val),) = doc.items()
    if not isinstance(val, list):
        raise PatchError(
            f"malformed overlay patch: top-level key {key!r} must map to a list, got {val!r}"
        )
    return key


def apply_yaml_patch(target_text: str, patch_text: str, mark_start: str, mark_end: str) -> str:
    """ADR-022-spec §2 pseudocode, verbatim.

    Insertion point — end of the addressee's block-sequence: the first following line that
    starts at column 0 (`^\\S`, i.e. the next top-level key or a top-level comment), or EOF if
    the addressee is the last block in the file. Text outside the insertion point is untouched
    byte-for-byte (ADR-022 Д2 — no YAML round-trip re-serialize).

    Raises PatchError — target_text is returned to the caller unmodified in that case — if the
    addressee key is not found in the target (FR-002/Д3: loud refusal, not a silent append).
    """
    key = find_addressee_key(patch_text)
    lines = target_text.splitlines(keepends=True)
    key_re = re.compile(rf"^{re.escape(key)}:\s*$")
    start_idx = next((i for i, line in enumerate(lines) if key_re.match(line)), None)
    if start_idx is None:
        raise PatchError(
            f"addressee list '{key}:' not found in target file — cannot apply patch. "
            f"Target unchanged."
        )
    end_idx = next(
        (j for j in range(start_idx + 1, len(lines)) if re.match(r"^\S", lines[j])),
        len(lines),
    )
    body_lines = patch_text.splitlines(keepends=True)[1:]  # без обёртывающей "key:\n" строки
    insertion = [f"{mark_start}\n"] + body_lines + [f"{mark_end}\n"]
    return "".join(lines[:end_idx] + insertion + lines[end_idx:])


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "usage: _apply_yaml_patch.py <target-file> <patch-file> <mark-start> <mark-end>",
            file=sys.stderr,
        )
        return 2
    target_path = Path(sys.argv[1])
    patch_path = Path(sys.argv[2])
    mark_start, mark_end = sys.argv[3], sys.argv[4]

    target_text = target_path.read_text(encoding="utf-8")
    patch_text = patch_path.read_text(encoding="utf-8")

    try:
        result = apply_yaml_patch(target_text, patch_text, mark_start, mark_end)
    except PatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    target_path.write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
