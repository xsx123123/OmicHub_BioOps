

# 可用技能（元数据索引 · 渐进式加载）

下面是你已挂载技能的名称与用途说明，**不含详细步骤**。
当判断当前任务命中某个技能的适用场景时，先调用 `use_skill` 工具（参数 `skill_id`）加载该技能的完整指令，再严格按指令执行；不要凭名称猜测技能内容。
技能正文中引用的 references/assets 文件，用 `skill_resource` 工具按需读取。
技能脚本的依赖声明在 `references/environment.md`，运行前先在当前执行环境核对并安装缺失依赖。所有沙盒均仅限 conda 通道安装：`micromamba install -y -n base -c <channel> <pkg>`；CRAN 与 GitHub 不在沙盒 egress 白名单内，`install.packages()` 和 `remotes::install_github()` 只会失败或装上来历不明的包，所以不走这两条通道，GitHub 独占包如实说明不可现场安装。

{{skills}}
