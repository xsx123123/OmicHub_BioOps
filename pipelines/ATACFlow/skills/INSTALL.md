# ATACFlow Skills 安装指南

## 快速安装

### 为 Claude Code 安装

```bash
cd /home/zj/pipeline/ATACFlow/skills
./install_claude_skills.sh
```

### 为 OpenCode 安装 (通用脚本)

```bash
cd /home/zj/pipeline/ATACFlow/skills
./install_skills.sh
```

### 为 Codex 安装

```bash
cd /home/zj/pipeline/ATACFlow/skills
./install_codex_skills.sh
```

## 手动安装

如果需要手动安装，按以下步骤操作：

### 1. 创建目标目录

```bash
mkdir -p ~/.claude/skills/ATACFlow
```

### 2. 复制文件

```bash
cd /home/zj/pipeline/ATACFlow/skills

# 复制核心文件
cp SKILL.md ~/.claude/skills/ATACFlow/
cp path_config.yaml ~/.claude/skills/ATACFlow/
cp start_atacflow.sh ~/.claude/skills/ATACFlow/

# 复制文档
cp README.md ~/.claude/skills/ATACFlow/
cp usage-guide.md ~/.claude/skills/ATACFlow/

# 复制示例配置
mkdir -p ~/.claude/skills/ATACFlow/examples
cp examples/*.yaml ~/.claude/skills/ATACFlow/examples/
cp examples/*.csv ~/.claude/skills/ATACFlow/examples/
cp examples/*.sh ~/.claude/skills/ATACFlow/examples/
```

### 3. 设置执行权限

```bash
chmod +x ~/.claude/skills/ATACFlow/start_atacflow.sh
chmod +x ~/.claude/skills/ATACFlow/examples/run_atacflow.sh
```

## 安装后配置

### 1. 验证路径配置

编辑 `~/.claude/skills/ATACFlow/path_config.yaml`，确保：

```yaml
ATACFLOW_ROOT: "/home/zj/pipeline/ATACFlow"
```

### 2. 重启 AI Agent

重启 opencode 或 Claude Code 以加载新安装的 skill。

## 使用

安装后，你可以这样使用：

```
"帮我运行ATACFlow分析"
"设置ATACFlow项目"
"使用ATACFlow进行差异peak分析"
```

## 卸载

如需卸载：

```bash
rm -rf ~/.claude/skills/ATACFlow
```
