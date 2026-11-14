#!/usr/bin/env python3
"""Build a standalone runnable AutoPlan single-file binary via PyInstaller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_target() -> str:
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    if sys_name == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"darwin-{arch}"
    if sys_name == "linux":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"linux-{arch}"
    return f"{sys_name}-{machine}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_frontend(root: Path) -> Path:
    frontend_dir = root / "frontend"
    static_dest = root / "backend" / "planaieditor" / "static_frontend"
    node_env = {**os.environ}
    existing_opts = node_env.get("NODE_OPTIONS", "").strip()
    if "--max-old-space-size" not in existing_opts:
        node_env["NODE_OPTIONS"] = f"{existing_opts} --max-old-space-size=6144".strip()
    if not (frontend_dir / "node_modules").is_dir():
        subprocess.run(
            ["npm", "ci"],
            cwd=str(frontend_dir),
            env=node_env,
            check=True,
        )
    subprocess.run(
        ["npm", "run", "build"],
        cwd=str(frontend_dir),
        env=node_env,
        check=True,
    )
    build_out = frontend_dir / "build"
    if not (build_out / "index.html").is_file():
        raise RuntimeError(f"Frontend build did not produce {build_out / 'index.html'}")

    if static_dest.exists():
        shutil.rmtree(static_dest)
    shutil.copytree(
        build_out,
        static_dest,
        ignore=shutil.ignore_patterns("*.map"),
    )
    return static_dest


def strip_sourcemaps_if_present(static_dest: Path) -> None:
    if not static_dest.is_dir():
        return
    for map_file in static_dest.rglob("*.map"):
        map_file.unlink(missing_ok=True)


def discover_mypyc_hidden_imports(python_exe: str) -> list[str]:
    """Discover top-level *__mypyc* compiled extension modules in target Python's site-packages."""
    probe = (
        "import json, pathlib, site; "
        "mods = sorted({p.name.split('.')[0] for sp in site.getsitepackages() "
        "if pathlib.Path(sp).is_dir() for p in pathlib.Path(sp).glob('*__mypyc*')}); "
        "print(json.dumps(mods))"
    )
    proc = subprocess.run(
        [python_exe, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    return list(json.loads(proc.stdout.strip() or "[]"))


def discover_dist_metadata_names(python_exe: str) -> list[str]:
    """Discover installed distribution names so importlib.metadata.version() works inside frozen binaries."""
    probe = (
        "import importlib.metadata as m, json; "
        "skip = {'pytest', 'pytest-playwright', 'pytest-cov', 'playwright', 'pyinstaller', "
        "'pyinstaller-hooks-contrib', 'flake8', 'pre-commit', 'planaieditor'}; "
        "names = sorted({(d.metadata.get('Name') or '').strip() for d in m.distributions() "
        "if (d.metadata.get('Name') or '').strip() and (d.metadata.get('Name') or '').strip().lower() not in skip}); "
        "print(json.dumps(names))"
    )
    proc = subprocess.run(
        [python_exe, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    return list(json.loads(proc.stdout.strip() or "[]"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--target", type=str, default=default_target())
    parser.add_argument(
        "--python",
        type=Path,
        default=None,
        help="Python interpreter with backend deps + PyInstaller installed.",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Reuse existing backend/planaieditor/static_frontend if already built.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="Output directory for built binary (default: <root>/dist/bin).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    python_exe = os.path.abspath(str(args.python)) if args.python else sys.executable
    static_dir = root / "backend" / "planaieditor" / "static_frontend"

    if args.skip_frontend_build and (static_dir / "index.html").is_file():
        strip_sourcemaps_if_present(static_dir)
    else:
        build_frontend(root)

    if not (static_dir / "index.html").is_file():
        raise RuntimeError(
            f"Missing bundled frontend index.html at {static_dir / 'index.html'}"
        )

    dist_dir = (args.dist_dir or (root / "dist" / "bin")).resolve()
    work_dir = (root / "build" / f"pyinstaller-{args.target}").resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    binary_name = f"autoplan-{args.target}"
    sep = os.pathsep
    backend_dir = root / "backend"
    entry_script = backend_dir / "run_autoplan_binary.py"
    snippets_dir = backend_dir / "planaieditor" / "codesnippets"
    swift_bridge = backend_dir / "planaieditor" / "apple_fm_bridge.swift"

    mypyc_imports = discover_mypyc_hidden_imports(python_exe)
    mypyc_flags: list[str] = []
    for mod_name in mypyc_imports:
        mypyc_flags.extend(["--hidden-import", mod_name])

    metadata_flags: list[str] = []
    for dist_name in discover_dist_metadata_names(python_exe):
        metadata_flags.extend(["--copy-metadata", dist_name])

    cmd = [
        python_exe,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        binary_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--paths",
        str(backend_dir),
        "--collect-submodules",
        "planaieditor",
        "--collect-submodules",
        "planai",
        "--collect-data",
        "planai",
        "--collect-submodules",
        "llm_interface",
        "--collect-all",
        "black",
        "--collect-submodules",
        "blib2to3",
        "--collect-submodules",
        "isort",
        "--hidden-import",
        "engineio.async_drivers.threading",
        "--hidden-import",
        "simple_websocket",
        "--hidden-import",
        "wsproto",
        *mypyc_flags,
        *metadata_flags,
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "playwright",
        "--add-data",
        f"{snippets_dir}{sep}planaieditor/codesnippets",
        "--add-data",
        f"{swift_bridge}{sep}planaieditor",
        "--add-data",
        f"{static_dir}{sep}planaieditor/static_frontend",
        str(entry_script),
    ]
    subprocess.run(cmd, cwd=str(root), check=True)

    binary_path = dist_dir / binary_name
    if not binary_path.is_file():
        raise RuntimeError(f"Expected binary was not created at {binary_path}")

    binary_path.chmod(0o755)
    size_bytes = binary_path.stat().st_size
    if size_bytes < 5 * 1024 * 1024:
        raise RuntimeError(
            f"Built binary {binary_path} looks unexpectedly small ({size_bytes} bytes)"
        )

    digest = sha256_file(binary_path)
    checksum_file = dist_dir / f"{binary_name}.sha256"
    checksum_file.write_text(f"{digest}  {binary_name}\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "binary_path": str(binary_path),
                "binary_name": binary_name,
                "size_bytes": size_bytes,
                "sha256": digest,
                "checksum_file": str(checksum_file),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
