"""BLAST API Locust 场景。

运行：
  OMICHUB_ACCESS_TOKEN=... uvx locust -f tests/performance/locust_blast.py \
    --host http://localhost:8000 --users 50 --spawn-rate 5 --run-time 10m

可选设置 OMICHUB_BLAST_DB_ID；未设置时自动选择第一个可用数据库。
"""

from __future__ import annotations

import os
import time

from locust import HttpUser, between, task

QUERY = ">locust-query\nATGCGTACGTATGCGTACGTATGCGTACGTATGCGTACGT"


class BlastUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        token = os.environ.get("OMICHUB_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("OMICHUB_ACCESS_TOKEN is required")
        self.client.headers.update({"Authorization": f"Bearer {token}"})
        self.db_id = os.environ.get("OMICHUB_BLAST_DB_ID")
        if not self.db_id:
            response = self.client.get("/api/v1/blast/databases", name="GET databases")
            response.raise_for_status()
            databases = response.json()
            if not databases:
                raise RuntimeError("No ready BLAST database is available")
            self.db_id = databases[0]["id"]

    @task(3)
    def submit_and_follow_query(self) -> None:
        with self.client.post(
            "/api/v1/blast/submit",
            name="POST submit",
            json={
                "db_id": self.db_id,
                "query_sequence": QUERY,
                "query_title": "locust-query",
                "evalue": 1e-5,
                "max_target_seqs": 10,
            },
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"submit failed: {response.status_code}")
                return
            task_data = response.json()
            task_id = task_data["task_id"]
            if task_data["status"] == "completed":
                response.success()
                return

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status_response = self.client.get(
                f"/api/v1/blast/tasks/{task_id}", name="GET task status"
            )
            if status_response.status_code != 200:
                return
            status = status_response.json()["status"]
            if status == "completed":
                self.client.get(
                    f"/api/v1/blast/results/{task_id}",
                    name="GET result",
                    params={"format": "json"},
                )
                return
            if status in {"failed", "cancelled"}:
                return
            time.sleep(2)

    @task(1)
    def list_history(self) -> None:
        self.client.get(
            "/api/v1/blast/tasks",
            name="GET task history",
            params={"page": 1, "page_size": 20},
        )
