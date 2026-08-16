# **🧬 生信分析平台架构演进路线：从独立交付到平台集成**

* **文档版本**: v1.1  
* **状态**: V1 (已就绪), V2 (规划中)  
* **目标**: 建立标准化的 RNA-seq 静态报告交付流程，并规划未来的 SaaS 平台集成方案。

## **📅 第一阶段：V1 独立交付模式 (Current MVP)**

**核心理念**：快速、轻量、无需开发后端。利用 Nginx 自带的 auth\_basic 模块实现最基础的密码保护。适用于目前的“手动/脚本化”交付流程。

### **1.1 V1 架构原理**

* **部署方式**：Docker 容器化部署 Nginx。  
* **鉴权方式**：HTTP Basic Auth (浏览器原生弹窗)。  
* **数据管理**：宿主机目录挂载。

```bash
宿主机目录结构: /home/docker\_deploy/  
├── html/                  \<-- \[动态\] 存放项目报告 (如 /html/RNA\_2025/)  
├── conf.d/  
│   └── default.conf       \<-- \[静态\] Nginx 配置  
└── passwords/  
    └── nginx.htpasswd     \<-- \[动态\] 密码本
```
### **1.2 V1 Nginx 配置 (default.conf)**

```bash
server {  
    listen 80;  
    server\_name \_;

    \# 通用配置  
    # 开启 Gzip
    gzip on;
    
    # 启用 Gzip 的最小文件大小 (太小的压缩反而慢)
    gzip_min_length 1k;
    
    # 压缩级别 1-9，建议 5 或 6 (平衡 CPU 和压缩率)
    gzip_comp_level 6;
    
    # 指定需要压缩的文件类型 (HTML, CSS, JS, JSON, XML)
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    
    # 让代理服务器也缓存压缩后的版本
    gzip_vary on;

    \# 项目路径匹配  
    location / {  
        root /usr/share/nginx/html;  
        index index.html;

        \# 开启密码验证  
        auth\_basic "Restricted Access: Bioinfo Report";  
        auth\_basic\_user\_file /etc/nginx/passwords/nginx.htpasswd;  
    }  
}
```
### **1.3 V1 部署命令 (Docker)**

```bash
docker run \-d \\  
  \--name rna\_report\_v1 \\  
  \-p 20000:80 \\  
  \-v /home/docker\_deploy/conf.d/default.conf:/etc/nginx/conf.d/default.conf \\  
  \-v /home/docker\_deploy/passwords/nginx.htpasswd:/etc/nginx/passwords/nginx.htpasswd \\  
  \-v /home/docker\_deploy/html:/usr/share/nginx/html \\  
  \--restart always \\  
  nginx:alpine
```
### **1.4 V1 交付流程**

1. **渲染**: 本地 quarto render。  
2. **上传**: scp 到服务器 /home/docker\_deploy/html/项目ID。  
3. **设密**: htpasswd 更新 /home/docker\_deploy/passwords/nginx.htpasswd。  
4. **交付**: 发送链接 http://IP:20000/项目ID 和密码给客户。

## **🚀 第二阶段：V2 平台集成模式 (Future SaaS)**

**核心理念**：无感鉴权、统一入口。将静态报告作为子模块嵌入自建 Web 平台（Django/FastAPI），利用平台的账户体系控制访问权限。

### **2.1 V2 架构原理**

在这个阶段，弃用 htpasswd。利用 Nginx 的 auth\_request 模块，将鉴权动作“外包”给 Web 后端。

**访问流程**：

1. **用户**：访问 https://platform.com/reports/RNA\_2025/。  
2. **Nginx**：拦截请求 \-\> 发起内部请求至后端 /api/check\_permission。  
3. **后端 API**：检查用户 Cookie/Session 是否有权查看该项目。  
   * ✅ 有权 \-\> 返回 200 OK。  
   * ❌ 无权 \-\> 返回 403 Forbidden。  
4. **Nginx**：根据后端返回的状态码，决定是放行文件还是跳转登录页。

### **2.2 V2 服务端规划**

Web 平台与静态报告共享存储（或通过 NFS 挂载）。
```bash
/home/bioinfo\_platform/  
├── backend\_app/           \<-- Python/Node.js 后端代码  
├── static\_reports/        \<-- \[核心\] 存放所有 Quarto 报告  
│   ├── project\_001/  
│   └── project\_002/  
└── nginx\_conf/  
    └── platform.conf
```
### **2.3 V2 Nginx 配置 (The Gatekeeper)**

这是实现“无缝嵌入”的关键配置。
```bash
server {  
    listen 80;  
    server\_name platform.your-domain.com;

    \# 1\. 主网站 (Web 平台)  
    location / {  
        proxy\_pass \[http://127.0.0.1:8000\](http://127.0.0.1:8000); \# 转发给后端  
        proxy\_set\_header Host $host;  
    }

    \# 2\. 受保护的报告目录 (静态文件)  
    \# 路径示例: /protected\_reports/project\_001/index.html  
    location /protected\_reports/ {  
        \# A. 核心指令：每次访问这里，先问问 /auth 答不答应  
        auth\_request /auth;

        \# B. 只有通过验证，才从这里读取文件  
        alias /home/bioinfo\_platform/static\_reports/;  
        index index.html;  
    }

    \# 3\. 内部验证接口 (只给 Nginx 内部使用)  
    location \= /auth {  
        internal;   
          
        \# 转发给后端 API 进行权限判断  
        proxy\_pass \[http://127.0.0.1:8000/api/check\_report\_permission\](http://127.0.0.1:8000/api/check\_report\_permission);  
          
        \# 传递原始 URI 和 用户 Cookie  
        proxy\_set\_header X-Original-URI $request\_uri;  
        proxy\_pass\_request\_body off;  
        proxy\_set\_header Content-Length "";  
    }  
}
```
### **2.4 V2 后端 API 逻辑示例 (Python/FastAPI)**
```bash
@app.get("/api/check\_report\_permission")  
async def check\_permission(request: Request):  
    \# 1\. 获取用户想看的路径  
    target\_uri \= request.headers.get("X-Original-URI", "")  
    project\_id \= parse\_project\_id(target\_uri)

    \# 2\. 获取当前登录用户 (从 Cookie)  
    user \= get\_current\_user(request)

    \# 3\. 鉴权逻辑  
    if not user:  
        raise HTTPException(status\_code=401) \# 未登录  
    if not user.has\_permission(project\_id):  
        raise HTTPException(status\_code=403) \# 无权限

    \# 4\. 放行  
    return {"status": "ok"}
```
### **2.5 V2 前端嵌入 (Iframe)**
```bash
用户登录平台后，在项目详情页通过 Iframe 查看报告，体验无缝衔接。

\<div class="report-wrapper"\>  
    \<\!-- src 指向受保护的 Nginx 路径，浏览器会自动带上 Cookie \--\>  
    \<iframe   
        src="/protected\_reports/project\_001/index.html"   
        width="100%" height="800px" frameborder="0"\>  
    \</iframe\>  
\</div\>
```
## **🔄 从 V1 到 V2 的迁移策略**

1. **数据迁移**：  
   * 将 /home/docker\_deploy/html/ 下的项目文件夹，移动到 V2 的 /home/bioinfo\_platform/static\_reports/。  
2. **自动化脚本升级**：  
   * **V1 脚本**: render \-\> scp \-\> htpasswd (生成密码)。  
   * **V2 脚本**: render \-\> scp \-\> Call API (注册项目权限到数据库)。  
3. **用户通知**：  
   * V1: 发送 "链接 \+ 密码"。  
   * V2: 发送 "平台登录链接"，提示用户在“我的项目”中查看。

## **✅ 总结对比**

| 特性 | V1 阶段 (MVP) | V2 阶段 (SaaS) |
| :---- | :---- | :---- |
| **部署难度** | ⭐ (简单 Docker) | ⭐⭐⭐ (需开发后端) |
| **鉴权方式** | 账号/密码 (Basic Auth) | 平台账户 (Cookie/Session) |
| **用户体验** | 差 (原生弹窗，密码难记) | 优 (无感嵌入，统一管理) |
| **适用场景** | 早期交付、临时分享 | 规模化运营、长期维护 |

