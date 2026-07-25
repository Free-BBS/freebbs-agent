# 数算提纲 RAG 验证说明

本文记录 `Data and Algorithm Review Sheet` 加入轻量 RAG 索引后的验证方式和验收结果。

## 资料来源

- 新增资料源：`data/rag/source/course-outlines/data-and-algorithm-review-sheet.txt`
- 新增索引片段：40 个 chunk，已写入 `data/rag/metadata.jsonl`
- 验证用例：`data/rag/evals/dsa_outline_queries.json`

## 运行方式

```bash
RAG_LOCAL_EMBEDDING_DIM=512 \
python scripts/evaluate_rag_retrieval.py \
  --query-set data/rag/evals/dsa_outline_queries.json \
  --top-k 5
```

当前项目的最小依赖环境没有安装 `sentence-transformers` 和 `torch`，所以上述命令会使用项目内置的确定性 hash embedding 降级路径。这个结果适合作为“是否能命中新资料源”的 smoke test。若需要完整 BGE 语义检索评估，需要先安装可选 embedding 运行时，并用同一套运行时重建 FAISS 索引和执行在线检索。

如需端到端手动验证，可以启动 RAG 服务，并在测试页中用 `agent=rag` 提问：

```bash
scripts/run_rag_5002.sh
```

测试页地址：

```text
http://127.0.0.1:5002/dev/agent-test
```

## 推荐手动验证问题

1. 数算课上讲过哪些算法设计思想？分别有什么例子？
2. 顺序表和单向链表在查找、插入、删除上的复杂度有什么区别？
3. 快速排序、归并排序和堆排序的时间复杂度、稳定性和附加存储怎么比较？
4. Dijkstra 算法和 Floyd 算法分别解决什么最短路径问题？
5. 数值计算里的截断误差和舍入误差分别是什么？

## 预期表现

检索结果的 TopK 中应包含：

- `course-outlines/data-and-algorithm-review-sheet.txt`

回答内容应能使用数算提纲中的课程细节，例如：

- 算法设计思想：蛮力法、分治法、减治法、变治法、贪心算法、动态规划、回溯法、分支定界法、随机算法
- 顺序表/链表基本操作复杂度
- 快速排序、归并排序、堆排序的复杂度和稳定性比较
- Dijkstra 单源最短路径与 Floyd 全源最短路径
- 截断误差、舍入误差、浮点运算误差

与 `general_chat` 相比，`rag` 应给出更贴合课程提纲的回答，并在响应的 `sources` 字段中返回数算提纲来源。

## 本地 Smoke Test 结果

在最小 `.venv` 环境下设置 `RAG_LOCAL_EMBEDDING_DIM=512` 后运行：

```text
Hit@5: 5/5 = 100.00%
MRR@5: 1.0000
```

5 条验证问题均在 Top5 内命中 `course-outlines/data-and-algorithm-review-sheet.txt`。
