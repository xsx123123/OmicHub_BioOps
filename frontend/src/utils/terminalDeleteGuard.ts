/**
 * 云端沙盒终端删除操作守护。
 *
 * 沙盒容器挂载了用户持久化的 workspace / raw_data / temp 目录，容器内删除
 * 即平台数据删除且不可恢复。这里在前端输入链路做行缓冲：用户按下回车时
 * 若命令行命中删除类命令，则拦截回车并弹出二次确认，确认后才把回车（或
 * 清行控制符）发给后端 ttyd，防止误删数据。
 *
 * 纯函数/纯状态机，不发起网络请求、不访问全局状态（fontend.md §13.5 同款纪律）。
 */

/** 删除类动词：rm / rmdir / unlink / shred */
const DELETE_VERBS = '(?:rm|rmdir|unlink|shred)'
/** 命令起点：行首、; & | 之后、换行、反引号或 $() 内 */
const CMD_BOUNDARY = '(?:^|[;&|]\\s*|\\n|`\\s*|\\$\\(\\s*)'
/** 常见前缀：sudo / env / command / time / nohup / nice / xargs 及其单横杠选项 */
const CMD_PREFIXES = '(?:(?:sudo|env|command|time|nohup|nice|xargs)\\s+(?:-\\S+\\s+)*)*'

const DELETE_COMMAND_RE = new RegExp(`${CMD_BOUNDARY}${CMD_PREFIXES}${DELETE_VERBS}(?=\\s|$)`)
/** find ... -delete / -exec rm 等变体 */
const FIND_DELETE_RE = /\bfind\b(?:(?![;&|]).)*(?:\s-delete\b|-exec\s+(?:\S+\/)?rm\b)/
/** git rm / git clean 同样会删除工作区文件 */
const GIT_DELETE_RE = /\bgit\s+(?:rm\b|clean\b)/

/**
 * 判断一行 shell 命令是否为删除类操作。
 * 仅做启发式匹配（命令边界 + 动词），用于"提示"而非安全边界。
 */
export function isDangerousDeleteCommand(command: string): boolean {
  const cmd = command.trim()
  if (!cmd) return false
  return DELETE_COMMAND_RE.test(cmd) || FIND_DELETE_RE.test(cmd) || GIT_DELETE_RE.test(cmd)
}

export interface LineFeedResult {
  /** 本次输入中包含一次回车提交时，返回提交的完整命令行（否则 null） */
  submitted: string | null
}

/**
 * 终端输入行缓冲状态机。
 *
 * 跟踪用户在 pty 当前行上输入的内容：打印字符累积、退格删减、
 * Ctrl+C/U/K 清零；方向键/历史搜索/Tab 补全等会"带外"改变 shell 行内容，
 * 标记 uncertain 后本次提交跳过删除检测（避免误报打扰）。
 * 括号粘贴（bracketed paste）内的内容按普通字符累积，粘贴中的换行不视为提交。
 */
export class TerminalLineBuffer {
  private buffer = ''
  private uncertain = false
  private inPaste = false
  private esc = ''

  reset(): void {
    this.buffer = ''
    this.uncertain = false
    this.inPaste = false
    this.esc = ''
  }

  feed(data: string): LineFeedResult {
    let submitted: string | null = null
    for (const ch of data) {
      // 转义序列累积到终止字节；仅识别括号粘贴标记，其余序列标记 uncertain
      if (this.esc) {
        this.esc += ch
        if (this.esc === '\x1b[200~') {
          this.inPaste = true
          this.esc = ''
        } else if (this.esc === '\x1b[201~') {
          this.inPaste = false
          this.esc = ''
        } else if (/[a-zA-Z~]/.test(ch)) {
          if (!this.inPaste) this.uncertain = true
          this.esc = ''
        }
        continue
      }
      if (ch === '\x1b') {
        this.esc = ch
        continue
      }
      if (ch === '\r' || ch === '\n') {
        // 粘贴内的换行是多行命令的一部分，不触发提交
        if (ch === '\n' && this.inPaste) {
          this.buffer += ch
          continue
        }
        submitted = this.uncertain ? '' : this.buffer
        this.buffer = ''
        this.uncertain = false
        continue
      }
      if (ch === '\x7f' || ch === '\b') {
        this.buffer = this.buffer.slice(0, -1)
        continue
      }
      if (ch === '\x03') {
        // Ctrl+C：行中断
        this.buffer = ''
        this.uncertain = false
        continue
      }
      if (ch === '\x15' || ch === '\x0b') {
        // Ctrl+U / Ctrl+K：清行
        this.buffer = ''
        continue
      }
      if (ch === '\t') {
        if (!this.inPaste) this.uncertain = true
        continue
      }
      if (ch < ' ') continue // 其余控制字符不影响行内容
      this.buffer += ch
    }
    return { submitted }
  }
}
