"""SiteContentService 单元测试 — 正常解析 / 文件缺失回退 / 字段缺失补齐 / 类型错误回退。"""

from pathlib import Path

import yaml

from omichub.application.services.site_content_service import (
    DEFAULT_CONTENT,
    SiteContentService,
)


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_get_content_returns_yaml_values(tmp_path: Path):
    """yaml 完整时返回 yaml 中的文案。"""
    yaml_path = _write_yaml(
        tmp_path / "OmicHub.yaml",
        {
            "hero": {"title": "自定义标题", "description": "自定义标语"},
            "quick_entries": [{"key": "rna-seq", "title": "RNA", "desc": "转录组"}],
            "guide_steps": [{"title": "步骤一", "desc": "描述一"}],
        },
    )
    content = SiteContentService(yaml_path).get_content()
    assert content.hero.title == "自定义标题"
    assert content.hero.description == "自定义标语"
    assert content.quick_entries[0].title == "RNA"
    assert content.guide_steps[0].title == "步骤一"


def test_get_content_falls_back_when_file_missing(tmp_path: Path):
    """yaml 文件不存在时回退默认文案，不抛异常。"""
    content = SiteContentService(tmp_path / "not-exist.yaml").get_content()
    assert content.hero.title == DEFAULT_CONTENT["hero"]["title"]
    assert content.hero.description == DEFAULT_CONTENT["hero"]["description"]
    assert len(content.quick_entries) == len(DEFAULT_CONTENT["quick_entries"])
    assert len(content.guide_steps) == len(DEFAULT_CONTENT["guide_steps"])


def test_get_content_fills_missing_fields_from_default(tmp_path: Path):
    """yaml 仅给出部分字段时，缺失字段由默认补齐，不报错。"""
    yaml_path = _write_yaml(
        tmp_path / "OmicHub.yaml",
        {
            "hero": {"title": "只有标题"},  # 缺 description
            "quick_entries": [{"key": "ai", "title": "AI", "desc": "助手"}],
        },
    )
    content = SiteContentService(yaml_path).get_content()
    assert content.hero.title == "只有标题"
    # description 缺失 -> 由默认补齐
    assert content.hero.description == DEFAULT_CONTENT["hero"]["description"]
    # guide_steps 整块缺失 -> 由默认补齐
    assert len(content.guide_steps) == len(DEFAULT_CONTENT["guide_steps"])


def test_get_content_falls_back_on_wrong_type(tmp_path: Path):
    """yaml 字段类型错误（hero 为字符串）时整体回退默认，不抛异常。"""
    yaml_path = _write_yaml(tmp_path / "OmicHub.yaml", {"hero": "不是字典"})
    content = SiteContentService(yaml_path).get_content()
    assert content.hero.title == DEFAULT_CONTENT["hero"]["title"]
    assert content.hero.description == DEFAULT_CONTENT["hero"]["description"]


def test_get_content_falls_back_on_invalid_syntax(tmp_path: Path):
    """yaml 语法错误时回退默认文案，不抛异常。"""
    bad = tmp_path / "OmicHub.yaml"
    bad.write_text("hero: [unclosed bracket\n", encoding="utf-8")
    content = SiteContentService(bad).get_content()
    assert content.hero.title == DEFAULT_CONTENT["hero"]["title"]


def test_get_content_includes_registration_defaults(tmp_path: Path):
    """yaml 未配置 registration 时，回退默认提示文案与管理员联系方式。"""
    yaml_path = _write_yaml(
        tmp_path / "OmicHub.yaml",
        {"hero": {"title": "t", "description": "d"}},
    )
    content = SiteContentService(yaml_path).get_content()
    assert (
        content.registration.disabled_message == DEFAULT_CONTENT["registration"]["disabled_message"]
    )
    assert content.registration.admin_contact == ""


def test_get_content_reads_registration_from_yaml(tmp_path: Path):
    """yaml 配置 registration 时返回其中的文案与联系方式。"""
    yaml_path = _write_yaml(
        tmp_path / "OmicHub.yaml",
        {
            "hero": {"title": "t", "description": "d"},
            "registration": {
                "disabled_message": "暂停注册，请联系管理员。",
                "admin_contact": "admin@hzau.edu.cn",
            },
        },
    )
    content = SiteContentService(yaml_path).get_content()
    assert content.registration.disabled_message == "暂停注册，请联系管理员。"
    assert content.registration.admin_contact == "admin@hzau.edu.cn"


def test_get_content_fills_partial_registration_from_default(tmp_path: Path):
    """yaml 仅给出 admin_contact 时，disabled_message 由默认补齐。"""
    yaml_path = _write_yaml(
        tmp_path / "OmicHub.yaml",
        {
            "hero": {"title": "t", "description": "d"},
            "registration": {"admin_contact": "admin@hzau.edu.cn"},
        },
    )
    content = SiteContentService(yaml_path).get_content()
    assert content.registration.admin_contact == "admin@hzau.edu.cn"
    assert (
        content.registration.disabled_message == DEFAULT_CONTENT["registration"]["disabled_message"]
    )
