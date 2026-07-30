from __future__ import annotations

import json


def build_navigation_test_page(api_base_url: str = "") -> str:
    """Build the navigation-agent test page for Flask or a standalone file."""

    endpoint = f"{api_base_url.rstrip('/')}/api/v1/chat" if api_base_url else "/api/v1/chat"
    endpoint_json = json.dumps(endpoint, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FREE-BBS 导引 Agent 测试</title>
  <style>
    :root {{ --ink:#17211d; --muted:#65716b; --paper:#f5f3ec; --card:#fff; --green:#126b52; --line:#d9ddd7; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ width:min(940px,calc(100% - 32px)); margin:48px auto; }}
    header {{ margin-bottom:24px; }}
    h1 {{ margin:0 0 8px; font-size:clamp(28px,5vw,44px); }}
    p {{ color:var(--muted); }}
    form {{ display:flex; gap:10px; padding:10px; background:var(--card); border:1px solid var(--line); border-radius:14px; }}
    input {{ flex:1; min-width:0; border:0; outline:0; padding:12px; font:inherit; font-size:16px; }}
    button {{ border:0; border-radius:9px; padding:0 22px; color:white; background:var(--green); font-weight:700; cursor:pointer; }}
    button:disabled {{ opacity:.55; cursor:wait; }}
    .toolbar {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
    .reset {{ padding:7px 11px; color:var(--green); background:#e5eee9; }}
    .examples {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 28px; }}
    .examples button {{ padding:7px 11px; color:var(--green); background:#e5eee9; font-weight:500; }}
    #conversation {{ display:flex; flex-direction:column; gap:10px; margin:0 0 18px; }}
    .bubble {{ max-width:82%; padding:11px 14px; border-radius:14px; line-height:1.55; white-space:pre-wrap; }}
    .user {{ align-self:flex-end; color:white; background:var(--green); border-bottom-right-radius:4px; }}
    .assistant {{ align-self:flex-start; background:var(--card); border:1px solid var(--line); border-bottom-left-radius:4px; }}
    #status {{ min-height:24px; color:var(--muted); }}
    #routes {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }}
    .route {{ display:block; padding:18px; color:inherit; background:var(--card); border:1px solid var(--line); border-radius:12px; text-decoration:none; }}
    .route:hover {{ border-color:var(--green); transform:translateY(-2px); }}
    .route strong {{ color:var(--green); }}
    .route p {{ margin:8px 0 0; line-height:1.55; }}
    details {{ margin-top:24px; }}
    pre {{ overflow:auto; padding:14px; background:#202722; color:#eaf2ed; border-radius:10px; white-space:pre-wrap; }}
    @media(max-width:560px) {{ form {{ flex-direction:column; }} button {{ min-height:44px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>你想去哪里学习？</h1>
    <div class="toolbar">
      <p>支持连续追问；导引 Agent 会结合本轮会话推荐 1–3 个 FREE-BBS 入口。</p>
      <button id="reset" class="reset" type="button">新会话</button>
    </div>
  </header>
  <section id="conversation" aria-live="polite"></section>
  <form id="form">
    <input id="message" aria-label="需求" value="我想找信号与系统的课程资料" required>
    <button type="submit">帮我导引</button>
  </form>
  <div class="examples">
    <button data-example="最近有什么讲座和课程通知？">公告通知</button>
    <button data-example="傅里叶变换不会做，我想去讨论区请教同学">课程讨论</button>
    <button data-example="我想找一个 FPGA 项目和队友">PBL 项目</button>
    <button data-example="帮我看看自己的学习进度和薄弱点">学习印记</button>
  </div>
  <p id="status">等待输入。</p>
  <section id="routes" aria-live="polite"></section>
  <details><summary>查看原始响应</summary><pre id="raw"></pre></details>
</main>
<script>
  const endpoint = {endpoint_json};
  const history = [];
  const form = document.getElementById("form");
  const message = document.getElementById("message");
  const submit = form.querySelector('button[type="submit"]');
  const reset = document.getElementById("reset");
  const conversation = document.getElementById("conversation");
  const status = document.getElementById("status");
  const routes = document.getElementById("routes");
  const raw = document.getElementById("raw");

  async function navigate() {{
    const content = message.value.trim();
    if (!content || submit.disabled) return;
    history.push({{role:"user", content}});
    addBubble("user", content);
    message.value = "";
    submit.disabled = true;
    status.textContent = "正在判断意图…";
    routes.replaceChildren();
    try {{
      const response = await fetch(endpoint, {{
        method: "POST",
        headers: {{"Content-Type":"application/json"}},
        body: JSON.stringify({{agent:"navigation", messages:history, stream:false}})
      }});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || `HTTP ${{response.status}}`);
      history.push({{role:"assistant", content:data.answer}});
      addBubble("assistant", data.answer);
      const engine = data.llm_used ? `LLM：${{data.model}}` : `规则降级：${{data.llm_status}}`;
      status.textContent = `${{data.answer}}（置信度 ${{Math.round(data.confidence * 100)}}%，${{engine}}）`;
      for (const item of data.routes) {{
        const link = document.createElement("a");
        link.className = "route";
        link.href = item.url;
        link.innerHTML = `<strong>${{escapeHtml(item.title)}} →</strong><p>${{escapeHtml(item.reason)}}</p>`;
        routes.appendChild(link);
      }}
      raw.textContent = JSON.stringify(data, null, 2);
    }} catch (error) {{
      status.textContent = `请求失败：${{error.message}}`;
    }} finally {{
      submit.disabled = false;
      message.focus();
    }}
  }}

  function addBubble(role, content) {{
    const bubble = document.createElement("div");
    bubble.className = `bubble ${{role}}`;
    bubble.textContent = content;
    conversation.appendChild(bubble);
  }}

  function escapeHtml(value) {{
    const node = document.createElement("span");
    node.textContent = value;
    return node.innerHTML;
  }}
  form.addEventListener("submit", event => {{ event.preventDefault(); navigate(); }});
  reset.addEventListener("click", () => {{
    history.length = 0;
    conversation.replaceChildren();
    routes.replaceChildren();
    raw.textContent = "";
    status.textContent = "已开始新会话。";
    message.value = "";
    message.focus();
  }});
  document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click", () => {{
    message.value = button.dataset.example;
    navigate();
  }}));
</script>
</body>
</html>"""


NAVIGATION_AGENT_TEST_HTML = build_navigation_test_page()
