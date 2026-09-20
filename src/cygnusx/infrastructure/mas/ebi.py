"""Safe EBIDownload invocation and manifest generation for MAS run workspaces."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class EBIDownloadError(ValueError):
    """Raised when an MAS download request falls outside the fixed public-data contract."""


_ACCESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DOWNLOAD_METHODS = frozenset({"aws", "aspera", "ftp"})


def build_ebi_download_command(
    *,
    binary: str,
    yaml_path: str,
    accession: str,
    output_directory: Path,
    method: str = "aws",
    multithreads: int = 4,
    aws_threads: int = 8,
) -> list[str]:
    if not _ACCESSION_PATTERN.fullmatch(accession):
        raise EBIDownloadError("accession contains unsupported characters")
    if method not in _DOWNLOAD_METHODS:
        raise EBIDownloadError("download method is not allowlisted")
    if not 1 <= multithreads <= 32 or not 1 <= aws_threads <= 64:
        raise EBIDownloadError("download thread settings exceed the MAS limits")
    if not str(binary).strip() or not str(yaml_path).strip():
        raise EBIDownloadError("EBIDownload binary and YAML configuration are required")
    return [
        binary,
        "--yaml",
        yaml_path,
        "--log-format",
        "json",
        "download",
        "-A",
        accession,
        "-o",
        str(output_directory),
        "-d",
        method,
        "-p",
        str(multithreads),
        "-t",
        str(aws_threads),
    ]


def write_download_manifest(staging_directory: Path, manifest_path: Path, accession: str) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(staging_directory.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        files.append(
            {
                "path": str(path.relative_to(staging_directory)),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not files:
        raise EBIDownloadError("EBIDownload completed without any data files")
    manifest = {"schema_version": "1.0", "accession": accession, "files": files}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
