"""pgvector SQLAlchemy type contracts."""

import pytest

from cygnusx.infrastructure.database.vector import Vector


def test_vector_binds_and_reads_pgvector_literals() -> None:
    vector = Vector(3)

    assert vector.get_col_spec() == "vector(3)"
    assert vector.bind_processor(None)([1, 2.5, -3]) == "[1,2.5,-3]"
    assert vector.result_processor(None, None)("[1,2.5,-3]") == [1.0, 2.5, -3.0]


def test_vector_rejects_wrong_dimension_and_non_finite_values() -> None:
    vector = Vector(3)
    bind = vector.bind_processor(None)

    with pytest.raises(ValueError, match="3-dimension"):
        bind([1, 2])
    with pytest.raises(ValueError, match="finite"):
        bind([1, float("nan"), 3])
