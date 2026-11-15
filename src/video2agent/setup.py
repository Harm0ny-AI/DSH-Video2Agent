from __future__ import annotations

import shutil
from pathlib import Path

from .util import Video2AgentError, ensure_dir


def skill_source() -> Path:
    # Installed wheel: src/video2agent/skills/video2agent; repo: skills/video2agent.
    here = Path(__file__).resolve().parent
    for p in (here / "skills" / "video2agent", here.parents[1] / "skills" / "video2agent"):
        if p.exists():
            return p
    raise Video2AgentError("E_SKILL_SOURCE", "Skill source not found.", "Reinstall video2agent, or install the skill manually from the repository.")


def install_skill(target: Path, *, force: bool = False) -> Path:
    src = skill_source()
    target = target.expanduser().resolve()
    if target.exists() and not force:
        # Copy over existing files but keep unrelated local edits.
        ensure_dir(target)
    ensure_dir(target)
    shutil.copytree(src, target, dirs_exist_ok=True)
    return target


def dsh_skill_target(project: bool = False, cwd: str | Path | None = None) -> Path:
    if project:
        base = Path(cwd or Path.cwd()) / ".dsh" / "skills"
    else:
        base = Path.home() / ".dsh" / "skills"
    return base / "video2agent"


def setup_dsh(project: bool = False, force: bool = False, cwd: str | Path | None = None) -> dict:
    target = install_skill(dsh_skill_target(project=project, cwd=cwd), force=force)
    return {
        "ok": True,
        "skill_path": str(target),
        "scope": "project" if project else "global",
        "next": "Restart/reload DSH, then ask it to use the video2agent skill. MCP is optional and not required.",
    }
