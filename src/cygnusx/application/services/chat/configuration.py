"""聊天助手、研究工具和系统提示词配置。"""

from __future__ import annotations

from typing import Any

from cygnusx.application.services.network_request_tool import NETWORK_REQUEST_TOOL_SCHEMA
from cygnusx.infrastructure.config.prompt_loader import get_prompt

BUILTIN_ASSISTANTS: list[dict[str, Any]] = [
    {
        "assistant_id": "general",
        "name": "通用助手",
        "description": "CygnusX 通用 AI 助手，回答各类问题",
        "system_prompt": get_prompt("agents.general"),
        "default_temperature": 0.7,
        "default_max_tokens": 65536,
        "icon": "🤖",
        "color": "#4f8ef7",
        "category": "general",
    },
    {
        "assistant_id": "rna_seq_analyst",
        "name": "RNA-seq 分析师",
        "description": "专注于 RNA-seq 差异表达分析、通路富集、可视化",
        "system_prompt": get_prompt("agents.rnaseq"),
        "default_temperature": 0.3,
        "default_max_tokens": 65536,
        "icon": "🧬",
        "color": "#4f8ef7",
        "category": "analysis",
    },
    {
        "assistant_id": "scrna_analyst",
        "name": "单细胞分析师",
        "description": "专注于单细胞转录组分析、降维聚类、细胞注释",
        "system_prompt": get_prompt("agents.scrna"),
        "default_temperature": 0.3,
        "default_max_tokens": 65536,
        "icon": "🔬",
        "color": "#e74c3c",
        "category": "analysis",
    },
    {
        "assistant_id": "code_helper",
        "name": "代码助手",
        "description": "帮助编写和调试生信分析代码（Python / R）",
        "system_prompt": get_prompt("agents.code"),
        "default_temperature": 0.2,
        "default_max_tokens": 65536,
        "icon": "💻",
        "color": "#f39c12",
        "category": "code",
    },
    {
        "assistant_id": "visualization",
        "name": "可视化助手",
        "description": "帮助创建和优化科研图表",
        "system_prompt": get_prompt("agents.visualization"),
        "default_temperature": 0.3,
        "default_max_tokens": 65536,
        "icon": "📊",
        "color": "#27ae60",
        "category": "visualization",
    },
]


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索，获取与用户问题相关的实时信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "top_n": {"type": "integer", "default": 5, "description": "返回结果数量"},
            },
            "required": ["query"],
        },
    },
}

# 知识库检索：普通聊天同样挂载（Studio 由 STUDIO_TOOL_SCHEMAS 携带），
# 让 Agent 能检索平台知识库（含用户个人笔记/实验经验文档）再作答。
KNOWLEDGE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "knowledge_search",
        "description": (
            "检索平台知识库（含用户个人笔记与实验经验文档），返回标题、分类和短摘录。"
            "涉及专业原理、分析流程、参数阈值、实验经验或平台使用方法的问题，先查知识库。"
            "若结果为空、相关性不足或无法覆盖问题，再调用 web_search 补充外部资料。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "知识检索关键词"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 8,
                    "description": "最多返回条数，缺省 5",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

RESEARCH_TOOL_NAMES = frozenset({"knowledge_search", "web_search"})
RESEARCH_TOOL_CHANNEL = "cygnusx-research"

FRESHNESS_SEARCH_TRIGGERS = (
    "实时",
    "最新",
    "最近",
    "今天",
    "今日",
    "昨天",
    "明天",
    "新闻",
    "天气",
    "时事",
    "价格",
    "股价",
    "汇率",
    "文献",
    "论文",
    "研究进展",
    "研究成果",
    "临床试验",
    "指南",
    "数据库更新",
    "latest",
    "recent",
    "today",
    "news",
    "weather",
    "literature",
    "paper",
    "pubmed",
)

BIOINFORMATICS_DOMAIN_TRIGGERS = (
    "生物信息",
    "组学",
    "转录组",
    "单细胞",
    "rna-seq",
    "rnaseq",
    "scrna",
    "atac",
    "chip-seq",
    "差异表达",
    "富集分析",
    "基因组",
    "测序",
)

PROFESSIONAL_LEARNING_TRIGGERS = (
    "学习",
    "原理",
    "流程",
    "方法",
    "教程",
    "怎么做",
    "如何做",
    "没有数据",
    "暂无数据",
)

MEMORY_TOOL_NAMES = {
    "cygnusx_save_memory",
    "cygnusx_update_memory",
    "cygnusx_forget_memory",
    "cygnusx_search_memory",
    "cygnusx_update_memory_block",
}

MEMORY_SYSTEM_PROMPT_SUFFIX = """## 长期记忆工具

你可保存、修正、遗忘或检索当前用户自己的跨会话研究记忆。
- 仅在用户明确要求记住，或提供稳定的研究偏好、物种、参考基因组、数据类型或项目进展时使用保存工具。
- 当前对话优先于历史记忆；冲突时修正记忆。用户要求忘记时调用遗忘工具。
- 禁止保存密钥、密码、Token、原始数据内容、他人隐私或仅对本轮有效的临时细节。
"""

MEMORY_V2_WRITE_DISCIPLINE = """## 记忆写入纪律

只在用户明确陈述持久偏好、纠正错误做法，或告知影响后续工作的项目事实时调用记忆工具。
不要记录一次性任务、当前对话已有的临时上下文、未确认的推测、密钥凭据或隐私信息。
更新记忆块前先读取内容并携带 version，做增量修改，不要整块重写无关部分。
"""

HANDOFF_SYSTEM_PROMPT_SUFFIX = """## Agent 转交协议
当用户当前任务已进入明确的下一专业阶段、且你已完成自己负责的部分时，可以调用
`transfer_to_agent` 将会话交给白名单中的下一位 Agent。交接必须包含已完成工作的摘要、
用户后续诉求、相关 workspace 产物和约束；不要为了回避简单问题或重复工作而转交。
如果经过澄清后确认任务超出你的能力边界、缺少你不具备的专业工具，且白名单中存在合适 Agent，
应调用 `transfer_to_agent`，不要勉强生成不可靠结论。无法确定目标时先用 `ask_user` 澄清。
回转交规则：如果要转回本会话中曾经转交过给你的 Agent，`reason` 必须用至少 16 个字符
清楚说明本次新增的信息或进展（例如新产物、新结论、用户新指示），否则会被服务端拒绝；
没有新增信息时不要回转交，直接在当前会话继续处理。
转交次数：每个会话最多允许 10 次转交，接近上限时应优先在当前 Agent 内完成剩余工作，
或汇总各 Agent 的结论直接回复用户。"""


ASK_USER_SYSTEM_PROMPT_SUFFIX = """## 用户澄清协议（强制）

当任务缺少关键信息、存在多种可行方案、或需要用户在候选项中做选择时：
- **必须**调用 `ask_user` 工具，通过弹窗 options 让用户点选作答，而不是等待用户手动输入。
- **禁止**在回复正文中用纯文本罗列"方案 1 / 方案 2"或"选项 1/2/3"，让用户回复编号或文字作答。
- 当你已经给出具体的分析执行方案、并在正文中询问“是否按上述方案开始/执行/分析”时，
  同样**必须**调用 `ask_user`；不要只输出这句文本问题。使用一个确认问题，并提供明确选项：
  “确认，按上述方案开始分析（推荐）”与“调整方案或参数”。本轮只等待用户选择，不得启动执行工具。
- `questions` 参数必须按 schema 传结构化数组，不要把 JSON 序列化成字符串。
- 选项有推荐项时放在第一位，并在选项文本中以（推荐）标注。
- 只有问题完全无法用预设选项表达时，才允许在正文直接提问。
"""

KNOWLEDGE_SEARCH_SYSTEM_PROMPT_SUFFIX = """## 专业问题检索与证据融合协议（强制）

平台知识库已收录用户的个人笔记、实验经验和已发布方法文档。面对生物信息学、组学分析、
统计方法、实验流程、参数阈值或平台使用等专业问题，即使用户只是学习原理、暂时没有数据，
也必须按以下顺序获取依据后再形成最终回答：

1. 先调用 `knowledge_search` 检索平台知识库，优先复用站内已经审核或沉淀的知识。
2. 检查知识库结果是否真实相关且足以覆盖问题。调用失败、结果为空、仅有弱相关摘录或信息明显
   不完整时，如果当前工具列表包含 `web_search`，继续调用 `web_search` 搜索外部资料；不要因为
   已调用过知识库就直接停止检索。涉及最新进展、论文、指南或时效性事实时，即使知识库有结果，
   也要使用联网搜索核验时效性。
3. 最终回答综合知识库证据、网络搜索结果和模型自身的通用知识：优先采用可验证资料，模型知识
   用于解释概念、串联流程和补足背景，不得把模型记忆伪装成知识库或网络来源。
4. 只声明实际执行过的检索。知识库无结果或联网失败时如实说明，但仍可基于可靠的通用知识回答，
   并明确哪些内容属于一般方法学解释、哪些来自检索证据。不要虚构文献、链接、知识库条目或结论。
5. `knowledge_search` 返回的每条结果都有 `citation_id`。使用某条知识库结果支撑结论时，
   在对应句末原样输出 `[[citation:<citation_id>]]`（例如 `[[citation:kb-0123abcd4567efgh]]`）。
   不要改写、猜测或复用未返回的 ID；前端会把这个标记显示为可悬停和点击核验的来源编号。
"""


def build_page_context_prompt(page_context: str) -> str:
    """把前端附加的用户当前页面上下文包装成系统提示词片段。

    全局侧边栏等入口在发消息时带上用户正在浏览的页面（名称/路径/参数），
    让 Agent 能回答"当前页面"类问题并结合页面场景作答。
    """
    return (
        "【用户当前页面】\n"
        f"{page_context.strip()}\n"
        "用户所说的「当前页面 / 这个页面 / 这里」均指上述页面，请结合该页面场景回答；"
        "此上下文由平台根据用户浏览位置自动附加，不要在回答中向用户提及它本身。"
    )
