#!/usr/bin/env python3
"""Bump AutoPlan semantic version across all repository manifests on push."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_semver(raw: str) -> Optional[Tuple[int, int, int]]:
    match = SEMVER_RE.match(raw.strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def format_semver(ver: Tuple[int, int, int]) -> str:
    return f"{ver[0]}.{ver[1]}.{ver[2]}"


def read_version_file(root: Path) -> Tuple[int, int, int]:
    version_file = root / "VERSION"
    if not version_file.is_file():
        return (0, 2, 0)
    parsed = parse_semver(version_file.read_text(encoding="utf-8").strip())
    if parsed is None:
        raise ValueError(f"Invalid semantic version in {version_file}")
    return parsed


def max_git_tag_semver(root: Path) -> Tuple[int, int, int]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "tag", "-l", "v*"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return (0, 0, 0)
    if proc.returncode != 0:
        return (0, 0, 0)
    highest = (0, 0, 0)
    for line in proc.stdout.splitlines():
        parsed = parse_semver(line)
        if parsed is not None and parsed > highest:
            highest = parsed
    return highest


def resolve_part(explicit_part: Optional[str], commit_message: str) -> str:
    if explicit_part:
        return explicit_part
    lowered = commit_message.lower()
    if "[bump:major]" in lowered:
        return "major"
    if "[bump:minor]" in lowered:
        return "minor"
    return "patch"


def bump_semver(base: Tuple[int, int, int], part: str) -> Tuple[int, int, int]:
    major, minor, patch = base
    if part == "major":
        return (major + 1, 0, 0)
    if part == "minor":
        return (major, minor + 1, 0)
    if part == "patch":
        return (major, minor, patch + 1)
    raise ValueError(f"Unsupported bump part: {part}")


def update_pyproject(path: Path, version_str: str) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"',
        f'version = "{version_str}"',
        original,
        count=1,
    )
    if count == 0:
        raise RuntimeError(f"Could not find version field in {path}")
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def update_python_init(path: Path, version_str: str) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    if re.search(r'(?m)^__version__\s*=\s*"[^"]+"', original):
        updated = re.sub(
            r'(?m)^__version__\s*=\s*"[^"]+"',
            f'__version__ = "{version_str}"',
            original,
            count=1,
        )
    else:
        suffix = "" if original.endswith("\n") or not original else "\n"
        updated = f'{original}{suffix}__version__ = "{version_str}"\n'
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def update_package_json(path: Path, version_str: str) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'("version"\s*:\s*)"[^"]+"',
        rf'\g<1>"{version_str}"',
        original,
        count=1,
    )
    if count == 0:
        raise RuntimeError(f"Could not find version field in {path}")
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def apply_version_across_repo(root: Path, version_str: str) -> List[str]:
    modified: List[str] = []
    version_file = root / "VERSION"
    desired = f"{version_str}\n"
    if not version_file.is_file() or version_file.read_text(encoding="utf-8") != desired:
        version_file.write_text(desired, encoding="utf-8")
        modified.append("VERSION")

    pyproject = root / "backend" / "pyproject.toml"
    if update_pyproject(pyproject, version_str):
        modified.append("backend/pyproject.toml")

    py_init = root / "backend" / "planaieditor" / "__init__.py"
    if update_python_init(py_init, version_str):
        modified.append("backend/planaieditor/__init__.py")

    for rel_pkg in (
        "nucleus/package.json",
        "frontend/package.json",
        "webclaw/apps/webclaw/package.json",
    ):
        pkg_path = root / rel_pkg
        if update_package_json(pkg_path, version_str):
            modified.append(rel_pkg)

    return modified


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory.",
    )
    parser.add_argument(
        "--part",
        choices=("major", "minor", "patch"),
        default=None,
        help="Semantic version segment to increment (default: patch, or commit tag).",
    )
    parser.add_argument(
        "--set-version",
        type=str,
        default=None,
        help="Explicitly set exact X.Y.Z version instead of incrementing.",
    )
    parser.add_argument(
        "--commit-message",
        type=str,
        default="",
        help="Commit message inspected for [bump:minor] or [bump:major].",
    )
    parser.add_argument(
        "--print-current",
        action="store_true",
        help="Print current VERSION without modifying any files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute next version and print JSON summary without modifying files.",
    )
    parser.add_argument(
        "--write-github-output",
        action="store_true",
        help="Append version, tag, and previous_version to $GITHUB_OUTPUT if set.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    file_ver = read_version_file(root)
    if args.print_current:
        print(format_semver(file_ver))
        return 0

    tag_ver = max_git_tag_semver(root)
    base_ver = max(file_ver, tag_ver)

    if args.set_version:
        parsed_target = parse_semver(args.set_version)
        if parsed_target is None:
            raise SystemExit(f"Invalid --set-version value: {args.set_version}")
        next_ver = parsed_target
        part_used = "explicit"
    else:
        part_used = resolve_part(args.part, args.commit_message)
        next_ver = bump_semver(base_ver, part_used)

    prev_str = format_semver(file_ver)
    next_str = format_semver(next_ver)
    tag_str = f"v{next_str}"

    modified_files: List[str] = []
    if not args.dry_run:
        modified_files = apply_version_across_repo(root, next_str)

    if args.write_github_output:
        gh_out = os.environ.get("GITHUB_OUTPUT", "").strip()
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as fh:
                fh.write(f"previous_version={prev_str}\n")
                fh.write(f"version={next_str}\n")
                fh.write(f"tag={tag_str}\n")

    summary = {
        "previous_version": prev_str,
        "highest_git_tag": format_semver(tag_ver),
        "version": next_str,
        "tag": tag_str,
        "part": part_used,
        "dry_run": args.dry_run,
        "modified_files": modified_files,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
