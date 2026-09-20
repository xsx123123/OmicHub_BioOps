import { describe, expect, it } from 'vitest'
import { MAX_SUGGESTIONS, normalizeSuggestions, parseNextStepSuggestions } from './nextStepSuggestions'

const SAMPLE_REPLY = [
  '分析已完成，进化树已构建。',
  '',
  '**可选下一步**',
  '',
  '1. 标签精简/分组着色：把叶片名改成短名，并按分组着色',
  '2. 进化枝注释：在关键分支上添加 bootstrap 支持度',
  '3. 版式微调：把树旋转为横向排版并放大字体',
  '4. 提供 .contree 文件路径：我可以基于它叠加更多注释',
].join('\n')

describe('parseNextStepSuggestions', () => {
  it('解析标准"可选下一步"章节，label 取冒号前短名、prompt 取条目全文', () => {
    const suggestions = parseNextStepSuggestions(SAMPLE_REPLY)
    expect(suggestions).toHaveLength(4)
    expect(suggestions[0]).toEqual({
      label: '标签精简/分组着色',
      prompt: '标签精简/分组着色：把叶片名改成短名，并按分组着色',
      action: 'send',
    })
    expect(suggestions[1].label).toBe('进化枝注释')
  })

  it('含"提供/上传/文件/路径"关键词的条目判定为 prefill，其余为 send', () => {
    const suggestions = parseNextStepSuggestions(SAMPLE_REPLY)
    expect(suggestions.map((s) => s.action)).toEqual(['send', 'send', 'send', 'prefill'])
    expect(parseNextStepSuggestions('可选下一步\n1. 上传参考基因组后继续比对')[0].action).toBe('prefill')
  })

  it('兼容变体标题：下一步建议 / Markdown 标题 / 全角冒号结尾', () => {
    const body = '1. 调整配色：换成蓝紫色系'
    expect(parseNextStepSuggestions(`### 下一步建议\n${body}`)[0]?.label).toBe('调整配色')
    expect(parseNextStepSuggestions(`## 可选下一步：\n${body}`)).toHaveLength(1)
    expect(parseNextStepSuggestions(`**可选的下一步**\n${body}`)).toHaveLength(1)
  })

  it('无"可选下一步"章节时返回空数组', () => {
    expect(parseNextStepSuggestions('闲聊回复，没有任何建议。')).toEqual([])
    expect(parseNextStepSuggestions('')).toEqual([])
  })

  it('章节下无有序列表项时返回空数组', () => {
    expect(parseNextStepSuggestions('可选下一步\n暂无更多建议。')).toEqual([])
    expect(parseNextStepSuggestions('可选下一步\n- 无序列表不算数\n- 也不算')).toEqual([])
  })

  it(`条目超过 ${MAX_SUGGESTIONS} 条时只取前 ${MAX_SUGGESTIONS} 条`, () => {
    const items = Array.from({ length: 6 }, (_, i) => `${i + 1}. 建议${i + 1}：继续`)
    const suggestions = parseNextStepSuggestions(['可选下一步', ...items].join('\n'))
    expect(suggestions).toHaveLength(MAX_SUGGESTIONS)
    expect(suggestions[MAX_SUGGESTIONS - 1].label).toBe('建议4')
  })

  it('条目无冒号/破折号时 label 截断前 12 字并加省略号', () => {
    const [suggestion] = parseNextStepSuggestions(
      '可选下一步\n1. 这是一条没有任何分隔符的超长建议条目文本内容',
    )
    expect(suggestion.label).toBe('这是一条没有任何分隔符的…')
    expect(suggestion.prompt).toBe('这是一条没有任何分隔符的超长建议条目文本内容')
  })

  it('支持破折号分隔符与全角编号标记', () => {
    const suggestions = parseNextStepSuggestions(
      '可选下一步\n1、支持度叠加 — 在分支上显示 bootstrap 值\n2) 导出图片 - 生成高清 PNG',
    )
    expect(suggestions).toHaveLength(2)
    expect(suggestions[0].label).toBe('支持度叠加')
    expect(suggestions[1].label).toBe('导出图片')
  })

  it('遇到下一个标题或段落即停止收集条目', () => {
    const markdown = '可选下一步\n1. 第一条：继续\n\n## 其他说明\n2. 这条属于别的章节\n3. 也是'
    expect(parseNextStepSuggestions(markdown)).toHaveLength(1)
  })

  it('剥除条目中的加粗/链接等行内 Markdown', () => {
    const [suggestion] = parseNextStepSuggestions(
      '可选下一步\n1. **版式调整**：参考 [样式指南](https://example.com) 微调',
    )
    expect(suggestion.label).toBe('版式调整')
    expect(suggestion.prompt).toBe('版式调整：参考 样式指南 微调')
  })

  it('异常输入不抛错，返回空数组', () => {
    expect(parseNextStepSuggestions(undefined as unknown as string)).toEqual([])
    expect(parseNextStepSuggestions(null as unknown as string)).toEqual([])
  })

  it('正文提到"可选下一步"的长句不被误判为章节标题', () => {
    const prose = '如果你愿意，我可以给出可选下一步的详细说明，包括更多分析方向供你选择'
    expect(parseNextStepSuggestions(`${prose}\n1. 误命中：不该被解析`)).toEqual([])
  })
})

describe('normalizeSuggestions（阶段 2 结构化字段校验）', () => {
  it('接受形状完整的结构化建议，action 以字段值为准', () => {
    const raw = [
      { label: '版式调整', prompt: '版式调整：把树旋转为横向排版', action: 'send' },
      { label: '叠加注释', prompt: '提供 .contree 文件路径', action: 'prefill' },
    ]
    expect(normalizeSuggestions(raw)).toEqual(raw)
  })

  it('含"提供/文件"关键词但 action 显式为 send 时不改判', () => {
    const [item] = normalizeSuggestions([
      { label: '说明文件格式', prompt: '说明支持的文件格式', action: 'send' },
    ])
    expect(item.action).toBe('send')
  })

  it('非数组 / 空数组 / 畸形条目一律返回空数组，不抛错', () => {
    expect(normalizeSuggestions(undefined)).toEqual([])
    expect(normalizeSuggestions(null)).toEqual([])
    expect(normalizeSuggestions('suggestions')).toEqual([])
    expect(normalizeSuggestions([])).toEqual([])
    expect(
      normalizeSuggestions([{ label: '', prompt: 'x' }, { prompt: 'y' }, null, 42]),
    ).toEqual([])
  })

  it('未知 action 回退为 send，且最多保留 4 条', () => {
    const items = Array.from({ length: 6 }, (_, i) => ({
      label: `建议${i + 1}`,
      prompt: `建议${i + 1}：继续`,
      action: i === 0 ? 'bogus' : 'send',
    }))
    const normalized = normalizeSuggestions(items)
    expect(normalized).toHaveLength(MAX_SUGGESTIONS)
    expect(normalized[0].action).toBe('send')
  })
})
