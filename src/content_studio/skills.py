"""The skills Park uses for content, grouped by step, editable from 「设置与 Skills」.

The repo ships a seed (`config/skills.json`, generic and public). The first time the
workbench reads the list it copies the seed to the user's own file
(`<config_dir>/skills.json`); from then on every add / edit / delete goes to that file, so
Park's own frameworks and local paths never land in the public repo.

Third-party skills are listed by name, author and repository only; their files are never
copied into this repository. A card can show the skill's own Markdown (its SKILL.md, or the
framework file it points at) read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .paths import config_dir
from .vault import parse_frontmatter

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "skills.json"
USER_FILE = "skills.json"
SKILL_ROOTS = (Path("~/.agents/skills"), Path("~/.claude/skills"), Path("~/.codex/skills"))
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_DOC_CHARS = 60000


class SkillsError(ValueError):
    """Shown to Park as-is."""


def user_path(root: Path | None = None) -> Path:
    return (root or config_dir()) / USER_FILE


def _read_registry(seed: Path, user: Path | None) -> dict[str, Any]:
    if user is not None and user.is_file():
        return json.loads(user.read_text(encoding="utf-8"))
    return json.loads(seed.read_text(encoding="utf-8"))


def _write_registry(user: Path, data: dict[str, Any]) -> None:
    user.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(user.parent), prefix=".skills-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, user)


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


ANNA_ROLE_ENV = "CONTENT_STUDIO_ANNA_ROLE"
WORKFLOWS_ENV = "CONTENT_STUDIO_WORKFLOWS"


def doc_roots(roots: tuple[Path, ...] = SKILL_ROOTS) -> list[Path]:
    """Where a card's Markdown may come from: the skill folders, and Anna's own folder
    (her knowledge and the writing frameworks). Nothing else — the vault holds _secrets,
    and the site is reachable with a password."""
    out = [r.expanduser() for r in roots]
    role = os.environ.get(ANNA_ROLE_ENV)
    if role:
        out.append(Path(role).expanduser().with_suffix(""))
    wf = os.environ.get(WORKFLOWS_ENV)
    if wf:
        out.append(Path(wf).expanduser())
    return out


def safe_doc_path(raw: str, roots: tuple[Path, ...] = SKILL_ROOTS) -> Path | None:
    try:
        p = Path(raw).expanduser().resolve()
    except OSError:
        return None
    for base in doc_roots(roots):
        try:
            p.relative_to(base.resolve())
        except (OSError, ValueError):
            continue
        return p if p.is_file() and p.suffix.lower() == ".md" else None
    return None


def _local_doc(entry: dict[str, Any], roots: tuple[Path, ...]) -> Path | None:
    """The Markdown a card shows: a framework file the entry points at, else the skill's SKILL.md."""
    if entry.get("path"):
        return safe_doc_path(entry["path"], roots)
    if entry.get("dir"):
        for root in roots:
            candidate = root.expanduser() / entry["dir"] / "SKILL.md"
            if candidate.is_file():
                return candidate
    return None


def load_skills(registry_path: Path = REGISTRY_PATH, roots: tuple[Path, ...] = SKILL_ROOTS, user: Path | None = None) -> dict[str, Any]:
    registry = _read_registry(registry_path, user)
    stages = {stage["key"] for stage in registry["stages"]}
    skills = []
    for entry in registry["skills"]:
        if entry["stage"] not in stages:
            raise ValueError(f"skill {entry['name']} has unknown stage {entry['stage']}")
        doc = _local_doc(entry, roots)
        skills.append(
            {
                **entry,
                "installed": doc is not None,
                "local_path": str(doc).replace(str(Path.home()), "~") if doc else None,
                "description": _description(doc) if doc and doc.name == "SKILL.md" else None,
                "source_known": bool(entry.get("author") and (entry.get("repo") or entry.get("path"))),
            }
        )
    return {"stages": registry["stages"], "skills": skills, "editable": user is not None,
            "file": str(user).replace(str(Path.home()), "~") if user is not None else None}


FIELDS = ("name", "title", "stage", "use", "invoke", "author", "repo", "dir", "path", "own")


def clean_entry(raw: dict[str, Any], stages: set[str]) -> dict[str, Any]:
    entry = {k: raw.get(k) for k in FIELDS}
    entry["name"] = str(entry["name"] or "").strip()
    if not NAME.match(entry["name"]):
        raise SkillsError("名字只能用字母、数字、点、横线和下划线，比如 khazix-writer")
    entry["title"] = str(entry["title"] or "").strip()[:40] or entry["name"]
    if entry["stage"] not in stages:
        raise SkillsError("选一个它用在哪一步")
    entry["use"] = str(entry["use"] or "").strip()[:300]
    if not entry["use"]:
        raise SkillsError("写一句它用来做什么")
    entry["invoke"] = str(entry["invoke"] or "").strip()[:300] or f"在 Claude 里说：用 {entry['name']}"
    entry["author"] = (str(entry["author"]).strip()[:60] or None) if entry["author"] else None
    repo = str(entry["repo"] or "").strip()
    if repo and not repo.startswith("https://"):
        raise SkillsError("链接要以 https:// 开头，比如 GitHub 仓库地址")
    entry["repo"] = repo or None
    entry["dir"] = (str(entry["dir"]).strip() or None) if entry["dir"] else None
    if entry["dir"] and not NAME.match(entry["dir"]):
        raise SkillsError("本机 skill 目录名只写文件夹名，比如 khazix-writer")
    path = str(entry["path"] or "").strip()
    if path and not (path.startswith("~/") and path.endswith(".md")):
        raise SkillsError("本机文件写成 ~/ 开头的 .md 路径")
    entry["path"] = path or None
    entry["own"] = bool(entry["own"])
    return entry


def upsert(raw: dict[str, Any], *, user: Path, registry_path: Path = REGISTRY_PATH, previous: str | None = None) -> dict[str, Any]:
    data = _read_registry(registry_path, user)
    entry = clean_entry(raw, {s["key"] for s in data["stages"]})
    names = [s["name"] for s in data["skills"]]
    target = previous or entry["name"]
    if entry["name"] != target and entry["name"] in names:
        raise SkillsError("已经有一个同名的 skill")
    if target in names:
        data["skills"][names.index(target)] = entry
    else:
        if entry["name"] in names:
            raise SkillsError("已经有一个同名的 skill")
        data["skills"].append(entry)
    _write_registry(user, data)
    return entry


def remove(name: str, *, user: Path, registry_path: Path = REGISTRY_PATH) -> bool:
    data = _read_registry(registry_path, user)
    kept = [s for s in data["skills"] if s["name"] != name]
    if len(kept) == len(data["skills"]):
        return False
    data["skills"] = kept
    _write_registry(user, data)
    return True


def read_doc(name: str, *, user: Path | None, registry_path: Path = REGISTRY_PATH, roots: tuple[Path, ...] = SKILL_ROOTS) -> dict[str, Any]:
    """A listed skill's Markdown, read-only. Only files that belong to a listed entry."""
    data = _read_registry(registry_path, user)
    entry = next((s for s in data["skills"] if s["name"] == name), None)
    if entry is None:
        raise SkillsError("没有这个 skill")
    doc = _local_doc(entry, roots)
    if doc is None:
        raise SkillsError("本机没有这个 skill 的文件")
    meta, body = parse_frontmatter(doc.read_text(encoding="utf-8", errors="replace"))
    return {"name": entry.get("title") or name, "path": str(doc).replace(str(Path.home()), "~"), "body": body[:MAX_DOC_CHARS]}
