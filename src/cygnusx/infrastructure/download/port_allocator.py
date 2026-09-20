"""动态端口分配 — 为 EBIDownload progress server 分配可用端口"""

from __future__ import annotations

import socket


def allocate_free_port() -> int:
    """分配一个当前可用的 TCP 端口。

    绑定到 127.0.0.1:0 让 OS 分配端口，然后立即关闭 socket 释放端口。
    存在极小的竞态窗口（毫秒级），若端口被抢占，EBIDownload 会启动失败，
    此时磁盘采样器自动兜底。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", 0))
        s.set_inheritable(False)
        return s.getsockname()[1]
