# FREE-BBS Agent CI/CD and Deployment

本仓库采用和 `../server` 相同的 GitHub Actions + SSH 部署方式：

1. 每次 push 到 `main` 自动触发部署
2. GitHub Actions 先执行 `scripts/ci-validate.sh`
3. 打包仓库代码并通过 SSH 上传到应用服务器
4. 应用服务器执行 `scripts/deploy.sh`
5. 部署脚本同步代码、创建/更新 `.venv`、安装依赖、重启 `free-bbs-agent`、检查 `/health`

## 1. 应用服务器准备

安装基础依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip rsync curl
```

创建部署用户、Agent 服务用户和后端共享的 socket 组：

```bash
sudo useradd -m -s /bin/bash deploy || true
sudo groupadd --system freebbs-agent-config || true
sudo groupadd --system freebbs-agent || true
id -u freebbs-agent >/dev/null 2>&1 || \
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin \
  --gid freebbs-agent-config --groups freebbs-agent freebbs-agent
sudo mkdir -p /data/www/freebbs-agent
sudo mkdir -p /etc/free-bbs
sudo chown -R deploy:deploy /data/www/freebbs-agent
sudo chown root:deploy /etc/free-bbs
sudo chmod 751 /etc/free-bbs
```

## 2. 环境变量文件

在服务器创建 `/etc/free-bbs/freebbs-agent.env`：

```bash
AGENT_SETTINGS_SOCKET=/run/free-bbs/agent-config.sock
AGENT_SERVICE_TOKEN=replace-with-the-same-long-random-token-used-by-free-bbs-server
AGENT_SETTINGS_TIMEOUT_SECONDS=2
AGENT_SETTINGS_CACHE_TTL_SECONDS=30
AGENT_SETTINGS_STALE_TTL_SECONDS=300
AGENT_HOST=127.0.0.1
AGENT_PORT=5001
AGENT_TIMEOUT_SECONDS=60
AGENT_SYSTEM_PROMPT=你是 FREE-BBS 的 AI 助手。
```

生产环境不要再把大模型 API key、base URL 或模型名放进这个文件；这些内容由管理员在主站
“系统设置”中维护，Agent 通过 `/run/free-bbs/agent-config.sock` 获取。这里的
`AGENT_SERVICE_TOKEN` 必须与 FREE-BBS 主服务配置完全一致，并应使用长随机值。

主服务需要先创建 Unix Domain Socket。后端与 Agent 分别使用独立系统用户，但都属于
`freebbs-agent-config` 组；socket 为 `0660`、运行目录为 `0750`。前端和部署用户不得加入
这个组。配置接口只能挂载在该 socket 上，不能挂载到公开 HTTP listener 或由 Nginx 代理。

```bash
sudo chown deploy:freebbs-agent /etc/free-bbs/freebbs-agent.env
sudo chmod 640 /etc/free-bbs/freebbs-agent.env
```

需要重建课程资料索引时，以 Agent 服务用户运行构建脚本，使它能读取自己的环境文件、连接
内部 socket 并写入课程资料根目录：

```bash
sudo -u freebbs-agent sh -c '
  set -a
  . /etc/free-bbs/freebbs-agent.env
  set +a
  cd /data/www/freebbs-agent
  .venv/bin/python scripts/build_rag_index.py
'
```

## 3. systemd 服务

复制服务文件并启用：

```bash
sudo cp /data/www/freebbs-agent/deploy/systemd/free-bbs-agent.service /etc/systemd/system/free-bbs-agent.service
sudo systemctl daemon-reload
sudo systemctl enable free-bbs-agent
sudo systemctl start free-bbs-agent
```

更新仓库中的 unit 模板后，需要再次复制它并执行 `daemon-reload`，否则新增的 socket 默认值
和服务加固选项不会生效。

服务默认使用：

- 工作目录：`/data/www/freebbs-agent`
- 环境文件：`/etc/free-bbs/freebbs-agent.env`
- 服务名：`free-bbs-agent`
- 运行用户：`freebbs-agent`
- socket 共享组：`freebbs-agent-config`

`deploy` 仅负责同步代码和重启服务，不运行 Agent，也不应加入 socket 共享组。如果服务器
路径不同，需要同步修改 `deploy/systemd/free-bbs-agent.service` 和 GitHub repository
variables。

## 4. sudoers

GitHub Actions 登录服务器后需要重启和查看这一个服务。建议写入：

```bash
sudo visudo -f /etc/sudoers.d/freebbs-agent-runner
```

内容：

```text
deploy ALL=NOPASSWD:/bin/systemctl restart free-bbs-agent,/bin/systemctl --no-pager --full status free-bbs-agent
```

如果 `systemctl` 路径不同，用下面命令确认后替换。Ubuntu 24.04 上常见路径是 `/usr/bin/systemctl`。

```bash
command -v systemctl
```

例如路径是 `/usr/bin/systemctl` 时，sudoers 应写成：

```text
deploy ALL=NOPASSWD:/usr/bin/systemctl restart free-bbs-agent,/usr/bin/systemctl --no-pager --full status free-bbs-agent
```

配置后可以用下面命令验证，不应该要求输入密码：

```bash
sudo -u deploy sudo -n "$(command -v systemctl)" status free-bbs-agent
```

## 5. GitHub Secrets 和 Variables

在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 配置 secrets：

- `DEPLOY_HOST`：应用服务器 IP 或域名
- `DEPLOY_USER`：例如 `deploy`
- `DEPLOY_SSH_KEY`：可登录服务器的 SSH 私钥全文

`DEPLOY_SSH_KEY` 必须包含完整私钥，包括首尾两行：

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

可选 repository variables：

- `DEPLOY_PORT`：默认 `22`
- `AGENT_DEPLOY_PATH`：默认 `/data/www/freebbs-agent`
- `FREEBBS_AGENT_ENV_FILE`：默认 `/etc/free-bbs/freebbs-agent.env`
- `AGENT_SERVICE_NAME`：默认 `free-bbs-agent`
- `AGENT_HEALTHCHECK_URL`：默认 `http://127.0.0.1:5001/health`

## 6. SSH Key

在应用服务器为 GitHub Actions 准备 SSH key：

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy chmod 700 /home/deploy/.ssh
sudo -u deploy ssh-keygen -t ed25519 -f /home/deploy/.ssh/github-actions -C "github-actions@freebbs-agent"
sudo -u deploy sh -c 'cat /home/deploy/.ssh/github-actions.pub >> /home/deploy/.ssh/authorized_keys'
sudo -u deploy chmod 600 /home/deploy/.ssh/authorized_keys
sudo -u deploy cat /home/deploy/.ssh/github-actions
```

把最后输出的私钥保存为 GitHub secret `DEPLOY_SSH_KEY`。

如果 GitHub Actions 报：

```text
Permission denied (publickey,password).
scp: Connection closed
```

说明还没有通过 SSH 认证，优先检查：

- `DEPLOY_USER` 是否就是服务器上写入 `authorized_keys` 的用户，例如 `deploy`
- `DEPLOY_SSH_KEY` 是否是 `/home/deploy/.ssh/github-actions` 的私钥全文，而不是 `.pub` 公钥
- `/home/deploy/.ssh/authorized_keys` 是否包含 `/home/deploy/.ssh/github-actions.pub`
- 权限是否正确：`~deploy/.ssh` 为 `700`，`authorized_keys` 为 `600`
- 服务器安全组或防火墙是否允许 GitHub runner 访问 `DEPLOY_PORT`

可以在服务器上检查：

```bash
sudo -u deploy ls -la /home/deploy/.ssh
sudo -u deploy ssh-keygen -y -f /home/deploy/.ssh/github-actions
sudo -u deploy cat /home/deploy/.ssh/authorized_keys
```

也可以比对 GitHub Actions 日志里输出的 fingerprint：

```bash
sudo -u deploy ssh-keygen -lf /home/deploy/.ssh/github-actions.pub
sudo -u deploy ssh-keygen -lf /home/deploy/.ssh/authorized_keys
```

两边 fingerprint 必须一致。如果不一致，把服务器上 `/home/deploy/.ssh/github-actions` 的私钥全文重新保存到 GitHub secret `DEPLOY_SSH_KEY`，或者把 GitHub 私钥对应的公钥追加到服务器 `authorized_keys`。

## 7. 首次上线建议

首次上线建议先手动跑一遍：

```bash
bash scripts/deploy.sh
sudo systemctl status free-bbs-agent
curl http://127.0.0.1:5001/health
```

确认服务正常后，再依赖 push 自动部署。

如果 GitHub Actions 报：

```text
Failed to restart free-bbs-agent.service: Unit free-bbs-agent.service not found.
```

说明第 3 步 systemd 服务还没有安装到 `/etc/systemd/system/`。先在服务器执行第 3 步命令，再重新跑 Actions。
