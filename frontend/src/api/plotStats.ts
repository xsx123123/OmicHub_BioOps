import apiClient from '@/api/client'

export interface PosthocComparison {
  group_a: string
  group_b: string
  p_value: number
}

export interface PosthocResult {
  method: 'tukey' | 'dunn'
  adjust: 'none' | 'bonferroni' | 'fdr_bh'
  comparisons: PosthocComparison[]
  letters: Record<string, string>
}

export async function fetchPosthocComparisons(payload: {
  groups: Record<string, number[]>
  method: 'tukey' | 'dunn'
  adjust: 'none' | 'bonferroni' | 'fdr_bh'
}): Promise<PosthocResult> {
  const { data } = await apiClient.post<PosthocResult>('/stats/posthoc', payload)
  return data
}
