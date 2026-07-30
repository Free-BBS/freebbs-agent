# Info Sub-Agent 联合接入说明

本文说明 `freebbs-agent` 如何调用独立仓库
[`Free-BBS/subagent-eeinfo`](https://github.com/Free-BBS/subagent-eeinfo)，以及 FreeBBS
主系统后端需要提供哪些可信身份信息。

## 1. 当前结论

`subagent-eeinfo` 已提供可用的标准接口：

```text
GET  /internal/tools/manifest
POST /internal/tools/execute
POST /internal/jobs/get
```

`freebbs-agent` 原有的 `AgentMux` 不是动态 Tool Calling 总线，因此不能只配置 URL 后自动接入。
本仓库新增 `InfoAgentBridge`，把现有 Agent 调用模型适配到标准 `info_agent` Tool Call。

```text
FreeBBS 后端
  -> POST freebbs-agent/api/v1/chat
  -> AgentMux 选择 InfoAgentBridge
  -> GET subagent-eeinfo/internal/tools/manifest（首次调用校验）
  -> POST subagent-eeinfo/internal/tools/execute
  -> 返回 answer + 标准 Tool Message + 结构化 result
```

## 2. 为什么需要两个服务 Token

两个 Token 保护不同的信任边界：

| 配置 | 方向 | 用途 |
|---|---|---|
| `FREEBBS_AGENT_INTERNAL_TOKEN` | FreeBBS 主系统后端 → `freebbs-agent` | 证明 UID、学号和权限来自可信后端 |
| `INFO_AGENT_INTERNAL_TOKEN` | `freebbs-agent` → `subagent-eeinfo` | 证明 Tool Call 来自受信任的主 Agent 服务 |
| `EEINFO_INTERNAL_TOKEN` | `subagent-eeinfo` 服务端配置 | 校验上一行的 Token；值应与 `INFO_AGENT_INTERNAL_TOKEN` 一致 |

以上 Token 均不得下发浏览器。用户名、密码、验证码和 Cookie 也不经过主 Agent。

## 3. 配置

`freebbs-agent/.env`：

```dotenv
INFO_AGENT_ENABLED=true
INFO_AGENT_BASE_URL=http://127.0.0.1:4310
INFO_AGENT_INTERNAL_TOKEN=<与 EEINFO_INTERNAL_TOKEN 相同的强随机值>
INFO_AGENT_TIMEOUT_SECONDS=30
INFO_AGENT_AUTO_AUTHENTICATE=true
FREEBBS_AGENT_INTERNAL_TOKEN=<FreeBBS 后端与主 Agent 之间的另一强随机值>
```

`subagent-eeinfo` 启动环境：

```powershell
$env:EEINFO_INTERNAL_TOKEN = '<与 INFO_AGENT_INTERNAL_TOKEN 相同的值>'
npm.cmd run demo
```

## 4. 主系统后端调用主 Agent

### 4.1 主页 JSON 兼容性

现有 `/api/v1/chat` 的请求主体无需重构。原调用继续有效：

```json
{
  "agent": "navigation",
  "message": "最近有什么通知？"
}
```

调用 Info Sub-Agent 时只需把 `agent` 改为 `info`：

```json
{
  "agent": "info",
  "message": "查询信号与系统最新公告"
}
```

响应继续保留主页已使用的 `answer`、`agent`、`model` 和 `finish_reason`，并为 Info
查询增加 `status`、`result`、`tool_message`、`execution` 与 `required_action`。因此普通聊天、
RAG 和 Navigation 调用不需要跟随修改。

身份字段故意不加入主页 JSON；它们由可信后端放在请求头中，以免普通前端伪造 UID 或学号。

FreeBBS 后端从已经验证的用户会话读取身份，并放入服务端请求头：

```http
POST /api/v1/chat
Content-Type: application/json
X-FreeBBS-Internal-Token: <FREEBBS_AGENT_INTERNAL_TOKEN>
X-FreeBBS-UID: freebbs_user_123
X-FreeBBS-Student-No: 2026000000
X-FreeBBS-Session-ID: session_456
X-FreeBBS-Permissions: web_learning:read,thu_info:read
```

```json
{
  "agent": "info",
  "message": "查询信号与系统最新公告"
}
```

这些请求头只能由 FreeBBS 后端生成。浏览器即使在 JSON 中伪造 `uid`、`student_no`
或权限，也不会被 `InfoAgentBridge` 使用。

### 支持的 Agent 名称

```text
info
info_agent
eeinfo
campus_info
```

启用 `INFO_AGENT_ENABLED=true` 后，包含“网络学堂”“课程公告”“我的课程”“我的课表”
“校内通知”或“THU Info”等明确表达的请求也会自动路由到 `InfoAgentBridge`。

## 5. Bridge 生成的标准 Tool Call

主 Agent 只把用户目标放进 `goal`：

```json
{
  "protocol_version": "1.0",
  "tool_call": {
    "id": "call_<uuid>",
    "type": "function",
    "function": {
      "name": "info_agent",
      "arguments": "{\"goal\": \"查询信号与系统最新公告\"}"
    }
  },
  "execution_options": {
    "sources": ["web_learning", "thu_info"],
    "refresh_policy": "if_stale",
    "max_results": 20,
    "max_tool_calls": 8,
    "timeout_ms": 30000,
    "auto_authenticate": true
  },
  "trusted_context": {
    "uid": "freebbs_user_123",
    "student_no": "2026000000",
    "session_id": "session_456",
    "permissions": ["web_learning:read", "thu_info:read"]
  }
}
```

`goal` 会进入 Info Agent 模型；`trusted_context` 和执行选项只由程序处理，不进入模型上下文。

## 6. 主 Agent 返回格式

查询成功时：

```json
{
  "answer": "查询到 3 条公告。",
  "agent": "info",
  "status": "success",
  "request_id": "req_xxx",
  "tool_call_id": "call_xxx",
  "tool_message": {
    "role": "tool",
    "tool_call_id": "call_xxx",
    "name": "info_agent",
    "content": "{...}"
  },
  "result": {
    "status": "success",
    "summary": "查询到 3 条公告。",
    "info": []
  },
  "execution": null,
  "required_action": null,
  "model": "subagent-eeinfo",
  "finish_reason": "stop"
}
```

- 当前 `AgentMux` 模式直接把 `answer` 返回前端。
- `tool_message` 保留标准格式，供未来真正的主 LLM Tool Calling 编排器直接追加到对话。
- `result` 供页面展示、状态判断、缓存和审计使用。

## 7. 登录与异步任务

网络学堂 Cookie 缺失且 `INFO_AGENT_AUTO_AUTHENTICATE=true` 时，返回：

```json
{
  "answer": "需要完成网络学堂认证；认证任务已由程序启动。",
  "agent": "info",
  "status": "pending",
  "execution": {
    "job_id": "job_xxx",
    "state": "authenticating"
  },
  "required_action": {
    "type": "interactive_authentication"
  }
}
```

前端不能直接调用 `subagent-eeinfo`。FreeBBS 后端应携带同一组可信身份请求主 Agent
的任务代理接口：

```http
POST /api/v1/info/jobs/get
X-FreeBBS-Internal-Token: <FREEBBS_AGENT_INTERNAL_TOKEN>
X-FreeBBS-UID: freebbs_user_123
X-FreeBBS-Student-No: 2026000000
X-FreeBBS-Session-ID: session_456
X-FreeBBS-Permissions: web_learning:read
Content-Type: application/json
```

```json
{
  "job_id": "job_xxx"
}
```

HTTP `202` 表示仍在认证/执行，HTTP `200` 表示已经取得最终结果。Cookie 始终由
`subagent-eeinfo` 按 UID 管理。

## 8. 与 Navigation Agent 的关系

当前 `NavigationAgent` 的目标是返回模块链接；`InfoAgentBridge` 的目标是实际执行课程和
通知查询。注册顺序为：

```text
CommentMentionAgent
RagAgent
InfoAgentBridge
NavigationAgent
GeneralChatAgent
```

因此明确的信息查询由 Bridge 执行；“我不知道去哪里看通知”之类的导航需求仍可显式调用
`agent=navigation` 返回模块入口。不要让 Navigation Agent 接触 Cookie 或用户凭据。

## 9. 联调步骤

1. 分别启动 `subagent-eeinfo`（4310）和 `freebbs-agent`（5001）。
2. 确认两端的 Info Token 相同。
3. 先显式发送 `agent=info` 的 THU Info 查询，验证无需网络学堂登录的路径。
4. 发送“查询我的课程”，验证官方认证窗口、`pending` 和任务轮询。
5. 使用两个 UID 分别认证，验证 Cookie 不串号。
6. 用错误的内部 Token 和浏览器自报 UID 请求，确认被拒绝。

本地开发已验证完整链路：`/api/v1/chat` → Manifest → Execute → `thu_info_search` →
标准 Tool Message。未配置 Info Agent 模型 API 时，下游会使用确定性回退 planner，接口格式不变。

## 10. 尚需主系统团队确认

- FreeBBS Web 后端从哪个服务端会话字段取得稳定 `uid` 和学号。
- 权限字段由现有用户系统生成，还是在后端按默认只读权限映射。
- 生产环境两个服务的地址、HTTPS/反向代理和 Secret 管理方式。
- 前端收到 `pending` 后的认证提示和轮询交互形式。

上述确认不影响 Bridge 的接口结构；只需要在部署层提供对应请求头和环境变量。
