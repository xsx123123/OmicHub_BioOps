"""参考基因组模块（常用物种基因数据库）。

物种 → 版本两级 YAML 注册表驱动；每版本一个 SQLite 基因索引（FTS5）；
基因组序列走纯 Python faidx 随机访问，序列不入库。

分层（对齐 tools/ 模块）：
- config.py   YAML 加载器（mtime 热重载，缺失回退空配置，绝不抛异常）
- schema.py   Pydantic DTO（alias 输出 camelCase，与前端类型对齐）
- service.py  查询逻辑（SQLite / faidx / YAML 审计）
- api.py      路由 + 鉴权（Depends(get_current_user)）
- indexer.py  离线构建：GFF3/GO/KEGG/注释 → SQLite（python -m omichub.reference_genomes.indexer）
- sequence.py 纯 Python faidx 读取器（不引入 pysam/pyfaidx 依赖）

设计文档：docs/26.8.4/常用物种基因数据库_实施方案.md（唯一权威设计）
原始蓝图：refdata/README.md
"""
