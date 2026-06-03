"""CAIAO server migrator — rename, version bump, archive, migrate-to-manifest.

All operations are file-system based and validated before execution.
No server code is modified — only file/directory structure and caiao.yaml.
"""

import os
import shutil
import logging
from datetime import date
from typing import Any

from .manifest import read_manifest, write_manifest, discover_manifests

logger = logging.getLogger(__name__)


def migrate_to_manifest(
    server_dir: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a caiao.yaml manifest for a server that doesn't have one.

    If config is None, creates a minimal manifest with best-guess fields.
    Returns {status, manifest_path} or {error}.
    """
    if not os.path.isdir(server_dir):
        return {"error": f"Directory not found: {server_dir}"}

    existing = read_manifest(server_dir)
    if existing is not None:
        return {"status": "skipped", "reason": "Manifest already exists", "manifest_path": os.path.join(server_dir, "caiao.yaml")}

    from .manifest import generate_manifest_from_server
    data = generate_manifest_from_server(server_dir, config)

    try:
        write_manifest(server_dir, data)
        return {"status": "ok", "manifest_path": os.path.join(server_dir, "caiao.yaml"), "server_name": data["name"]}
    except Exception as e:
        return {"error": str(e)}


def rename_server(
    server_dir: str,
    new_name: str,
    servers_root: str | None = None,
) -> dict[str, Any]:
    """Rename a CAIAO server (directory + manifest + update references).

    This is a safe operation:
    1. Validates the new name is available
    2. Updates the manifest's name field
    3. Renames the directory
    4. Scans other manifests for references and warns about them

    Returns {status, old_name, new_name, warnings}.
    """
    if not os.path.isdir(server_dir):
        return {"error": f"Server directory not found: {server_dir}"}

    manifest = read_manifest(server_dir)
    old_name = manifest.get("name") if manifest else os.path.basename(os.path.normpath(server_dir))

    if servers_root is None:
        servers_root = os.path.dirname(server_dir)

    new_dir = os.path.join(servers_root, new_name)
    if os.path.exists(new_dir):
        return {"error": f"Target directory already exists: {new_dir}"}

    if not _is_valid_server_name(new_name):
        return {"error": f"Invalid server name: '{new_name}'. Use snake_case (lowercase, underscores)."}

    warnings = []
    all_manifests = discover_manifests(servers_root)
    for m in all_manifests:
        refs = _find_references(m, old_name)
        if refs:
            warnings.append({
                "server": m.get("name"),
                "references": refs,
                "message": f"Server '{m.get('name')}' references '{old_name}' in: {refs}",
            })

    try:
        if manifest:
            manifest["name"] = new_name
            write_manifest(server_dir, manifest)

        os.rename(server_dir, new_dir)
        logger.info(f"Renamed server '{old_name}' → '{new_name}'")
        return {
            "status": "ok",
            "old_name": old_name,
            "new_name": new_name,
            "old_dir": server_dir,
            "new_dir": new_dir,
            "warnings": warnings,
            "note": "References in other manifests need manual update" if warnings else None,
        }
    except Exception as e:
        return {"error": str(e)}


def bump_version(server_dir: str, bump: str = "patch") -> dict[str, Any]:
    """Bump the semantic version of a server in its caiao.yaml.

    Args:
        server_dir: Path to the server directory.
        bump: One of 'major', 'minor', 'patch'.

    Returns {status, old_version, new_version}.
    """
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": "No caiao.yaml found — run migrate_to_manifest first"}

    old_version = manifest.get("version", "0.1.0")
    new_version = _bump_semver(old_version, bump)
    manifest["version"] = new_version

    try:
        write_manifest(server_dir, manifest)
        return {"status": "ok", "old_version": old_version, "new_version": new_version, "bump": bump}
    except Exception as e:
        return {"error": str(e)}


def archive_server(server_dir: str, archive_root: str | None = None) -> dict[str, Any]:
    """Archive a server: mark as deprecated in manifest and optionally move to archive directory.

    Returns {status, server_name, archive_path} or {error}.
    """
    manifest = read_manifest(server_dir)
    if manifest is None:
        return {"error": "No caiao.yaml found"}

    manifest["status"] = "deprecated"

    try:
        write_manifest(server_dir, manifest)
        logger.info(f"Marked server '{manifest.get('name')}' as deprecated")
        return {"status": "ok", "server_name": manifest.get("name"), "note": "Marked as deprecated in manifest"}
    except Exception as e:
        return {"error": str(e)}


def bulk_migrate(servers_root: str) -> dict[str, Any]:
    """Run migrate_to_manifest on all server directories that lack a caiao.yaml.

    Uses hardcoded SERVER_CONFIGS as the config source for each server.
    Returns a summary of results.
    """
    results = []
    success_count = 0
    skip_count = 0
    error_count = 0

    if not os.path.isdir(servers_root):
        return {"error": f"Servers directory not found: {servers_root}"}

    for entry in os.scandir(servers_root):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue

        result = migrate_to_manifest(entry.path, config=None)
        results.append({"server": entry.name, **result})

        status = result.get("status", "error")
        if status == "ok":
            success_count += 1
        elif status == "skipped":
            skip_count += 1
        else:
            error_count += 1

    return {
        "status": "ok",
        "total": len(results),
        "created": success_count,
        "skipped": skip_count,
        "errors": error_count,
        "results": results,
    }


def _is_valid_server_name(name: str) -> bool:
    import re
    return bool(re.match(r"^[a-z][a-z0-9_]*$", name))


def _find_references(manifest: dict, target_name: str) -> list[str]:
    """Find all references to target_name in a manifest."""
    refs = []
    for imp in manifest.get("imports", []):
        if target_name in imp.get("module", ""):
            refs.append(f"imports.module: {imp['module']}")
    for step in manifest.get("pipeline", []):
        if step.get("server") == target_name:
            refs.append(f"pipeline.server: {target_name}")
    return refs


def _bump_semver(version: str, bump: str) -> str:
    try:
        parts = version.lstrip("v").split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        if bump == "major":
            major += 1
            minor = 0
            patch = 0
        elif bump == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1
        return f"{major}.{minor}.{patch}"
    except (ValueError, IndexError):
        return "0.2.0"
