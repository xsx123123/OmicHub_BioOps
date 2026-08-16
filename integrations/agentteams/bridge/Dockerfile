FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi 'httpx>=0.27.0' 'pydantic-settings>=2.1.0' 'redis>=5.0.0' 'uvicorn[standard]>=0.27.0'
COPY omichub_agentteams_bridge ./omichub_agentteams_bridge
RUN useradd --create-home --uid 10001 bridge
RUN mkdir -p /var/lib/omichub-agentteams-bridge && chown bridge:bridge /var/lib/omichub-agentteams-bridge
USER bridge
EXPOSE 8080
