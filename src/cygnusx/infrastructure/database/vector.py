"""Minimal PostgreSQL pgvector SQLAlchemy type support.

Keeping this local avoids making the application import depend on the optional
``pgvector`` Python package while still mapping vector columns correctly.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    """PostgreSQL ``vector(dimensions)`` column type."""

    cache_ok = True

    class comparator_factory(UserDefinedType.Comparator[list[float]]):  # noqa: N801
        def cosine_distance(self, other: list[float]):
            return self.expr.op("<=>")(other)

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kwargs: Any) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, _dialect: Any):
        def process(value: list[float] | tuple[float, ...] | None) -> str | None:
            if value is None:
                return None
            values = [float(item) for item in value]
            if len(values) != self.dimensions:
                raise ValueError(
                    f"Expected a {self.dimensions}-dimension vector, received {len(values)} values"
                )
            if not all(math.isfinite(item) for item in values):
                raise ValueError("Vector values must be finite numbers")
            return "[" + ",".join(format(item, ".12g") for item in values) + "]"

        return process

    def result_processor(self, _dialect: Any, _coltype: Any):
        def process(value: str | list[float] | None) -> list[float] | None:
            if value is None or isinstance(value, list):
                return value
            return [float(item) for item in value.strip("[]").split(",") if item]

        return process
