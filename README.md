# FREE-BBS Agent

`freebbs-agent` 是 FREE-BBS 的本地 AI 服务，使用 Python 与 Flask 提供统一聊天接口，
并通过 AgentMux 路由到通用问答、评论回复、课程资料 RAG、站内导航或 Info Sub-Agent。
本文是仓库唯一的说明文档，涵盖使用、接口、配置、开发、联调、测试与部署。

## 1. 系统定位

最终用户只需访问 FREE-BBS 网站的“问问 Max”等页面，不需要安装本仓库、配置模型密钥
或直接访问 Agent 端口。典型调用链如下：

```text
用户浏览器
  -> freebbs-web 前端
  -> freebbs-web 后端
  -> freebbs-agent（127.0.0.1:5001）
  -> General / Comment / Navigation / RAG / Info Agent
  -> 模型服务、课程索引或 subagent-eeinfo
```

服务默认只监听 `127.0.0.1:5001`，并拒绝非 loopback 来源。生产环境只应公开主站的
HTTPS 入口，不应直接公开 Agent、Info、数据库或 Unix Socket 配置接口。

### 内置 Agent

| Agent | 请求名称 | 作用 |
| --- | --- | --- |
| General Chat | `general_chat`、`general`、`chat` | 通用问答，也是默认兜底 |
| Comment | `comment_mention`、`comment`、`comment_at_max` | 回复评论区中的 `@max` |
| Navigation | `navigation`、`guide`、`navigator`、`intent_router` | 识别意图并返回可信站内入口，可委派 RAG/Info |
| RAG | `rag`、`rag_agent` | 检索课程索引后调用模型，并返回来源 |
| Info | `info`、`info_agent`、`eeinfo`、`campus_info` | 查询网络学堂、课程公告和 THU Info |

请求未显式指定 `agent` 时，系统先尝试评论区和 Info 等确定性场景路由；启用在线路由后，
再由模型在 RAG 与 General Chat 之间选择，失败或低置信度时回退到 General Chat。

## 2. 仓库结构

```text
app.py                              启动入口
freebbs_agent/app.py                Flask 路由与请求校验
freebbs_agent/agent_utils.py        Agent 基类、调用参数和 AgentMux
freebbs_agent/agents.py             内置 Agent 注册
freebbs_agent/ai_client.py          OpenAI-compatible 模型客户端
freebbs_agent/navigation_agent.py   Navigation Agent
freebbs_agent/rag_agent.py          RAG Agent
freebbs_agent/rag/                  索引、切块、embedding 与检索
freebbs_agent/info_agent.py         Info Sub-Agent bridge
scripts/                            建索引、评估、测试与部署脚本
tests/                              单元测试
deploy/systemd/                     systemd unit 模板
data/rag/                           默认 FAISS 索引与 metadata
```

`docs/plans4rag_agent/` 中保留的 JSON/XLSX 是课程知识图谱数据模板，不是说明文档：

- `FREE_BBS_课程知识图谱轻量模板.json`
- `FREE_BBS_课程知识点整理模板_轻量版(1).xlsx`

## 3. 本地运行

### 3.1 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 不会被 Git 跟踪。不要把模型 API key、内部 Token、Cookie、密码或验证码提交到
仓库。

### 3.2 选择模型配置模式

本地独立开发可以使用静态配置：

```dotenv
AGENT_API_KEY=your-api-key
AGENT_BASE_URL=https://cloud.infini-ai.com/maas/v1
AGENT_MODEL=glm-5.1
AGENT_HOST=127.0.0.1
AGENT_PORT=5001
```

确保没有同时启用主服务配置：

```bash
unset AGENT_SETTINGS_SOCKET AGENT_SERVICE_TOKEN
```

生产环境使用主站管理员维护的模型配置，不在 Agent 环境文件中保存模型密钥：

```dotenv
AGENT_SETTINGS_SOCKET=/run/free-bbs/agent-config.sock
AGENT_SERVICE_TOKEN=replace-with-a-long-random-shared-token
```

这两个变量必须同时存在或同时不存在。只配置一个会导致启动失败；启用主服务配置后，
模型认证或配置读取失败不会回退到环境变量中的 API key。

### 3.3 启动与检查

`.env` 不会由 Flask 自动加载，启动前需要导入：

```bash
set -a
. ./.env
set +a
python app.py
```

健康检查与问答：

```bash
curl http://127.0.0.1:5001/health

curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"解释傅里叶变换在电子信息知识体系中的位置"}'
```

开发测试页：

| 地址 | 用途 |
| --- | --- |
| `/dev/agent-test` | 选择 Agent、来源、上下文与流式模式 |
| `/dev/general-test` | 通用问答 |
| `/dev/navigation-test` | 导航意图、入口与子 Agent 委派 |
| `/dev/rag-test` | RAG 检索与引用 |
| `/dev/comment-test` | 评论区 `@max` |
| `/dev/info-test` | 跳转到 Info Sub-Agent 控制台 |
| `/dev/course-graph-test` | 课程图谱场景 |
| `/dev/project-test` | PBL 项目场景 |
| `/dev/learning-profile-test` | 学习印记场景 |

这些页面只供本地开发，不能作为最终用户入口。

## 4. HTTP 接口

### `GET /health`

```json
{"status":"ok","service":"freebbs-agent"}
```

### `POST /api/v1/chat`

最简请求：

```json
{"agent":"general_chat","message":"解释傅里叶变换"}
```

也可以使用 OpenAI 风格多轮消息：

```json
{
  "agent": "navigation",
  "messages": [
    {"role":"user","content":"我不知道该去哪里"},
    {"role":"assistant","content":"你想找资料、讨论、项目还是通知？"},
    {"role":"user","content":"我想找课程资料"}
  ],
  "execute_subagent": "none"
}
```

通用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `message` | string | 单轮用户消息；与 `messages` 二选一 |
| `messages` | array | 非空的 `system`、`user`、`assistant` 消息列表 |
| `agent` | string | 可选；不填时由 mux 路由 |
| `source` / `channel` | string | 请求来源；评论区自动路由会使用 |
| `model` | string | 可选模型覆盖 |
| `temperature` | number | 可选采样温度 |
| `max_tokens` | integer | 可选输出上限 |
| `stream` | boolean | 是否返回 SSE |

非流式模型响应至少包含 `answer`、`model` 和 `finish_reason`。流式响应使用 SSE：

```text
data: {"delta":"你"}

data: {"done":true}
```

当前 SSE 只传输文本增量，不携带 Navigation 的 `routes` 或 RAG 的 `sources`；需要结构化
字段的页面应使用 `stream: false`。

### `POST /api/v1/info/jobs/get`

用于代理查询 Info Sub-Agent 的认证或异步任务：

```json
{"job_id":"job_xxx"}
```

请求必须携带与首次 Info 调用相同的可信身份头。HTTP `202` 表示仍在执行，HTTP `200`
表示已得到最终结果。

## 5. Navigation Agent

Navigation 使用关键词规则与可选 LLM 增强识别一个或多个意图。模型缺失、不可用或输出
异常时自动回退到规则路由。LLM 只能选择受支持的意图，所有 URL 都由服务端白名单生成。

多轮会话采用“当前明确意图优先、模糊追问继承上下文”的规则：

- 最新一轮明确提出新板块时，新目标会覆盖此前的板块意图，避免旧关键词继续占据按钮；
- 最新一轮同时明确提出多个目标时，仍可返回最多三个相关入口；
- “就去那里看看”“再详细一点”等无法独立判断的追问会结合历史消息补全意图；
- 确定性规则与 LLM 导航使用相同原则，因此模型回退不会改变多轮行为。

例如，用户先说“我想找课程资料和讲义”，随后说“现在我想找一个项目和队友”，第二轮
应以 PBL 项目入口为主，不再重复上一轮的知识库按钮。

| 意图 | 模块 | 页面 |
| --- | --- | --- |
| `knowledge_search` | `knowledge_rag` | `/knowledge` |
| `announcement` | `announcements` | `/workbench` |
| `course_discussion` | `course_discussion` | `/discussion` |
| `course_graph` | `course_graph` | `/course` |
| `project` | `pbl` | `/development` |
| `learning_profile` | `learning_profile` | `/profile` |

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"agent":"navigation","message":"最近有什么讲座通知？"}'
```

响应包括 `intent`、`confidence`、`needs_clarification`、`routes`、`llm_used` 和
`llm_status`。`routes` 最多包含三个入口，每项提供 `module`、`title`、`url`、`reason`
与匹配分数。

`execute_subagent` 支持：

| 值 | 行为 |
| --- | --- |
| `none` | 只返回导航结果，默认值 |
| `auto` | `knowledge_search` 委派 RAG，`announcement` 委派 Info |
| `rag` | 强制委派 RAG |
| `info` | 强制委派 Info |

委派响应保留导航字段并增加 `delegation` 与 `subagent`。成功时顶层 `answer` 使用子 Agent
回答，原导航文案保存在 `navigation_answer`。模糊问题需要澄清时不会执行委派。

## 6. RAG Agent

RAG 的在线链路为“查询规划 → 多子查询检索 → Reciprocal Rank Fusion → 拼接资料上下文
→ 调用模型”。响应增加 `query_plan` 与 `sources`。

### 准备模型与索引

```bash
. .venv/bin/activate
python scripts/prepare_local_embedding_model.py \
  --model-id BAAI/bge-small-zh-v1.5 \
  --output-dir data/models/bge-small-zh-v1.5 \
  --source auto

export RAG_ENABLED=true
python scripts/build_rag_index.py
```

### 自动同步 Web 课程知识点

生产环境通过 Web 后端的鉴权 Unix Socket 读取 MySQL 课程快照。数据库迁移
`024_add_rag_index_revision.sql` 会创建课程索引 revision；Web 在课程知识点、正文分区和图谱
关系成功变更后递增 revision。定时任务仅在 revision 变化时构建新索引。新索引写入版本目录，校验成功后原子更新
`RAG_INDEX_MANIFEST_PATH`，运行中的 Agent 会自动热加载；加载失败时继续使用旧索引。

首次部署：

```bash
# 先在 freebbs-web 仓库执行数据库迁移（或运行 db-migrate 工作流），
# 确认 024_add_rag_index_revision.sql 已应用。
sudo cp deploy/systemd/free-bbs-rag-indexer.service /etc/systemd/system/
sudo cp deploy/systemd/free-bbs-rag-indexer.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start free-bbs-rag-indexer.service
sudo systemctl enable --now free-bbs-rag-indexer.timer
systemctl status free-bbs-rag-indexer.timer
```

定时任务通过 `AGENT_SETTINGS_SOCKET` 和 `AGENT_SERVICE_TOKEN` 获取课程数据，不需要在
Agent 环境中配置 MySQL 密码。正式启用前先完成一次同步并运行
`python -m freebbs_agent.rag.preflight`；随后设置 `RAG_ENABLED=true`、重启 Agent，并确认
`/health` 中 `rag.ready=true`。生产索引目录应放在部署目录之外的持久化课程资料根目录中，
并授予 `freebbs-agent` 写权限。

推荐的生产路径配置如下；静态 seed 索引使用绝对路径，自动生成的 manifest 使用课程资料
根目录下的相对路径：

```dotenv
RAG_INDEX_PATH=/data/www/freebbs-agent/data/rag/index.faiss
RAG_METADATA_PATH=/data/www/freebbs-agent/data/rag/metadata.jsonl
RAG_INDEX_MANIFEST_PATH=data/rag/current.json
```

国内环境可以设置 `RAG_HF_ENDPOINT=https://hf-mirror.com`。若模型已下载，使用：

```dotenv
RAG_LOCAL_MODEL_DIR=data/models/bge-small-zh-v1.5
RAG_LOCAL_FILES_ONLY=true
```

默认资料仓库为：

```text
https://github.com/Lucas-Song-zero/2025HardWareContestOptionalPDFs_THUEE.git
```

可覆盖数据源与切块参数：

```bash
python scripts/build_rag_index.py \
  --repo-url https://github.com/Lucas-Song-zero/2025HardWareContestOptionalPDFs_THUEE.git \
  --repo-dir data/rag/source/2025HardWareContestOptionalPDFs_THUEE \
  --chunk-size 800 \
  --chunk-overlap 120
```

### 调用、独立运行与评估

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"agent":"rag","message":"解释傅里叶变换在电子信息体系中的位置"}'

scripts/run_rag_5002.sh
PORT=5003 scripts/run_rag_5002.sh

python scripts/evaluate_rag_retrieval.py --top-k 5
python scripts/evaluate_rag_retrieval.py \
  --query-set data/rag/evals/dsa_outline_queries.json \
  --top-k 5
```

评估报告包含 TopK、首个相关结果排名、`Hit@K` 与 `MRR@K`。项目内置 hash embedding
只适合链路 smoke test；正式质量评估应安装真实 embedding 运行时，并用同一模型重建
索引和执行评估。

历史数算提纲 smoke test 曾在 `RAG_LOCAL_EMBEDDING_DIM=512` 下取得 `Hit@5=100%`、
`MRR@5=1.0`。该结果只说明当时的五条用例能命中新资料源，不代表完整语义检索质量。

## 7. Info Sub-Agent 联调

Info Bridge 调用独立的 `subagent-eeinfo`：

```text
freebbs-web 后端
  -> freebbs-agent /api/v1/chat
  -> InfoAgentBridge
  -> subagent-eeinfo /internal/tools/manifest + /internal/tools/execute
```

| 配置 | 方向 | 用途 |
| --- | --- | --- |
| `FREEBBS_AGENT_INTERNAL_TOKEN` | Web 后端 → Agent | 证明用户身份来自可信后端 |
| `INFO_AGENT_INTERNAL_TOKEN` | Agent → Info | 证明 Tool Call 来自主 Agent |
| `EEINFO_INTERNAL_TOKEN` | Info 服务端 | 校验上一项，值必须相同 |

前两个 Token 保护不同边界，不应复用，也不能下发浏览器。

Agent 配置：

```dotenv
INFO_AGENT_ENABLED=true
INFO_AGENT_BASE_URL=http://127.0.0.1:4310
INFO_AGENT_INTERNAL_TOKEN=replace-with-info-token
INFO_AGENT_TIMEOUT_SECONDS=30
INFO_AGENT_AUTO_AUTHENTICATE=true
FREEBBS_AGENT_INTERNAL_TOKEN=replace-with-web-to-agent-token
```

Info 服务启动：

```bash
cd /home/jl2004/subagent-eeinfo
export EEINFO_INTERNAL_TOKEN='replace-with-info-token'
npm run demo
```

浏览器 JSON 中自报的 UID、学号和权限不会被使用。`freebbs-web` 后端必须从已验证会话
取得身份并注入：

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
{"agent":"info","message":"查询信号与系统最新公告"}
```

支持的权限只有 `web_learning:read` 和 `thu_info:read`。响应增加 `status`、`request_id`、
`tool_call_id`、`tool_message`、`result`、`execution` 与 `required_action`。需要登录时通常
返回 `status: "pending"` 和 `job_id`，随后通过 `/api/v1/info/jobs/get` 轮询。

## 8. 与 freebbs-web 联调

| 服务 | 默认地址 |
| --- | --- |
| freebbs-web 前端 | `127.0.0.1:3000` |
| freebbs-web 后端 | `127.0.0.1:3001` |
| freebbs-agent | `127.0.0.1:5001` |
| subagent-eeinfo | `127.0.0.1:4310` |
| MySQL | `127.0.0.1:3306` |

启动顺序：

1. 需要 Info 时启动 `subagent-eeinfo`。
2. 导入本仓库 `.env` 并运行 `python app.py`。
3. 在 `freebbs-web/backend/.env` 中设置 `AGENT_URL=http://127.0.0.1:5001` 及相同的
   `FREEBBS_AGENT_INTERNAL_TOKEN`。
4. 在 `freebbs-web` 执行 `npm install && npm run start:local`。
5. 打开 `http://127.0.0.1:3000/aichat`，不要把 `/dev/*` 页面当作正式入口。

主站渲染 Navigation 的 `routes` 时必须再次校验同源地址和允许路径。Info 请求必须由
后端注入身份，不能由浏览器直连 Info。

`freebbs-web` 会把每条 assistant 消息的 Navigation 快照与对话一起保存，快照只包含导引
说明以及最多三个经过白名单过滤的 `title`、`reason` 和 `url`。重新加载页面、切换历史
会话或从导引页面返回“问问 Max”时，前端会根据该快照重新渲染按钮。旧版本已经保存但
不含快照的历史消息无法反向恢复按钮；升级后新生成的消息会正常持久化。

最低验收包括：

1. `/aichat` 能得到 Navigation 回答和真实站内按钮；
2. 知识入口指向 `/knowledge`，讨论入口指向 `/discussion`；
3. 点击按钮离开后再返回或重新加载历史会话，按钮仍然存在；
4. 同一会话改去其他板块时，新按钮覆盖此前明确意图；
5. 省略或指代式追问能继续利用历史 `messages`；
6. RAG 委派返回来源，Info 委派不出现 `trusted_context_missing`；
7. 伪造 UID 或外部 URL 均不能越过后端与前端白名单；
8. 浏览器响应、页面源码和日志中不出现内部 Token。

## 9. 环境变量参考

优先复制 `.env.example`；以下为代码当前支持的变量。

### 服务与模型

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_HOST` | `127.0.0.1` | 监听地址 |
| `AGENT_PORT` | `5001` | 监听端口 |
| `AGENT_TIMEOUT_SECONDS` | `60` | 模型请求超时 |
| `AGENT_SYSTEM_PROMPT` | 内置提示词 | 默认系统提示词 |
| `AGENT_API_KEY` | 空 | 本地模型密钥，也兼容 `OPENAI_API_KEY` |
| `AGENT_BASE_URL` | Infini-AI MaaS | OpenAI-compatible 地址 |
| `AGENT_MODEL` | `glm-5.1` | 默认模型 |
| `AGENT_SETTINGS_SOCKET` | 空 | 主服务模型配置 Unix Socket |
| `AGENT_SERVICE_TOKEN` | 空 | Socket 配置服务认证 Token |
| `AGENT_SETTINGS_TIMEOUT_SECONDS` | `2` | 配置读取超时 |
| `AGENT_SETTINGS_CACHE_TTL_SECONDS` | `30` | 正常配置缓存秒数 |
| `AGENT_SETTINGS_STALE_TTL_SECONDS` | `300` | 旧配置最长使用时间 |
| `COURSE_MATERIALS_ROOT` | 空 | 主服务托管课程资料根目录 |

### Navigation 与在线路由

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FREEBBS_WEB_BASE_URL` | 空 | 生成绝对站内链接时使用 |
| `NAVIGATION_LLM_ENABLED` | `true` | 是否启用导航 LLM |
| `NAVIGATION_MODEL` | 空 | 空时使用默认模型 |
| `NAVIGATION_LLM_CONFIDENCE_THRESHOLD` | `0.7` | 规则达到该值时跳过 LLM |
| `ONLINE_ROUTER_ENABLED` | `true` | 未指定 Agent 时启用在线路由 |
| `ONLINE_ROUTER_CONFIDENCE_THRESHOLD` | `0.7` | 在线路由最低置信度 |

### RAG

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RAG_ENABLED` | `false` | 是否启用 RAG |
| `RAG_INDEX_PATH` | `data/rag/index.faiss` | FAISS 索引 |
| `RAG_METADATA_PATH` | `data/rag/metadata.jsonl` | 索引 metadata |
| `RAG_INDEX_MANIFEST_PATH` | `data/rag/current.json` | 自动同步索引的原子版本清单 |
| `RAG_INDEX_RELOAD_INTERVAL_SECONDS` | `5` | Agent 检查新索引版本的间隔 |
| `RAG_COURSE_SNAPSHOT_ENDPOINT` | `/internal/v1/rag-course-snapshot` | Web 内部课程快照接口 |
| `RAG_COURSE_SNAPSHOT_SOCKET` | 回退到 `AGENT_SETTINGS_SOCKET` | 课程快照 Unix Socket |
| `RAG_COURSE_SNAPSHOT_TOKEN` | 回退到 `AGENT_SERVICE_TOKEN` | 课程快照认证 Token |
| `RAG_SYNC_TIMEOUT_SECONDS` | `30` | 索引器读取课程快照的超时 |
| `RAG_VERSION_RETENTION` | `3` | 保留的索引版本数 |
| `RAG_TOP_K` | `5` | 每次检索候选数 |
| `RAG_MAX_CONTEXT_CHUNKS` | `4` | 注入模型的最大 chunk 数 |
| `RAG_EMBEDDING_PROVIDER` | `local` | `local` 或 `api` |
| `RAG_LOCAL_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地模型 ID |
| `RAG_LOCAL_EMBEDDING_DIM` | `512` | embedding 维度 |
| `RAG_LOCAL_MODEL_DIR` | 空 | 本地模型目录 |
| `RAG_LOCAL_FILES_ONLY` | `false` | 是否禁止在线下载 |
| `RAG_HF_ENDPOINT` | 空 | HuggingFace 镜像地址 |
| `RAG_EMBEDDING_API_KEY` | 空 | API embedding 密钥 |
| `RAG_EMBEDDING_BASE_URL` | 空 | API embedding 地址 |
| `RAG_EMBEDDING_MODEL` | `text-embedding-3-small` | API embedding 模型 |
| `RAG_QUERY_AUGMENTATION_ENABLED` | `true` | 是否生成扩展查询 |
| `RAG_MAX_SUBQUERIES` | `3` | 子查询最大数量 |

### Info

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INFO_AGENT_ENABLED` | `false` | 是否启用 Info Bridge |
| `INFO_AGENT_BASE_URL` | `http://127.0.0.1:4310` | Info 服务地址 |
| `INFO_AGENT_INTERNAL_TOKEN` | 空 | Agent 到 Info 的 Token |
| `INFO_AGENT_TIMEOUT_SECONDS` | `30` | Info 调用超时 |
| `INFO_AGENT_AUTO_AUTHENTICATE` | `true` | 缺少 Cookie 时是否发起认证 |
| `FREEBBS_AGENT_INTERNAL_TOKEN` | 空 | Web 后端到 Agent 的 Token |

## 10. 新增 Agent

新 Agent 继承 `FreeBBSAgent`，实现清晰的 `can_handle()`，需要定制流程时再覆盖 `run()` 与
`stream()`：

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

在 `freebbs_agent/agents.py` 的 `create_default_mux()` 中注册。具体 Agent 放前面，
`GeneralChatAgent` 始终放最后。不要在 Agent 中直接处理 Flask response 或读取环境变量；
使用 `AgentInvocation` 与 `self.config`。

`freebbs_agent/agent_tools.py` 提供 `http_request()`、默认只读的 `execute_sqlite()` 和
`execute_mysql()`。数据库查询必须使用参数绑定；写操作需要显式 `read_only=False`，且
只能用于受控内部流程。

新增 Agent 至少测试显式路由、自动路由、不误接请求、非流式、流式以及未知 Agent 的
`400` 响应。

## 11. 测试与 CI

```bash
.venv/bin/python -m unittest discover -s tests -v

.venv/bin/python -m unittest tests.test_navigation_agent -v
.venv/bin/python -m unittest tests.test_rag_agent -v
.venv/bin/python -m unittest tests.test_info_agent -v

.venv/bin/python scripts/test_navigation_agent.py \
  --base-url http://127.0.0.1:5001

scripts/ci-validate.sh
```

CI 脚本创建虚拟环境、安装依赖、执行 Python 与 shell 语法检查、运行测试，并验证部署所需
文件。Push 到 `main` 时，`.github/workflows/deploy.yml` 会先运行校验，再通过 SSH 部署。

当前版本的完整 Agent 测试套件包含 98 项测试，其中包括“明确切换到新板块”和“模糊追问
沿用旧上下文”两类多轮 Navigation 回归用例。主站侧还应运行：

```bash
cd /home/jl2004/freebbs-web
npm run test:aichat-navigation
npm run test:agent-surfaces
npm run check
```

## 12. 生产部署

### 服务器准备

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip rsync curl

sudo useradd -m -s /bin/bash deploy || true
sudo groupadd --system freebbs-agent-config || true
sudo groupadd --system freebbs-agent || true
id -u freebbs-agent >/dev/null 2>&1 || \
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin \
  --gid freebbs-agent-config --groups freebbs-agent freebbs-agent

sudo mkdir -p /data/www/freebbs-agent /etc/free-bbs
sudo chown -R deploy:deploy /data/www/freebbs-agent
sudo chown root:deploy /etc/free-bbs
sudo chmod 751 /etc/free-bbs
```

### 环境文件与 systemd

创建 `/etc/free-bbs/freebbs-agent.env`：

```dotenv
AGENT_SETTINGS_SOCKET=/run/free-bbs/agent-config.sock
AGENT_SERVICE_TOKEN=replace-with-the-token-used-by-freebbs-web
AGENT_SETTINGS_TIMEOUT_SECONDS=2
AGENT_SETTINGS_CACHE_TTL_SECONDS=30
AGENT_SETTINGS_STALE_TTL_SECONDS=300
AGENT_HOST=127.0.0.1
AGENT_PORT=5001
AGENT_TIMEOUT_SECONDS=60
```

生产环境不要在该文件保存模型 API key、模型名或 base URL；它们由主站“系统设置”维护。
Socket 权限应为 `0660`，运行目录为 `0750`，且不能由 Nginx 代理。

```bash
sudo chown deploy:freebbs-agent /etc/free-bbs/freebbs-agent.env
sudo chmod 640 /etc/free-bbs/freebbs-agent.env

sudo cp /data/www/freebbs-agent/deploy/systemd/free-bbs-agent.service \
  /etc/systemd/system/free-bbs-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now free-bbs-agent
```

模板默认使用工作目录 `/data/www/freebbs-agent`、环境文件
`/etc/free-bbs/freebbs-agent.env`、用户 `freebbs-agent`、主组 `freebbs-agent-config`
和服务名 `free-bbs-agent`。更新 unit 模板后必须重新复制并执行 `daemon-reload`。

### sudoers 与 GitHub Actions

通过 `command -v systemctl` 确认路径，然后创建 `/etc/sudoers.d/freebbs-agent-runner`：

```text
deploy ALL=NOPASSWD:/usr/bin/systemctl restart free-bbs-agent,/usr/bin/systemctl --no-pager --full status free-bbs-agent
```

Repository secrets：

- `DEPLOY_HOST`：服务器 IP 或域名；
- `DEPLOY_USER`：通常为 `deploy`；
- `DEPLOY_SSH_KEY`：完整 OpenSSH 私钥，不是 `.pub` 文件。

可选 variables：`DEPLOY_PORT`、`AGENT_DEPLOY_PATH`、`FREEBBS_AGENT_ENV_FILE`、
`AGENT_SERVICE_NAME`、`AGENT_HEALTHCHECK_URL`。

首次上线先手动验证：

```bash
bash scripts/deploy.sh
sudo systemctl status free-bbs-agent
curl http://127.0.0.1:5001/health
```

SSH 认证失败时检查部署用户、私钥、`authorized_keys` 及其 `700/600` 权限；出现
`Unit free-bbs-agent.service not found` 时先完成 systemd 安装。

## 13. 安全与故障处理

- Agent、Info 与数据库只监听 loopback；
- 用户身份必须由 Web 后端从已验证会话取得；
- 不信任浏览器 JSON 中的 UID、学号、权限或内部服务信息；
- 内部 Token 不进入前端、Local Storage、模型上下文或日志；
- Navigation 链接同时经过服务端与前端白名单；
- 密码、验证码、Cookie 和模型密钥不进入对话上下文；
- 生产网站只通过 HTTPS 对外提供。

| 现象 | 处理 |
| --- | --- |
| `unknown agent: rag` | 确认请求命中了当前仓库启动的实例 |
| RAG 返回 disabled | 设置 `RAG_ENABLED=true` 并构建索引 |
| `Missing local embedding model directory` | 运行模型准备脚本或修正模型目录 |
| 端口被占用 | 设置其他 `AGENT_PORT` 或 RAG 脚本的 `PORT` |
| Navigation `llm_used=false` | 根据 `llm_status` 检查密钥、开关或上游模型 |
| Info `trusted_context_missing` | 从 Web 后端注入可信身份头 |
| Info 返回 pending | 引导认证并轮询 `/api/v1/info/jobs/get` |
| 无法读取主服务配置 | 检查 Socket、共享组、Token 与权限 |

Agent 不可用时，主站应显示可理解的临时错误，不得暴露内部堆栈、Token 或服务地址；模型
不可用时 Navigation 仍可使用规则路由；RAG 未启用时仍可返回知识页面入口。

## 14. 历史设计说明

仓库曾分别维护 Navigation 开发总结、Max 接入方案、Info 联调文档、RAG 开发日志、课程
图谱填写说明和 2026 年三周计划。这些内容已按当前代码状态合并到本文；过时的分支名、旧
页面路径和已完成任务不再作为操作说明保留。

课程知识图谱后续开发仍遵循稳定 ID、结构化资料来源、关系端点校验、真实 embedding、可
追溯引用、索引一致性、低置信度澄清和明确权限边界。历史细节仍可通过 Git 记录查看。
