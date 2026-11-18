# 腾讯云部署与验收

下面以一台可以登录、有管理员权限的 Ubuntu 22.04 或 24.04 服务器为例。请先在腾讯云实例详情确认产品类型、地域、系统和公网 IPv4。进入「登录」打开终端后，`whoami` 会显示你当前的用户名，`cat /etc/os-release` 会显示系统版本。

如果服务器上已有站点或管理面板，先检查现有的 80、443 和 18080 端口。下面的反向代理配置适用于由 Nginx 管理入口的服务器。其他入口应根据实际情况配置。

```bash
sudo ss -ltnp '( sport = :80 or sport = :443 or sport = :18080 )'
```

如果服务器在中国内地，网站正式对外提供服务前需要办理 ICP 备案。仅通过公网 IP 直接访问测试时，腾讯云文档说明可暂不备案。也可以先使用下面的 SSH 隧道私下验收。[腾讯云备案场景](https://cloud.tencent.com/document/product/243/18910) · [腾讯云公网 IP 测试说明](https://cloud.tencent.com/document/api/243/19630)

## 1. 把代码上传到服务器

### 在腾讯云控制台上传

从实例详情点「登录」，进入 OrcaTerm 网页终端。如果手上已有 `gin-task-list.tar.gz`，可以直接上传。需要重新打包时，在 Mac 的终端运行下面两行，部署包会保存在「下载」文件夹。[腾讯云 OrcaTerm 登录说明](https://cloud.tencent.com/document/product/1665/97739/)

```bash
cd /Users/gin/Documents/ChatGPT/GinCode
COPYFILE_DISABLE=1 tar -czf ~/Downloads/gin-task-list.tar.gz app.py requirements.txt templates static deploy
```

打开 OrcaTerm 的「文件管理器」，把 `gin-task-list.tar.gz` 上传到登录用户的主目录。在网页终端输入 `echo ~` 可以看到这个目录的完整路径。上传后，在网页终端解压，再继续第 2 步。[OrcaTerm 文件上传说明](https://cloud.tencent.com/document/product/1665/84580/)

```bash
mkdir -p ~/gin-task-list-upload
tar -xzf ~/gin-task-list.tar.gz -C ~/gin-task-list-upload
```

### 从 Mac 的终端上传

把第二行里的 `用户名` 和 `公网IP` 换成自己服务器的信息。SSH 是登录服务器终端的方式，`scp` 复用同一种登录方式传文件。第一次连接时，先核对 SSH 提示的服务器指纹，再确认。

```bash
cd /Users/gin/Documents/ChatGPT/GinCode
SERVER='用户名@公网IP'
ssh "$SERVER" 'mkdir -p ~/gin-task-list-upload'
scp -r app.py requirements.txt templates static deploy "$SERVER:gin-task-list-upload/"
ssh "$SERVER"
```

最后一行登录之后，终端里输入的命令就在腾讯云执行。如果在控制台能登录，Mac 这边却连接超时，先检查实例的 SSH 端口入站规则和实际端口。通过控制台登录的用户名也可以用 `whoami` 核对。[轻量应用服务器防火墙](https://cloud.tencent.com/document/product/1207/44577) · [云服务器 CVM 安全组](https://cloud.tencent.com/document/product/213/112614/)

## 2. 在服务器终端安装应用

第一组命令安装 Python 和 `curl`，然后把代码放到 `/opt/gin-task-list` 并安装依赖。若终端已用 `root` 登录，也可以直接执行管理员命令。

```bash
cd ~/gin-task-list-upload
sudo apt-get update
sudo apt-get install -y python3 python3-venv curl
sudo install -d -m 0755 /opt/gin-task-list
sudo cp -R app.py requirements.txt templates static /opt/gin-task-list/
sudo python3 -m venv /opt/gin-task-list/.venv
sudo /opt/gin-task-list/.venv/bin/python -m pip install -r /opt/gin-task-list/requirements.txt
```

再把项目交给 `systemd` 管理。它可以随服务器开机启动应用。Waitress 负责接收 HTTP 请求，应用使用服务器自己的 `127.0.0.1:18080`。`/healthz` 会检查应用能否读取任务表。[Flask 官方 Waitress 部署说明](https://flask.palletsprojects.com/en/stable/deploying/waitress/)

```bash
sudo install -m 0644 deploy/gin-task-list.service /etc/systemd/system/gin-task-list.service
sudo systemctl daemon-reload
sudo systemctl enable gin-task-list
sudo systemctl restart gin-task-list
curl --retry 4 --retry-connrefused -fsS http://127.0.0.1:18080/healthz
```

看到 `{"status":"ok"}` 就可以继续。遇到错误时，用下面两行看服务状态和应用日志。

```bash
sudo systemctl status gin-task-list --no-pager
sudo journalctl -u gin-task-list -n 50 --no-pager
```

云端数据文件是 `/var/lib/gin-task-list/tasks.sqlite3`。以后上传代码和重启应用时，都使用这份独立保存的数据库。

## 3. 从自己的电脑验收云端版本

如果可以从 Mac 使用 SSH，在 Mac 新开一个终端窗口，使用自己的登录信息。下面这条命令把 Mac 的 18080 端口通过 SSH 转发到腾讯云上的应用。如果目前只能用网页终端，第 2 步的健康检查也能先确认云端应用已启动。

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:18080 用户名@公网IP
```

命令保持运行时，打开 [云端私下预览](http://127.0.0.1:18080)。从页面添加一条任务、标记完成、刷新。虽然浏览器地址仍是 `127.0.0.1`，这次处理请求和存数据的是腾讯云上的程序。按 `Ctrl+C` 即可关闭隧道。

## 4. 配置公网入口

确认服务器可以对外提供网站后，使用域名作为正式入口。先把域名的 A 记录指向服务器公网 IPv4。允许网站使用公网 IP 做演示时，也可以把 `WEB_HOST` 设成公网 IPv4，使用 HTTP 和练习数据。

如果服务器已经由 1Panel 的 OpenResty 管理网站，在 1Panel 里选择「网站 → 创建网站 → 反向代理」，绑定本站域名，目标设为 `http://127.0.0.1:18080`。这个目标要求 OpenResty 与应用共用主机网络。再在站点的 HTTPS 设置里选择对应域名的证书。部署到已存在的网站路径时，使用下文的路径配置。[1Panel 反向代理说明](https://awesome.1panel.cn/archives/openresty-nginx-1panel-intro)

### 新装 Nginx 的服务器

在服务器终端执行下面的命令，把 `tasks.example.com` 换成实际地址。Nginx 匹配这个地址，并把浏览器的请求转给 Waitress。如果已配置过本站 HTTPS，更新应用时只需重新上传应用文件并重启应用服务。

```bash
cd ~/gin-task-list-upload
WEB_HOST='tasks.example.com'
sudo apt-get install -y nginx
sed "s/TASK_LIST_HOST/$WEB_HOST/" deploy/nginx.conf.template | sudo tee /etc/nginx/conf.d/gin-task-list.conf >/dev/null
sudo nginx -t && sudo systemctl enable --now nginx && sudo systemctl reload nginx
curl -fsS -H "Host: $WEB_HOST" http://127.0.0.1/healthz
```

在腾讯云控制台给网站放行入站 TCP 80。启用 HTTPS 时同时放行 TCP 443。轻量应用服务器在实例「防火墙」里配置，CVM 在所绑定的「安全组」里配置。如果 Ubuntu 已启用 UFW，服务器本身也要允许对应端口。应用的 18080 保持服务器本机监听。[轻量实例防火墙](https://cloud.tencent.com/document/product/1207/44577) · [CVM 安全组入站规则](https://cloud.tencent.com/document/product/213/112614/)

如果使用域名，先从 Mac 打开 `http://实际域名/healthz` 核对入口，再按照官方指南为该域名签发 HTTPS 证书并启用 HTTPS 跳转。证书生效后，在服务器执行下面的命令，让浏览器的清单 Cookie 仅通过 HTTPS 发送。[Certbot 官方 Nginx 指南](https://certbot.eff.org/instructions?ws=nginx&os=snap)

```bash
sudo install -d /etc/systemd/system/gin-task-list.service.d
printf '[Service]\nEnvironment=TASK_LIST_HTTPS=1\n' | sudo tee /etc/systemd/system/gin-task-list.service.d/https.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart gin-task-list
```

### 使用现有站点下的路径

如果需要在现有站点的 `/NiTaskList/` 打开应用，用 `sudo systemctl edit gin-task-list` 添加下面的设置，再执行 `sudo systemctl restart gin-task-list`。这会让该入口的首页、静态文件、API 和 Cookie 都使用该路径。应用仍可通过服务器内部的根路径 `/` 访问。

```ini
[Service]
Environment=TASK_LIST_URL_PREFIX=/NiTaskList
```

在现有站点的对应 `server` 配置中加入下面这两段。`proxy_pass` 的目标保留传入的路径。保存后先检查 OpenResty 或 Nginx 的配置语法，再重载。最后访问站点的 `/NiTaskList/healthz`。如果站点启用了 HTTPS，也应使用上面的安全 Cookie 设置。

```nginx
location = /NiTaskList {
    return 308 /NiTaskList/;
}

location ^~ /NiTaskList/ {
    proxy_pass http://127.0.0.1:18080;
    proxy_set_header Host $host;
}
```

如果只用公网 IP 做个人临时测试，可以在 `location ^~ /NiTaskList/` 内添加 `allow 你的公网IP;` 和 `deny all;`。这两条规则按顺序生效，允许指定的测试网络访问该路径。直接用 HTTP 测试时，请使用练习数据。

## 5. 用公网地址完成上线验收

从 Mac 或手机打开公网地址，确认显示「小任务清单」。在该应用的地址末尾加上 `healthz`，例如 `https://实际域名/healthz` 或 `https://实际域名/NiTaskList/healthz`，确认返回 `{"status":"ok"}`。回到首页，添加一条练习任务、勾选完成、刷新，确认状态保持，最后删除练习任务。使用域名时还要确认浏览器能正常建立 HTTPS 连接。
