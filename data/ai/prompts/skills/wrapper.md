

# 可用技能

技能脚本的依赖声明在各技能 `references/environment.md`，运行前先核对执行环境并现场安装缺失依赖（所有沙盒均仅限 conda 通道安装：`micromamba install -y -n base -c <channel> <pkg>`；CRAN/GitHub 不可达，禁止 `install.packages()` 和 `remotes::install_github()`）。

{{skills}}
