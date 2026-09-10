"""Invalidate research caches when code, configuration or raw-file revisions change."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(
    root: Path, config: dict, raw_dir: Path | None = None, features: Path | None = None
) -> str:
    """Hash code/config and input identity. Raw revisions use relative path/size/mtime.

    Feature content itself is SHA256-hashed for downstream runs. Raw archives must
    preserve mtime on unchanged files and update it when replacing a revision.
    """
    code = {str(p.relative_to(root)): file_digest(p) for p in sorted((root / "src").rglob("*.py"))}
    payload: dict = {"config": config, "code": code}
    if raw_dir is not None:
        payload["raw"] = [
            (str(p.relative_to(raw_dir)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(raw_dir.rglob("*"))
            if p.is_file()
        ]
    if features is not None:
        payload["features_sha256"] = file_digest(features)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def cache_matches(manifest: Path, expected: str) -> bool:
    try:
        return bool(json.loads(manifest.read_text())["fingerprint"] == expected)
    except (OSError, ValueError, KeyError):
        return False


def write_manifest(manifest: Path, value: str) -> None:
    manifest.write_text(json.dumps({"fingerprint": value}, indent=2) + "\n")
