"""知识库文件同步清单的单元测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel


def _sync_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "sync_knowledge_from_files.py"
    spec = importlib.util.spec_from_file_location("sync_knowledge_from_files", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expand_knowledge_items_indexes_wiki_and_omits_navigation(tmp_path: Path) -> None:
    section_dir = tmp_path / "docs" / "knowledge"
    wiki_dir = tmp_path / "wiki"
    section_dir.mkdir(parents=True)
    wiki_dir.mkdir()
    (section_dir / "local.md").write_text("# 本地文档\n", encoding="utf-8")
    (wiki_dir / "Home.md").write_text("# Wiki 首页\n", encoding="utf-8")
    (wiki_dir / "_Sidebar.md").write_text("# 导航\n", encoding="utf-8")

    module = _sync_module()
    items = module.expand_knowledge_items(
        {
            "items": [{"id": "local", "title": "本地文档", "file": "local.md"}],
            "collections": [
                {
                    "id_prefix": "wiki",
                    "source_dir": "../../wiki",
                    "exclude": ["_Sidebar.md"],
                    "category": "平台 Wiki",
                    "title_prefix": "Wiki · ",
                }
            ],
        },
        section_dir,
    )

    assert [item["id"] for item in items[:1]] == ["local"]
    wiki_items = [item for item in items if item["id"].startswith("wiki-")]
    assert len(wiki_items) == 1
    assert wiki_items[0]["title"] == "Wiki · Wiki 首页"
    assert Path(wiki_items[0]["source_file"]).name == "Home.md"


@pytest.mark.asyncio
async def test_sync_imports_repository_document_into_lab_knowledge_base(tmp_path: Path) -> None:
    section_dir = tmp_path / "knowledge"
    section_dir.mkdir()
    (section_dir / "guide.md").write_text("# 平台指南\n", encoding="utf-8")
    meta_path = section_dir / "meta.yaml"
    meta_path.write_text(
        "items:\n  - id: platform-guide\n    title: 平台指南\n    file: guide.md\n",
        encoding="utf-8",
    )
    actor_id = uuid4()
    created: list[object] = []
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_with_row(SimpleNamespace(username="platform", nickname="平台")),
            _result_with_scalar(None),
        ]
    )
    session.add.side_effect = created.append

    async def assign_ids() -> None:
        for item in created:
            if isinstance(item, KbDocumentModel) and item.id is None:
                item.id = uuid4()
            if isinstance(item, DocRevisionModel) and item.id is None:
                item.id = uuid4()

    session.flush = AsyncMock(side_effect=assign_ids)
    session.commit = AsyncMock()

    result = await _sync_module().sync(
        meta_path, actor_id, session, index_documents=False
    )

    document = next(item for item in created if isinstance(item, KbDocumentModel))
    revision = next(item for item in created if isinstance(item, DocRevisionModel))
    assert result == (0, 1, 0)
    assert document.kb_id == "lab"
    assert document.created_by == actor_id
    assert revision.edited_by == actor_id


def _result_with_scalar(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _result_with_row(value: object) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = value
    return result
