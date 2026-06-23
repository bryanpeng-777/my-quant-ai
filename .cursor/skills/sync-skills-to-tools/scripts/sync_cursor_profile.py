#!/usr/bin/env python3
"""Sync ~/.claude skills/agents to a Cursor project by profile (.cursor/sync-profile)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = SKILL_ROOT / "references" / "cursor-profiles"
DEFAULT_CLAUDE_SKILLS = Path.home() / ".claude" / "skills"
DEFAULT_CLAUDE_AGENTS = Path.home() / ".claude" / "agents"


def read_profile_name(project_root: Path) -> str:
    marker = project_root / ".cursor" / "sync-profile"
    if marker.is_file():
        name = marker.read_text(encoding="utf-8").strip()
        if name:
            return name.splitlines()[0].strip()
    return "full"


def load_profile(profile_name: str) -> dict:
    path = PROFILES_DIR / f"{profile_name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Profile not found: {profile_name} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles() -> list[dict]:
    profiles: list[dict] = []
    if not PROFILES_DIR.is_dir():
        return profiles
    for path in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sync_mode = data.get("sync_mode", "selective")
        skills = data.get("skills", [])
        agents = data.get("agents", [])
        profiles.append(
            {
                "name": data.get("name", path.stem),
                "description": data.get("description", ""),
                "sync_mode": sync_mode,
                "skills_count": len(skills) if sync_mode != "all" else "all",
                "agents_count": len(agents) if sync_mode != "all" else "all",
            }
        )
    return profiles


def init_profile(project_root: Path, profile_name: str) -> Path:
    load_profile(profile_name)  # validate exists
    cursor_dir = project_root / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    marker = cursor_dir / "sync-profile"
    marker.write_text(f"{profile_name}\n", encoding="utf-8")
    return marker


def run_rsync(src: Path, dest: Path, *, update: bool = False, delete: bool = False) -> int:
    src_arg = f"{src}/" if src.is_dir() else str(src)
    dest_arg = f"{dest}/" if src.is_dir() else str(dest)
    cmd = ["rsync", "-aL", "--itemize-changes"]
    if update:
        cmd.append("--update")
    if delete:
        cmd.append("--delete")
    cmd.extend([src_arg, dest_arg])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"rsync failed: {' '.join(cmd)}")
    return sum(1 for line in result.stdout.splitlines() if line and line[0] in "<>c*")


def is_valid_skill_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "SKILL.md").is_file():
        return True
    return any(path.rglob("SKILL.md"))


def collect_all_skill_names(skills_src: Path) -> list[str]:
    names: list[str] = []
    if not skills_src.is_dir():
        return names
    for entry in sorted(skills_src.iterdir()):
        if entry.is_dir() and is_valid_skill_dir(entry):
            names.append(entry.name)
    return names


def resolve_skill_src(skills_src: Path, skill_name: str) -> Path | None:
    path = skills_src / skill_name
    if path.is_dir() and is_valid_skill_dir(path):
        return path
    return None


def sync_skill_entry(
    skills_src: Path,
    dest_skills: Path,
    skill_name: str,
    stats: dict,
    warnings: list[str],
) -> None:
    src = resolve_skill_src(skills_src, skill_name)
    if src is None:
        warnings.append(f"skill missing in source: {skill_name}")
        return

    dest_skills.mkdir(parents=True, exist_ok=True)
    target = dest_skills / skill_name
    if target.is_symlink():
        target.unlink()

    if not target.exists():
        run_rsync(src, target)
        stats["skills"]["added"].append(skill_name)
        return

    changes = run_rsync(src, target, update=True)
    if changes > 0:
        stats["skills"]["updated"].append(skill_name)
    else:
        stats["skills"]["skipped"] += 1


def sync_skills_selective(
    skills_src: Path,
    dest_skills: Path,
    skill_names: list[str],
    stats: dict,
    warnings: list[str],
) -> None:
    allowed = set(skill_names)
    for name in skill_names:
        sync_skill_entry(skills_src, dest_skills, name, stats, warnings)

    if not dest_skills.is_dir():
        return
    for entry in dest_skills.iterdir():
        if not entry.is_dir() or not is_valid_skill_dir(entry):
            continue
        if entry.name not in allowed:
            shutil.rmtree(entry)
            stats["skills"]["deleted"].append(entry.name)


def sync_skills_full(skills_src: Path, dest_skills: Path, stats: dict) -> None:
    names = collect_all_skill_names(skills_src)
    allowed = set(names)
    for name in names:
        sync_skill_entry(skills_src, dest_skills, name, stats, [])

    if not dest_skills.is_dir():
        return
    for entry in dest_skills.iterdir():
        if not entry.is_dir() or not is_valid_skill_dir(entry):
            continue
        if entry.name not in allowed:
            shutil.rmtree(entry)
            stats["skills"]["deleted"].append(entry.name)


def normalize_agent_entry(entry: str) -> tuple[str, str]:
    """Return (basename, kind) where kind is 'file' or 'dir'."""
    entry = entry.strip()
    if entry.endswith("/"):
        return entry.rstrip("/"), "dir"
    if entry.endswith(".md"):
        return entry, "file"
    return entry, "file"


def resolve_agent_src(agents_src: Path, entry: str) -> Path | None:
    base, kind = normalize_agent_entry(entry)
    path = agents_src / base
    if kind == "dir":
        return path if path.is_dir() else None
    return path if path.is_file() else None


def sync_agent_entry(
    agents_src: Path,
    dest_agents: Path,
    entry: str,
    stats: dict,
    warnings: list[str],
) -> None:
    base, kind = normalize_agent_entry(entry)
    src = resolve_agent_src(agents_src, entry)
    if src is None:
        warnings.append(f"agent missing in source: {entry}")
        return

    dest_agents.mkdir(parents=True, exist_ok=True)
    target = dest_agents / base

    if kind == "dir":
        if target.is_symlink():
            target.unlink()
        if not target.exists():
            run_rsync(src, target)
            stats["agents"]["added"].append(entry)
            return
        changes = run_rsync(src, target, update=True, delete=True)
        if changes > 0:
            stats["agents"]["updated"].append(entry)
        else:
            stats["agents"]["skipped"] += 1
        return

    if target.is_symlink():
        target.unlink()
    if not target.exists():
        shutil.copy2(src, target)
        stats["agents"]["added"].append(entry)
    elif src.stat().st_mtime_ns > target.stat().st_mtime_ns:
        shutil.copy2(src, target)
        stats["agents"]["updated"].append(entry)
    else:
        stats["agents"]["skipped"] += 1


def allowed_agent_basenames(entries: list[str]) -> set[str]:
    allowed: set[str] = set()
    for entry in entries:
        base, _ = normalize_agent_entry(entry)
        allowed.add(base)
    return allowed


def sync_agents_selective(
    agents_src: Path,
    dest_agents: Path,
    agent_entries: list[str],
    stats: dict,
    warnings: list[str],
) -> None:
    allowed = allowed_agent_basenames(agent_entries)
    for entry in agent_entries:
        sync_agent_entry(agents_src, dest_agents, entry, stats, warnings)

    if not dest_agents.is_dir():
        return
    for entry in dest_agents.iterdir():
        if entry.name in allowed:
            continue
        if entry.is_file() and entry.suffix == ".md":
            entry.unlink()
            stats["agents"]["deleted"].append(entry.name)
        elif entry.is_dir():
            shutil.rmtree(entry)
            stats["agents"]["deleted"].append(f"{entry.name}/")


def sync_agents_full(agents_src: Path, dest_agents: Path, stats: dict) -> None:
    if not agents_src.is_dir():
        return
    dest_agents.mkdir(parents=True, exist_ok=True)
    changes = run_rsync(agents_src, dest_agents, delete=True)
    if changes > 0:
        stats["agents"]["updated"].append("(full mirror)")
    else:
        stats["agents"]["skipped"] += 1


def empty_stats() -> dict:
    return {
        "skills": {"added": [], "updated": [], "deleted": [], "skipped": 0},
        "agents": {"added": [], "updated": [], "deleted": [], "skipped": 0},
    }


def sync_project(
    project_root: Path,
    *,
    skills_src: Path = DEFAULT_CLAUDE_SKILLS,
    agents_src: Path = DEFAULT_CLAUDE_AGENTS,
    profile_override: str | None = None,
) -> dict:
    project_root = project_root.resolve()
    profile_name = profile_override or read_profile_name(project_root)
    profile = load_profile(profile_name)
    sync_mode = profile.get("sync_mode", "selective")

    dest_skills = project_root / ".cursor" / "skills"
    dest_agents = project_root / ".cursor" / "agents"
    stats = empty_stats()
    warnings: list[str] = []

    if sync_mode == "all":
        sync_skills_full(skills_src, dest_skills, stats)
        sync_agents_full(agents_src, dest_agents, stats)
    else:
        sync_skills_selective(
            skills_src, dest_skills, profile.get("skills", []), stats, warnings
        )
        sync_agents_selective(
            agents_src, dest_agents, profile.get("agents", []), stats, warnings
        )

    skill_total = 0
    if dest_skills.is_dir():
        skill_total = sum(1 for _ in dest_skills.rglob("SKILL.md"))

    agent_total = 0
    if dest_agents.is_dir():
        agent_total = sum(1 for _ in dest_agents.rglob("*.md"))

    return {
        "project_root": str(project_root),
        "profile": profile_name,
        "sync_mode": sync_mode,
        "warnings": warnings,
        "stats": stats,
        "totals": {"skills": skill_total, "agents_md": agent_total},
    }


def print_human_report(result: dict) -> None:
    project = result["project_root"]
    profile = result["profile"]
    print(f"Cursor 项目：{project}")
    print(f"  profile：{profile}（{result['sync_mode']}）")

    for label, key in [("skills", "skills"), ("agents", "agents")]:
        s = result["stats"][key]
        print(f"  {label}：")
        if s["added"]:
            print(f"    新增：{', '.join(s['added'])}")
        if s["updated"]:
            print(f"    更新：{', '.join(s['updated'])}")
        if s["deleted"]:
            print(f"    删除：{', '.join(s['deleted'])}")
        print(f"    跳过（已最新）：{s['skipped']} 个")
        total_key = "skills" if key == "skills" else "agents_md"
        print(f"    目标共 {result['totals'][total_key]} 个")

    for warning in result.get("warnings", []):
        print(f"  警告：{warning}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Cursor project skills/agents by profile")
    sub = parser.add_subparsers(dest="command")

    sync_p = sub.add_parser("sync", help="Sync one project")
    sync_p.add_argument("project_root", type=Path)
    sync_p.add_argument("--json", action="store_true")
    sync_p.add_argument("--profile", help="Override .cursor/sync-profile")

    sub.add_parser("list-profiles", help="List available profiles")

    init_p = sub.add_parser("init-profile", help="Write .cursor/sync-profile")
    init_p.add_argument("profile_name")
    init_p.add_argument("project_root", type=Path)

    args = parser.parse_args()
    command = args.command or "sync"

    if command == "list-profiles":
        print(json.dumps(list_profiles(), ensure_ascii=False, indent=2))
        return

    if command == "init-profile":
        marker = init_profile(args.project_root.resolve(), args.profile_name)
        print(f"已写入 {marker}")
        return

    if command == "sync":
        result = sync_project(
            args.project_root,
            profile_override=args.profile,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_human_report(result)
        if result.get("warnings"):
            sys.exit(2)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
