# OmicStudio 沙盒基础镜像（omichub-sandbox:base）
# 构建：docker build -t omichub-sandbox:base -f deploy/studio/base.Dockerfile deploy/studio
#
# 设计（架构设计 §6.1）：
# - python:3.12-slim + 数据分析栈（pandas/numpy/matplotlib/plotly/seaborn
#   + scikit-learn/scipy/statsmodels + openpyxl/pyarrow）
# - 内置 sandbox-agent 小服务（/exec /files/*），宿主经工作区 Unix Socket 直连交互
# - 统一非 root 用户（uid 10001），/workspace 为唯一可写工作区
FROM python:3.12-slim

LABEL maintainer="OmicHub"
LABEL description="OmicStudio sandbox base image (data science stack + sandbox-agent)"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    SANDBOX_WORKSPACE=/workspace

# 非 root 运行用户 + 工作区目录（uid 10001，宿主编排侧负责挂载目录放权）
RUN useradd --create-home --uid 10001 sandbox \
    && mkdir -p /workspace/.logs \
    && chown -R 10001:10001 /workspace

# 预置中科大 PyPI 镜像，加速构建期与运行期 pip 安装
RUN printf '%s\n' \
      '[global]' \
      'index-url = https://pypi.mirrors.ustc.edu.cn/simple' \
      'extra-index-url = https://mirrors.aliyun.com/pypi/simple/' \
      'timeout = 60' \
      'retries = 10' \
      > /etc/pip.conf

# sandbox-agent 依赖（最小集）+ 数据分析栈
COPY requirements-agent.txt /tmp/requirements-agent.txt
RUN pip install -i https://pypi.mirrors.ustc.edu.cn/simple -r /tmp/requirements-agent.txt \
    && pip install -i https://pypi.mirrors.ustc.edu.cn/simple \
        pandas \
        numpy \
        matplotlib \
        plotly \
        seaborn \
        scikit-learn \
        scipy \
        statsmodels \
        openpyxl \
        pyarrow \
    && rm -f /tmp/requirements-agent.txt

# 烘焙 sandbox-agent 服务
COPY sandbox_agent.py /opt/sandbox/sandbox_agent.py

USER 10001
WORKDIR /workspace
CMD ["sh", "-c", "rm -f /workspace/.agent.sock && exec uvicorn --app-dir /opt/sandbox sandbox_agent:app --uds /workspace/.agent.sock"]
