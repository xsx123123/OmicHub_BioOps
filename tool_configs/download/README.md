# 统一下载器配置

`download_config.yaml` 是 SRA、云存储和 HTTP/HTTPS/FTP 直链下载共用的运行配置。
配置由 `DownloadConfigManager` 按文件 mtime 热重载；解析失败时保留上一份有效配置。

## 配置范围

- `features`: 三类下载功能开关。环境变量中的 `enable_*_download` 仍可作为临时启用回退。
- `binaries`: EBIDownload、aria2c、ossutil、tosutil、obsutil 的绝对路径。
- `aria2`: 直链下载的并发、重试、超时和完整性检查参数。
- `validation`: 单任务最大链接数和允许的 URL 协议。

生产环境需要安装 `aria2c`，并将 `features.direct_link` 设置为 `true`；修改 YAML 后无需重启 Web/Worker。
