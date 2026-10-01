"""CygnusX 沙盒启动注入模块（sitecustomize）。

Python 启动时自动执行（对 `docker exec -i <c> python -` 投递的用户代码生效）。
后端池每次执行都 fork 新 Python 进程，因此启动开销必须极小。

职责：
1. 注入 show_echarts / show_image / show_plotly / show_df（零开销，立即可用）
2. 对 scanpy/numpy/pandas 等重库使用懒加载代理——仅在用户代码实际访问属性时才 import，
   避免每次执行都付出 3-5s 的 scanpy 导入代价
3. matplotlib 强制 Agg 无头后端
"""

from __future__ import annotations

import base64 as _b64
import builtins as _builtins
import importlib
import json as _json
import os as _os
from pathlib import Path as _Path
import sys as _sys
import time as _time
import warnings as _warnings
from typing import Any

_warnings.filterwarnings("ignore", category=UserWarning)

_ECHARTS_PREFIX = "%%ECHARTS%%"
_IMAGE_PREFIX = "%%IMAGE%%"
_PLOTLY_PREFIX = "%%PLOTLY%%"
# plotly figure JSON 单行回传上限：超出说明数据量过大，引导降采样，
# 避免单行撑爆后端落库护栏（tool_invocations 200KB）与前端渲染。
_PLOTLY_MAX_BYTES = 3 * 1024 * 1024
_INLINE_ARTIFACT_COUNTER = 0


def _save_inline_artifact(data: bytes | str, suffix: str, stem: str) -> None:
    """把内联预览同步落盘，让聊天结果进入统一 artifact manifest。"""
    global _INLINE_ARTIFACT_COUNTER
    try:
        _INLINE_ARTIFACT_COUNTER += 1
        target_dir = _Path("/tmp/chat_output/figures")
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{_os.getpid()}_{_time.time_ns()}_{_INLINE_ARTIFACT_COUNTER}"
        target = target_dir / f"{stem}_{stamp}{suffix}"
        if isinstance(data, str):
            target.write_text(data, encoding="utf-8")
        else:
            target.write_bytes(data)
    except Exception:  # noqa: BLE001
        # 预览协议不能因产物落盘失败而阻断用户代码执行；后端仍会收集用户显式写入的文件。
        pass


def _is_deliverable_path(path: str) -> bool:
    try:
        candidate = _Path(path).resolve()
        return any(
            candidate == root or root in candidate.parents
            for root in (_Path("/tmp/chat_output"), _Path("/workspace/output"))
        )
    except Exception:  # noqa: BLE001
        return False


class _LazyModule:
    """延迟导入代理：首次属性访问才触发 importlib.import_module。

    例：sc = _LazyModule("scanpy")
        sc.read_h5ad(...)  # 此刻才真正 import scanpy
    """

    __slots__ = ("_name", "_mod", "_imported")

    def __init__(self, name: str) -> None:
        self._name = name
        self._mod: Any = None
        self._imported = False

    def _load(self) -> Any:
        if not self._imported:
            self._mod = importlib.import_module(self._name)
            self._imported = True
        return self._mod

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)

    def __repr__(self) -> str:
        return f"<LazyModule '{self._name}'{' [loaded]' if self._imported else ' [pending]'}>"

    def __dir__() -> list[str]:  # type: ignore[override]
        return []


# ---- matplotlib：必须 eager 设置 Agg（在 import pyplot 之前） ----
try:
    import matplotlib

    matplotlib.use("Agg", force=True)
except Exception:  # noqa: BLE001
    pass

# ---- 注入懒加载别名（零启动开销，首次访问才 import） ----
_lazy: dict[str, _LazyModule] = {
    "scanpy": _LazyModule("scanpy"),
    "sc": _LazyModule("scanpy"),
    "anndata": _LazyModule("anndata"),
    "ad": _LazyModule("anndata"),
    "numpy": _LazyModule("numpy"),
    "np": _LazyModule("numpy"),
    "pandas": _LazyModule("pandas"),
    "pd": _LazyModule("pandas"),
    "seaborn": _LazyModule("seaborn"),
    "sns": _LazyModule("seaborn"),
    "matplotlib": _LazyModule("matplotlib"),
    "plt": _LazyModule("matplotlib.pyplot"),
    "sklearn": _LazyModule("sklearn"),
}
for _name, _proxy in _lazy.items():
    setattr(_builtins, _name, _proxy)


# ---- 零开销 helper 函数（立即注册，不含任何重 import） ----
def show_echarts(option: object, *, flush: bool = True) -> None:
    """输出 ECharts option，前端按 vue-echarts 渲染（含 GL 的 scatterGL/heatmap）。

    用法：show_echarts({"series": [{"type": "scatterGL", "data": points}]})
    """
    payload = _json.dumps(option, default=str, ensure_ascii=False)
    _save_inline_artifact(payload, ".json", "echarts")
    print(_ECHARTS_PREFIX + payload, flush=flush)


def show_image(path: str, *, mime: str = "image/png") -> None:
    """读取本地图片文件并以 base64 输出，前端按 <img> 渲染。

    用法：plt.savefig("/workspace/output/umap.png"); show_image("/workspace/output/umap.png")
    """
    with open(path, "rb") as fh:
        image_bytes = fh.read()
    extension = {
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(mime.lower(), ".png")
    if not _is_deliverable_path(path):
        _save_inline_artifact(image_bytes, extension, "image")
    b64 = _b64.b64encode(image_bytes).decode("ascii")
    print(f"{_IMAGE_PREFIX}data:{mime};base64,{b64}", flush=True)


def show_plotly(fig: object, *, flush: bool = True) -> None:
    """输出 plotly Figure 的 JSON，前端按交互式 plotly 渲染（缩放/悬停/图例开关）。

    用法：fig = px.scatter(...); show_plotly(fig)
    与 fig.write_html("output/figures/xxx.html") 互补：前者内联预览，后者文件交付。
    """
    to_json = getattr(fig, "to_json", None)
    if not callable(to_json):
        print("[show_plotly] 参数不是 plotly Figure（缺少 to_json），已跳过", file=_sys.stderr)
        return
    payload = str(to_json())
    if len(payload.encode("utf-8")) > _PLOTLY_MAX_BYTES:
        print(
            f"[show_plotly] 图表 JSON 超过 {_PLOTLY_MAX_BYTES // 1024 // 1024}MB，"
            "未回传预览；请降采样后重试",
            file=_sys.stderr,
        )
        return
    _save_inline_artifact(payload, ".json", "plotly")
    print(_PLOTLY_PREFIX + payload, flush=flush)


def show_df(df: object, max_rows: int = 50) -> None:
    """把 DataFrame 以文本表格输出到 stdout。"""
    try:
        import pandas as _pd  # noqa: PLC0415

        if isinstance(df, _pd.DataFrame):
            print(df.head(max_rows).to_string(), flush=True)
            return
    except Exception:  # noqa: BLE001
        pass
    print(str(df), flush=True)


_builtins.show_echarts = show_echarts
_builtins.show_image = show_image
_builtins.show_plotly = show_plotly
_builtins.show_df = show_df

print(
    "[cygnusx-sandbox] 就绪：show_echarts/show_image/show_plotly/show_df 已注入，sc/np/pd 懒加载",
    file=_sys.stderr,
)
