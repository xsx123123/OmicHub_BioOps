# MAS Apptainer Worker

RNAFlow 的嵌套执行使用原生宿主机上的专用 Celery Worker，而不是 Docker-in-Docker。该服务只消费 `mas_apptainer` 队列；常规 Docker Worker 继续消费 `analysis` 队列。

## 安装前提

1. 计算节点安装 Apptainer，并将经审核的 RNAFlow SIF 放在本地受控目录。
2. `/data/omichub` 与 Web/API 节点使用同一共享存储，且服务用户仅拥有该目录的读写权限。
3. 检出 OmicHub 代码到 `/opt/omichub/app`，建立 Python 虚拟环境，并复制 `deploy/mas/mas-apptainer-worker.env.example` 到 `/etc/omichub/mas-apptainer-worker.env` 后填写数据库和 Redis 凭据。
4. 安装 `deploy/mas/omichub-mas-apptainer-worker.service` 后执行 `systemctl daemon-reload`、`systemctl enable --now omichub-mas-apptainer-worker`。

执行命令固定使用 `--containall`、`--cleanenv`、`--no-home`，仅绑定当前 Run 工作区为 `/workspace:rw` 和 RNAFlow 管线为只读路径。服务不应安装 Docker CLI，也不得获得 `/var/run/docker.sock`、host PID 或特权容器权限。
