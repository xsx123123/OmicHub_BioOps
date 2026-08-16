"""DocsService 知识库可见性回归测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from omichub.application.services.docs_service import DocsService
from omichub.core.exceptions import NotFoundError


def _scalar_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def test_hidden_managed_docs_are_not_restored_from_meta(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "title": "实验室知识库",
                "items": [
                    {"id": "lab-guide", "title": "实验室指南", "category": "实验室"},
                    {"id": "scseq-guide", "title": "单细胞指南", "category": "单细胞"},
                    {"id": "legacy-guide", "title": "旧文件指南", "category": "兼容"},
                ],
            }
        ),
        encoding="utf-8",
    )

    visible_doc = SimpleNamespace(
        doc_id="lab-guide",
        title="实验室指南",
        category="实验室",
        status=1,
    )
    db = AsyncMock()
    db.execute.return_value = _scalar_result([visible_doc])

    nav = asyncio.run(DocsService(tmp_path).list_knowledge(db))

    assert [item["id"] for item in nav["items"]] == ["lab-guide"]


def test_hidden_knowledge_doc_cannot_be_opened_directly(tmp_path: Path) -> None:
    service = DocsService(tmp_path)
    hidden_doc = SimpleNamespace(doc_id="scseq-guide", kb_id="scseq")
    service._get_document_by_doc_id = AsyncMock(return_value=hidden_doc)
    hidden_base_result = MagicMock()
    hidden_base_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = hidden_base_result

    with pytest.raises(NotFoundError, match="scseq-guide"):
        asyncio.run(service.get_knowledge_doc(db, "scseq-guide"))
