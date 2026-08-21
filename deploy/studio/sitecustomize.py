"""OmicStudio 沙盒启动注入模块（sitecustomize）。

随 base 镜像放入 site-packages，Python 启动时自动加载，
对 sandbox-agent 经 `python <script>` 投递的用户代码生效。

当前只注入 show_plotly：sandbox-agent 在 stdout 泵送时解析 %%PLOTLY%%
标记行并产出 plotly 事件，宿主侧写入 ui_payload.plotly_figures，
前端按交互式 plotly 渲染。与聊天轻量沙盒的 deploy/sandbox/sitecustomize.py
保持同一标记协议。
"""

from __future__ import annotations

import builtins as _builtins
import sys as _sys

_PLOTLY_PREFIX = "%%PLOTLY%%"
# 与 sandbox-agent 的 PLOTLY_CAP_BYTES 对齐：超出即丢弃并提示降采样。
_PLOTLY_MAX_BYTES = 3 * 1024 * 1024


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
    print(_PLOTLY_PREFIX + payload, flush=flush)


_builtins.show_plotly = show_plotly
