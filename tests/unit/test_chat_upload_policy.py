import pytest

from omichub.api.v1.files import _validate_chat_upload_filename
from omichub.core.exceptions import ValidationError


@pytest.mark.parametrize("filename", ["sample.bam", "sample.cram", "cells.h5ad", "object.rds", "bundle.zip"])
def test_chat_upload_routes_managed_data_files_to_file_management(filename: str) -> None:
    with pytest.raises(ValidationError, match="文件管理"):
        _validate_chat_upload_filename(filename)


@pytest.mark.parametrize("filename", ["plot.png", "metadata.csv", "report.pdf", "genes.fasta"])
def test_chat_upload_keeps_lightweight_files_available(filename: str) -> None:
    _validate_chat_upload_filename(filename)
