# Navigation Agent

`NavigationAgent` 根据当前问题和对话上下文识别一个或多个学习意图，并返回可点击的
FREE-BBS 模块入口。它采用混合路由：先以可解释的关键词规则召回候选，再由 LLM 理解
省略、指代和模糊需求，生成个性化引导或澄清问题。模型不可用、输出异常或未配置 API
key 时会自动回退到规则路由，因此基础导引始终可用。

## 配置 LLM

复制示例配置并编辑项目根目录的 `.env`：

```bash
cp .env.example .env
```

至少设置：

```dotenv
AGENT_API_KEY=你的模型服务-api-key
AGENT_BASE_URL=https://cloud.infini-ai.com/maas/v1
AGENT_MODEL=glm-5.1
```

服务读取的是环境变量；如果你的启动方式不会自动加载 `.env`，请先执行
`set -a; source .env; set +a`，再启动服务。也可直接 `export AGENT_API_KEY=...`。
`OPENAI_API_KEY` 可作为 `AGENT_API_KEY` 的兼容替代。

导引 Agent 的可选配置：

```dotenv
NAVIGATION_LLM_ENABLED=true
NAVIGATION_MODEL=
NAVIGATION_LLM_CONFIDENCE_THRESHOLD=0.7
FREEBBS_WEB_BASE_URL=https://bbs.example.edu
```

`NAVIGATION_MODEL` 留空时复用 `AGENT_MODEL`；`NAVIGATION_LLM_ENABLED=false`
可关闭模型增强。规则置信度达到 `NAVIGATION_LLM_CONFIDENCE_THRESHOLD` 时会直接
返回规则结果，只有低置信度请求才调用模型。
API key 只应写入未提交的 `.env` 或部署平台的 Secret/环境变量中，不要提交到 Git。

## 接口

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"最近有什么讲座通知？"}'
```

响应中的主要字段：

- `intent`：首要意图；低置信度时为 `clarify`
- `confidence`：首要路由的启发式置信度
- `needs_clarification`：是否建议继续询问用户
- `routes`：最多三个入口，包含 `module`、`title`、`url`、`reason` 和匹配分数

目前支持知识 RAG、公告通知、课程讨论、课程与知识图谱、PBL 项目、个性化学习印记。
设置 `FREEBBS_WEB_BASE_URL` 可把返回链接指向实际前端；不设置时返回站内相对路径。

## 子 Agent 编排

请求可通过 `execute_subagent` 控制是否在导航后继续执行：

```json
{
  "agent": "navigation",
  "message": "查询数据结构课程资料",
  "execute_subagent": "auto"
}
```

`auto` 将 `knowledge_search` 委派给 RAG、将 `announcement` 委派给 Info；也可使用
`rag` 或 `info` 强制选择一个子 Agent，使用 `none` 仅执行导航。一次请求最多委派一个
子 Agent，模糊问题需要澄清时不会执行委派。

Info 委派沿用标准可信身份请求头。浏览器测试页不会要求用户输入内部 Token；若需验证
完整 Info 链路，应由 FreeBBS 后端或 `curl` 按 `docs/info-agent-integration.md` 注入请求头。

## 测试

服务启动后访问：

```text
http://127.0.0.1:5001/dev/navigation-test
```

页面会在浏览器内保存当前会话的 user/assistant 消息，并在每次请求时通过 `messages`
一并发送，因此可以连续回答 Agent 的澄清问题。“新会话”按钮可清空上下文。
页面的下拉框可选择仅导航、自动执行、显式 RAG 或显式 Info，并显示委派状态和子 Agent
返回摘要。

也可以生成一个独立测试页：

```bash
python scripts/generate_navigation_test_page.py
```

默认输出 `data/navigation_agent_test.html`，页面请求
`http://127.0.0.1:5001/api/v1/chat`。自定义示例：

```bash
python scripts/generate_navigation_test_page.py \
  --output /tmp/navigation-test.html \
  --api-base-url http://127.0.0.1:5002
```

运行实时接口冒烟测试：

```bash
python scripts/test_navigation_agent.py --base-url http://127.0.0.1:5001
```

运行无网络单元测试：

```bash
python -m unittest tests.test_navigation_agent
```

## 设计参考

实现借鉴了成熟对话产品的几项通用做法：

- Microsoft Copilot Studio 的 classic orchestration 使用 topic trigger phrases
  做可重复控制；多个 topic 同时匹配时让用户选择。
- Copilot Studio 的 generative orchestration 支持多意图、模块化 topic/tool/knowledge
  路由，并在信息缺失或含糊时追问。
- RAGRouter 研究将路由明确建模为对不同 RAG 能力的选择，并使用分数阈值权衡效果与延迟。

路由链接和模块信息始终由服务端白名单生成，LLM 只能返回合法 intent，不能生成任意
URL。响应中的 `llm_used` 表示本次是否成功使用模型；`false` 表示使用了规则回退。
`llm_status` 会进一步标明 `missing_api_key`、`disabled` 或
`provider_error_or_invalid_response`，便于排查配置和模型服务问题。规则回退也会综合本轮
会话中的历史 user 消息，不会因用户继续追问而丢失已经确定的主题。

参考：

- <https://learn.microsoft.com/en-us/microsoft-copilot-studio/nlu-overview>
- <https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/triggering-topics>
- <https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/ai-capabilities>
- <https://arxiv.org/abs/2505.23052>
