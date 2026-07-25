# RAG 开发记录

## 2026-05-12 轻量 RAG 一期

### 背景
- 目标是在不影响现有 `general_chat` 和 `comment_mention` 的前提下，引入独立 `rag_agent`。
- 数据源第一期来自电子工程系资料仓库：`2025HardWareContestOptionalPDFs_THUEE`。

### 决策
- 路由策略：显式 `agent=rag`，避免默认请求被误路由。
- embedding 架构：本地优先（`RAG_EMBEDDING_PROVIDER=local`），云端 API 作为可选 provider。
- 检索引擎：`faiss-cpu` + `metadata.jsonl`，索引和文本元信息解耦存储。

### 实现
- 新增 `freebbs_agent/rag/` 子模块：
  - `ingest.py`：仓库拉取与文本抽取
  - `chunking.py`：文档切分
  - `embeddings.py`：embedding provider 抽象
  - `faiss_store.py`：索引构建、保存、加载、检索
- 新增 `freebbs_agent/rag_agent.py`，在线请求时执行“检索 -> 拼接上下文 -> LLM”。
- 新增 `scripts/build_rag_index.py`，用于离线建索引。

### 遇到的问题
- 部分环境缺少本地 embedding 运行时（如 `sentence-transformers`），已在本地 provider 中保留降级路径。
- 资料仓库可能包含大量 PDF，抽取质量受 PDF 文本层质量影响。

### 下一步
- 增加 reranker（如 BGE reranker）提升 TopK 相关性。
- 支持多数据源合并索引与增量更新。
- 在响应中增加可选引用文本片段，便于前端展示可追溯答案。
