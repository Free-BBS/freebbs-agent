# 在 FREE-BBS“问问 Max”中接入 Navigation Agent

本文说明如何把 `freebbs-agent` 的 `NavigationAgent` 接入真实主站
[`Free-BBS/freebbs-web`](https://github.com/Free-BBS/freebbs-web) 的“问问 Max”页面。

本文基于以下本地仓库：

```text
/home/jl2004/freebbs-agent
/home/jl2004/freebbs-web
/home/jl2004/subagent-eeinfo
```

目标不是把 Navigation 的测试页嵌入主站，而是让真实的 `/aichat` 页面完成如下流程：

```text
浏览器 /aichat
  -> freebbs-web POST /api/ai/chat
  -> freebbs-agent POST /api/v1/chat (agent=navigation)
  -> NavigationAgent 判断意图
  -> 页面展示回答和真实模块跳转按钮
  -> 可选：NavigationAgent 继续调用 RAG 或 Info
```

## 1. 当前实现与问题

真实主站的关键文件是：

```text
freebbs-web/public/aichat.html       “问问 Max”页面结构
freebbs-web/public/app.js           对话交互和 SSE 解析
freebbs-web/backend/server.js       /api/ai/chat 代理
freebbs-web/backend/config.js       AGENT_URL 配置
freebbs-web/server.js               主站页面路由
```

当前 `/aichat` 构造的请求固定使用：

```json
{
  "agent": "general_chat",
  "source": "direct_chat",
  "channel": "aichat"
}
```

后端虽然会把请求转发到 `freebbs-agent`，但存在三个缺口：

1. “问问 Max”没有调用 `navigation`。
2. 前端只消费 SSE 文本增量，无法取得 Navigation 的结构化 `routes`。
3. 后端没有为 Info Agent 注入可信身份请求头。

因此推荐先使用非流式 Navigation 请求完成意图识别和按钮渲染，再按需增加流式体验。

## 2. 使用真实主站路由

`freebbs-agent/freebbs_agent/navigation_agent.py` 中的生产路径必须与
`freebbs-web/server.js` 的 `pageRoutes` 保持一致。

推荐映射：

| Navigation intent | module | 主站页面 |
|---|---|---|
| `knowledge_search` | `knowledge_rag` | `/knowledge` |
| `announcement` | `announcements` | `/workbench` |
| `course_discussion` | `course_discussion` | `/discussion` |
| `course_graph` | `course_graph` | `/course` |
| `project` | `pbl` | `/development` |
| `learning_profile` | `learning_profile` | `/profile` |

不要继续使用以下不存在的主站路径：

```text
/knowledge/rag
/notifications
/discussions
/courses
/projects
/profile/learning
```

生产运行时设置：

```dotenv
FREEBBS_WEB_BASE_URL=http://127.0.0.1:3000
```

生产环境应改为：

```dotenv
FREEBBS_WEB_BASE_URL=https://www.free-bbs.cn
```

如果主站与 Agent 返回同域相对链接，也可以保持为空，但此时必须确保 Agent 返回的
`path` 本身就是上述真实路径。

## 3. 把“问问 Max”默认 Agent 改为 Navigation

修改 `freebbs-web/public/app.js` 的 `buildAiChatPayload()`。

当前逻辑中的：

```js
agent: 'general_chat',
```

改为：

```js
agent: 'navigation',
execute_subagent: 'none',
```

建议一期完整请求为：

```js
function buildAiChatPayload(userMessage) {
  const recentMessages = aiChatState.messages.slice(-13);

  return {
    agent: 'navigation',
    execute_subagent: 'none',
    source: 'direct_chat',
    channel: 'aichat',
    did: aiChatState.currentDid || '',
    messages: [
      ...recentMessages,
      { role: 'user', content: userMessage },
    ],
    stream: false,
  };
}
```

`messages` 必须保留，因为 Navigation 会用历史 user 消息处理澄清和指代。

一期先设置 `stream: false`。当前 Agent 的 SSE 协议只传输字符：

```text
data: {"delta":"..."}
data: {"done":true}
```

它不会在流式响应中传输 `routes`、`intent` 和 `delegation`，因此流式模式无法渲染按钮。

## 4. 主站后端保留客户端选择的 Agent

`freebbs-web/backend/server.js` 的 `/api/ai/chat` 已通过
`buildAgentChatPayload()` 保留 `payload.agent`，所以浏览器发送 `navigation` 后通常不需要
重写该字段。

建议增加白名单，避免客户端指定任意未知 Agent：

```js
const WEB_ALLOWED_AGENTS = new Set([
  'navigation',
  'general_chat',
  'rag',
  'info',
  'comment_mention',
]);

function normalizeWebAgent(value) {
  const agent = String(value || 'navigation').trim();
  return WEB_ALLOWED_AGENTS.has(agent) ? agent : 'navigation';
}
```

然后在 `buildAgentChatPayload()` 中使用：

```js
agent: normalizeWebAgent(payload.agent || defaults.agent),
```

同时只允许：

```js
const mode = ['none', 'auto', 'rag', 'info'].includes(payload.execute_subagent)
  ? payload.execute_subagent
  : 'none';
```

## 5. 前端改为解析 Navigation JSON

在 `freebbs-web/public/app.js` 新增一个非流式请求函数：

```js
async function requestNavigation(payload) {
  const response = await fetch(`${API_BASE_URL}/ai/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(userState.token ? { Authorization: `Bearer ${userState.token}` } : {}),
    },
    body: JSON.stringify({ ...payload, stream: false }),
  });

  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.error?.message || result.message || 'Navigation 请求失败');
  }
  return result;
}
```

提交消息后执行：

```js
const result = await requestNavigation(buildAiChatPayload(userMessage));
updateAiChatMessage(assistantArticle, result.answer || '没有取得回答。');
renderNavigationRoutes(assistantArticle, result.routes || []);
```

## 6. 在 Max 回复下方渲染跳转按钮

在 `freebbs-web/public/app.js` 增加：

```js
function isAllowedNavigationUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    const allowedPaths = new Set([
      '/knowledge',
      '/workbench',
      '/discussion',
      '/course',
      '/development',
      '/profile',
    ]);
    return url.origin === window.location.origin && allowedPaths.has(url.pathname);
  } catch {
    return false;
  }
}

function renderNavigationRoutes(article, routes) {
  const bubble = article?.querySelector('.aichat-bubble');
  if (!bubble || !Array.isArray(routes)) return;

  const validRoutes = routes.filter(
    (route) => route && isAllowedNavigationUrl(route.url),
  );
  if (!validRoutes.length) return;

  const actions = document.createElement('nav');
  actions.className = 'aichat-navigation-actions';
  actions.setAttribute('aria-label', 'Max 推荐入口');

  for (const route of validRoutes.slice(0, 3)) {
    const link = document.createElement('a');
    link.className = 'aichat-navigation-action';
    link.href = route.url;
    link.textContent = route.title || '打开推荐页面';
    actions.append(link);
  }

  bubble.append(actions);
}
```

必须在前端再次校验路径。不要把 Agent 或 LLM 返回的任意 URL 直接插入 `href`。
Agent 当前使用服务端目标白名单，前端白名单是第二层防护。

可在主站样式中增加：

```css
.aichat-navigation-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 1rem;
}

.aichat-navigation-action {
  display: inline-flex;
  align-items: center;
  padding: 0.65rem 0.9rem;
  border: 1px solid currentColor;
  border-radius: 0.7rem;
  text-decoration: none;
  font-weight: 600;
}
```

## 7. 是否自动执行子 Agent

建议分两阶段。

### 阶段一：只导航

```json
{
  "agent": "navigation",
  "execute_subagent": "none"
}
```

优点是响应结构稳定，用户通过按钮主动进入模块，最符合“Navigation Agent 是入口导航”的定位。

### 阶段二：允许用户选择“直接帮我查询”

只有用户明确选择时发送：

```json
{
  "agent": "navigation",
  "execute_subagent": "auto"
}
```

当前自动委派规则：

```text
knowledge_search -> rag
announcement     -> info
```

响应中应同时处理：

```json
{
  "answer": "子 Agent 的回答",
  "navigation_answer": "原导航说明",
  "routes": [],
  "delegation": {
    "requested": "auto",
    "selected": "rag",
    "executed": true
  },
  "subagent": {}
}
```

即使完成委派，也应继续显示 `routes` 按钮。

## 8. Info Agent 的可信身份接入

这是主站后端当前缺失的部分。`freebbs-agent` 不信任 JSON 中的 `user` 字段；Info 查询必须由
`freebbs-web` 后端注入可信请求头。

为主站后端增加独立配置：

```dotenv
FREEBBS_AGENT_INTERNAL_TOKEN=<强随机值>
```

Agent 服务使用相同值：

```dotenv
FREEBBS_AGENT_INTERNAL_TOKEN=<同一个值>
```

修改 `postAgentChat()`，让它接收经过 `requireAuth()` 验证的用户：

```js
async function postAgentChat(payload, user) {
  const permissions = [
    'thu_info:read',
    'web_learning:read',
  ];

  return fetch(`${config.agentBaseUrl.replace(/\/$/, '')}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-FreeBBS-Internal-Token': config.freebbsAgentInternalToken,
      'X-FreeBBS-UID': String(user.uid || ''),
      'X-FreeBBS-Student-No': String(user.student_id || ''),
      'X-FreeBBS-Session-ID': String(payload.did || ''),
      'X-FreeBBS-Permissions': permissions.join(','),
    },
    body: JSON.stringify(payload),
  });
}
```

并把调用改为：

```js
const agentResponse = await postAgentChat(agentPayload, user);
```

注意：

- Token 只能存在于主站后端和 Agent 服务环境变量中，不能下发浏览器。
- `uid` 和学号必须来自 `requireAuth()` 得到的数据库用户，不能取自请求 JSON。
- 权限应由主站角色/权限系统映射，示例中的默认只读权限仅适合开发联调。
- 评论区后台调用 `postAgentChat()` 时也应传入真实触发用户，或明确使用受控系统身份。

## 9. RAG 页面当前还需要修正

`freebbs-web/public/course.js` 的知识页 RAG 面板当前发送：

```js
agent: 'general_chat'
```

应改成：

```js
agent: 'rag'
```

并确保 Agent 服务开启：

```dotenv
RAG_ENABLED=true
RAG_INDEX_PATH=data/rag/index.faiss
RAG_METADATA_PATH=data/rag/metadata.jsonl
RAG_LOCAL_MODEL_DIR=data/models/bge-small-zh-v1.5
RAG_LOCAL_FILES_ONLY=true
```

否则 Navigation 按钮虽然能进入 `/knowledge`，课程页里的提问仍然只是普通对话。

## 10. 本地联调启动顺序

### 10.1 启动 Info Sub-Agent（需要 Info 时）

```bash
cd /home/jl2004/subagent-eeinfo
export EEINFO_INTERNAL_TOKEN='<INFO_TOKEN>'
npm run demo
```

地址：`http://127.0.0.1:4310`

### 10.2 启动 Agent

```bash
cd /home/jl2004/freebbs-agent
source .venv/bin/activate
set -a
source .env
set +a

export AGENT_HOST=127.0.0.1
export AGENT_PORT=5001
export FREEBBS_WEB_BASE_URL=http://127.0.0.1:3000
export RAG_ENABLED=true
export INFO_AGENT_ENABLED=true
export INFO_AGENT_BASE_URL=http://127.0.0.1:4310
export INFO_AGENT_INTERNAL_TOKEN='<INFO_TOKEN>'
export FREEBBS_AGENT_INTERNAL_TOKEN='<WEB_TO_AGENT_TOKEN>'

python app.py
```

### 10.3 启动真实主站

`freebbs-web` 声明需要 Node.js 24 或以上，并依赖 MySQL。

```bash
cd /home/jl2004/freebbs-web
cp backend/.env.example backend/.env
```

至少设置：

```dotenv
API_HOST=127.0.0.1
API_PORT=3001
PUBLIC_WEB_URL=http://127.0.0.1:3000
CORS_ORIGIN=http://127.0.0.1:3000
AGENT_URL=http://127.0.0.1:5001
FREEBBS_AGENT_INTERNAL_TOKEN=<WEB_TO_AGENT_TOKEN>
```

初始化或迁移 MySQL 后：

```bash
npm install
npm run start:local
```

打开：

```text
http://127.0.0.1:3000/aichat
```

## 11. 验收用例

### Navigation 按钮

输入：

```text
我想找信号与系统的资料
```

预期：

- 调用 `agent=navigation`；
- 回复下方出现“知识 RAG Agent”按钮；
- 按钮进入 `/knowledge`；
- 不出现 `/knowledge/rag` 的 404。

### 讨论区

输入：

```text
我想去讨论区请教傅里叶变换
```

预期按钮进入 `/discussion`。

### 多轮澄清

第一轮：

```text
我不知道该去哪里
```

第二轮：

```text
我想找课程资料
```

预期第二轮能利用第一轮上下文，并给出 `/knowledge`。

### RAG 委派

使用 `execute_subagent=auto` 输入课程资料问题，预期：

```text
delegation.selected = rag
delegation.executed = true
subagent.agent = rag
```

### Info 委派

登录后查询课程公告，预期后端注入可信身份，不能出现：

```text
trusted_context_missing
```

### 安全回归

- 浏览器在 JSON 中伪造 `uid` 不应改变 Info 查询身份；
- 外部 URL 不应被渲染为 Navigation 按钮；
- 未登录用户继续由主站 `/api/ai/chat` 返回认证错误；
- Agent、Info 和主站内部 Token 不得出现在浏览器网络响应或页面源码中。

## 12. 推荐实施顺序

1. 修正 Navigation 的真实主站路径。
2. 把 `/aichat` 默认 Agent 改为 `navigation`。
3. 使用非流式响应渲染 `answer + routes`。
4. 修正课程页从 `general_chat` 到 `rag`。
5. 增加主站后端到 Agent 的可信身份请求头。
6. 接通 Info 登录和异步任务轮询。
7. 最后再扩展 SSE 协议，使流式响应同时传输结构化 Navigation 元数据。

完成前四步后，“问问 Max”即可作为 Navigation Agent 的真实入口；完成第五、六步后，
Navigation 才能安全地自动委派 Info Agent。
