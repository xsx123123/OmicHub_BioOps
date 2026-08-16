#!/bin/bash
# ATACFlow Skills Installer for Claude Code
# Installs ATACFlow skills to .claude/skills directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATACFLOW_SKILLS_DIR="$SCRIPT_DIR"

# Claude Code skills directory
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
TARGET_DIR="$CLAUDE_SKILLS_DIR/ATACFlow"

echo "=========================================="
echo "ATACFlow Skills Installer for Claude Code"
echo "=========================================="
echo "Source: $ATACFLOW_SKILLS_DIR"
echo "Target: $TARGET_DIR"
echo ""

# Check if .claude directory exists
if [ ! -d "$HOME/.claude" ]; then
    echo "Creating Claude config directory: $HOME/.claude"
    mkdir -p "$HOME/.claude"
fi

# Create skills directory if it doesn't exist
if [ ! -d "$CLAUDE_SKILLS_DIR" ]; then
    echo "Creating Claude skills directory: $CLAUDE_SKILLS_DIR"
    mkdir -p "$CLAUDE_SKILLS_DIR"
fi

# Ask for confirmation
read -p "Do you want to proceed with installation to Claude Code? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

# Create target directory
echo ""
echo "Creating target directory..."
mkdir -p "$TARGET_DIR"

# Copy files
echo "Copying skills files..."

# Essential skill files
cp "$ATACFLOW_SKILLS_DIR/SKILL.md" "$TARGET_DIR/"
cp "$ATACFLOW_SKILLS_DIR/path_config.yaml" "$TARGET_DIR/"
cp "$ATACFLOW_SKILLS_DIR/start_atacflow.sh" "$TARGET_DIR/"

# Documentation
cp "$ATACFLOW_SKILLS_DIR/README.md" "$TARGET_DIR/"
cp "$ATACFLOW_SKILLS_DIR/usage-guide.md" "$TARGET_DIR/"
cp "$ATACFLOW_SKILLS_DIR/INSTALL.md" "$TARGET_DIR/"

# Examples
mkdir -p "$TARGET_DIR/examples"
cp "$ATACFLOW_SKILLS_DIR/examples/"*.yaml "$TARGET_DIR/examples/" 2>/dev/null || true
cp "$ATACFLOW_SKILLS_DIR/examples/"*.csv "$TARGET_DIR/examples/" 2>/dev/null || true
cp "$ATACFLOW_SKILLS_DIR/examples/"*.sh "$TARGET_DIR/examples/" 2>/dev/null || true

# Make scripts executable
chmod +x "$TARGET_DIR/start_atacflow.sh"
chmod +x "$TARGET_DIR/examples/run_atacflow.sh" 2>/dev/null || true

# Update paths in path_config.yaml
echo "Updating paths in path_config.yaml..."
ATACFLOW_PROJECT_ROOT=$(cd "$ATACFLOW_SKILLS_DIR/.." && pwd)
# Use a different delimiter for sed since paths contain slashes
sed -i "s|/home/zj/pipeline/ATACFlow|$ATACFLOW_PROJECT_ROOT|g" "$TARGET_DIR/path_config.yaml"

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "ATACFlow skills have been installed to:"
echo "  $TARGET_DIR"
echo ""
echo "Next steps:"
echo "1. Restart Claude Code to load the new skill"
echo "2. Edit $TARGET_DIR/path_config.yaml if needed"
echo "3. Try: 'Run ATACFlow analysis on my data'"
