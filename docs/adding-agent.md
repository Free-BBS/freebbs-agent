# Adding a New Agent

本文说明如何在 `freebbs-agent` 中添加新的 agent。

当前设计里，Flask 只负责 HTTP 层。真正的业务逻辑在 `freebbs_agent/agents.py`：

- `freebbs_agent/agent_utils.py`：通用基类、mux、数据结构和公共类型 import
- `freebbs_agent/agents.py`：具体业务 agent 和默认 mux 注册列表

`agent_utils.py` 中包含：

- `FreeBBSAgent`：所有 agent 的统一基类
- `AgentMux`：根据请求参数和内容选择 agent
- `AgentInvocation`：一次请求的统一入参
- `ChatOptions`：模型、温度、max tokens、是否流式等选项

## 1. Agent 的基本结构

新 agent 继承 `FreeBBSAgent`：

```python
from .agent_utils import AgentInvocation, FreeBBSAgent


class MyAgent(FreeBBSAgent):
    name = "my_agent"

    def can_handle(self, invocation: AgentInvocation) -> bool:
        return invocation.payload.get("agent") == self.name

    def run(self, invocation: AgentInvocation) -> dict:
        return self.call_llm(invocation.messages, invocation.options)

    def stream(self, invocation: AgentInvocation):
        yield from self.stream_llm(invocation.messages, invocation.options)
```

核心约定：

- `name` 是 agent 的稳定 ID，前端可以通过 `agent` 参数指定
- `can_handle(...)` 决定 mux 是否选择这个 agent
- `run(...)` 是非流式入口，类似 `main(params...)`
- `stream(...)` 是流式入口
- `call_llm(prompt, options)` 用于普通 LLM 调用
- `stream_llm(prompt, options)` 用于流式 LLM 调用

`prompt` 可以是字符串，也可以是 OpenAI 风格 messages：

```python
self.call_llm("解释傅里叶变换", invocation.options)
```

```python
self.call_llm(
    [
        {"role": "system", "content": "你是一个课程助教。"},
        {"role": "user", "content": invocation.message},
    ],
    invocation.options,
)
```

## 2. 读取请求参数

一次请求会被封装成 `AgentInvocation`。

常用字段：

```python
invocation.payload      # 原始 JSON body
invocation.messages     # 已注入默认 system prompt 的 messages
invocation.options      # ChatOptions
invocation.message      # 最后一条 user message，适合做路由判断
```

示例：

```python
thread_id = invocation.payload.get("thread_id")
source = invocation.payload.get("source")
message = invocation.message
```

## 3. 多次调用 LLM

agent 内部可以多次调用 LLM，也可以在中间执行数据库查询、RAG、工具调用等操作：

```python
class PlanningAgent(FreeBBSAgent):
    name = "planning"

    def can_handle(self, invocation: AgentInvocation) -> bool:
        return invocation.payload.get("agent") == self.name

    def run(self, invocation: AgentInvocation) -> dict:
        plan = self.call_llm(
            f"先把这个问题拆成学习计划：{invocation.message}",
            invocation.options,
        )

        answer = self.call_llm(
            [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": f"基于这个计划回答用户：{plan['answer']}"},
            ],
            invocation.options,
        )

        return {
            "answer": answer["answer"],
            "model": answer.get("model"),
            "finish_reason": answer.get("finish_reason"),
            "agent": self.name,
        }
```

建议返回值保持至少包含：

```json
{
  "answer": "...",
  "model": "...",
  "finish_reason": "stop"
}
```

可以额外加：

```json
{
  "agent": "planning",
  "sources": [],
  "steps": []
}
```

## 4. 使用工具函数

通用工具函数放在 `freebbs_agent/agent_tools.py`。当前提供：

- `http_request(...)`：发送 HTTP/HTTPS 请求，自动解析 JSON
- `execute_sqlite(...)`：访问 SQLite，默认只允许 `SELECT` / `WITH`
- `execute_mysql(...)`：访问 MySQL，需要额外安装 `pymysql`，默认只允许 `SELECT` / `WITH`

示例：

```python
from .agent_tools import execute_mysql, http_request


class SearchAgent(FreeBBSAgent):
    name = "search"

    def can_handle(self, invocation: AgentInvocation) -> bool:
        return invocation.payload.get("agent") == self.name

    def run(self, invocation: AgentInvocation) -> dict:
        result = http_request(
            "http://127.0.0.1:3001/api/health",
            timeout_seconds=3,
        )

        answer = self.call_llm(
            f"后端健康检查结果：{result.json}\n用户问题：{invocation.message}",
            invocation.options,
        )
        return answer
```

SQL 查询建议始终使用参数绑定：

```python
rows = execute_mysql(
    {
        "host": "127.0.0.1",
        "user": "freebbs",
        "password": "...",
        "database": "free_bbs",
    },
    "SELECT title FROM discussion_posts WHERE title LIKE %s LIMIT 5",
    [f"%{keyword}%"],
).rows
```

默认 `read_only=True`，写操作会被拒绝。需要写入时必须显式传 `read_only=False`，并且只应放在受控的内部 workflow 中。

## 5. 注册到 Mux

在 `create_default_mux(...)` 中注册新 agent：

```python
def create_default_mux(config: AgentConfig, chat_client: ChatClient) -> AgentMux:
    return AgentMux(
        [
            MyAgent(config, chat_client),
            CommentMentionAgent(config, chat_client),
            GeneralChatAgent(config, chat_client),
        ]
    )
```

顺序很重要：

- 更具体的 agent 放前面
- 兜底的 `GeneralChatAgent` 放最后

否则普通聊天 agent 可能会提前接走请求。

## 6. 路由方式

### 显式指定 agent

请求：

```json
{
  "agent": "my_agent",
  "message": "帮我规划通信原理怎么学"
}
```

`can_handle(...)`：

```python
def can_handle(self, invocation: AgentInvocation) -> bool:
    return invocation.payload.get("agent") == self.name
```

### 根据场景自动路由

例如评论区 `@max`：

```python
def can_handle(self, invocation: AgentInvocation) -> bool:
    source = invocation.payload.get("source") or invocation.payload.get("channel")
    return source == "comment" and "@max" in invocation.message.lower()
```

前端请求：

```json
{
  "source": "comment",
  "thread_id": 123,
  "comment_id": 456,
  "message": "@max 这个问题应该怎么问？"
}
```

## 7. 流式输出

如果 agent 只需要把 LLM 流直接转发：

```python
def stream(self, invocation: AgentInvocation):
    yield from self.stream_llm(invocation.messages, invocation.options)
```

如果 agent 要先做内部操作，再流式输出：

```python
def stream(self, invocation: AgentInvocation):
    context = self.lookup_context(invocation)
    messages = [
        {"role": "system", "content": self.config.system_prompt},
        {"role": "user", "content": f"资料：{context}\n\n问题：{invocation.message}"},
    ]
    yield from self.stream_llm(messages, invocation.options)
```

HTTP 层会把每个 chunk 拆成字符并用 SSE 返回：

```text
data: {"delta":"你"}

data: {"done":true}
```

## 8. 测试

新增 agent 时至少补这几类测试：

- 显式 `agent` 能路由到新 agent
- 自动路由条件能命中
- 不该命中的请求会落到 `GeneralChatAgent`
- 非流式返回正常
- 流式返回正常
- 未知 `agent` 返回 400

测试文件在 `tests/test_app.py`。

运行：

```bash
.venv/bin/python -m unittest discover -s tests
scripts/ci-validate.sh
```

## 9. 设计建议

- 不要把 HTTP request、Flask response 放进 agent；agent 只处理 `AgentInvocation`
- 不要在 agent 里直接读环境变量；配置从 `self.config` 取
- 新 agent 的 `can_handle(...)` 要尽量明确，避免误接请求
- 需要查数据库、搜索、RAG 时，先封装成单独函数或 service，再让 agent 调用
- `GeneralChatAgent` 应保持兜底，不承担具体业务场景逻辑

## 10. RAG Agent 参考实现

仓库内的一期轻量 RAG 可作为模板：

- `freebbs_agent/rag_agent.py`：独立 `rag` agent，显式 `agent=rag` 路由
- `freebbs_agent/rag/embeddings.py`：本地优先、API 可选的 embedding provider 抽象
- `freebbs_agent/rag/faiss_store.py`：FAISS 向量索引读写与 TopK 检索
- `scripts/build_rag_index.py`：离线建库脚本（拉取资料、切分、向量化、落盘）

建议开发顺序是先完成离线建库，再接在线检索。这样可以把数据问题与在线路由问题分开调试。
