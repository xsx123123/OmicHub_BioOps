"""终端域值对象"""

from enum import Enum


class TerminalStatus(str, Enum):
    """终端会话状态"""

    CREATING = "creating"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
