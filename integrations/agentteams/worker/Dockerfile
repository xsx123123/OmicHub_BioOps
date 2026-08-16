FROM python:3.11-slim

WORKDIR /app
COPY claim_next.py ./claim_next.py
COPY production_runner.py ./production_runner.py
COPY analysis_runner.py ./analysis_runner.py
COPY quality_runner.py ./quality_runner.py
COPY delivery_runner.py ./delivery_runner.py
COPY worker_runner.py ./worker_runner.py
COPY entrypoint.sh ./entrypoint.sh
RUN useradd --create-home --uid 10002 worker
USER worker

ENTRYPOINT ["/app/entrypoint.sh"]
