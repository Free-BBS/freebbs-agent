# 导引 Agent 开发与测试说明

## 1. 功能概述

本次在 `feat/ljh_dev` 分支新增了 FREE-BBS 导引 Agent。

用户可以输入自然语言需求，例如：

- “我想找信号与系统的课程资料”
- “最近有什么讲座通知？”
- “这道题不会做，我想去讨论区请教同学”
- “我想找一个 FPGA 项目和队友”
- “帮我看看自己的学习进度”

导引 Agent 会识别用户意图，并返回 1～3 个可点击的模块入口。

目前支持以下模块：

| 意图 | 模块 | 默认路径 |
| --- | --- | --- |
| 查找资料、讲义、概念解释 | 知识 RAG Agent | `/knowledge/rag` |
| 查看课程、活动、讲座通知 | 公告与通知 | `/notifications` |
| 提问、交流、课程答疑 | 课程讨论区 | `/discussions` |
| 选课、先修知识、学习规划 | 课程与知识图谱 | `/courses` |
| 寻找项目、竞赛和队友 | PBL 项目孵化器 | `/projects` |
| 查看学习轨迹和薄弱点 | 个性化学习印记 | `/profile/learning` |

Agent 支持一次识别多个意图。例如“先找资料，再去讨论区提问”会同时推荐知识
RAG 和课程讨论区。

如果输入过于模糊，Agent 会返回 `needs_clarification: true`，提示用户说明是在找
资料、通知、讨论、项目还是学习记录。

## 2. 修改和新增的文件

### Agent 后端

- `freebbs_agent/navigation_agent.py`
  - 实现意图关键词与权重配置。
  - 实现多意图评分和排序。
  - 生成包含查询参数的模块跳转链接。
  - 提供低置信度澄清机制。
  - 支持普通 JSON 和 SSE 流式输出。

- `freebbs_agent/agents.py`
  - 将 `NavigationAgent` 注册到默认 AgentMux。
  - 支持以下 Agent 名称：
    - `navigation`
    - `guide`
    - `navigator`
    - `intent_router`

- `freebbs_agent/config.py`
  - 增加 `web_base_url` 配置。
  - 支持通过 `FREEBBS_WEB_BASE_URL` 设置正式前端地址。

- `freebbs_agent/app.py`
  - 增加可视化测试页面路由：
    - `GET /dev/navigation-test`

### 测试页面和脚本

- `freebbs_agent/navigation_dev_page.py`
  - 实现导引 Agent 可视化测试页面。
  - 展示识别结果、置信度、推荐入口卡片和原始 JSON。

- `scripts/generate_navigation_test_page.py`
  - 生成可以独立打开的 HTML 测试页面。

- `scripts/test_navigation_agent.py`
  - 对运行中的 Agent 服务执行多组自然语言冒烟测试。

- `tests/test_navigation_agent.py`
  - 覆盖知识 RAG、公告通知、多意图、模糊输入、流式链接及测试页面接口。

### 文档

- `docs/navigation-agent.md`
  - 记录接口协议、配置方法、测试方式和设计参考。

- `README.md`
  - 增加导引 Agent 调用示例、测试入口和环境变量说明。

## 3. 返回数据示例

请求：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"最近有什么讲座通知？"}'
```

响应结构示例：

```json
{
  "agent": "navigation",
  "intent": "announcement",
  "confidence": 0.8,
  "needs_clarification": false,
  "answer": "我判断你的需求适合前往：公告与通知。点击下面的入口即可继续。",
  "routes": [
    {
      "intent": "announcement",
      "module": "announcements",
      "title": "公告与通知",
      "url": "/notifications?q=最近有什么讲座通知？",
      "reason": "查看课程、考试、作业、讲座、活动和项目通知。",
      "score": 9
    }
  ],
  "model": "deterministic-intent-router-v1",
  "finish_reason": "stop"
}
```

其中：

- `intent`：首要意图；无法确定时为 `clarify`。
- `confidence`：首要意图的启发式置信度。
- `needs_clarification`：是否需要继续询问用户。
- `routes`：推荐入口列表，最多三个。
- `url`：前端可以直接渲染成链接或按钮。

## 4. 配置前端地址

默认返回站内相对路径。如果 Agent 服务和 FREE-BBS 前端使用同一个域名，不需要额外
配置。

如果前端部署在其他地址，启动前设置：

```bash
export FREEBBS_WEB_BASE_URL="https://your-freebbs-domain.example"
```

此时链接会变成：

```text
https://your-freebbs-domain.example/notifications?q=...
```

当前模块路径是按照功能名称设置的默认路径。如果正式前端路由不同，请修改
`freebbs_agent/navigation_agent.py` 中 `TARGETS` 对应项目的 `path`。

## 5. 测试方法

### 5.1 启动服务

在项目根目录运行：

```bash
.venv/bin/python app.py
```

如果使用其他虚拟环境，也可以运行：

```bash
python app.py
```

默认服务地址：

```text
http://127.0.0.1:5001
```

先检查健康状态：

```bash
curl http://127.0.0.1:5001/health
```

### 5.2 使用可视化测试页面

服务启动后，在浏览器访问：

```text
http://127.0.0.1:5001/dev/navigation-test
```

在输入框中输入需求并点击“帮我导引”。页面会显示：

- Agent 的判断结果。
- 意图置信度。
- 推荐模块卡片。
- 可点击跳转链接。
- 完整原始 JSON。

页面也提供公告通知、课程讨论、PBL 项目和学习印记等快捷样例。

### 5.3 使用 curl 测试

知识资料：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"帮我找信号与系统的课程资料和讲义"}'
```

公告通知：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"最近有什么讲座通知，报名什么时候截止？"}'
```

多意图：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"这道习题不会做，我想找资料再去讨论区请教同学"}'
```

模糊输入：

```bash
curl -X POST http://127.0.0.1:5001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"navigation","message":"帮帮我"}'
```

### 5.4 运行实时接口冒烟测试

先启动服务，然后在另一个终端运行：

```bash
.venv/bin/python scripts/test_navigation_agent.py
```

指定其他端口：

```bash
.venv/bin/python scripts/test_navigation_agent.py \
  --base-url http://127.0.0.1:5002
```

### 5.5 生成独立测试页面

运行：

```bash
.venv/bin/python scripts/generate_navigation_test_page.py
```

默认生成：

```text
data/navigation_agent_test.html
```

指定输出位置和 Agent 地址：

```bash
.venv/bin/python scripts/generate_navigation_test_page.py \
  --output /tmp/navigation-test.html \
  --api-base-url http://127.0.0.1:5002
```

独立 HTML 页面仍然需要已经启动的 Agent 服务。

### 5.6 运行自动化测试

只测试导引 Agent：

```bash
.venv/bin/python -m unittest tests.test_navigation_agent -v
```

运行完整测试套件：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

本次开发完成时，完整测试结果为：

```text
Ran 24 tests
OK
```

还可以运行 Python 编译检查：

```bash
.venv/bin/python -m compileall -q freebbs_agent scripts tests
```

## 6. 后续扩展建议

目前采用确定性的加权触发词方案，优点是无模型成本、响应快、结果可解释，适合当前模块
数量较少的阶段。

积累真实用户查询和人工标注意图后，可以进一步：

1. 用 embedding 相似度或分类模型替换 `_rank_targets`。
2. 把模块定义和关键词迁移到 JSON/YAML 配置文件。
3. 从前端或模块注册中心动态读取真实路由。
4. 记录匿名化的路由选择与用户点击结果，用于评估 Top-1、Top-3 命中率。
5. 对低置信度输入调用 LLM 分类器，同时保留当前确定性规则作为回退。
