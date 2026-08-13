#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""_resolve_agents.py — base + delta merge resolver for agent prompts.

Reads base prompts from .claude/plugins/project/agents/<role>-agent.md and
profile overrides from <profile-dir>/agent-overrides/<role>.md, merges them
according to base + delta rules (frontmatter merge, section-level body merge
with {{super}} placeholder), writes resolved prompts to target-dir.

CLI:
    python3 scripts/_resolve_agents.py <profile-dir> --base-dir <base> --target-dir <target>
    python3 scripts/_resolve_agents.py --merge-only <base.md> <override.md>  # for unit tests

See:
    docs/architecture/spec-resolve-agents.md (a20da89) — authoritative contract
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("error: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


class OverrideError(Exception):
    """Override file is malformed or violates contract."""


@dataclass
class Frontmatter:
    """Parsed frontmatter + body."""
    fm: dict
    body: str


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def parse_frontmatter(path: Path) -> Frontmatter:
    """Parse YAML frontmatter + markdown body. No frontmatter → fm={}, body=text."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match:
        fm_text, body = match.group(1), match.group(2)
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as e:
            raise OverrideError(f"{path}: malformed YAML frontmatter — {e}")
    else:
        fm, body = {}, text
    return Frontmatter(fm=fm, body=body)


SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def parse_sections(body: str) -> list[tuple[str, str]]:
    """Split body into (heading, content) pairs. Preamble before first ## → ('', preamble).

    Returns list (preserving order); content includes the heading line.
    Heading match — exact (case + whitespace + punctuation sensitive).
    """
    matches = list(SECTION_RE.finditer(body))
    if not matches:
        return [("", body)] if body.strip() else []

    parts: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        parts.append(("", body[: matches[0].start()].rstrip() + "\n"))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].rstrip() + "\n"
        parts.append((heading, content))

    return parts


def merge_delta(base_path: Path, override_path: Path) -> str:
    """Merge override into base according to W4a delta rules.

    Returns merged file as string (frontmatter + body, NO GENERATED marker).
    Marker is added by main() / build_marker() — keep merge_delta pure for unit testing.
    """
    base = parse_frontmatter(base_path)
    override = parse_frontmatter(override_path)

    # Validate extends present
    if "extends" not in override.fm:
        raise OverrideError(
            f"{override_path}: missing required 'extends' frontmatter field"
        )

    # Validate extends matches role (file basename without .md)
    expected_role = override_path.stem
    if override.fm["extends"] != expected_role:
        raise OverrideError(
            f"{override_path}: extends '{override.fm['extends']}' but role is '{expected_role}'"
        )

    # Frontmatter merge:
    # - scalar fields (description, model, name): override fully replaces base
    # - list fields (tools, disallowedTools, skills): override fully REPLACES base (no union)
    # - missing fields: inherit from base
    # NB: shallow merge — nested dicts/lists in override REPLACE base wholesale
    merged_fm = {**base.fm, **override.fm}
    merged_fm.pop("extends", None)  # not needed in resolved

    # Body merge: section-level
    base_sections = parse_sections(base.body)
    override_sections_list = parse_sections(override.body)
    override_sections = {h: c for h, c in override_sections_list if h}
    base_section_names = {h for h, _ in base_sections if h}

    # Validate {{super}} only in sections that exist in base
    for name, content in override_sections.items():
        if "{{super}}" in content and name not in base_section_names:
            raise OverrideError(
                f"{override_path}: section '## {name}' uses {{{{super}}}} but base has no such section"
            )

    merged_body_parts: list[str] = []

    # Override preamble (text before first ##) replaces base preamble if present
    override_preamble = next((c for h, c in override_sections_list if h == ""), None)

    for heading, content in base_sections:
        if heading == "":
            merged_body_parts.append(override_preamble if override_preamble is not None else content)
        elif heading in override_sections:
            override_content = override_sections[heading]
            # Substitute {{super}} with base section body (without ## heading line)
            base_section_body = "\n".join(content.split("\n")[1:]).rstrip()
            override_content = override_content.replace("{{super}}", base_section_body)
            merged_body_parts.append(override_content)
        else:
            merged_body_parts.append(content)

    # Append override sections not in base
    base_heading_set = {h for h, _ in base_sections}
    for heading, content in override_sections_list:
        if heading and heading not in base_heading_set:
            merged_body_parts.append(content)

    merged_body = "\n".join(merged_body_parts).strip() + "\n"
    fm_str = yaml.safe_dump(merged_fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_str}\n---\n\n{merged_body}"


def build_marker(profile_name: str, role: str, override_path: Optional[Path]) -> str:
    """GENERATED marker prepended to resolved files."""
    if override_path is None:
        source = f".claude/plugins/project/agents/{role}-agent.md (no override)"
    else:
        source = f"base + docs/overlays/profiles/{profile_name}/agent-overrides/{role}.md"
    return (
        f"<!-- GENERATED by scripts/_resolve_agents.py — do not edit.\n"
        f"     Source: {source}\n"
        f"     Regenerate: bash scripts/apply-overlay.sh --profile {profile_name} -->\n\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_dir_or_base", nargs="?")
    parser.add_argument("override_path", nargs="?")
    parser.add_argument("--base-dir", type=Path)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--merge-only", action="store_true",
                        help="Test mode: print merge_delta(base, override) to stdout")
    args = parser.parse_args()

    if args.merge_only:
        if not args.profile_dir_or_base or not args.override_path:
            print("error: --merge-only requires <base.md> <override.md>", file=sys.stderr)
            return 1
        try:
            result = merge_delta(Path(args.profile_dir_or_base), Path(args.override_path))
        except OverrideError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(result)
        return 0

    # Main flow: resolve all roles for profile
    if not args.profile_dir_or_base or not args.base_dir or not args.target_dir:
        print("error: requires <profile-dir> --base-dir <dir> --target-dir <dir>", file=sys.stderr)
        return 1

    profile_dir = Path(args.profile_dir_or_base)
    manifest_path = profile_dir / "manifest.yaml"
    if not manifest_path.exists():
        print(f"error: manifest.yaml not found in {profile_dir}", file=sys.stderr)
        return 1

    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as e:
        print(f"error: {manifest_path}: malformed YAML — {e}", file=sys.stderr)
        return 1
    overrides = manifest.get("agent_overrides", {}) or {}
    profile_name = manifest.get("name", profile_dir.name)

    args.target_dir.mkdir(parents=True, exist_ok=True)

    for role, status in (manifest.get("subagents", {}) or {}).items():
        if status == "disabled":
            continue

        # Special-case: pm — main-context operator (Opus), not a Task-invoked subagent.
        # `.claude/plugins/<slug>/agents/pm-agent.md` was removed from the plugin
        # entirely (ADR-009 Д1, PT-EPIC-14 impl DEV-039): the orphaned file was never
        # actually read by `/pm` (commands/pm.md is self-sufficient, does not delegate
        # via Task to a prompt file). Manifests keep listing `pm: core|optional` for
        # profile-summary purposes only — there is no base prompt left to merge/copy,
        # so this role is skipped rather than erroring like a missing base for any
        # other role would (BR-001-equivalent for code: no base to resolve against).
        if role == "pm":
            continue

        # Special-case: qa role is split into qa-author + qa-runner (no qa-agent.md exists)
        if role == "qa" and not (args.base_dir / "qa-agent.md").exists():
            override_path: Optional[Path] = None
            if role in overrides:
                override_entry = overrides[role]
                if not isinstance(override_entry, dict):
                    override_entry = {}
                source = override_entry.get("source")
                if not source:
                    print(f"error: agent_overrides.{role} missing 'source' field в manifest",
                          file=sys.stderr)
                    return 1
                override_path = profile_dir / source
                if not override_path.exists():
                    print(f"error: override not found: {override_path}", file=sys.stderr)
                    return 1

            for qa_variant in ["qa-author", "qa-runner"]:
                qa_base = args.base_dir / f"{qa_variant}-agent.md"
                if not qa_base.exists():
                    print(f"error: base prompt not found: {qa_base}", file=sys.stderr)
                    return 1
                if override_path is not None:
                    try:
                        qa_resolved = merge_delta(qa_base, override_path)
                    except OverrideError as e:
                        print(f"error: {e}", file=sys.stderr)
                        return 1
                else:
                    qa_resolved = qa_base.read_text()
                qa_marker = build_marker(profile_name, qa_variant, override_path)
                qa_target = args.target_dir / f"{qa_variant}-agent.md"
                qa_target.write_text(qa_marker + qa_resolved, encoding="utf-8")
            continue

        base_path = args.base_dir / f"{role}-agent.md"
        if not base_path.exists():
            print(f"error: base prompt not found for role '{role}': {base_path}",
                  file=sys.stderr)
            return 1

        override_path = None
        if role in overrides:
            override_entry = overrides[role]
            if not isinstance(override_entry, dict):
                # active: (null value) or active: "string" — treat as missing source
                override_entry = {}
            source = override_entry.get("source")
            if not source:
                print(f"error: agent_overrides.{role} missing 'source' field в manifest",
                      file=sys.stderr)
                return 1
            override_path = profile_dir / source

        if override_path is not None:
            if not override_path.exists():
                print(f"error: override not found: {override_path}", file=sys.stderr)
                return 1
            try:
                resolved = merge_delta(base_path, override_path)
            except OverrideError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
        else:
            resolved = base_path.read_text()

        marker = build_marker(profile_name, role, override_path)

        target_path = args.target_dir / f"{role}-agent.md"
        target_path.write_text(marker + resolved, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
