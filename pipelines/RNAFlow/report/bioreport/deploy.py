import os
import subprocess
import secrets
import string
import sys
import time

# --- 1. 配置区域 (请修改这里) ---
SERVER_CONFIG = {
    "ip": "123.45.67.89",           # 你的云服务器公网 IP
    "user": "root",                 # SSH 登录用户名
    "base_path": "/home/data/nginx_server",  # 服务器上的挂载目录 (同第一步)
    "container_name": "my_nginx"    # Docker 容器名字
}

# --- 2. 工具函数 ---

def run_command(cmd, shell=True):
    """运行本地命令"""
    try:
        subprocess.check_call(cmd, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"❌ 命令执行失败: {cmd}")
        sys.exit(1)

def ssh_command(cmd):
    """通过 SSH 在服务器上执行命令"""
    ssh_cmd = f"ssh {SERVER_CONFIG['user']}@{SERVER_CONFIG['ip']} '{cmd}'"
    run_command(ssh_cmd)

def generate_password(length=8):
    """生成随机密码"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))

def main():
    if len(sys.argv) < 2:
        print("❌ 用法: python deploy.py <项目ID>")
        print("示例: python deploy.py RNA_2025")
        sys.exit(1)

    project_id = sys.argv[1]
    password = generate_password()
    
    print(f"\n🚀 开始部署项目: [{project_id}]")
    print("-" * 40)

    # 1. 本地渲染 Quarto
    print("1️⃣  正在渲染 Quarto 报告...")
    # 这里用了 --output-dir 强制指定输出到临时文件夹，避免污染 _site
    run_command(f"quarto render --output-dir _deploy_temp")

    # 2. 准备服务器目录
    print("2️⃣  准备服务器环境...")
    # 在服务器 html 目录下创建项目文件夹
    ssh_command(f"mkdir -p {SERVER_CONFIG['base_path']}/html/{project_id}")

    # 3. 上传文件 (SCP)
    print("3️⃣  上传文件到云服务器...")
    # 将本地 _deploy_temp 里的所有内容上传到服务器对应目录
    run_command(f"scp -r _deploy_temp/* {SERVER_CONFIG['user']}@{SERVER_CONFIG['ip']}:{SERVER_CONFIG['base_path']}/html/{project_id}/")

    # 4. 设置密码 (在 Docker 容器内执行 htpasswd)
    print(f"4️⃣  设置访问密码: {password}")
    # 生成密码文件路径
    htpasswd_file = f"/etc/nginx/passwords/{project_id}.htpasswd"
    # 调用 Docker 里的 htpasswd 生成密码文件
    ssh_command(f"docker exec {SERVER_CONFIG['container_name']} htpasswd -bc {htpasswd_file} admin {password}")

    # 5. 生成 Nginx 配置文件 (动态生成 location 块)
    print("5️⃣  配置 Nginx 权限...")
    nginx_conf = f"""
server {{
    listen 80;
    server_name _;

    location /{project_id}/ {{
        alias /usr/share/nginx/html/{project_id}/;
        index index.html report.html;
        auth_basic "Restricted: {project_id}";
        auth_basic_user_file {htpasswd_file};
    }}
}}
"""
    # 将配置写入本地临时文件，然后传上去
    with open("temp_nginx.conf", "w") as f:
        f.write(nginx_conf)
    
    # 上传配置文件到 conf.d 目录 (文件名必须以 .conf 结尾)
    run_command(f"scp temp_nginx.conf {SERVER_CONFIG['user']}@{SERVER_CONFIG['ip']}:{SERVER_CONFIG['base_path']}/conf.d/{project_id}.conf")
    
    # 6. 重载 Nginx
    print("6️⃣  重载 Nginx 服务...")
    ssh_command(f"docker exec {SERVER_CONFIG['container_name']} nginx -s reload")

    # 7. 清理本地临时文件
    run_command("rm -rf _deploy_temp temp_nginx.conf")

    print("-" * 40)
    print("✅ 部署成功！")
    print(f"🔗 访问链接: http://{SERVER_CONFIG['ip']}/{project_id}/")
    print(f"👤 账号: admin")
    print(f"🔑 密码: {password}")
    print("-" * 40)

if __name__ == "__main__":
    main()