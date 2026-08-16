import { describe, it, expect } from 'vitest'
import { isDangerousDeleteCommand, TerminalLineBuffer } from '../terminalDeleteGuard'

describe('isDangerousDeleteCommand', () => {
  it.each([
    ['rm file.txt'],
    ['rm -rf workspace/data'],
    ['  rm -i a b  '],
    ['sudo rm -rf /x'],
    ['sudo -E rm a'],
    ['ls && rm a'],
    ['cd /tmp;rm a'],
    ['echo hi | xargs rm'],
    ['find . -name "*.tmp" -delete'],
    ['find . -exec rm {} \\;'],
    ['git rm src/a.txt'],
    ['git clean -fd'],
    ['rm'],
    ['$(rm a)'],
  ])('识别删除命令: %s', (cmd) => {
    expect(isDangerousDeleteCommand(cmd)).toBe(true)
  })

  it.each([
    ['ls -l'],
    ['echo rm'],
    ['cat README.md'],
    ['rmfoo bar'],
    ['grep rm a.txt'],
    ['python train.py --model rm'],
    [''],
    ['   '],
    ['alias rm="rm -i"'],
  ])('放行非删除命令: %s', (cmd) => {
    expect(isDangerousDeleteCommand(cmd)).toBe(false)
  })
})

describe('TerminalLineBuffer', () => {
  function submit(buffer: TerminalLineBuffer, input: string): string | null {
    return buffer.feed(input).submitted
  }

  it('累积打印字符并在回车时提交', () => {
    const buf = new TerminalLineBuffer()
    expect(submit(buf, 'rm -rf foo')).toBe(null)
    expect(submit(buf, '\r')).toBe('rm -rf foo')
    // 提交后缓冲清零
    expect(submit(buf, '\r')).toBe('')
  })

  it('退格删减缓冲', () => {
    const buf = new TerminalLineBuffer()
    buf.feed('rm -rf foo\x7f\x7f\x7f')
    expect(submit(buf, '\r')).toBe('rm -rf ')
  })

  it('Ctrl+C / Ctrl+U 清零缓冲', () => {
    const buf = new TerminalLineBuffer()
    buf.feed('rm a\x03ls -l')
    expect(submit(buf, '\r')).toBe('ls -l')
    buf.feed('rm b\x15echo ok')
    expect(submit(buf, '\r')).toBe('echo ok')
  })

  it('方向键等转义序列标记 uncertain，本次提交跳过检测', () => {
    const buf = new TerminalLineBuffer()
    buf.feed('\x1b[A')
    expect(submit(buf, '\r')).toBe('')
    // 下一行恢复正常检测
    buf.feed('rm a')
    expect(submit(buf, '\r')).toBe('rm a')
  })

  it('括号粘贴累积内容，粘贴内换行不提交', () => {
    const buf = new TerminalLineBuffer()
    const res = buf.feed('\x1b[200~rm -rf a\nrm -rf b\x1b[201~')
    expect(res.submitted).toBe(null)
    expect(submit(buf, '\r')).toBe('rm -rf a\nrm -rf b')
  })

  it('一次性输入含回车的粘贴块逐段处理', () => {
    const buf = new TerminalLineBuffer()
    const res = buf.feed('ls\r')
    expect(res.submitted).toBe('ls')
  })
})
