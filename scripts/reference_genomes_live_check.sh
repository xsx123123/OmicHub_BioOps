#!/bin/sh
# 实栈验证：在 cygnusx-web 容器内生成合法 token 并调全部关键端点。
# 用法：sh scripts/reference_genomes_live_check.sh
set -e
docker exec cygnusx-web sh -c '
TOKEN=$(PYTHONPATH=/app/src python -c "
import logging
logging.disable(logging.CRITICAL)  # 静音 SQLAlchemy echo 日志，避免污染 stdout
import asyncio
from sqlalchemy import text
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.core.security import create_access_token
async def main():
    factory = get_session_factory()
    async with factory() as db:
        row = (await db.execute(text(\"SELECT id, token_version FROM users WHERE status=\$\$active\$\$ ORDER BY created_at LIMIT 1\"))).fetchone()
        print(\"TOKEN:\" + create_access_token(str(row[0]), row[1]))
asyncio.run(main())
" 2>/dev/null | grep "^TOKEN:" | cut -c7-)
echo "token-len=${#TOKEN}"
B="http://localhost:8000/api/v1/reference-genomes"
A="Authorization: Bearer $TOKEN"
echo "--- GET /species (截断)"
curl -s -H "$A" "$B/species" | head -c 300; echo
echo "--- GET /versions/tair10 (截断)"
curl -s -H "$A" "$B/versions/tair10" | head -c 400; echo
echo "--- GET genes?field=gene_id&q=AT1G01010"
curl -s -H "$A" "$B/versions/tair10/genes?field=gene_id&q=AT1G01010" | head -c 400; echo
echo "--- GET genes/AT1G01010 聚合"
curl -s -H "$A" "$B/versions/tair10/genes/AT1G01010" | python -c "import json,sys; d=json.load(sys.stdin); print(\"go:\", len(d[\"go\"]), \"| kos:\", [k[\"koId\"] for k in d[\"kegg\"][\"kos\"]], \"| seqAvail:\", d[\"sequenceAvailable\"])"
echo "--- GET AT1G51370 cds/protein"
curl -s -H "$A" "$B/versions/tair10/genes/AT1G51370/sequence?type=cds" | python -c "import json,sys; d=json.load(sys.stdin); print(\"cds head:\", d[\"sequence\"][:24], \"tx:\", d.get(\"transcriptId\"))"
curl -s -H "$A" "$B/versions/tair10/genes/AT1G51370/sequence?type=protein" | python -c "import json,sys; d=json.load(sys.stdin); print(\"pep head:\", d[\"sequence\"][:20])"
echo "--- GET sequence region"
curl -s -H "$A" "$B/versions/tair10/sequence?chrom=Chr1&start=3631&end=3730" | python -c "import json,sys; d=json.load(sys.stdin); print(\"len:\", d[\"length\"], d[\"sequence\"][:40])"
echo "--- GO/KEGG 反查"
curl -s -H "$A" "$B/versions/tair10/genes?field=go&q=GO:0003700" | python -c "import json,sys; print(\"go 反查 total:\", json.load(sys.stdin)[\"total\"])"
curl -s -H "$A" "$B/versions/tair10/genes?field=kegg&q=glycolysis" | python -c "import json,sys; print(\"kegg 反查 total:\", json.load(sys.stdin)[\"total\"])"
echo "--- 全局搜索 NAC"
curl -s -H "$A" "$B/search?q=NAC&limit=3" | python -c "import json,sys; d=json.load(sys.stdin); print(\"genes:\",len(d[\"genes\"]),\"| goTerms:\",len(d[\"goTerms\"]),\"| kegg:\",len(d[\"kegg\"]))"
echo "--- batch"
curl -s -X POST -H "$A" -H "Content-Type: application/json" -d "{\"gene_ids\":[\"AT1G01010\",\"AT1G01020\",\"NOPE\"]}" "$B/versions/tair10/genes/batch" | python -c "import json,sys; d=json.load(sys.stdin); print(\"total:\",d[\"total\"],\"found:\",d[\"found\"])"
'
