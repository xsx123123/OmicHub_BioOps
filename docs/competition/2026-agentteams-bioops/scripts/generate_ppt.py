#!/usr/bin/env python3
"""Generate an editable competition deck from the supplied PPTX template.

Only standard-library modules are used so the deck can be regenerated in the
repository environment.  Every visible element is a native PowerPoint shape
or text box, rather than a screenshot.
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ROOT / "docs/competition/2e567d1a-99c1-45ce-8a0f-3d36d11f3314.pptx"
OUTPUT = ROOT / "docs/competition/2026-agentteams-bioops/output/OmicHub_BioOps_初赛方案_可编辑版.pptx"
SCREENSHOTS = {
    1: ROOT / "docs/26.8.10/image copy 5.png",
    2: ROOT / "docs/26.8.10/image copy 4.png",
    3: ROOT / "docs/26.8.10/image copy 8.png",
    4: ROOT / "docs/26.8.9/multi-agent/Screenshot 2026-08-09 at 21.59.59.png",
    5: ROOT / "docs/26.8.12/Screenshot 2026-08-12 at 02.21.00.png",
    6: ROOT / "docs/26.8.7/ai-studio/Screenshot 2026-08-07 at 21.12.48.png",
    7: ROOT / "docs/26.8.12/Screenshot 2026-08-12 at 02.20.45.png",
    8: ROOT / "docs/26.8.12/Screenshot 2026-08-12 at 02.21.00.png",
    9: ROOT / "docs/26.8.9/multi-agent/Screenshot 2026-08-09 at 22.00.23.png",
    10: ROOT / "docs/26.8.10/image copy 8.png",
    11: ROOT / "docs/26.8.11/image copy 4.png",
    12: ROOT / "docs/26.8.9/multi-agent/Screenshot 2026-08-09 at 21.59.59.png",
}

EMU = 914400
SW, SH = 12192000, 6858000

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def rgb(value: str) -> ET.Element:
    return ET.Element(q("a", "srgbClr"), {"val": value.replace("#", "")})


def xml(tag: str, attrs: dict[str, str] | None = None, children: list[ET.Element] | None = None) -> ET.Element:
    if isinstance(attrs, list):
        children = attrs
        attrs = None
    node = ET.Element(tag, attrs or {})
    for child in children or []:
        node.append(child)
    return node


class SlideBuilder:
    def __init__(self, root: ET.Element):
        self.root = root
        self.tree = root.find(q("p", "cSld")).find(q("p", "spTree"))
        for node in list(self.tree)[2:]:
            self.tree.remove(node)
        self.shape_id = 1

    @staticmethod
    def e(value: float) -> str:
        return str(int(value * EMU))

    def shape(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        line: str | None = None,
        radius: bool = False,
        transparency: int | None = None,
    ) -> None:
        self.shape_id += 1
        sp = xml(q("p", "sp"))
        sp.append(xml(q("p", "nvSpPr"), [
            xml(q("p", "cNvPr"), {"id": str(self.shape_id), "name": f"Shape {self.shape_id}"}),
            xml(q("p", "cNvSpPr")),
            xml(q("p", "nvPr")),
        ]))
        preset = "roundRect" if radius else "rect"
        sppr = xml(q("p", "spPr"), children=[
            xml(q("a", "xfrm"), children=[
                xml(q("a", "off"), {"x": self.e(x), "y": self.e(y)}),
                xml(q("a", "ext"), {"cx": self.e(w), "cy": self.e(h)}),
            ]),
            xml(q("a", "prstGeom"), {"prst": preset}, [xml(q("a", "avLst"))]),
        ])
        fill_node = xml(q("a", "solidFill"), children=[rgb(fill)])
        if transparency is not None:
            fill_node[0].append(xml(q("a", "alpha"), {"val": str(transparency)}))
        sppr.append(fill_node)
        if line:
            sppr.append(xml(q("a", "ln"), {"w": "12700"}, [xml(q("a", "solidFill"), children=[rgb(line)])]))
        else:
            sppr.append(xml(q("a", "ln"), children=[xml(q("a", "noFill"))]))
        sp.append(sppr)
        sp.append(xml(q("p", "txBody"), children=[xml(q("a", "bodyPr")), xml(q("a", "lstStyle")), xml(q("a", "p"))]))
        self.tree.append(sp)

    def text(
        self,
        value: str,
        x: float,
        y: float,
        w: float,
        h: float,
        size: float = 16,
        color: str = "18243A",
        bold: bool = False,
        align: str = "l",
        font: str = "Microsoft YaHei",
        valign: str = "top",
        margin: float = 0.03,
    ) -> None:
        self.shape_id += 1
        sp = xml(q("p", "sp"))
        sp.append(xml(q("p", "nvSpPr"), [
            xml(q("p", "cNvPr"), {"id": str(self.shape_id), "name": f"Text {self.shape_id}"}),
            xml(q("p", "cNvSpPr"), {"txBox": "1"}),
            xml(q("p", "nvPr")),
        ]))
        sp.append(xml(q("p", "spPr"), children=[
            xml(q("a", "xfrm"), children=[
                xml(q("a", "off"), {"x": self.e(x), "y": self.e(y)}),
                xml(q("a", "ext"), {"cx": self.e(w), "cy": self.e(h)}),
            ]),
            xml(q("a", "prstGeom"), {"prst": "rect"}, [xml(q("a", "avLst"))]),
            xml(q("a", "noFill")),
            xml(q("a", "ln"), children=[xml(q("a", "noFill"))]),
        ]))
        body = xml(q("p", "txBody"), children=[
            xml(q("a", "bodyPr"), {
                "wrap": "square", "lIns": self.e(margin), "rIns": self.e(margin),
                "tIns": self.e(margin), "bIns": self.e(margin), "anchor": valign,
            }),
            xml(q("a", "lstStyle")),
        ])
        for line in value.split("\n"):
            p = xml(q("a", "p"), {"algn": align})
            p.append(xml(q("a", "pPr"), {"algn": align, "lvl": "0"}))
            r = xml(q("a", "r"))
            r.append(xml(q("a", "rPr"), {
                "lang": "zh-CN", "sz": str(int(size * 100)), "b": "1" if bold else "0",
                "typeface": font,
            }, [xml(q("a", "solidFill"), children=[rgb(color)]), xml(q("a", "latin"), {"typeface": font}), xml(q("a", "ea"), {"typeface": font})]))
            r.append(xml(q("a", "t")))
            r[-1].text = line
            p.append(r)
            p.append(xml(q("a", "endParaRPr"), {"lang": "zh-CN", "sz": str(int(size * 100))}))
            body.append(p)
        sp.append(body)
        self.tree.append(sp)

    def line(self, x: float, y: float, w: float, h: float, color: str = "27C7B8", width: int = 2) -> None:
        self.shape(x, y, w, h, "FFFFFF", color)

    def image(self, rel_id: str, x: float, y: float, w: float, h: float, name: str = "Platform Screenshot") -> None:
        self.shape_id += 1
        pic = xml(q("p", "pic"))
        pic.append(xml(q("p", "nvPicPr"), [
            xml(q("p", "cNvPr"), {"id": str(self.shape_id), "name": name}),
            xml(q("p", "cNvPicPr"), children=[xml(q("a", "picLocks"), {"noChangeAspect": "1"})]),
            xml(q("p", "nvPr")),
        ]))
        blip_fill = xml(q("p", "blipFill"), children=[
            xml(q("a", "blip"), {f"{{{REL_NS}}}embed": rel_id}),
            xml(q("a", "stretch"), children=[xml(q("a", "fillRect"))]),
        ])
        pic.append(blip_fill)
        pic.append(xml(q("p", "spPr"), children=[
            xml(q("a", "xfrm"), children=[
                xml(q("a", "off"), {"x": self.e(x), "y": self.e(y)}),
                xml(q("a", "ext"), {"cx": self.e(w), "cy": self.e(h)}),
            ]),
            xml(q("a", "prstGeom"), {"prst": "roundRect"}, [xml(q("a", "avLst"))]),
            xml(q("a", "ln"), {"w": "19050"}, [xml(q("a", "solidFill"), children=[rgb("D5E0ED")])]),
        ]))
        self.tree.append(pic)


NAVY = "0C1830"
INK = "16253D"
MUTED = "5E6E85"
TEAL = "16B8AE"
CYAN = "37D4D8"
LIME = "C9F36A"
BLUE = "4E7CF4"
PAPER = "F5F8FC"
WHITE = "FFFFFF"
ORANGE = "FFAA5B"
RED = "E96673"


def base(builder: SlideBuilder, section: str, title: str, index: int, dark: bool = False) -> None:
    builder.shape(0, 0, 13.333, 7.5, NAVY if dark else PAPER)
    if dark:
        builder.shape(9.8, -0.7, 4.3, 4.3, TEAL, transparency=16000)
        builder.shape(-1.1, 5.2, 3.0, 3.0, BLUE, transparency=20000)
    else:
        builder.shape(0, 0, 13.333, 0.14, TEAL)
        builder.shape(10.6, 0.14, 2.733, 0.05, LIME)
    color = WHITE if dark else MUTED
    builder.text(section, 0.65, 0.35, 7.5, 0.3, 11, color, True)
    builder.text(title, 0.65, 0.72, 11.5, 0.65, 25, WHITE if dark else INK, True)
    builder.text(f"{index:02d}", 12.1, 6.88, 0.55, 0.28, 9, "B4C0D0" if dark else MUTED, True, "r")


def pill(b: SlideBuilder, label: str, x: float, y: float, w: float, color: str = TEAL) -> None:
    b.shape(x, y, w, 0.3, color, radius=True)
    b.text(label, x + 0.06, y + 0.04, w - 0.12, 0.18, 9, NAVY if color == LIME else WHITE, True, "c")


def card(b: SlideBuilder, title: str, body: str, x: float, y: float, w: float, h: float, accent: str = TEAL, body_size: float = 12) -> None:
    b.shape(x, y, w, h, WHITE, "DCE5F1", True)
    b.shape(x, y, 0.08, h, accent, radius=True)
    b.text(title, x + 0.24, y + 0.18, w - 0.4, 0.34, 14, INK, True)
    b.text(body, x + 0.24, y + 0.63, w - 0.45, h - 0.75, body_size, MUTED)


def add_content(slide: SlideBuilder, n: int) -> None:
    if n == 1:
        base(slide, "GOAI 世界人工智能开源大赛 · Agent Infra 新智基座", "OmicHub BioOps", n, True)
        slide.text("面向生命科学研发的可审计多 Agent 协同基础设施", 0.7, 1.68, 8.8, 0.55, 22, "D7E5F5", True)
        slide.text("让每一次组学交付都可审计、可验证、可复用", 0.72, 2.4, 7.4, 0.35, 14, CYAN, True)
        for label, x, color in [("Case", 0.75, TEAL), ("Skill", 2.15, BLUE), ("Artifact", 3.55, ORANGE), ("Evidence", 5.15, LIME)]:
            pill(slide, label, x, 3.25, 1.15, color)
        slide.text("华中农业大学园艺林学学院 · OmicHub Team", 0.72, 6.1, 6.8, 0.3, 11, "D7E5F5")
        slide.text("初赛方案 · 可编辑草案", 0.72, 6.48, 5.2, 0.26, 10, "99AEC8")
        # Editable data-flow illustration
        for title, sub, x, color in [
            ("研究需求", "样本 / 分组", 8.55, CYAN), ("多 Agent", "职责分离", 10.2, TEAL), ("可信交付", "证据可追溯", 11.85, LIME),
        ]:
            slide.shape(x, 3.8, 1.2, 1.2, "173355", color, True)
            slide.text(title, x + 0.08, 4.08, 1.04, 0.22, 11, WHITE, True, "c")
            slide.text(sub, x + 0.08, 4.4, 1.04, 0.2, 8.5, "B9CBE0", False, "c")
        slide.text("→", 9.78, 4.22, 0.35, 0.3, 17, CYAN, True, "c")
        slide.text("→", 11.43, 4.22, 0.35, 0.3, 17, CYAN, True, "c")
    elif n == 2:
        base(slide, "P0 · 一页纸速览", "作品简介", n)
        entries = [
            ("项目名称", "OmicHub BioOps\n可审计组学交付协同", TEAL),
            ("问题与场景", "RNA-seq 项目跨数据、计算、质控、报告多角色协作；信息断裂、责任混杂、结果难复核。", RED),
            ("核心解决方案", "将自然语言需求转为 Case → Work Item → Skill → Artifact → Quality Decision → Manifest 闭环。", BLUE),
            ("创新与差异化", "不让万能 Agent 自己申请、执行、验收；以职责分离、规则质量门和证据链保证可信。", ORANGE),
            ("开放 / 复用价值", "Team、Skill Contract、Bridge 与规则配置可迁移到 ATAC-seq、单细胞和其他科学计算。", LIME),
            ("当前进展", "MAS、Bridge、受控流程、Artifact/审计基础已具备；真实 E2E 按 staging 部署验收推进。", TEAL),
        ]
        for index, (title, body, color) in enumerate(entries):
            col, row = index % 3, index // 3
            card(slide, title, body, 0.65 + col * 4.18, 1.55 + row * 2.45, 3.75, 2.0, color, 11.3)
    elif n == 3:
        base(slide, "全景", "目录", n, True)
        chapters = ["场景与价值", "方案总览", "多 Agent 协同设计", "Skill 工程体系", "工程与安全审计", "开放 / 开源计划", "落地计划与进展", "团队介绍"]
        for i, title in enumerate(chapters):
            col, row = i % 2, i // 2
            x, y = 0.85 + col * 6.15, 1.65 + row * 1.17
            slide.text(f"{i+1:02d}", x, y, 0.52, 0.32, 13, LIME, True)
            slide.text(title, x + 0.72, y, 4.9, 0.34, 16, WHITE, True)
            slide.shape(x + 0.72, y + 0.48, 4.7, 0.025, "32506F")
    elif n == 4:
        base(slide, "第一章 · 场景与价值", "一次组学交付，为什么需要多 Agent？", n, True)
        slide.text("真实问题不是“能否跑出流程”，而是如何在跨角色协作中保证输入正确、执行受控、质量独立、交付可复核。", 0.7, 1.58, 9.9, 0.45, 15, "D7E5F5")
        issues = [("信息断裂", "FASTQ、样本表、分组与参考版本分散，错误常在计算后期暴露。", RED), ("权限混杂", "研究人员、工程师、质控共享高权限入口，责任边界不清。", ORANGE), ("结果黑箱", "仅交付压缩包，参数、重试、判断和版本关系难以复核。", BLUE), ("经验难复用", "同类项目反复从沟通开始，无法沉淀为规则、Skill 与模板。", TEAL)]
        for i, (title, body, color) in enumerate(issues):
            card(slide, title, body, 0.7 + (i % 2) * 6.05, 2.35 + (i // 2) * 1.8, 5.55, 1.35, color, 11.3)
        pill(slide, "评分维度：场景价值与行业可复制性 · 25%", 0.7, 6.35, 3.55, LIME)
    elif n == 5:
        base(slide, "第一章 · 目标用户与价值", "从 RNA-seq 交付出发，复制到多组学研发", n)
        slide.text("真实平台已具备统一 AI 工作台与任务协作入口；本次 Demo 聚焦 bulk RNA-seq 差异分析交付。", 0.7, 1.42, 11.6, 0.35, 13, MUTED)
        slide.image("rId1", 0.72, 1.95, 7.55, 4.35, "OmicHub Home")
        slide.image("rId2", 8.55, 1.95, 4.05, 2.2, "OmicHub Agent Chat")
        card(slide, "可复制目标用户", "药企 / 转化医学\n种业 / 农业科研\n检验 / 科研服务\n高校核心设施", 8.55, 4.42, 4.05, 1.88, TEAL, 11.2)
        pill(slide, "真实平台界面", 0.92, 5.78, 1.25, LIME)
    elif n == 6:
        base(slide, "第二章", "方案总览", n, True)
        slide.text("BioOps 将项目协作抽象为一个可编排、可审计、可复用的业务闭环。", 0.7, 1.55, 10, 0.4, 16, "D7E5F5")
        steps = [("需求", "研究问题与数据引用"), ("Case", "责任边界与目标"), ("Work Item", "结构化分工与依赖"), ("Skill", "受控工具调用"), ("Artifact", "逻辑产物与校验"), ("Evidence", "审计事件与质量决策"), ("Manifest", "可信交付与复盘")]
        for i, (t, sub) in enumerate(steps):
            x = 0.55 + i * 1.78
            slide.shape(x, 3.15, 1.35, 1.15, "173355", TEAL if i in (1, 3, 5) else "315477", True)
            slide.text(t, x + 0.08, 3.45, 1.19, 0.23, 11, WHITE, True, "c")
            slide.text(sub, x + 0.08, 3.78, 1.19, 0.24, 8.4, "B9CBE0", False, "c")
            if i < len(steps) - 1:
                slide.text("→", x + 1.4, 3.55, 0.3, 0.24, 14, CYAN, True, "c")
        slide.text("只传递小型元数据、Artifact 引用与短摘要；原始 FASTQ、表达矩阵和长日志不进入 Agent 提示词。", 1.1, 5.35, 11.1, 0.36, 13, LIME, True, "c")
    elif n == 7:
        base(slide, "第二章 · 端到端主流程", "一次 RNA-seq 任务如何闭环", n)
        slide.image("rId1", 0.72, 1.72, 8.05, 5.0, "Agent Workflow Progress")
        steps = [("01 数据预检", "样本 / 分组 / 版本"), ("02 审批放行", "范围确认与授权"), ("03 受控执行", "提交 / 监控 / 重试"), ("04 质量与交付", "QC / Manifest / 复盘")]
        for i, (title, body) in enumerate(steps):
            card(slide, title, body, 9.05, 1.55 + i * 1.18, 3.55, 0.92, [TEAL, BLUE, ORANGE, LIME][i], 10.2)
        slide.text("图：平台内真实任务计划、工具调用与阶段状态展示", 0.85, 6.48, 7.7, 0.22, 10.2, MUTED, False, "c")
    elif n == 8:
        base(slide, "第三章", "多 Agent 协同设计", n, True)
        slide.text("多 Agent 的目的不是“更多对话”，而是责任分离、独立质量判断和可审计责任链。", 0.7, 1.55, 11.3, 0.36, 15, "D7E5F5")
        roles = [("BioOps Manager", "agent-general\n建 Case、拆 Work Item、汇总风险\n禁止直接提交计算", BLUE), ("Data Steward", "agent-data\n预检样本、分组、物种与版本\n只读，不运行计算", TEAL), ("Domain Executor", "agent-rnaseq / atacseq / scrna\n审批后提交与监控同模态流程", ORANGE), ("Quality Auditor", "agent-qc\n按版本化规则核验\n证据不足转人工复核", LIME), ("Delivery Reporter", "agent-delivery\n汇总验证过的产物与风险\n不发布文件", TEAL)]
        positions = [(0.55, 2.4), (3.0, 2.4), (5.45, 2.4), (7.9, 2.4), (10.35, 2.4)]
        for (title, body, color), (x, y) in zip(roles, positions):
            card(slide, title, body, x, y, 2.25, 2.4, color, 10.1)
        slide.text("Manager 负责编排，但不拥有执行权；执行者不判定质量；质控者不发布交付。", 0.9, 5.7, 11.6, 0.3, 13, LIME, True, "c")
    elif n == 9:
        base(slide, "第三章 · 协同闭环", "状态、上下文与异常处理", n)
        slide.image("rId1", 0.72, 1.62, 6.05, 3.06, "Multi Agent Planning")
        slide.image("rId2", 6.98, 1.62, 5.62, 2.53, "Agent Tool Execution")
        card(slide, "结构化上下文", "Case / Work Item / Artifact Ref / Evidence Event\n只传 ID、短摘要、规则与逻辑引用", 6.98, 4.42, 5.62, 1.02, TEAL, 10.4)
        card(slide, "异常处理", "blocked / manual_review / 有界重试\n所有状态由 trace_id 与事件链关联", 0.72, 4.95, 6.05, 0.95, ORANGE, 10.2)
        slide.text("真实界面展示了 Agent 计划、子任务状态和工具执行结果，而非仅停留在架构图。", 0.8, 6.38, 11.5, 0.25, 11, INK, True, "c")
    elif n == 10:
        base(slide, "第四章", "Skill 工程体系", n, True)
        slide.text("以稳定 I/O、失败语义、权限边界和版本治理，把领域经验沉淀为可复用的工程能力。", 0.7, 1.55, 11.2, 0.36, 15, "D7E5F5")
        skills = [("case-create", "创建 Case 与初始工作项", BLUE), ("project-preflight", "校验元数据、分组、物种、参考版本", TEAL), ("workflow-submit", "按审批范围提交受控流程", ORANGE), ("workflow-monitor", "查询状态、日志摘要与产物引用", BLUE), ("quality-gate", "规则化 QC 决策或转人工", LIME), ("delivery-manifest", "生成交付清单、风险与复盘入口", TEAL)]
        for i, (title, body, color) in enumerate(skills):
            col, row = i % 3, i // 3
            card(slide, title, body, 0.72 + col * 4.15, 2.25 + row * 1.75, 3.75, 1.38, color, 10.8)
        pill(slide, "评分维度：Skill 工程体系与生态复用 · 25%", 0.72, 6.22, 3.55, LIME)
    elif n == 11:
        base(slide, "第四章 · Skill 契约", "从一次调用到可治理的生命周期", n)
        slide.image("rId1", 0.72, 1.55, 7.55, 4.9, "AI Studio Skill Invocation")
        contract = [("输入", "参数 schema\n权限上下文"), ("执行", "allowlist\n审批与幂等"), ("输出", "结构化结果\nArtifact 引用"), ("治理", "版本 / 测试\n灰度与回滚")]
        for i, (title, body) in enumerate(contract): card(slide, title, body, 8.55, 1.55 + i * 1.18, 4.05, 0.92, [BLUE, TEAL, ORANGE, LIME][i], 10.4)
        slide.text("图：AI Studio 中真实的工具调用与结果回传", 1.0, 6.5, 7.0, 0.2, 10.2, MUTED, False, "c")
    elif n == 12:
        base(slide, "第五章", "工程落地、运行验证与安全可审计", n, True)
        slide.text("工程重点是“每个动作可控制、每条链路可验证、每项结果可解释”。", 0.7, 1.55, 10.8, 0.36, 15, "D7E5F5")
        for title, body, x, y, color in [
            ("可运行底座", "FastAPI / PostgreSQL / Redis / Celery\nVue 3 / Snakemake / Docker Compose", 0.72, 2.25, BLUE),
            ("协同与执行", "AgentTeams Bridge + OmicHub MAS\n独立 Worker 计算面与流程 YAML", 4.52, 2.25, TEAL),
            ("审计与证据", "Case、Artifact、Outbox、Trace\nDelivery Manifest 与 Evidence Event", 8.32, 2.25, ORANGE),
            ("安全与治理", "最小权限、审批、幂等、质量门\n关闭高风险默认能力，支持回滚", 2.62, 4.62, LIME),
            ("验证边界", "单元/契约测试已有基础；真实 RNAFlow、Matrix 等以 staging 部署验收为准。", 6.42, 4.62, RED),
        ]: card(slide, title, body, x, y, 3.25, 1.65, color, 10.8)
        pill(slide, "评分维度：工程落地与安全可审计 · 20%", 0.72, 6.3, 3.45, LIME)
    elif n == 13:
        base(slide, "第五章 · 可审计运行", "一条 Case 的最小证据包", n)
        slide.text("真实执行界面 + 结构化证据共同证明链路可运行、可复核。", 0.7, 1.42, 11.2, 0.35, 13.5, MUTED)
        positions = [(0.72, 1.9), (6.78, 1.9), (0.72, 4.25), (6.78, 4.25)]
        for rel, (x, y), label in zip(["rId1", "rId2", "rId3", "rId4"], positions, ["执行计划与子任务", "工具输出与文件证据", "领域分析与判断", "任务状态与运行记录"]):
            slide.image(rel, x, y, 5.82, 1.95, label)
            pill(slide, label, x + 0.12, y + 1.55, 1.6, LIME)
        slide.text("证据包同时保留 case-summary、approvals、task-events、artifact-manifest、quality-decision 与 delivery-manifest。", 0.8, 6.45, 11.5, 0.25, 10.8, INK, True, "c")
    elif n == 14:
        base(slide, "第六章", "开放 / 开源计划", n, True)
        slide.text("开源的目标不是仅发布代码，而是让第三方能理解边界、复现链路、扩展场景。", 0.7, 1.58, 10.8, 0.36, 15, "D7E5F5")
        for i, (title, body, color) in enumerate([( "协同模板", "Team / Role / Case / Work Item 声明", BLUE), ("Skill 契约", "输入输出、失败语义、权限边界、版本", TEAL), ("Bridge 适配", "REST 等价协议与 MCP-ready 迁移接口", ORANGE), ("Demo 与测试", "脱敏演示、契约测试、部署与排障文档", LIME)]):
            card(slide, title, body, 0.8 + i * 3.1, 2.48, 2.75, 2.0, color, 11.2)
        slide.text("许可证与依赖边界：现仓库使用 Apache-2.0 + Commons Clause（非商业使用）；对外发布前应完成依赖清单与授权复核。", 0.9, 5.45, 11.3, 0.35, 12, "D7E5F5", True, "c")
        pill(slide, "评分维度：开放 / 开源贡献 · 5%", 0.7, 6.25, 2.85, LIME)
    elif n == 15:
        base(slide, "第六章 · 复用与贡献", "配置优先，让新场景接入不必重写主链路", n)
        slide.shape(0.7, 1.85, 11.9, 3.95, WHITE, "DCE5F1", True)
        layers = [("场景层", "RNA-seq · ATAC-seq · 单细胞 · 其他科学计算", TEAL), ("协同层", "Team / Role / Case / Work Item / 审批策略", BLUE), ("能力层", "Skill Contract / Bridge / 质量规则 / 交付模板", ORANGE), ("执行层", "OmicHub MAS / Worker / Snakemake / Artifact Registry", LIME)]
        for i, (title, content, color) in enumerate(layers):
            y = 2.2 + i * 0.82
            slide.shape(1.05, y, 2.0, 0.55, color, radius=True)
            slide.text(title, 1.17, y + 0.14, 1.75, 0.18, 11, NAVY if color == LIME else WHITE, True, "c")
            slide.text(content, 3.35, y + 0.13, 8.4, 0.22, 12, INK, True)
        slide.text("新增流程或行业场景时，优先配置 Team、Skill、Artifact、规则和交付模板；协同主链路保持稳定。", 0.9, 6.18, 11.2, 0.35, 13, TEAL, True, "c")
    elif n == 16:
        base(slide, "第七章", "落地计划与进展", n, True)
        slide.text("以“可验证闭环”为阶段目标，清晰区分已有工程基础、比赛增量与后续部署验收。", 0.7, 1.55, 11.2, 0.38, 15, "D7E5F5")
        phases = [("已有基础", "OmicHub 平台、领域 Agent、流程 YAML、MAS/Artifact/审计、AgentTeams Bridge 与契约", TEAL), ("比赛增量", "BioOps Team/Role、Case 编排、专职 Agent、质量规则、三条可验证 Demo", ORANGE), ("部署验收", "staging Worker、RNAFlow 容器、审批链、Matrix/Gateway（可选）与真实 E2E", BLUE), ("扩展演进", "SOP / 规则 RAG、指标看板、更多组学与企业客户场景", LIME)]
        for i, (title, body, color) in enumerate(phases):
            x = 0.8 + i * 3.07
            card(slide, title, body, x, 2.35, 2.7, 2.6, color, 11)
        slide.text("展示口径：已实现基础 / 比赛增量 / 待部署验收必须分层表达，不将单测或设计表述为生产上线。", 0.85, 5.75, 11.5, 0.32, 12.2, RED, True, "c")
    elif n == 17:
        base(slide, "第七章 · 里程碑与风险控制", "从可运行 Demo 到行业复制", n)
        slide.image("rId1", 0.72, 1.55, 6.0, 3.7, "Agent Execution Record")
        slide.image("rId2", 6.95, 1.55, 5.65, 3.7, "Multi Agent Scientific Review")
        milestones = [("M1", "Case 可见"), ("M2", "可信闭环"), ("M3", "三条证据 Demo"), ("M4", "多组学复制")]
        for i, (tag, text_value) in enumerate(milestones):
            x = 0.8 + i * 3.0
            slide.shape(x, 5.62, 2.55, 0.72, WHITE, "DCE5F1", True)
            pill(slide, tag, x + 0.12, 5.83, 0.55, [TEAL, ORANGE, BLUE, LIME][i])
            slide.text(text_value, x + 0.82, 5.8, 1.55, 0.22, 11, INK, True)
        slide.text("当前界面已经能呈现 Agent 执行与科学分析过程；下一步补齐 staging E2E 与可导出证据包。", 0.8, 6.48, 11.5, 0.22, 10.8, RED, True, "c")
    elif n == 18:
        base(slide, "第八章", "团队介绍", n, True)
        slide.text("请在提交前替换以下占位信息：避免在公开材料中披露个人隐私、未授权成果或敏感联系方式。", 0.72, 1.55, 11.0, 0.35, 13.5, "D7E5F5")
        placeholders = [("项目负责人", "【姓名 / 单位 / 职务】\n系统架构、产品与项目统筹", TEAL), ("生信与领域专家", "【姓名 / 单位 / 专业】\n流程设计、质量规则与科学验证", BLUE), ("AI 与后端工程", "【姓名 / 单位 / 专业】\nAgentTeams、MAS、Bridge 与审计", ORANGE), ("前端与体验设计", "【姓名 / 单位 / 专业】\nCase 工作台、交付界面与可视化", LIME)]
        for i, (title, body, color) in enumerate(placeholders): card(slide, title, body, 0.8 + (i % 2) * 6.1, 2.25 + (i // 2) * 1.85, 5.55, 1.4, color, 11.4)
        slide.text("团队分工原则：科学正确性、工程可靠性与用户体验并重；所有外部合作与成果署名以实际贡献及授权为准。", 0.85, 6.25, 11.5, 0.3, 12, LIME, True, "c")
    elif n == 19:
        base(slide, "第八章 · 团队与致谢", "谢谢聆听", n, True)
        slide.text("OmicHub BioOps", 0.72, 1.65, 5.2, 0.55, 25, WHITE, True)
        slide.text("让每一次组学交付都可审计、可验证、可复用", 0.75, 2.35, 7.2, 0.38, 15, CYAN, True)
        slide.shape(0.72, 3.2, 6.2, 1.55, "173355", "3A5D81", True)
        slide.text("提交前请补充", 1.02, 3.52, 1.5, 0.23, 12, LIME, True)
        slide.text("【团队成员】  【代码仓库 / Demo 链接】  【联系邮箱】", 1.02, 3.95, 5.55, 0.28, 11.2, "D7E5F5")
        slide.text("项目资料：docs/competition/2026-agentteams-bioops/", 0.75, 6.3, 5.8, 0.25, 10.5, "9FB6D0")


def main() -> None:
    if not TEMPLATE.exists():
        raise SystemExit(f"Template not found: {TEMPLATE}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        unpacked = Path(tmpdir) / "pptx"
        with zipfile.ZipFile(TEMPLATE) as archive:
            archive.extractall(unpacked)
        for media_index, screenshot in SCREENSHOTS.items():
            if not screenshot.exists():
                raise SystemExit(f"Screenshot not found: {screenshot}")
            shutil.copy2(screenshot, unpacked / f"ppt/media/image{media_index}.png")
        slides = sorted((unpacked / "ppt/slides").glob("slide*.xml"), key=lambda item: int(item.stem.replace("slide", "")))
        if len(slides) != 19:
            raise SystemExit(f"Expected 19 slides in template, got {len(slides)}")
        for index, slide_path in enumerate(slides, 1):
            root = ET.parse(slide_path).getroot()
            add_content(SlideBuilder(root), index)
            ET.ElementTree(root).write(slide_path, encoding="UTF-8", xml_declaration=True)
        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in unpacked.rglob("*"):
                if path.is_file(): archive.write(path, path.relative_to(unpacked))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
