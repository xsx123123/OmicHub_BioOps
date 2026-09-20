import apiClient from '../client'

/** 连接池占用快照（NullPool 等无容量语义的池只有 class 字段） */
export interface PoolStats {
  class: string
  size?: number
  checked_out?: number
  checked_in?: number
  overflow?: number
}

/** 数据库健康汇总（GET /admin/database/health） */
export interface DatabaseHealth {
  service_name: string
  /** alembic_version 表中的版本戳列表 */
  alembic_db_version: string[]
  /** 代码侧 alembic head 列表 */
  alembic_head: string[]
  version_in_sync: boolean
  table_count: number
  readonly_replica_configured: boolean
  pool: PoolStats
}

/** Schema 漂移对账结果（GET /admin/database/drift） */
export interface SchemaDrift {
  ok: boolean
  missing_tables: string[]
  missing_columns: string[]
  extra_tables: string[]
}

export const adminDatabaseApi = {
  /** 数据库健康汇总 */
  async getHealth(): Promise<DatabaseHealth> {
    const res = await apiClient.get('/admin/database/health')
    return res.data
  },

  /** Schema 漂移检查（ORM metadata ↔ 数据库对账） */
  async getDrift(): Promise<SchemaDrift> {
    const res = await apiClient.get('/admin/database/drift')
    return res.data
  },
}
