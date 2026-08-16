import type { FastaRecord, SequenceStats } from '../types'

export function generateSequenceAiPrompt(record: FastaRecord, stats: SequenceStats, orfCount = 0): string {
  return `# 序列生物学分析请求

请以生物信息学专家身份分析以下序列，并明确区分事实、推测与建议。

## 序列摘要
- ID：${record.id}
- 类型：${record.type}
- 长度：${record.length}
- GC：${stats.gcContent}%
- AT/U：${stats.atContent}%
- N：${stats.nContent}%
- 已检测 ORF：${orfCount}

## 分析任务
1. 评估 GC 偏好及可能的生物学来源特征，包括线粒体、叶绿体或高 GC 微生物等可能性。
2. 结合 ORF 数量与长度讨论编码潜力，并指出还需要哪些证据才能形成结论。
3. 推荐后续检索策略，包括适合的 BLAST 程序与数据库。
4. 给出引物设计、结构预测（如 AlphaFold / RiboFold）或其它下游分析建议。
5. 列出数据质量风险，例如简并碱基、序列过短或潜在污染。

## 序列
\`\`\`fasta
>${record.header}
${record.sequence}
\`\`\``
}
