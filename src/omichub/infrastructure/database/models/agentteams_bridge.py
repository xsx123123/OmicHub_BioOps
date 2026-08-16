"""AgentTeams Bridge 单例运行配置。"""

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class AgentTeamsBridgeSettingsModel(Base, TimestampMixin):
    """管理员维护的 Bridge 接入配置，令牌字段以密文落盘。"""

    __tablename__ = "agentteams_bridge_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bridge_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    manager_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_steward_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_operator_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    element_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
