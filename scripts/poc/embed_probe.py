"""PoC Step 0.2 — Embedding 端点探针。

探测现有云端 key 是否支持 OpenAI 兼容 embedding：
  1) 阿里云 compatible-mode: text-embedding-v3 / v4（AL_API_KEY）
  2) 火山 Ark /api/v3: doubao-embedding-large-250528 等（ARK_API_KEY）

成功标准：HTTP 200 且返回向量维度可用。密钥只从环境变量读取，不打印。
用法：python3 scripts/poc/embed_probe.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

PROBES = [
    # (label, url, model, key_env, extra_body)
    (
        "aliyun/text-embedding-v3(dim=1024)",
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings",
        "text-embedding-v3",
        "AL_API_KEY",
        {"dimensions": 1024},
    ),
    (
        "aliyun/text-embedding-v4(dim=1024)",
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings",
        "text-embedding-v4",
        "AL_API_KEY",
        {"dimensions": 1024},
    ),
    (
        "ark/doubao-embedding-large-250528",
        "https://ark.cn-beijing.volces.com/api/v3/embeddings",
        "doubao-embedding-large-250528",
        "ARK_API_KEY",
        {},
    ),
    (
        "ark/doubao-embedding-large",
        "https://ark.cn-beijing.volces.com/api/v3/embeddings",
        "doubao-embedding-large",
        "ARK_API_KEY",
        {},
    ),
]

TEXT = "用户偏好使用 DESeq2 做差异表达分析，研究对象是小鼠肝脏组织。"


def probe(label: str, url: str, model: str, key_env: str, extra: dict) -> None:
    key = os.environ.get(key_env, "")
    if not key:
        print(f"[SKIP] {label}: env {key_env} 未设置")
        return
    body = {"model": model, "input": TEXT, **extra}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        vec = data.get("data", [{}])[0].get("embedding", [])
        print(f"[OK]   {label}: HTTP {resp.status}, dim={len(vec)}, "
              f"usage={data.get('usage', {})}")
    except urllib.error.HTTPError as exc:
        snippet = exc.read().decode(errors="replace")[:200]
        print(f"[FAIL] {label}: HTTP {exc.code} -> {snippet}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")


def main() -> None:
    for args in PROBES:
        probe(*args)


if __name__ == "__main__":
    main()
