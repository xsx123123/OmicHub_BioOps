#!/usr/bin/env python3
"""Studio 沙箱「运行前现场装包」路径多线程验证

完全复刻真实 Studio 会话的网络形态：
- Docker internal bridge 网络（无直接外网）
- cygnusx-studio-egress-proxy 以别名 studio-egress-proxy 接入
- 容器注入 HTTP_PROXY/HTTPS_PROXY=http://studio-egress-proxy:3128
  （与 infrastructure/studio/manager.py 的 ensure_running 一致）

验证提示词（data/ai/prompts/*.md）教给 AI 的每条装包路径在白名单下是否走得通，
装完后复跑此前 FAIL 的代表性技能脚本，确认"安装后可运行"闭环。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = Path("/data/cygnusx/skills")
CORE_IMAGE = "cygnusx-analysis:core-v0.0.2dev"
SCRNA_IMAGE = "cygnusx-analysis:scrna-v0.0.3dev"
PROXY_CONTAINER = "cygnusx-studio-egress-proxy"
PROXY_ALIAS = "studio-egress-proxy"

NET_NAME = f"smoke-egress-{datetime.now().strftime('%H%M%S')}"
CORE_NAME = f"smoke-inst-core-{datetime.now().strftime('%H%M%S')}"
SCRNA_NAME = f"smoke-inst-scrna-{datetime.now().strftime('%H%M%S')}"

PROXY_ENV = {
    "HTTP_PROXY": f"http://{PROXY_ALIAS}:3128",
    "HTTPS_PROXY": f"http://{PROXY_ALIAS}:3128",
    "http_proxy": f"http://{PROXY_ALIAS}:3128",
    "https_proxy": f"http://{PROXY_ALIAS}:3128",
    "NO_PROXY": "localhost,127.0.0.1",
    "no_proxy": "localhost,127.0.0.1",
}

_conda_lock = threading.Lock()  # 同容器 micromamba 串行，避免 proc lock 争用

RESULTS: list[dict] = []
_res_lock = threading.Lock()


def run(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"
    except Exception as e:  # noqa: BLE001
        return 125, str(e)


def dexec(container: str, cmd: list[str], timeout: int = 300) -> tuple[int, str]:
    return run(["docker", "exec", container, *cmd], timeout=timeout)


def record(probe: str, container: str, expect: str, rc: int, out: str,
           verdict: str, note: str = "") -> None:
    tail = " | ".join(ln.strip() for ln in out.strip().splitlines() if ln.strip())[-500:]
    with _res_lock:
        RESULTS.append({
            "probe": probe, "container": container, "expect": expect,
            "rc": rc, "verdict": verdict, "note": note, "tail": tail,
        })
    mark = {"PASS": "✅", "FAIL": "❌", "BLOCKED-AS-EXPECTED": "🚫(预期内拦截)"}
    print(f"{mark.get(verdict, '❓')} [{probe}] rc={rc} {note}")


def setup_network_and_containers() -> bool:
    ok, out = run(["docker", "network", "create", "--internal",
                   "--label", "cygnusx.studio.egress=smoke", NET_NAME], 60)
    if ok != 0:
        print(f"创建 internal 网络失败: {out}")
        return False
    ok, out = run(["docker", "network", "connect", "--alias", PROXY_ALIAS,
                   NET_NAME, PROXY_CONTAINER], 60)
    if ok != 0:
        print(f"接入代理失败: {out}")
        return False
    for name, image in ((CORE_NAME, CORE_IMAGE), (SCRNA_NAME, SCRNA_IMAGE)):
        env_args = [a for kv in PROXY_ENV.items() for a in ("-e", f"{kv[0]}={kv[1]}")]
        ok, out = run(["docker", "run", "-d", "--name", name, "--network", NET_NAME,
                       "--entrypoint", "sleep", *env_args, image, "infinity"], 180)
        if ok != 0:
            print(f"启动 {name} 失败: {out}")
            return False
    print(f"[setup] internal 网络 {NET_NAME} + 代理别名 {PROXY_ALIAS} + 2 容器就绪")
    return True


def teardown() -> None:
    for name in (CORE_NAME, SCRNA_NAME):
        run(["docker", "rm", "-f", name], 60)
    run(["docker", "network", "disconnect", NET_NAME, PROXY_CONTAINER], 60)
    run(["docker", "network", "rm", NET_NAME], 60)
    print("[teardown] 清理完成")


def mm(prefix: list[str]) -> list[str]:
    return prefix  # micromamba 镜像统一前缀


PRE = ["micromamba", "run", "-n", "base"]

# ---------------------------------------------------------------------------
# 探针
# ---------------------------------------------------------------------------
def probe_conda_r_core() -> None:
    """提示词路径①：micromamba install（.condarc→USTC 镜像）装 R 包"""
    with _conda_lock:
        rc, out = dexec(CORE_NAME, PRE + ["micromamba", "install", "-y", "-n", "base",
                                          "r-optparse", "r-pheatmap", "r-dplyr", "r-tidyr"],
                        timeout=600)
    verdict = "PASS" if rc == 0 else "FAIL"
    record("conda装R包(optparse/pheatmap/dplyr/tidyr)@core", CORE_NAME,
           "白名单内(USTC 镜像)", rc, out, verdict)


def probe_uv_pip_core() -> None:
    """提示词路径②：uv pip install（默认走 pypi.org）"""
    rc, out = dexec(CORE_NAME, PRE + ["uv", "pip", "install", "loguru", "polars",
                                      "requests", "rich", "plotly"], timeout=600)
    record("uv pip install(loguru/polars/requests/rich/plotly)@core", CORE_NAME,
           "白名单内(pypi.org)", rc, out, "PASS" if rc == 0 else "FAIL")


def probe_pip_conf_then_pypi_core() -> None:
    """提示词路径③：裸 pip install（/etc/pip.conf→pypi.mirrors.ustc.edu.cn），随后对照 -i pypi.org。
    串行执行避免同容器 pip 并发锁争用。"""
    dexec(CORE_NAME, PRE + ["pip", "uninstall", "-y", "humanize"], timeout=60)
    rc, out = dexec(CORE_NAME, PRE + ["pip", "install", "humanize"], timeout=300)
    ustc_403 = "403 Forbidden" in out or "Tunnel connection failed: 403" in out
    if ustc_403 and rc == 0:
        verdict, note = "PASS", "主源 pypi.mirrors.ustc.edu.cn 被 403 拦截，靠 pip.conf 备用源 mirrors.aliyun.com(白名单内) 兜底成功"
    elif ustc_403:
        verdict, note = "BLOCKED-AS-EXPECTED", "pip.conf 主源 pypi.mirrors.ustc.edu.cn 不在白名单"
    elif rc == 0:
        verdict, note = "PASS", ""
    else:
        verdict, note = "FAIL", ""
    record("裸pip install(/etc/pip.conf→pypi.mirrors.ustc.edu.cn)@core", CORE_NAME,
           "主源预期可达", rc, out, verdict, note)
    # 对照：显式指定白名单内的 pypi.org
    rc2, out2 = dexec(CORE_NAME, PRE + ["pip", "install", "-i", "https://pypi.org/simple",
                                        "humanize"], timeout=300)
    record("pip -i pypi.org install@core", CORE_NAME, "白名单内", rc2, out2,
           "PASS" if rc2 == 0 else "FAIL")


def probe_r_install_packages_core() -> None:
    """提示词路径④(visualization.md)：install.packages() → CRAN"""
    code = ("options(timeout=120); "
            "tryCatch({install.packages('ggpubr', repos='https://cloud.r-project.org'); "
            "cat('INSTALL_OK\\n')}, error=function(e) cat('INSTALL_ERR:', conditionMessage(e), '\\n'))")
    rc, out = dexec(CORE_NAME, PRE + ["Rscript", "-e", code], timeout=300)
    # install.packages 失败不抛错：需按输出特征判断
    really_installed = "INSTALL_OK" in out and "not available" not in out \
        and "unable to access index" not in out
    verdict = "PASS" if really_installed else "BLOCKED-AS-EXPECTED"
    record("R install.packages(CRAN)@core", CORE_NAME,
           "cloud.r-project.org 不在白名单，预期被拦", rc, out, verdict)


def probe_github_r_scrna() -> None:
    """提示词路径⑤(visualization.md)：remotes::install_github（ProjecTILs/scCustomize 类）"""
    code = ("if (!requireNamespace('remotes', quietly=TRUE)) { cat('NO_REMOTES\\n') } else { "
            "tryCatch({remotes::install_github('carmonalab/ProjecTILs', upgrade='never'); "
            "cat('INSTALL_OK\\n')}, error=function(e) cat('INSTALL_ERR:', conditionMessage(e), '\\n')) }")
    rc, out = dexec(SCRNA_NAME, PRE + ["Rscript", "-e", code], timeout=300)
    if "NO_REMOTES" in out:
        record("remotes::install_github(ProjecTILs)@scrna", SCRNA_NAME,
               "github.com 不在白名单", rc, out, "FAIL",
               "scrna 镜像连 remotes 包都没有，GitHub 路径双重不可达")
        return
    blocked = "INSTALL_OK" not in out
    record("remotes::install_github(ProjecTILs)@scrna", SCRNA_NAME,
           "github.com 不在白名单，预期被拦", rc, out,
           "BLOCKED-AS-EXPECTED" if blocked else "PASS")


def probe_conda_bioc_scrna() -> None:
    """Bioconductor 依赖走 conda 通道（bioconda 经USTC 镜像）"""
    with _conda_lock:
        rc, out = dexec(SCRNA_NAME, PRE + ["micromamba", "install", "-y", "-n", "base",
                                           "r-optparse", "r-log4r", "r-tidyverse",
                                           "bioconductor-celldex"], timeout=900)
    record("conda装bioc(celldex)+R CLI包@scrna", SCRNA_NAME,
           "白名单内(USTC 镜像)", rc, out, "PASS" if rc == 0 else "FAIL")


def probe_kegg_network_core() -> None:
    """业务外网：kegg-pull 所需 rest.kegg.jp"""
    rc, out = dexec(CORE_NAME, PRE + ["python", "-c",
                                      "import urllib.request;print(urllib.request.urlopen('https://rest.kegg.jp/info/kegg', timeout=15).status)"],
                    timeout=60)
    blocked = rc != 0
    record("KEGG REST 业务外网@core", CORE_NAME,
           "rest.kegg.jp 不在白名单，预期被拦", rc, out,
           "BLOCKED-AS-EXPECTED" if blocked else "PASS")


def probe_pypi_reachable_core() -> None:
    """白名单本身可达性对照"""
    rc, out = dexec(CORE_NAME, PRE + ["python", "-c",
                                      "import urllib.request;print(urllib.request.urlopen('https://pypi.org/simple/', timeout=15).status)"],
                    timeout=60)
    record("pypi.org 可达性对照@core", CORE_NAME, "白名单内", rc, out,
           "PASS" if (rc == 0 and "200" in out) else "FAIL")


# ---------------------------------------------------------------------------
# 安装后复跑此前 FAIL 的技能脚本（闭环验证）
# ---------------------------------------------------------------------------
def rerun_scripts(container: str, skill: str, scripts: list[str], prefix: list[str]) -> None:
    run(["docker", "exec", "-u", "root", container, "mkdir", "-p", "/workspace/.skills"], 30)
    run(["docker", "cp", str(SKILLS_DIR / skill), f"{container}:/workspace/.skills/{skill}"], 120)
    for s in scripts:
        path = f"/workspace/.skills/{skill}/scripts/{s}"
        if s.endswith(".py"):
            rc, out = dexec(container, prefix + ["python", path, "--help"], timeout=180)
        else:
            rc, out = dexec(container, prefix + ["Rscript", path, "--help"], timeout=300)
        record(f"安装后复跑 {skill}/{s}", container, "装包后应通过", rc, out,
               "PASS" if rc == 0 else "FAIL")


def main() -> int:
    print("[install-smoke] 复刻 Studio 白名单网络，验证现场装包路径")
    if not setup_network_and_containers():
        teardown()
        return 2

    probes = [
        probe_conda_r_core,       # conda 持锁串行
        probe_conda_bioc_scrna,   # 不同容器，但 conda 各自串行
        probe_uv_pip_core,
        probe_pip_conf_then_pypi_core,
        probe_r_install_packages_core,
        probe_github_r_scrna,
        probe_kegg_network_core,
        probe_pypi_reachable_core,
    ]
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="inst") as pool:
        futures = {pool.submit(p): p.__name__ for p in probes}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                record(name, "-", "-", 125, str(e), "FAIL")
        # 闭环复跑（依赖上面装好的包）
        reruns = []
        if any(r["probe"].startswith("conda装R包") and r["verdict"] == "PASS" for r in RESULTS):
            reruns.append(pool.submit(rerun_scripts, CORE_NAME, "deg",
                                      ["run_deseq2.r", "run_pheatmap.r"], PRE))
        if any(r["probe"].startswith("uv pip") and r["verdict"] == "PASS" for r in RESULTS):
            reruns.append(pool.submit(rerun_scripts, CORE_NAME, "deg", ["gtf2tsv.py"], PRE))
        if any(r["probe"].startswith("conda装bioc") and r["verdict"] == "PASS" for r in RESULTS):
            reruns.append(pool.submit(rerun_scripts, SCRNA_NAME, "scrna-deg-analysis",
                                      ["deg_analysis.R"], PRE))
        for fut in as_completed(reruns):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                record("rerun", "-", "-", 125, str(e), "FAIL")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = REPO / "logs" / "skill_mcp_smoke" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "install_path_result.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 汇总 ==")
    for r in RESULTS:
        print(f"{r['verdict']:22s} {r['probe']:48s} {r['note']}")
    print(f"\n[install-smoke] 结果: {out_dir / 'install_path_result.json'}")
    teardown()
    hard_fail = [r for r in RESULTS if r["verdict"] == "FAIL"]
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
