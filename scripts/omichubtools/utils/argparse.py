"""argparse formatter helpers for omichubtools."""

from __future__ import annotations

import argparse

try:
    from rich_argparse import ArgumentDefaultsRichHelpFormatter

    class OmicHubHelpFormatter(ArgumentDefaultsRichHelpFormatter):
        """Rich help formatter with OmicHub-oriented colors and defaults."""

        styles = {
            **ArgumentDefaultsRichHelpFormatter.styles,
            "argparse.args": "bold cyan",
            "argparse.groups": "bold deep_sky_blue1",
            "argparse.help": "default",
            "argparse.metavar": "bold dark_cyan",
            "argparse.prog": "bold magenta",
            "argparse.syntax": "bold",
            "argparse.default": "italic grey62",
        }

except ImportError:  # pragma: no cover - fallback for source-only debugging

    class OmicHubHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        """Fallback formatter when rich-argparse is not installed."""
