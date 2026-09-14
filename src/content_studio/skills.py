"""The skills Park uses for content, with authorship and local install status.

Third-party skills are listed by name, author and repository only; their files are
never copied into this repository.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .vault import parse_frontmatter

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "skills.json"
SKILL_ROOTS = (Path("~/.agents/skills"), Path("~/.claude/skills"), Path("~/.codex/skills"))


def _description(skill_md: Path) -> str | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.match(r"\A---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    block = match.group(1)
    folded = re.search(r"^description:\s*[|>][-+]?\s*\n((?:[ \t]+.*\n?)+)", block, re.MULTILINE)
    if folded:
        return " ".join(line.strip() for line in folded.group(1).splitlines() if line.strip())[:300]
    meta, _ = parse_frontmatter(text)
    return (meta.get("description") or None) and meta["description"][:300]


def load_skills(registry_path: Path = REGISTRY_PATH, roots: tuple[Path, ...] = SKILL_ROOTS) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    stages = {stage["key"] for stage in registry["stages"]}
    skills = []
    for entry in registry["skills"]:
        if entry["stage"] not in stages:
            raise ValueError(f"skill {entry['name']} has unknown stage {entry['stage']}")
        installed = None
        for root in roots:
            candidate = root.expanduser() / entry["dir"] / "SKILL.md"
            if candidate.is_file():
                installed = candidate
                break
        skills.append(
            {
                **entry,
                "installed": installed is not None,
                "local_path": str(installed.parent).replace(str(Path.home()), "~") if installed else None,
                "description": _description(installed) if installed else None,
                "source_known": bool(entry.get("author") and entry.get("repo")),
            }
        )
    return {"stages": registry["stages"], "skills": skills}
