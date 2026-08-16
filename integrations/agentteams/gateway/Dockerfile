FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi 'httpx>=0.27.0' 'pydantic-settings>=2.1.0' 'redis>=5.0.0' 'uvicorn[standard]>=0.27.0'
COPY omichub_agent_gateway ./omichub_agent_gateway
RUN useradd --create-home --uid 10002 gateway
RUN mkdir -p /var/lib/omichub-agent-gateway && chown gateway:gateway /var/lib/omichub-agent-gateway
USER gateway
EXPOSE 8081
CMD ["uvicorn", "omichub_agent_gateway.app:app", "--host", "0.0.0.0", "--port", "8081"]
