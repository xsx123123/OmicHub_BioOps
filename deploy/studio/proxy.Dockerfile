# OmicStudio 域名白名单出站代理
FROM python:3.12-slim

RUN useradd --create-home --uid 10002 studio_proxy
COPY requirements-proxy.txt /tmp/requirements-proxy.txt
RUN pip install --no-cache-dir -r /tmp/requirements-proxy.txt \
    && rm -f /tmp/requirements-proxy.txt
COPY egress_proxy.py /opt/studio/egress_proxy.py

USER 10002
WORKDIR /opt/studio
EXPOSE 3128
CMD ["python", "/opt/studio/egress_proxy.py"]
