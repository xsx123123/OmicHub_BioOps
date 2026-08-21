FROM python:3.11-slim

# 部署版本可观测：构建时经 --build-arg 注入，/healthz 的 build_sha/build_time 由此取值。
ARG BRIDGE_BUILD_SHA=unknown
ARG BRIDGE_BUILD_TIME=unknown
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV BRIDGE_BUILD_SHA=${BRIDGE_BUILD_SHA} \
    BRIDGE_BUILD_TIME=${BRIDGE_BUILD_TIME} \
    PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app
COPY pyproject.toml ./
RUN python -m pip install \
    --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout 60 \
    --retries 5 \
    fastapi 'httpx>=0.27.0' 'minio>=7.2.0' 'pydantic-settings>=2.1.0' 'redis>=5.0.0' 'uvicorn[standard]>=0.27.0'
COPY omichub_agentteams_bridge ./omichub_agentteams_bridge
RUN useradd --create-home --uid 10001 bridge
RUN mkdir -p /var/lib/omichub-agentteams-bridge && chown bridge:bridge /var/lib/omichub-agentteams-bridge
USER bridge
EXPOSE 8080
