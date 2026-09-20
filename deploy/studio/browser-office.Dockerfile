# syntax=docker/dockerfile:1.7
# OmicStudio 独立浏览器/文档能力镜像。
# 先构建 base，再执行：
ARG CYGNUSX_IMAGE_TAG=v0.0.2dev
# docker build --build-arg CYGNUSX_IMAGE_TAG=v0.0.2dev \
#   -t cygnusx-sandbox-browser-office:v0.0.2dev \
#   -f deploy/studio/browser-office.Dockerfile deploy/studio
FROM cygnusx-sandbox-bio:${CYGNUSX_IMAGE_TAG}

USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    CHROME_BIN=/usr/bin/chromium \
    PYTHONPATH=/opt/sandbox \
    TMPDIR=/tmp/chromium \
    ONLYOFFICE_DOCUMENT_SERVER_URL=http://onlyoffice-documentserver

# 构建期切换中科大 apt 源，加速 apt-get（兼容 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list; \
    fi

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    mkdir -p /opt/playwright-browsers /tmp/chromium /tmp/downloads \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        fonts-liberation \
    && python -m pip install --prefer-binary playwright python-docx python-pptx \
    && chown -R 10001:10001 /opt/playwright-browsers /tmp/chromium /tmp/downloads \
    && rm -rf /var/lib/apt/lists/*

USER 10001:10001
WORKDIR /workspace
CMD ["sh", "-c", "rm -f /workspace/.agent.sock && exec uvicorn --app-dir /opt/sandbox sandbox_agent:app --uds /workspace/.agent.sock"]
