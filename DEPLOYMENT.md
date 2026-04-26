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

创建部署用户和目录：

```bash
sudo useradd -m -s /bin/bash deploy || true
sudo mkdir -p /data/www/freebbs-agent
sudo mkdir -p /etc/free-bbs
sudo chown -R deploy:deploy /data/www/freebbs-agent
sudo chown -R deploy:deploy /etc/free-bbs
```

## 2. 环境变量文件

在服务器创建 `/etc/free-bbs/freebbs-agent.env`：

```bash
AGENT_API_KEY=replace-me
AGENT_BASE_URL=https://cloud.infini-ai.com/maas/v1
AGENT_MODEL=glm-5.1
AGENT_HOST=127.0.0.1
AGENT_PORT=5001
AGENT_TIMEOUT_SECONDS=60
AGENT_SYSTEM_PROMPT=你是 FREE-BBS 的 AI 助手。
```

## 3. systemd 服务

复制服务文件并启用：

```bash
sudo cp deploy/systemd/free-bbs-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable free-bbs-agent
```

服务默认使用：

- 工作目录：`/data/www/freebbs-agent`
- 环境文件：`/etc/free-bbs/freebbs-agent.env`
- 服务名：`free-bbs-agent`
- 运行用户：`deploy`

如果服务器用户名或路径不同，需要同步修改 `deploy/systemd/free-bbs-agent.service` 和 GitHub repository variables。

## 4. sudoers

GitHub Actions 登录服务器后需要重启和查看这一个服务。建议写入：

```bash
sudo visudo -f /etc/sudoers.d/freebbs-agent-runner
```

内容：

```text
deploy ALL=NOPASSWD:/bin/systemctl restart free-bbs-agent,/bin/systemctl --no-pager --full status free-bbs-agent
```

如果 `systemctl` 路径不同，用 `which systemctl` 确认后替换。

## 5. GitHub Secrets 和 Variables

在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 配置 secrets：

- `DEPLOY_HOST`：应用服务器 IP 或域名
- `DEPLOY_USER`：例如 `deploy`
- `DEPLOY_SSH_KEY`：可登录服务器的 SSH 私钥全文

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

## 7. 首次上线建议

首次上线建议先手动跑一遍：

```bash
bash scripts/deploy.sh
sudo systemctl status free-bbs-agent
curl http://127.0.0.1:5001/health
```

确认服务正常后，再依赖 push 自动部署。
