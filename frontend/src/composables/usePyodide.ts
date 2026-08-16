import { ref } from 'vue'

let pyodidePromise: Promise<any> | null = null

export interface PyodideResult {
  output: string
  images: string[]
  error?: string
}

export function usePyodide() {
  async function init(): Promise<any> {
    if (pyodidePromise) return pyodidePromise
    pyodidePromise = (async () => {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore — Pyodide 从 CDN 动态加载，无本地类型声明
      const mod: any = await import('https://cdn.jsdelivr.net/pyodide/v0.26.0/full/pyodide.mjs')
      const py = await mod.loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.0/full/',
      })
      // 预装生信常用库
      await py.loadPackage(['numpy', 'pandas', 'matplotlib'])
      return py
    })()
    return pyodidePromise
  }

  async function execute(code: string): Promise<PyodideResult> {
    const py = await init()
    const output: string[] = []
    const images: string[] = []

    py.setStdout({ batched: (text: string) => output.push(text) })
    py.setStderr({ batched: (text: string) => output.push(text) })

    try {
      // 自动按需安装 import 的第三方包
      await py.loadPackagesFromImports(code)
      await py.runPythonAsync(code)

      // 尝试捕获 matplotlib 图表（如果代码生成了 figure）
      try {
        const buf = py.runPython(`
import matplotlib.pyplot as plt
import io, base64
fig = plt.gcf()
buf = io.BytesIO()
fig.savefig(buf, format='png', bbox_inches='tight')
plt.close(fig)
base64.b64encode(buf.getvalue()).decode('utf-8')
        `)
        if (buf) {
          images.push(`data:image/png;base64,${buf}`)
        }
      } catch {
        // 没有图表时静默忽略
      }

      return { output: output.join(''), images }
    } catch (e: any) {
      return { output: output.join(''), images, error: String(e) }
    }
  }

  return { init, execute }
}
