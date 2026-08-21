

# 可用技能

技能脚本的依赖声明在各技能 `references/environment.md`，运行前先核对执行环境并现场安装缺失依赖。所有沙盒均仅限 conda 通道安装：`micromamba install -y -n base -c <channel> <pkg>`；CRAN 与 GitHub 不在沙盒 egress 白名单内，`install.packages()` 和 `remotes::install_github()` 只会失败或装上来历不明的包，所以不走这两条通道，GitHub 独占包如实说明不可现场安装。

{{skills}}
