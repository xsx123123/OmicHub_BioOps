import { describe, expect, it } from 'vitest'
import { readActiveMentionQuery } from '@/components/ai-chat/mentionQuery'

describe('readActiveMentionQuery', () => {
  it('保留包含空格的未提交文件查询', () => {
    expect(readActiveMentionQuery('请分析 @docs/report copy')).toBe('docs/report copy')
  })

  it('Agent 被选中后关闭提及查询', () => {
    expect(readActiveMentionQuery('@RNA-seq 分析师 ', ['RNA-seq 分析师'])).toBeNull()
    expect(readActiveMentionQuery('@RNA-seq 分析师 你可以干什么呀', ['RNA-seq 分析师'])).toBeNull()
  })

  it('已提交引用后输入新的 @ 可再次打开查询', () => {
    expect(readActiveMentionQuery('@RNA-seq 分析师 请使用 @enri', ['RNA-seq 分析师'])).toBe('enri')
  })
})
