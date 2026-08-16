#!/bin/bash
# ============================================================
# 一键下载 JBrowse 2 Web 产物到 pipelines/jbrowse2/
# 用法: chmod +x scripts/download_jbrowse2.sh && ./scripts/download_jbrowse2.sh
#
# 下载后由 nginx 以只读挂载到 /usr/share/nginx/html/jbrowse2，
# 经 /jbrowse2/ 路径提供静态资源；浏览器配置与轨道数据由后端 API + /tracks/ 提供。
# ============================================================

set -e

VERSION="2.15.1"
# 解析为脚本所在仓库根目录下的 pipelines/jbrowse2，无论从哪里调用都正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${REPO_ROOT}/pipelines/jbrowse2"
URL="https://github.com/GMOD/jbrowse-components/releases/download/v${VERSION}/jbrowse-web-v${VERSION}.zip"

echo "📦 下载 JBrowse 2 v${VERSION}..."
echo "🎯 目标目录: ${TARGET_DIR}"

mkdir -p "${TARGET_DIR}"
cd "${TARGET_DIR}"

# 已有文件先清理（覆盖更新）
if [ -f "index.html" ]; then
    echo "⚠️  检测到已有 JBrowse 2 文件，将覆盖更新"
    rm -rf static index.html favicon.ico manifest.json test_data 2>/dev/null || true
fi

# 下载
if command -v wget &> /dev/null; then
    wget -q --show-progress "${URL}" -O jbrowse.zip
elif command -v curl &> /dev/null; then
    curl -L --progress-bar -o jbrowse.zip "${URL}"
else
    echo "❌ 错误: 需要 wget 或 curl"
    exit 1
fi

# 解压
echo "📂 解压中..."
if ! command -v unzip &> /dev/null; then
    echo "❌ 错误: 需要 unzip（sudo apt-get install unzip）"
    exit 1
fi
unzip -q -o jbrowse.zip
rm -f jbrowse.zip

# 校验关键文件
if [ ! -f "index.html" ]; then
    echo "❌ 错误: index.html 不存在，部署可能失败"
    exit 1
fi

echo "✅ JBrowse 2 v${VERSION} 已部署到 ${TARGET_DIR}/"
echo ""
echo "📁 文件结构（前 20 项）:"
find . -maxdepth 2 -type f | head -20
echo ""
echo "🚀 下一步:"
echo "   1. docker-compose.yml 中 nginx 服务已挂载 ../../pipelines/jbrowse2（本脚本产物）"
echo "   2. 重启 nginx: docker compose -f deploy/docker/docker-compose.yml restart nginx"
echo "   3. 访问 /jbrowse2/ 确认静态资源可加载"
echo "   4. 编辑 data/jbrowse_config.yaml 配置参考基因组路径，调用 POST /api/v1/jbrowse/config/reload 生效"
