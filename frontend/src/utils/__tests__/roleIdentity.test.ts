import { describe, expect, it } from 'vitest'
import { resolveRoleIdentity } from '@/utils/roleIdentity'

describe('resolveRoleIdentity', () => {
  it('uses localized fallback fields when backend fields are absent', () => {
    expect(resolveRoleIdentity('agent-rnaseq')).toEqual({
      name: 'RNA-seq 分析师',
      avatar: '🧬',
      color: '#7c3aed',
      role: 'worker',
    })
  })

  it('keeps dynamic Agent YAML identity fields when supplied', () => {
    expect(resolveRoleIdentity('agent-rnaseq', {
      name: '动态名称',
      avatar: 'R',
      color: '#123456',
    })).toMatchObject({ name: '动态名称', avatar: 'R', color: '#123456' })
  })
})
