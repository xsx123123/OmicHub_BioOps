"""知识库文件同步清单的单元测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


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
