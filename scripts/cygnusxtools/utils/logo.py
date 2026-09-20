#!/usr/bin/env python3
"""Logo display helpers for cygnusxtools.

The structure mirrors the gpse ``LogoDisplay`` utility while using CygnusX
metadata and graceful fallbacks when rich/rich-gradient are not installed.
"""

from __future__ import annotations

import random
import textwrap

try:
    from rich.align import Align
    from rich.console import Console
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback for minimal environments
    Align = None
    Console = None
    Text = None
    _RICH_AVAILABLE = False

try:
    from rich_gradient import Gradient
    from rich_gradient import Text as GradientText

    _GRADIENT_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Gradient = None
    GradientText = None
    _GRADIENT_AVAILABLE = False


class LogoDisplay:
    GRADIENT_SCHEMES = {
        "ocean": ["#00CED1", "#1E90FF", "#000080"],
        "galaxy": ["#483D8B", "#6A5ACD", "#9370DB"],
        "mint": ["#98FF98", "#00FA9A", "#00CED1"],
        "cyber": ["#00FFFF", "#00FF00", "#FFFF00"],
    }

    def __init__(
        self,
        version: str = "0.1.0",
        app_name: str = "cygnusxtools",
        description: str = "CygnusX offline maintenance toolkit",
        url: str = "",
        rice_color: str = "bold cyan",
        gradient_colors: list[str] | None = None,
        use_gradient: bool = True,
        gradient_scheme: str | None = "galaxy",
    ) -> None:
        self.console = Console() if _RICH_AVAILABLE else None
        self.app_name = app_name
        self.version = version
        self.description = description
        self.url = url
        self.rice_color = rice_color
        self.use_gradient = bool(use_gradient and _GRADIENT_AVAILABLE)
        if gradient_scheme == "random":
            scheme_name = random.choice(list(self.GRADIENT_SCHEMES.keys()))
            self.gradient_colors = self.GRADIENT_SCHEMES[scheme_name]
        elif gradient_scheme and gradient_scheme in self.GRADIENT_SCHEMES:
            self.gradient_colors = self.GRADIENT_SCHEMES[gradient_scheme]
        elif gradient_colors:
            self.gradient_colors = gradient_colors
        else:
            self.gradient_colors = ["cyan", "magenta", "yellow"]

    def create_ascii_logo(self) -> str:
        logos = [
            r"""
            █▀█ █▀▄▀█ █ █▀▀ █ █ █ █▄▄
            █▄█ █ ▀ █ █ █▄▄ █▀█ █ █▄█
                    T O O L S
            """,
            r"""
            ┌─ CygnusXTools ─────────────────┐
            │ Build • Register • Maintain    │
            └────────────────────────────────┘
            """,
        ]
        return textwrap.dedent(random.choice(logos)).strip("\n")

    def display_welcome_logo(self) -> None:
        url_line = f"\n{self.url}" if self.url else ""
        full_text_content = (
            f"{self.create_ascii_logo()}\n"
            f"{self.app_name}: {self.version}\n"
            f"{self.description}{url_line}\n"
        )
        if not _RICH_AVAILABLE or self.console is None:
            print(full_text_content)
            return
        if self.use_gradient and Gradient is not None:
            text = Gradient(full_text_content, colors=self.gradient_colors)
        else:
            text = Text(full_text_content)
            text.stylize(self.rice_color)
        self.console.print(text)

    def display_mini_logo(self) -> None:
        logo_content = f"{self.app_name}: {self.version}"
        if not _RICH_AVAILABLE or self.console is None:
            print(logo_content)
            return
        if self.use_gradient and GradientText is not None:
            mini_logo = GradientText(logo_content, colors=self.gradient_colors)
        else:
            mini_logo = Text(logo_content, style="bold")
        self.console.print(Align.center(mini_logo))


def show_logo(
    style: str = "welcome",
    version: str = "0.1.0",
    app_name: str = "cygnusxtools",
    description: str = "CygnusX offline maintenance toolkit",
    url: str = "",
    rice_color: str = "bold cyan",
    use_gradient: bool = True,
    gradient_colors: list[str] | None = None,
    gradient_scheme: str = "galaxy",
) -> None:
    logo = LogoDisplay(
        version=version,
        app_name=app_name,
        description=description,
        url=url,
        rice_color=rice_color,
        use_gradient=use_gradient,
        gradient_colors=gradient_colors,
        gradient_scheme=gradient_scheme,
    )
    if style == "mini":
        logo.display_mini_logo()
    else:
        logo.display_welcome_logo()


def config2logo(config: dict | None = None) -> None:
    config = config or {}
    sw = config.get("software", config)
    show_logo(
        "welcome",
        version=sw.get("version", "unknown"),
        app_name=sw.get("app_name", "cygnusxtools"),
        description=sw.get("description", ""),
        url=sw.get("url", ""),
        rice_color=sw.get("rice_color", "bold cyan"),
        use_gradient=True,
        gradient_scheme="galaxy",
    )
