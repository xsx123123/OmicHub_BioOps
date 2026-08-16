#!/bin/bash
# scripts/download_jbrowse2.sh
# ============================================================
# 一键下载 JBrowse 2 Web 产物到 pipelines/jbrowse2/
# 用法: chmod +x scripts/download_jbrowse2.sh && ./scripts/download_jbrowse2.sh
# ============================================================

set -e

VERSION="2.15.1"
TARGET_DIR="pipelines/jbrowse2"
URL="https://github.com/GMOD/jbrowse-components/releases/download/v${VERSION}/jbrowse-web-v${VERSION}.zip"

echo "📦 下载 JBrowse 2 v${VERSION}..."
echo "🎯 目标目录: ${TARGET_DIR}"

# 确保目录存在
mkdir -p ${TARGET_DIR}
cd ${TARGET_DIR}

# 如果已有文件，先备份
if [ -f "index.html" ]; then
    echo "⚠️ 检测到已有 JBrowse 2 文件，将覆盖更新"
    rm -rf static index.html favicon.ico manifest.json 2>/dev/null || true
fi

# 下载
if command -v wget &> /dev/null; then
    wget -q --show-progress ${URL} -O jbrowse.zip
elif command -v curl &> /dev/null; then
    curl -L -o jbrowse.zip ${URL}
else
    echo "❌ 错误: 需要 wget 或 curl"
    exit 1
fi

# 解压
echo "📂 解压中..."
unzip -q -o jbrowse.zip
rm -f jbrowse.zip

echo "✅ JBrowse 2 v${VERSION} 已部署到 ${TARGET_DIR}/"
echo ""
echo "📁 文件结构:"
find . -maxdepth 2 -type f | head -20

# 验证关键文件
if [ ! -f "index.html" ]; then
    echo "❌ 错误: index.html 不存在，部署可能失败"
    exit 1
fi

echo ""
echo "🚀 下一步:"
echo "   1. 确保 nginx.conf 中配置了 /jbrowse2/ 路径"
echo "   2. 确保 docker-compose.yml 中 nginx 服务挂载了 ${TARGET_DIR}"
echo "   3. 重启 nginx: docker compose restart nginx"
