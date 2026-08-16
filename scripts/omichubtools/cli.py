#!/usr/bin/env python3
"""Command-line entry point for omichubtools."""

from __future__ import annotations

import argparse
import sys

from omichubtools.commands import reference_database
from omichubtools.utils.argparse import OmicHubHelpFormatter
from omichubtools.utils.configuration import load_software_config
from omichubtools.utils.log_utils import logger_init
from omichubtools.utils.logo import config2logo
from omichubtools.utils.version import show_versions


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-logo", action="store_true", help="Do not print the startup logo")
    parser.add_argument("--log-level", default="INFO", help="Console log level")
    parser.add_argument("--config", help="Optional omichubtools YAML override")


def _version_command(args: argparse.Namespace) -> int:
    software_conf = load_software_config(args.config) if args.config else load_software_config()
    sw = software_conf.get("software", {})
    show_versions(
        project_name=sw.get("app_name", "omichubtools"),
        extras={
            "Version": sw.get("version", "unknown"),
            "Author": sw.get("author", "unknown"),
            "URL": sw.get("url", ""),
            "Description": sw.get("description", ""),
        },
        software_conf=software_conf,
    )
    return 0


def _refdb_build_command(args: argparse.Namespace) -> int:
    return reference_database.run_build(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omichubtools",
        description="OmicHub offline maintenance toolkit",
        formatter_class=OmicHubHelpFormatter,
    )
    _add_global_args(parser)
    parser.set_defaults(func=None)

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    version_parser = subparsers.add_parser("version", help="Show version and runtime information")
    version_parser.set_defaults(func=_version_command)

    refdb_parser = subparsers.add_parser("refdb", help="Reference database offline tools")
    refdb_subparsers = refdb_parser.add_subparsers(dest="refdb_command", metavar="REFDB_COMMAND")
    refdb_build = refdb_subparsers.add_parser(
        "build",
        help="Build FA/GFF/GO/KO/KEGG SQLite assets offline",
        formatter_class=OmicHubHelpFormatter,
    )
    reference_database.add_build_arguments(refdb_build)
    refdb_build.set_defaults(func=_refdb_build_command)

    legacy_parser = subparsers.add_parser(
        "build-reference-database",
        help="Alias for: refdb build",
        formatter_class=OmicHubHelpFormatter,
    )
    reference_database.add_build_arguments(legacy_parser)
    legacy_parser.set_defaults(func=_refdb_build_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    software_conf = load_software_config(args.config) if args.config else load_software_config()

    if args.func is None:
        if not args.no_logo:
            config2logo(software_conf)
        parser.print_help()
        return 0

    logger_init(log_level=args.log_level)
    if not args.no_logo:
        config2logo(software_conf)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
