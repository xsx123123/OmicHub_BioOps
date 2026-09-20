"""Agent Skills 开放格式（SKILL.md）解析与校验

一个技能 = 一个文件夹：
    SKILL.md            YAML frontmatter（name/description 必填）+ Markdown 正文（L2 指令）
    scripts/            可选可执行脚本（L3，代码不进上下文，仅回收执行输出）
    references/         可选参考文档（L3，按需读取）
    assets/             可选静态资源（L3）

参考：Anthropic Agent Skills（2025-10）事实标准，Claude Code / Codex / Cursor 兼容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

SKILL_MD_NAME = "SKILL.md"

# 单技能文件总量上限（防上下文炸弹 / 磁盘占用失控）
MAX_FOLDER_BYTES = 1024 * 1024  # 1 MiB
MAX_FILE_BYTES = 512 * 1024
# 正文建议长度（超过则提示拆分到 references/）；按 1 token≈4 字符估算 5000 tokens
BODY_SOFT_LIMIT_CHARS = 20_000

# 脚本危险模式（静态扫描，仅告警不拦截——治理层要求"安装前审查"）
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/(?!tmp|var/tmp)", "疑似删除根目录的 rm -rf"),
    (r"curl[^\n|]*\|\s*(ba|z|da)?sh", "curl 管道直接执行远程脚本"),
    (r"wget[^\n|]*\|\s*(ba|z|da)?sh", "wget 管道直接执行远程脚本"),
    (r"\bmkfs\b", "格式化文件系统命令"),
    (r"\bdd\s+if=[^\n]*of=/dev/", "dd 直写块设备"),
    (r"\bchmod\s+(-R\s+)?777\s+/", "对根路径开放 777 权限"),
    (r"\bshutdown\b|\breboot\b", "关机/重启命令"),
    (r":\(\)\s*\{\s*:\|:&\s*\}", "fork 炸弹"),
]

# 允许的目录前缀（其余文件一并收纳但标记；scripts 目录单独统计）
SCRIPT_DIRS = ("scripts/",)
RESOURCE_DIRS = ("references/", "assets/")


@dataclass
class SkillFileEntry:
    """技能文件夹中的单个文件（导入预览清单用）"""

    path: str
    size: int
    kind: str  # skill_md | script | reference | asset | other
    content: str | None = None  # 文本文件保留内容；二进制置 None


@dataclass
class ParsedSkill:
    """SKILL.md 文件夹解析结果——导入预览与入库的统一中间结构"""

    skill_id: str
    name: str
    description: str
    body: str  # SKILL.md 正文（L2 指令）
    frontmatter: dict = field(default_factory=dict)
    icon: str = "\U0001f9e9"  # 🧩
    category: str = "general"
    version: str = ""
    author: str = ""
    files: list[SkillFileEntry] = field(default_factory=list)
    has_scripts: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_preview_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "frontmatter": self.frontmatter,
            "icon": self.icon,
            "category": self.category,
            "version": self.version,
            "author": self.author,
            "has_scripts": self.has_scripts,
            "warnings": self.warnings,
            "files": [
                {"path": f.path, "size": f.size, "kind": f.kind, "content": f.content}
                for f in self.files
            ],
        }

    @classmethod
    def from_preview_dict(cls, data: dict) -> "ParsedSkill":
        files = [
            SkillFileEntry(
                path=f["path"],
                size=int(f.get("size", 0)),
                kind=f.get("kind", "other"),
                content=f.get("content"),
            )
            for f in data.get("files", [])
        ]
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data.get("description", ""),
            body=data.get("body", ""),
            frontmatter=data.get("frontmatter") or {},
            icon=data.get("icon") or "\U0001f9e9",
            category=data.get("category") or "general",
            version=data.get("version") or "",
            author=data.get("author") or "",
            files=files,
            has_scripts=bool(data.get("has_scripts")),
            warnings=list(data.get("warnings") or []),
        )


class SkillParseError(ValueError):
    """技能解析失败（结构不合法 / 缺必填字段 / 超限）"""


def slugify_skill_id(name: str) -> str:
    """从技能名生成 skill_id：小写、非字母数字转连字符。

    与项目 flow_id 规范不同：skill_id 采用连字符（对齐 agentskills.io 生态命名，
    如 pdf-processing），flow_id 才强制下划线。
    """
    slug = re.sub(r"[^a-z0-9一-鿿]+", "-", name.lower()).strip("-")
    return slug[:48] or "skill"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """拆分 SKILL.md 的 YAML frontmatter 与正文"""
    match = FRONTMATTER_RE.match(text.lstrip("﻿"))
    if not match:
        raise SkillParseError("SKILL.md 缺少 YAML frontmatter（应以 --- 开头）")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"frontmatter YAML 解析失败: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillParseError("frontmatter 必须是键值映射")
    return meta, match.group(2).strip()


def _is_safe_relpath(path: str) -> bool:
    """拒绝绝对路径与 .. 穿越"""
    if path.startswith("/") or path.startswith("\\"):
        return False
    parts = path.replace("\\", "/").split("/")
    return ".." not in parts


def _classify(path: str) -> str:
    lower = path.lower()
    if lower.endswith("/skill.md") or lower == "skill.md":
        return "skill_md"
    if lower.startswith(SCRIPT_DIRS):
        return "script"
    if lower.startswith(RESOURCE_DIRS):
        return "reference" if lower.startswith("references/") else "asset"
    return "other"


def _scan_danger(path: str, content: str) -> list[str]:
    warnings: list[str] = []
    for pattern, label in DANGEROUS_PATTERNS:
        if re.search(pattern, content):
            warnings.append(f"{path}: {label}")
    return warnings


def parse_skill_folder(
    files: dict[str, bytes],
    *,
    source_type: str = "json",
    source_ref: str = "",
) -> ParsedSkill:
    """解析一个技能文件夹（path → 原始字节）。

    - 定位唯一 SKILL.md（根目录或一级子目录）
    - 校验 frontmatter 必填字段、正文长度、总量上限
    - 统计 scripts/、扫描危险模式 → warnings
    """
    if not files:
        raise SkillParseError("技能包为空")

    # 若所有文件共享同一顶层目录前缀（zip 常见），先剥掉
    normalized: dict[str, bytes] = {}
    tops = {p.split("/", 1)[0] for p in files if "/" in p}
    no_dir = [p for p in files if "/" not in p]
    prefix = ""
    if not no_dir and len(tops) == 1:
        prefix = f"{next(iter(tops))}/"
    for path, raw in files.items():
        rel = path[len(prefix):] if prefix and path.startswith(prefix) else path
        if not rel or rel.endswith("/"):
            continue
        if not _is_safe_relpath(rel):
            raise SkillParseError(f"非法文件路径: {path}")
        if len(raw) > MAX_FILE_BYTES:
            raise SkillParseError(f"文件过大（>{MAX_FILE_BYTES // 1024}KB）: {rel}")
        normalized[rel.replace("\\", "/")] = raw

    total = sum(len(v) for v in normalized.values())
    if total > MAX_FOLDER_BYTES:
        raise SkillParseError(f"技能包总大小超过 {MAX_FOLDER_BYTES // 1024}KB 上限")

    skill_md_paths = [p for p in normalized if p.lower() == "skill.md"]
    if not skill_md_paths:
        raise SkillParseError("未找到 SKILL.md（技能文件夹必须包含 SKILL.md）")
    if len(skill_md_paths) > 1:
        raise SkillParseError("存在多个 SKILL.md，无法确定技能入口")

    try:
        skill_md_text = normalized[skill_md_paths[0]].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillParseError("SKILL.md 不是有效的 UTF-8 文本") from exc

    meta, body = split_frontmatter(skill_md_text)
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name:
        raise SkillParseError("frontmatter 缺少必填字段 name")
    if not description:
        raise SkillParseError(
            "frontmatter 缺少必填字段 description（决定技能何时被触发，必填）"
        )

    warnings: list[str] = []
    if len(body) > BODY_SOFT_LIMIT_CHARS:
        warnings.append(
            f"正文约 {len(body) // 4} tokens，超过建议上限 5000 tokens，"
            "建议将细节拆分到 references/ 按需加载"
        )

    entries: list[SkillFileEntry] = []
    has_scripts = False
    for path in sorted(normalized):
        raw = normalized[path]
        kind = _classify(path)
        content: str | None = None
        if kind == "skill_md":
            content = skill_md_text
        elif raw:
            try:
                content = raw.decode("utf-8")
                if kind == "script":
                    warnings.extend(_scan_danger(path, content))
            except UnicodeDecodeError:
                content = None  # 二进制资源：仅登记清单，不随预览传输
        if kind == "script":
            has_scripts = True
        entries.append(SkillFileEntry(path=path, size=len(raw), kind=kind, content=content))

    skill_id = str(meta.get("skill_id") or meta.get("id") or "").strip() or slugify_skill_id(name)

    icon = str(meta.get("icon") or meta.get("emoji") or "").strip() or "\U0001f9e9"
    category = str(meta.get("category") or "general").strip().lower()
    if len(category) > 50:
        category = category[:50]

    return ParsedSkill(
        skill_id=skill_id,
        name=name[:100],
        description=description,
        body=body,
        frontmatter={k: v for k, v in meta.items() if isinstance(k, str)},
        icon=icon[:10],
        category=category,
        version=str(meta.get("version") or "").strip()[:50],
        author=str(meta.get("author") or meta.get("maintainer") or "").strip()[:100],
        files=entries,
        has_scripts=has_scripts,
        warnings=warnings,
    )


def render_skill_md(parsed: ParsedSkill) -> str:
    """将解析结果回写为标准 SKILL.md 文本（迁移脚本 / 入库落盘用）"""
    meta: dict = {
        "name": parsed.name,
        "description": parsed.description,
    }
    if parsed.version:
        meta["version"] = parsed.version
    if parsed.author:
        meta["author"] = parsed.author
    if parsed.icon:
        meta["icon"] = parsed.icon
    if parsed.category:
        meta["category"] = parsed.category
    for key, value in parsed.frontmatter.items():
        meta.setdefault(key, value)
    dump = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{dump}---\n\n{parsed.body}\n"


def parsed_from_legacy_json(obj: dict) -> ParsedSkill:
    """兼容旧 JSON 配置型技能：提示词字段 → SKILL.md 正文，元信息 → frontmatter"""
    name = str(obj.get("name") or "").strip()
    if not name:
        raise SkillParseError("JSON 配置缺少必填字段 name")
    body_parts: list[str] = []
    for key in ("prompt", "instructions", "flow", "content"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            body_parts.append(value.strip())
    description = str(obj.get("description") or "").strip() or f"{name} 技能"
    skill_id = str(obj.get("skill_id") or "").strip() or slugify_skill_id(name)
    return ParsedSkill(
        skill_id=skill_id,
        name=name[:100],
        description=description,
        body="\n\n".join(body_parts),
        frontmatter={"migrated_from": "json"},
        icon=str(obj.get("icon") or "").strip()[:10] or "\U0001f9e9",
        category=str(obj.get("category") or "general").strip().lower()[:50] or "general",
        version=str(obj.get("version") or "").strip()[:50],
        author=str(obj.get("author") or "").strip()[:100],
        files=[],
        has_scripts=False,
        warnings=[],
    )
