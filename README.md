# freebbs-agent

FREE-BBS 的本地 Agent 服务，基于 Python Flask。

当前接口：

- `GET /health`：服务健康检查
- `POST /api/v1/chat`：普通 AI 问答

服务默认只监听 `127.0.0.1:5001`，并且会拒绝非 loopback 来源的请求。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

设置 `.env` 或当前 shell 环境变量：

```bash
export AGENT_API_KEY="your-api-key"
export AGENT_BASE_URL="https://cloud.infini-ai.com/maas/v1"
export AGENT_MODEL="glm-5.1"
```

启动：

```bash
python app.py
```

健康检查：

```bash
curl http://127.0.0.1:5001/health
```

问答：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Explain to me how AI works"}'
```

流式问答：

```bash
curl -N -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Explain to me how AI works","stream":true}'
```

流式响应使用 SSE，每条消息格式如下：

```text
data: {"delta":"你"}

data: {"done":true}
```

也可以传 OpenAI 风格的 `messages`：

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain to me how AI works"}
  ]
}
```

可选路由参数：

- `agent`：指定 agent。当前支持 `general_chat` / `general` / `chat`，以及 `comment_mention` / `comment` / `comment_at_max`
- `source` 或 `channel`：请求来源。当前 `source: "comment"` 且消息包含 `@max` 时，会自动路由到评论区 agent

后端内部会通过 mux 选择 agent。每个 agent 继承统一的 `FreeBBSAgent` 基类，核心入口是 `run(invocation)` 和 `stream(invocation)`；agent 内部可以多次调用 `call_llm(...)` 或执行其它操作。

## 环境变量

- `AGENT_API_KEY`：模型服务 API key，也兼容 `OPENAI_API_KEY`
- `AGENT_BASE_URL`：OpenAI-compatible API 地址，默认 `https://cloud.infini-ai.com/maas/v1`
- `AGENT_MODEL`：模型名，默认 `glm-5.1`
- `AGENT_HOST`：监听地址，默认 `127.0.0.1`
- `AGENT_PORT`：监听端口，默认 `5001`
- `AGENT_TIMEOUT_SECONDS`：请求模型超时时间，默认 `60`
- `AGENT_SYSTEM_PROMPT`：默认系统提示词。请求传 `system` 或 `messages` 时，以请求内容为准

## CI/CD

目录结构参考 `../server`，push 到 `main` 会自动部署：

- `.github/workflows/deploy.yml`：GitHub Actions 自动部署
- `scripts/ci-validate.sh`：安装依赖、语法检查、单元测试、必要文件检查
- `scripts/deploy.sh`：同步代码、创建 venv、安装依赖、重启 systemd 服务、健康检查
- `deploy/systemd/free-bbs-agent.service`：systemd 服务模板

部署准备细节见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## Agent 开发

新增 agent 的方式见 [docs/adding-agent.md](docs/adding-agent.md)。
