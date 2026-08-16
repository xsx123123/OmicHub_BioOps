"""Load report prompts from the shared OmicHub data directory."""

from __future__ import annotations

import os
from pathlib import Path


def prompt_root() -> Path:
    explicit = os.environ.get("OMICHUB_PROMPT_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "prompts"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "OmicHub prompt root not found; set OMICHUB_PROMPT_ROOT to the mounted data/prompts directory"
    )


def load_report_prompt(name: str) -> str:
    root = prompt_root() / "report"
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"Report prompt path escapes root: {name}")
    return path.read_text(encoding="utf-8").strip()
