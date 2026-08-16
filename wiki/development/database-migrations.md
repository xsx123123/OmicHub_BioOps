# 数据库迁移

使用 Alembic 管理 PostgreSQL 迁移。

## 常用命令

```bash
# 执行迁移到最新
make migrate

# 创建新迁移
make migrate-new m="add xxx table"

# 回滚上一个
make migrate-rollback

# 合并多分支
make migrate-merge

# 静态检查迁移链
make check-migrations

# 检查 Alembic 多分支
make check-alembic-heads
```

## 迁移链健康检查

`make check-migrations` 会检查：

- 每个迁移能解析 `revision`、`down_revision`、`depends_on`
- 父迁移真实存在
- 迁移链只有一个 root 且拓扑连通
- `alembic heads` 唯一

## 常见错误

### `down_revision` 指向错误

迁移应指向创建其依赖表的父迁移，否则空库升级会报：

```text
sqlalchemy.exc.ProgrammingError: relation "xxx" does not exist
```

### Multiple Heads

多人并行创建迁移且未合并时出现。修复：

```bash
make migrate-merge
```
