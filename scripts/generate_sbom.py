#!/usr/bin/env python3
"""Generate and verify a full CycloneDX 1.5 SBOM with every dependency tagged."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata as importlib_metadata
import json
import re
import sys
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_TAG_KEYS = (
    "autoplan:tag",
    "autoplan:ecosystem",
    "autoplan:subsystem",
    "autoplan:scope",
    "autoplan:source-manifest",
)


def normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def make_npm_purl(name: str, version: str) -> str:
    if name.startswith("@") and "/" in name:
        scope, pkg = name.split("/", 1)
        return f"pkg:npm/{quote(scope, safe='')}/{quote(pkg, safe='')}@{quote(version, safe='')}"
    return f"pkg:npm/{quote(name, safe='')}@{quote(version, safe='')}"


def make_pypi_purl(name: str, version: str) -> str:
    norm = normalize_pypi_name(name)
    return f"pkg:pypi/{quote(norm, safe='')}@{quote(version, safe='')}"


def parse_sri_hash(integrity: str) -> Optional[Dict[str, str]]:
    """Convert npm/pnpm SRI integrity (e.g. sha512-base64==) to CycloneDX hash."""
    raw = (integrity or "").strip()
    if not raw or "-" not in raw:
        return None
    token = raw.split()[0]
    alg_raw, b64_part = token.split("-", 1)
    alg_map = {
        "sha512": "SHA-512",
        "sha384": "SHA-384",
        "sha256": "SHA-256",
        "sha1": "SHA-1",
    }
    cdx_alg = alg_map.get(alg_raw.lower())
    if not cdx_alg:
        return None
    try:
        digest_hex = base64.b64decode(b64_part).hex()
    except Exception:
        return None
    if not digest_hex:
        return None
    return {"alg": cdx_alg, "content": digest_hex}


def build_properties(
    *,
    tag: str,
    ecosystem: str,
    subsystem: str,
    scope: str,
    source_manifest: str,
    extra: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    props = [
        {"name": "autoplan:tag", "value": tag},
        {"name": "autoplan:ecosystem", "value": ecosystem},
        {"name": "autoplan:subsystem", "value": subsystem},
        {"name": "autoplan:scope", "value": scope},
        {"name": "autoplan:source-manifest", "value": source_manifest},
    ]
    if extra:
        for k, v in sorted(extra.items()):
            if v:
                props.append({"name": k, "value": str(v)})
    return props


def collect_python_components(
    root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """Collect Python dependencies from backend/poetry.lock + active Python env."""
    poetry_lock = root / "backend" / "poetry.lock"
    installed_versions: Dict[str, Tuple[str, str]] = {}
    for dist in importlib_metadata.distributions():
        raw_name = dist.metadata.get("Name") or ""
        raw_ver = dist.version or ""
        if not raw_name or not raw_ver:
            continue
        norm = normalize_pypi_name(raw_name)
        lic = (dist.metadata.get("License") or "").strip()
        if lic and "\n" in lic:
            lic = lic.splitlines()[0].strip()[:120]
        installed_versions[norm] = (raw_ver, lic)

    components_by_ref: Dict[str, Dict[str, Any]] = {}
    dep_edges: Dict[str, List[str]] = {}
    poetry_ref_by_norm: Dict[str, str] = {}
    raw_poetry_deps: List[Tuple[str, List[str]]] = []

    if poetry_lock.is_file():
        lock_data = tomllib.loads(poetry_lock.read_text(encoding="utf-8"))
        for pkg in lock_data.get("package", []):
            name = str(pkg.get("name") or "").strip()
            version = str(pkg.get("version") or "").strip()
            if not name or not version:
                continue
            norm = normalize_pypi_name(name)
            groups = [str(g) for g in (pkg.get("groups") or ["main"])]
            is_runtime = "main" in groups or norm in installed_versions
            subsystem = "backend-binary" if is_runtime else "backend-dev"
            scope_tag = "runtime" if is_runtime else "dev"
            cdx_scope = "required" if is_runtime else "optional"
            purl = make_pypi_purl(norm, version)
            bom_ref = f"{purl}#subsystem={subsystem}"

            hashes: List[Dict[str, str]] = []
            for f_entry in (pkg.get("files") or [])[:2]:
                h = str(f_entry.get("hash") or "")
                if h.startswith("sha256:"):
                    hashes.append({"alg": "SHA-256", "content": h.split(":", 1)[1]})
                    break

            _, inst_lic = installed_versions.get(norm, ("", ""))
            comp: Dict[str, Any] = {
                "type": "library",
                "bom-ref": bom_ref,
                "name": norm,
                "version": version,
                "scope": cdx_scope,
                "purl": purl,
                "properties": build_properties(
                    tag=f"dep:pypi:{subsystem}:{norm}@{version}",
                    ecosystem="pypi",
                    subsystem=subsystem,
                    scope=scope_tag,
                    source_manifest="backend/poetry.lock",
                    extra={"autoplan:poetry-groups": ",".join(sorted(groups))},
                ),
            }
            desc = str(pkg.get("description") or "").strip()
            if desc:
                comp["description"] = desc
            if hashes:
                comp["hashes"] = hashes
            if inst_lic and inst_lic.upper() != "UNKNOWN":
                comp["licenses"] = [{"license": {"name": inst_lic[:120]}}]

            components_by_ref[bom_ref] = comp
            poetry_ref_by_norm[norm] = bom_ref
            child_norms = [
                normalize_pypi_name(dep_name)
                for dep_name in (pkg.get("dependencies") or {}).keys()
            ]
            raw_poetry_deps.append((bom_ref, child_norms))

    # Add any active build-environment packages not already at the same version in poetry.lock
    # (for example pyinstaller, altgraph, macholib, packaging, simple-websocket)
    for norm, (ver, inst_lic) in sorted(installed_versions.items()):
        if norm == "planaieditor":
            continue
        purl = make_pypi_purl(norm, ver)
        existing_ref = poetry_ref_by_norm.get(norm)
        if existing_ref and components_by_ref[existing_ref]["version"] == ver:
            continue
        bom_ref = f"{purl}#subsystem=backend-build-env"
        comp = {
            "type": "library",
            "bom-ref": bom_ref,
            "name": norm,
            "version": ver,
            "scope": "required",
            "purl": purl,
            "properties": build_properties(
                tag=f"dep:pypi:backend-build-env:{norm}@{ver}",
                ecosystem="pypi",
                subsystem="backend-build-env",
                scope="build-runtime",
                source_manifest="python-build-environment",
            ),
        }
        if inst_lic and inst_lic.upper() != "UNKNOWN":
            comp["licenses"] = [{"license": {"name": inst_lic[:120]}}]
        components_by_ref[bom_ref] = comp
        poetry_ref_by_norm.setdefault(norm, bom_ref)

    for parent_ref, child_norms in raw_poetry_deps:
        resolved_children = sorted(
            {
                poetry_ref_by_norm[c]
                for c in child_norms
                if c in poetry_ref_by_norm and poetry_ref_by_norm[c] != parent_ref
            }
        )
        dep_edges[parent_ref] = resolved_children

    for ref in components_by_ref:
        dep_edges.setdefault(ref, [])

    return list(components_by_ref.values()), dep_edges


def extract_npm_name_from_lock_key(path_key: str, entry: Dict[str, Any]) -> str:
    explicit = str(entry.get("name") or "").strip()
    if explicit:
        return explicit
    marker = "node_modules/"
    idx = path_key.rfind(marker)
    if idx != -1:
        return path_key[idx + len(marker) :].strip("/")
    return path_key.strip("/")


def collect_npm_package_lock(
    lock_path: Path,
    *,
    subsystem: str,
    rel_manifest: str,
) -> List[Dict[str, Any]]:
    if not lock_path.is_file():
        return []
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = data.get("packages") or {}
    seen: Dict[str, Dict[str, Any]] = {}
    for path_key, entry in packages.items():
        if path_key == "" or not isinstance(entry, dict):
            continue
        if entry.get("link"):
            continue
        name = extract_npm_name_from_lock_key(path_key, entry)
        version = str(entry.get("version") or "").strip()
        if not name or not version:
            continue
        is_dev = bool(entry.get("dev", False))
        scope_tag = "dev" if is_dev else "runtime"
        cdx_scope = "optional" if is_dev else "required"
        purl = make_npm_purl(name, version)
        bom_ref = f"{purl}#subsystem={subsystem}"
        if bom_ref in seen:
            continue
        comp: Dict[str, Any] = {
            "type": "library",
            "bom-ref": bom_ref,
            "name": name,
            "version": version,
            "scope": cdx_scope,
            "purl": purl,
            "properties": build_properties(
                tag=f"dep:npm:{subsystem}:{name}@{version}",
                ecosystem="npm",
                subsystem=subsystem,
                scope=scope_tag,
                source_manifest=rel_manifest,
            ),
        }
        h = parse_sri_hash(str(entry.get("integrity") or ""))
        if h:
            comp["hashes"] = [h]
        lic = str(entry.get("license") or "").strip()
        if lic:
            comp["licenses"] = [{"license": {"name": lic[:120]}}]
        seen[bom_ref] = comp
    return list(seen.values())


PNPM_PKG_HEADER_RE = re.compile(r"^  (?:'([^']+)'|\"([^\"]+)\"|([^\s:]+)):\s*$")
PNPM_INTEGRITY_RE = re.compile(r"integrity:\s*([^\s,}]+)")


def split_pnpm_pkg_key(raw_key: str) -> Optional[Tuple[str, str]]:
    key = raw_key.strip()
    if not key or "@" not in key:
        return None
    if key.startswith("@"):
        at_idx = key.find("@", 1)
    else:
        at_idx = key.find("@")
    if at_idx <= 0:
        return None
    name = key[:at_idx]
    ver_raw = key[at_idx + 1 :]
    # Strip peer suffix if any, e.g. 1.2.3(react@19.0.0)
    version = ver_raw.split("(", 1)[0].strip()
    if not name or not version or version.startswith(("file:", "link:", "workspace:")):
        return None
    return (name, version)


def collect_pnpm_lock(
    lock_path: Path,
    *,
    subsystem: str,
    rel_manifest: str,
) -> List[Dict[str, Any]]:
    if not lock_path.is_file():
        return []
    seen: Dict[str, Dict[str, Any]] = {}
    in_packages = False
    current_ref: Optional[str] = None

    for line in lock_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("packages:"):
            in_packages = True
            current_ref = None
            continue
        if in_packages and line and not line.startswith(" "):
            # Reached next top-level YAML section (e.g. snapshots:)
            break
        if not in_packages:
            continue

        header_match = PNPM_PKG_HEADER_RE.match(line)
        if header_match:
            raw_key = (
                header_match.group(1)
                or header_match.group(2)
                or header_match.group(3)
                or ""
            )
            parsed = split_pnpm_pkg_key(raw_key)
            if parsed is None:
                current_ref = None
                continue
            name, version = parsed
            purl = make_npm_purl(name, version)
            bom_ref = f"{purl}#subsystem={subsystem}"
            current_ref = bom_ref
            if bom_ref not in seen:
                seen[bom_ref] = {
                    "type": "library",
                    "bom-ref": bom_ref,
                    "name": name,
                    "version": version,
                    "scope": "optional",
                    "purl": purl,
                    "properties": build_properties(
                        tag=f"dep:npm:{subsystem}:{name}@{version}",
                        ecosystem="npm",
                        subsystem=subsystem,
                        scope="workspace",
                        source_manifest=rel_manifest,
                    ),
                }
            continue

        if current_ref and current_ref in seen and "integrity:" in line:
            int_match = PNPM_INTEGRITY_RE.search(line)
            if int_match:
                h = parse_sri_hash(int_match.group(1))
                if h:
                    seen[current_ref]["hashes"] = [h]

    return list(seen.values())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_sbom(
    *,
    root: Path,
    version: str,
    target: str,
    binary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    py_components, py_dep_edges = collect_python_components(root)
    fe_components = collect_npm_package_lock(
        root / "frontend" / "package-lock.json",
        subsystem="frontend-static",
        rel_manifest="frontend/package-lock.json",
    )
    wc_components = collect_pnpm_lock(
        root / "webclaw" / "pnpm-lock.yaml",
        subsystem="webclaw",
        rel_manifest="webclaw/pnpm-lock.yaml",
    )
    nuc_components = collect_npm_package_lock(
        root / "nucleus" / "package-lock.json",
        subsystem="nucleus-desktop",
        rel_manifest="nucleus/package-lock.json",
    )

    all_components = sorted(
        [*py_components, *fe_components, *wc_components, *nuc_components],
        key=lambda c: c["bom-ref"],
    )

    root_ref = f"pkg:generic/autoplan@{version}?target={target}"
    root_component: Dict[str, Any] = {
        "type": "application",
        "bom-ref": root_ref,
        "name": "autoplan",
        "version": version,
        "purl": root_ref,
        "properties": build_properties(
            tag=f"app:autoplan@{version}:{target}",
            ecosystem="generic",
            subsystem="release-binary",
            scope="application",
            source_manifest="VERSION",
            extra={"autoplan:target": target},
        ),
    }
    if binary_path and binary_path.is_file():
        root_component["hashes"] = [
            {"alg": "SHA-256", "content": sha256_file(binary_path)}
        ]

    dependencies: List[Dict[str, Any]] = [
        {
            "ref": root_ref,
            "dependsOn": [c["bom-ref"] for c in all_components],
        }
    ]
    for comp in all_components:
        ref = comp["bom-ref"]
        dependencies.append(
            {
                "ref": ref,
                "dependsOn": py_dep_edges.get(ref, []),
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": [
                {
                    "vendor": "autoplan",
                    "name": "generate_sbom.py",
                    "version": version,
                }
            ],
            "component": root_component,
        },
        "components": all_components,
        "dependencies": dependencies,
    }


def verify_sbom_file(sbom_path: Path) -> Dict[str, Any]:
    if not sbom_path.is_file():
        raise AssertionError(f"SBOM file does not exist: {sbom_path}")
    size_bytes = sbom_path.stat().st_size
    if size_bytes >= 16 * 1024 * 1024:
        raise AssertionError(
            f"SBOM size {size_bytes} exceeds GitHub attestation 16MB limit"
        )
    doc = json.loads(sbom_path.read_text(encoding="utf-8"))
    if doc.get("bomFormat") != "CycloneDX":
        raise AssertionError(f"Unexpected bomFormat: {doc.get('bomFormat')}")
    if doc.get("specVersion") != "1.5":
        raise AssertionError(f"Unexpected specVersion: {doc.get('specVersion')}")
    serial = str(doc.get("serialNumber") or "")
    if not serial.startswith("urn:uuid:"):
        raise AssertionError(f"Invalid serialNumber: {serial}")

    components = doc.get("components") or []
    if len(components) < 100:
        raise AssertionError(
            f"Expected full dependency inventory (>=100 components), got {len(components)}"
        )

    seen_refs: Set[str] = set()
    by_subsystem: Dict[str, int] = {}
    for idx, comp in enumerate(components):
        ref = str(comp.get("bom-ref") or "").strip()
        name = str(comp.get("name") or "").strip()
        ver = str(comp.get("version") or "").strip()
        purl = str(comp.get("purl") or "").strip()
        if not ref or not name or not ver or not purl.startswith("pkg:"):
            raise AssertionError(
                f"Component #{idx} missing required identity fields: {comp}"
            )
        if ref in seen_refs:
            raise AssertionError(f"Duplicate bom-ref in SBOM: {ref}")
        seen_refs.add(ref)

        props = {
            str(p.get("name") or ""): str(p.get("value") or "")
            for p in (comp.get("properties") or [])
            if isinstance(p, dict)
        }
        for req_key in REQUIRED_TAG_KEYS:
            if not props.get(req_key):
                raise AssertionError(
                    f"Component '{ref}' missing required tag '{req_key}'"
                )
        subsys = props["autoplan:subsystem"]
        by_subsystem[subsys] = by_subsystem.get(subsys, 0) + 1

    for expected_subsys in ("backend-binary", "frontend-static", "webclaw"):
        if by_subsystem.get(expected_subsys, 0) == 0:
            raise AssertionError(
                f"Expected tagged dependencies for subsystem '{expected_subsys}', got {by_subsystem}"
            )

    return {
        "valid": True,
        "sbom_path": str(sbom_path),
        "size_bytes": size_bytes,
        "total_components": len(components),
        "all_components_tagged": True,
        "subsystems": by_subsystem,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Release version string (defaults to VERSION file).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=sys.platform,
        help="Build target identifier (e.g. linux-x86_64, darwin-arm64).",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="Optional path to built binary to attach root SHA-256 digest.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output CycloneDX JSON path.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run strict schema and 100%% dependency-tag assertions after writing.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    version = args.version or (root / "VERSION").read_text(encoding="utf-8").strip()
    sbom_doc = generate_sbom(
        root=root,
        version=version,
        target=args.target,
        binary_path=args.binary,
    )
    out_path = args.output.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sbom_doc, indent=2) + "\n", encoding="utf-8")

    if args.verify:
        report = verify_sbom_file(out_path)
        print(json.dumps(report))
    else:
        print(
            json.dumps(
                {
                    "sbom_path": str(out_path),
                    "total_components": len(sbom_doc["components"]),
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
