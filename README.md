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

开发测试页：

```text
http://127.0.0.1:5001/dev/agent-test
```

这个页面只通过本地 agent 服务访问，用于开发人员测试指定 `agent`、`source`、`channel`、上下文 JSON 和流式输出。

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

- `agent`：指定 agent。当前支持 `general_chat` / `general` / `chat`、`comment_mention` / `comment` / `comment_at_max`、`rag` / `rag_agent`
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
- `RAG_ENABLED`：是否启用 RAG agent（默认 `false`）
- `RAG_INDEX_PATH`：FAISS 索引路径（默认 `data/rag/index.faiss`）
- `RAG_METADATA_PATH`：索引元数据路径（默认 `data/rag/metadata.jsonl`）
- `RAG_TOP_K`：检索候选数量（默认 `5`）
- `RAG_MAX_CONTEXT_CHUNKS`：拼接进 prompt 的最大 chunk 数（默认 `4`）
- `RAG_EMBEDDING_PROVIDER`：`local` 或 `api`，默认 `local`
- `RAG_LOCAL_EMBEDDING_MODEL`：本地 embedding 模型名（默认 `BAAI/bge-small-zh-v1.5`）
- `RAG_LOCAL_EMBEDDING_DIM`：本地 embedding 维度（默认 `512`）
- `RAG_LOCAL_MODEL_DIR`：本地模型目录（设置后优先使用，不走网络）
- `RAG_LOCAL_FILES_ONLY`：是否仅使用本地缓存模型（默认 `false`）
- `RAG_ALLOW_HASH_FALLBACK`：仅供测试的确定性 hash embedding 降级（默认 `false`，生产环境不应启用）
- `RAG_HF_ENDPOINT`：HuggingFace 镜像端点（推荐国内环境配置 `https://hf-mirror.com`）
- `RAG_EMBEDDING_API_KEY`：云端 embedding API key（`provider=api` 时使用）
- `RAG_EMBEDDING_BASE_URL`：云端 embedding base url（可选）
- `RAG_EMBEDDING_MODEL`：云端 embedding 模型名（默认 `text-embedding-3-small`）
- `ONLINE_ROUTER_ENABLED`：无显式 `agent` 时是否在线判断使用 RAG（默认 `true`）
- `ONLINE_ROUTER_CONFIDENCE_THRESHOLD`：自动路由到目标 Agent 的最低置信度（默认 `0.7`）
- `RAG_QUERY_AUGMENTATION_ENABLED`：是否结合对话改写问题并生成子查询（默认 `true`）
- `RAG_MAX_SUBQUERIES`：一次检索最多使用的扩展子查询数量（默认 `3`）

## 轻量 RAG（一期）

一期提供独立 `rag_agent`，流程是：

1. 从指定仓库拉取资料
2. 切分 chunk 并计算 embedding
3. 建立 FAISS 索引与 metadata
4. 在线请求通过 `agent=rag` 检索后再调用 LLM

### 构建索引

```bash
. .venv/bin/activate
export RAG_ENABLED=true
export RAG_HF_ENDPOINT="https://hf-mirror.com"
python scripts/build_rag_index.py
```

说明：脚本已内置项目根目录导入路径，直接执行即可，不需要再手动设置 `PYTHONPATH=.`

如果机器无法直连 HuggingFace，建议：

- 优先设置 `RAG_HF_ENDPOINT=https://hf-mirror.com`
- 若你已提前下载模型缓存，可设 `RAG_LOCAL_FILES_ONLY=true` 强制离线加载
- 最稳妥方式是直接指定本地目录：`RAG_LOCAL_MODEL_DIR=/path/to/local/model`

推荐国内环境配置组合：

```bash
export RAG_HF_ENDPOINT="https://hf-mirror.com"
export RAG_LOCAL_FILES_ONLY=true
# 如果已下载到本地目录，优先使用目录，完全不依赖 huggingface.co
export RAG_LOCAL_MODEL_DIR="/data/models/bge-small-zh-v1.5"
```

一键下载轻量模型并做离线可用性验证：

```bash
. .venv/bin/activate
python scripts/prepare_local_embedding_model.py \
  --model-id "BAAI/bge-small-zh-v1.5" \
  --output-dir "data/models/bge-small-zh-v1.5" \
  --hf-endpoint "https://hf-mirror.com"
```

如果镜像仍不稳定，可启用自动源切换（HF 镜像失败后自动尝试 ModelScope）：

```bash
python scripts/prepare_local_embedding_model.py \
  --model-id "BAAI/bge-small-zh-v1.5" \
  --output-dir "data/models/bge-small-zh-v1.5" \
  --source auto
```

通过后可直接绑定：

```bash
export RAG_LOCAL_MODEL_DIR="/home/sxz/freebbs-agent/data/models/bge-small-zh-v1.5"
export RAG_LOCAL_FILES_ONLY=true
```

默认数据源是：

```text
data/rag/sources.json
```

manifest 会记录每个资料仓库的 URL、本地目录、许可证和主题。构建脚本按需 clone/update，
不会把外部仓库内容提交到本仓库。当前包含 THUEE 硬件竞赛资料，以及开放许可的
Signals and Systems、Digital Signal Processing 课程资料。

也可以通过参数临时覆盖为单个仓库：

```bash
python scripts/build_rag_index.py \
  --repo-url "https://github.com/Lucas-Song-zero/2025HardWareContestOptionalPDFs_THUEE.git" \
  --repo-dir "data/rag/source/2025HardWareContestOptionalPDFs_THUEE" \
  --chunk-size 800 \
  --chunk-overlap 120
```

### 调用 rag_agent

启用 RAG 且索引存在时，普通请求可以省略 `agent`。服务会先在线判断是否需要平台知识，
再把依赖对话的问题改写为独立查询，通过向量与 BM25 关键词混合召回，
最后用 RRF 融合多条查询和两种召回通道的结果：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"课程资料里如何比较 Dijkstra 和 Floyd？"}'
```

显式传入 `agent` 仍可用于开发调试或强制路由：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"rag","message":"解释傅里叶变换在电子信息体系中的位置"}'
```

返回会额外包含 `agent` 与 `sources` 字段，便于前端展示引用来源。

### 一键在 5002 启用 RAG 服务

```bash
scripts/run_rag_5002.sh
```

默认行为：

- 监听 `127.0.0.1:5002`
- 启用 `RAG_ENABLED=true`
- 使用本地模型目录 `data/models/bge-small-zh-v1.5`
- 使用索引 `data/rag/index.faiss` 与 `data/rag/metadata.jsonl`

常见覆盖方式：

```bash
# 改端口
PORT=5003 scripts/run_rag_5002.sh

# 自定义模型目录或索引
RAG_LOCAL_MODEL_DIR=/data/models/bge-small-zh-v1.5 \
RAG_INDEX_PATH=data/rag/index.faiss \
RAG_METADATA_PATH=data/rag/metadata.jsonl \
scripts/run_rag_5002.sh
```

前置条件：

- 已完成依赖安装：`pip install -r requirements.txt`
- 已准备本地模型目录：`data/models/bge-small-zh-v1.5`
- 已构建索引文件：`data/rag/index.faiss` 与 `data/rag/metadata.jsonl`

停止服务：

- 在启动脚本的终端按 `Ctrl+C`

常见问题：

- `unknown agent: rag`：你访问到的不是当前目录启动的实例，确认使用 `http://127.0.0.1:5002/dev/agent-test`
- `Port 5002 is already in use`：换端口启动，例如 `PORT=5003 scripts/run_rag_5002.sh`
- `Missing local embedding model directory`：先执行模型准备脚本 `python scripts/prepare_local_embedding_model.py --source auto`

### 检索效果评估（与当前语料对齐）

当前默认评估 query set 已对齐第一期资料主题（网络基础/8266、PCB 打板焊接），避免用不在语料范围内的问题误判检索质量。

```bash
. .venv/bin/activate
python scripts/evaluate_rag_retrieval.py --top-k 5
```

输出包含：

- 每个 query 的 TopK 命中
- 首个相关结果 rank（first_relevant_rank）
- 汇总指标 `Hit@K` 与 `MRR@K`

也支持自定义 query set（JSON）：

```json
[
  {
    "query": "ESP8266 的 AP 模式和 STA 模式有什么区别？",
    "expected_source_keywords": ["网络基础知识和8266实战"],
    "expected_text_keywords": ["ap", "sta", "esp8266"],
    "note": "网络资料命中验证"
  }
]
```

```bash
python scripts/evaluate_rag_retrieval.py --query-set path/to/queries.json --top-k 5
```

## CI/CD

目录结构参考 `../server`，push 到 `main` 会自动部署：

- `.github/workflows/deploy.yml`：GitHub Actions 自动部署
- `scripts/ci-validate.sh`：安装依赖、语法检查、单元测试、必要文件检查
- `scripts/deploy.sh`：同步代码、创建 venv、安装依赖、重启 systemd 服务、健康检查
- `deploy/systemd/free-bbs-agent.service`：systemd 服务模板

部署准备细节见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## Agent 开发

新增 agent 的方式见 [docs/adding-agent.md](docs/adding-agent.md)。
