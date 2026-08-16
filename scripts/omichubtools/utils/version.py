#!/usr/bin/env python3
"""Version and runtime information display for omichubtools."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

try:
    from rich.console import Console
    from rich.table import Table

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Console = None
    Table = None
    _RICH_AVAILABLE = False

from .configuration import load_software_config


def _find_pyproject() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _get_project_deps() -> list[str]:
    pyproject = _find_pyproject()
    if pyproject is None:
        return []
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    deps = data.get("project", {}).get("dependencies", [])
    names = []
    for dep in deps:
        name = str(dep).split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _get_package_version(package: str) -> str:
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return "Not Found"


def _tool_status(tool: dict) -> str:
    cmd = tool.get("cmd") or tool.get("name")
    if not cmd or shutil.which(str(cmd)) is None:
        return "Not Found"
    version_flag = tool.get("version_flag")
    if not version_flag:
        return "OK"
    result = subprocess.run(
        [str(cmd), str(version_flag)],
        capture_output=True,
        text=True,
        check=False,
    )
    first_line = (result.stdout or result.stderr or "OK").splitlines()[0]
    return first_line[:80]


def show_versions(
    project_name: str | None = None,
    deps: list[str] | None = None,
    extras: dict[str, str] | None = None,
    software_conf: dict | None = None,
) -> None:
    software_conf = software_conf or load_software_config()
    sw = software_conf.get("software", {})
    project_name = project_name or sw.get("app_name", "omichubtools")
    deps = deps if deps is not None else _get_project_deps()
    extras = extras or {
        "Version": sw.get("version", "unknown"),
        "Description": sw.get("description", ""),
    }
    runtime = {
        "Python": sys.version.split("|", 1)[0].strip(),
        "Executable": sys.executable,
        "Platform": platform.platform(),
    }
    for tool in software_conf.get("external_tools", []):
        runtime[f"Tool: {tool.get('name', tool.get('cmd', 'unknown'))}"] = _tool_status(tool)

    if _RICH_AVAILABLE and Console is not None and Table is not None:
        console = Console()
        meta = Table(title=f"{project_name} info")
        meta.add_column("Attribute", style="cyan")
        meta.add_column("Value")
        for key, value in extras.items():
            meta.add_row(str(key), str(value))
        runtime_table = Table(title="Runtime")
        runtime_table.add_column("Component", style="cyan")
        runtime_table.add_column("Details")
        for key, value in runtime.items():
            runtime_table.add_row(str(key), str(value))
        deps_table = Table(title="Python dependencies")
        deps_table.add_column("Package", style="cyan")
        deps_table.add_column("Version")
        for dep in deps:
            deps_table.add_row(dep, _get_package_version(dep))
        console.print(meta)
        console.print(runtime_table)
        console.print(deps_table)
        return

    print(f"{project_name} info")
    for key, value in extras.items():
        print(f"  {key}: {value}")
    print("Runtime")
    for key, value in runtime.items():
        print(f"  {key}: {value}")
    print("Python dependencies")
    for dep in deps:
        print(f"  {dep}: {_get_package_version(dep)}")
