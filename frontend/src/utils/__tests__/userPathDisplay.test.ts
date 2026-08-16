import { describe, expect, it } from 'vitest'
import { formatUserPath, redactUserHomePaths } from '../userPathDisplay'

describe('formatUserPath', () => {
  it('only exposes the path below a user home directory', () => {
    expect(formatUserPath('/data/omichub/users/cb79a200-b2ca-441f-9a42-d3417fbfa89d/raw_data/raw-data/PRJNA1478012'))
      .toBe('/raw_data/raw-data/PRJNA1478012')
  })

  it('represents a user home itself as the visible root', () => {
    expect(formatUserPath('/data/omichub/users/cb79a200-b2ca-441f-9a42-d3417fbfa89d')).toBe('/')
  })

  it('does not rewrite platform or temporary paths', () => {
    expect(formatUserPath('/data/omichub/omichub_data/db/Ath/TAIR10')).toBe('/data/omichub/omichub_data/db/Ath/TAIR10')
    expect(formatUserPath('/tmp/omichub/task-1')).toBe('/tmp/omichub/task-1')
  })

  it('handles empty values safely', () => {
    expect(formatUserPath(undefined)).toBe('')
    expect(formatUserPath('  ')).toBe('')
  })
})

describe('redactUserHomePaths', () => {
  it('removes every embedded user-home prefix from status text', () => {
    expect(redactUserHomePaths(
      'Failed writing /data/omichub/users/user-a/raw_data/a.txt; retry /data/omichub/users/user-a/raw_data/b.txt.',
    )).toBe('Failed writing /raw_data/a.txt; retry /raw_data/b.txt.')
  })

  it('keeps non-user paths intact', () => {
    expect(redactUserHomePaths('Missing /tmp/task.log')).toBe('Missing /tmp/task.log')
  })
})
