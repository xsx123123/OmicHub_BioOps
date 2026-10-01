#!/usr/bin/env python3
"""Validate the deployment image inventory against checked-in configuration."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "deploy" / "image-mapping.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-local",
        action="store_true",
        help="also verify that every manifest image exists in the local Docker daemon",
    )
    args = parser.parse_args()

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    images = manifest.get("images", {})

    for image_id, spec in images.items():
        image = spec.get("image")
        if not image:
            errors.append(f"images.{image_id} has no image")
            continue

        dockerfile = ROOT / spec["dockerfile"]
        if not dockerfile.is_file():
            errors.append(f"{image_id}: Dockerfile does not exist: {spec['dockerfile']}")

        for relative_path in spec.get("config_files", []):
            path = ROOT / relative_path
            if not path.is_file():
                errors.append(f"{image_id}: config file does not exist: {relative_path}")
            elif image not in path.read_text(encoding="utf-8"):
                errors.append(f"{image_id}: {image} is missing from {relative_path}")

    for check in manifest.get("content_checks", []):
        relative_path = check["file"]
        path = ROOT / relative_path
        if not path.is_file():
            errors.append(f"content check file does not exist: {relative_path}")
            continue
        content = path.read_text(encoding="utf-8")
        for expected in check.get("contains", []):
            if expected not in content:
                errors.append(f"{relative_path} is missing required text: {expected}")

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for image in manifest.get("makefile_images", []):
        if image not in makefile:
            errors.append(f"Makefile is missing inventory image: {image}")

    if args.check_local:
        for image in dict.fromkeys(spec["image"] for spec in images.values()):
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode:
                errors.append(f"local Docker image is missing: {image}")

    if errors:
        print("Image mapping validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Image mapping validation passed ({len(images)} images).")
    if args.check_local:
        print("Local Docker image inspection passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
