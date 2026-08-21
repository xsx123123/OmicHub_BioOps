#!/bin/bash
#
# Install bioSkills to Kimi Code CLI
#
# Usage:
#   ./install-kimi.sh              # Install globally to ~/.kimi-code/skills/
#   ./install-kimi.sh --project    # Install to current project's .agents/skills/
#   ./install-kimi.sh --project /path/to/project  # Install to specific project
#   ./install-kimi.sh --categories "single-cell,variant-calling"  # Selective install
#   ./install-kimi.sh --validate   # Validate all skills before installing
#   ./install-kimi.sh --update     # Only update changed skills
#   ./install-kimi.sh --uninstall  # Remove all bio-* skills
#
# Kimi Code CLI 扫描目录：项目级 .agents/skills/ 与 .kimi-code/skills/，
# 用户级 ~/.kimi-code/skills/ 与 ~/.agents/skills/。目录形式技能为 <name>/SKILL.md，
# frontmatter 的 name/description 必填，支持同目录携带 references/examples/scripts。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/install-common.sh"

TOOL_NAME="Kimi Code CLI"
DEFAULT_TARGET_DIR="$HOME/.kimi-code/skills"
PROJECT_SUBDIR=".agents/skills"

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Install bioSkills to Kimi Code CLI"
    echo ""
    echo "Options:"
    print_common_options
}

copy_skill_files() {
    local src_dir="$1" target_dir="$2"
    # Kimi 目录形式技能支持同目录任意配套文件（${KIMI_SKILL_DIR} 可引用），
    # 因此除 SKILL.md / usage-guide.md 外一并带上 examples/、references/、scripts/
    cp "$src_dir/SKILL.md" "$target_dir/SKILL.md" 2>/dev/null || return 1
    if [ -f "$src_dir/usage-guide.md" ]; then
        cp "$src_dir/usage-guide.md" "$target_dir/" 2>/dev/null || true
    fi
    for extra in examples references scripts assets; do
        if [ -d "$src_dir/$extra" ]; then
            cp -r "$src_dir/$extra" "$target_dir/" 2>/dev/null || true
        fi
    done
}

run_installer "$@"
