# 1. 使用稳定版基础镜像 (Bookworm)
FROM python:3.12.12-slim-bookworm

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai

# --- 关键修复：解决非 Root 用户运行时的权限问题 ---
# 创建一个所有用户可写的目录作为 HOME
RUN mkdir -p /tmp_home && chmod 777 /tmp_home
ENV HOME=/tmp_home

# 2. 安装系统依赖
# fonts-noto-cjk: 解决绘图和报告中的中文乱码
# gdebi-core: 用于安装 Quarto deb 包
# procps: 某些监控工具可能需要 ps 命令
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gdebi-core \
    fonts-noto-cjk \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 Quarto（vendor 本地化，见 Protocol/镜像构建国内加速规范_v1.md §5.2）
#    缺失时重新下载：
#    curl -L -o pipelines/ATACFlow/report/docker/RNA/docker_build/vendor/quarto-1.8.26-linux-amd64.deb \
#      "https://github.com/quarto-dev/quarto-cli/releases/download/v1.8.26/quarto-1.8.26-linux-amd64.deb"
COPY vendor/quarto-1.8.26-linux-amd64.deb /tmp/quarto.deb
RUN dpkg -i /tmp/quarto.deb \
    && rm /tmp/quarto.deb

# 验证安装
RUN quarto check install

# 4. 安装 Python 依赖
COPY docker_build/requirements.txt /tmp/requirements.txt

# 使用中科大源加速
RUN pip install --no-cache-dir -i https://mirrors.ustc.edu.cn/pypi/simple \
    -r /tmp/requirements.txt

# 5. 部署应用代码
# 建议保持在 /app 目录下，结构清晰
WORKDIR /app

COPY entrypoint.py /app/
# 复制一个默认配置作为 fallback (运行时会被挂载覆盖)
COPY project_summary.json /app/project_summary.json
COPY templates /app/templates/

RUN chmod -R 777 /app/templates /tmp_home/

# 6. 启动命令
# 确保使用 list 格式 ["executable", "param"]
ENTRYPOINT ["python", "entrypoint.py"]
