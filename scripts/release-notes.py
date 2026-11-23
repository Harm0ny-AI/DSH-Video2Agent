#!/usr/bin/env python3
"""Extract one release's notes from CHANGELOG.md.

The GitHub Release body is exactly the current version's
"## X.Y.Z (YYYY-MM-DD)" section: no earlier history, no auto-generated commit
list. Used by .github/workflows/publish.yml (the release job writes the body,
the verify job checks it exists before anything is published). Runnable locally:

    python scripts/release-notes.py --version 0.3.6
    python scripts/release-notes.py --check
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECTION = re.compile(
    r"^##\s+(?P<version>\S+)\s+\((?P<date>\d{4}-\d{2}-\d{2})\)\s*$", re.MULTILINE
)


def extract(text: str, version: str) -> str:
    """Return the section body for the given version, or fail with a clear message."""
    sections = list(SECTION.finditer(text))
    match = next((m for m in sections if m.group("version") == version), None)
    if match is None:
        found = ", ".join(m.group("version") for m in sections) or "none"
        raise SystemExit(
            f"CHANGELOG.md has no dated '## {version} (YYYY-MM-DD)' section "
            f"(found: {found}); date the release entry before tagging"
        )
    rest = text[match.end():]
    following = re.search(r"^##\s+", rest, re.MULTILINE)
    body = (rest[:following.start()] if following else rest).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md section for {version} is empty")
    return body + "\n"


def default_version() -> str:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("pyproject.toml has no project version")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a release's CHANGELOG section.")
    parser.add_argument("--changelog", type=Path, default=REPO / "CHANGELOG.md")
    parser.add_argument("--version", default="", help="defaults to the pyproject version")
    parser.add_argument("--check", action="store_true", help="validate, print nothing")
    args = parser.parse_args()

    version = args.version or default_version()
    body = extract(args.changelog.read_text(encoding="utf-8"), version)
    if args.check:
        print(f"release notes for {version}: {len(body.splitlines())} lines")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
