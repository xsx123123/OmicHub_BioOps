# BLAST 性能测试

## 50 并发查询

```bash
OMICHUB_ACCESS_TOKEN=<access-token> \
OMICHUB_BLAST_DB_ID=<optional-db-uuid> \
uvx locust -f tests/performance/locust_blast.py \
  --host http://localhost:8000 \
  --headless --users 50 --spawn-rate 5 --run-time 10m \
  --html artifacts/blast-locust.html
```

验收：平均 API 响应时间低于 3 秒，失败率为 0，提交的任务均能进入终态。结果缓存开启后，重复查询应直接返回 `completed`。
