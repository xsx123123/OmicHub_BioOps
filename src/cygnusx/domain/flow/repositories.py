"""流程域仓储接口 — YAML 配置中心定位。

flow_id 为字符串（来自 YAML meta.id），不使用 UUID。
仓储实现可基于文件系统（YAML 目录）或数据库。
"""

from __future__ import annotations

from typing import Protocol

from cygnusx.domain.flow.entities import FlowConfig


class IFlowRepository(Protocol):
    """流程仓储接口"""

    def get_by_flow_id(self, flow_id: str) -> FlowConfig | None:
        """根据流程 ID（meta.id）获取流程配置"""
        ...

    def list_flows(self, category: str | None = None) -> list[FlowConfig]:
        """列出所有流程配置，可按分类过滤"""
        ...

    def reload(self) -> int:
        """重新加载所有流程配置（热重载），返回加载数量"""
        ...
