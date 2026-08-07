from html import escape


DEV_AGENT_TEST_HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FREE-BBS Agent Test</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f7f7f4;
        --panel: #ffffff;
        --line: #d8d8d1;
        --text: #20211f;
        --muted: #6f726b;
        --accent: #16675a;
        --accent-strong: #0f4e44;
        --danger: #9d2f22;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        background: var(--bg);
        color: var(--text);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      main {
        width: min(1120px, calc(100vw - 32px));
        margin: 24px auto;
        display: grid;
        grid-template-columns: 380px 1fr;
        gap: 16px;
      }

      h1 {
        margin: 0 0 4px;
        font-size: 24px;
        line-height: 1.2;
      }

      p {
        margin: 0;
      }

      .header {
        grid-column: 1 / -1;
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 16px;
        padding: 6px 0 2px;
      }

      .subtle {
        color: var(--muted);
        font-size: 13px;
      }

      .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 16px;
      }

      .form-grid {
        display: grid;
        gap: 12px;
      }

      label {
        display: grid;
        gap: 6px;
        color: var(--muted);
        font-size: 13px;
        font-weight: 600;
      }

      input,
      textarea,
      select {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 9px 10px;
        color: var(--text);
        background: #fff;
        font: inherit;
        font-size: 14px;
      }

      textarea {
        min-height: 132px;
        resize: vertical;
        line-height: 1.45;
      }

      .row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
      }

      .check-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }

      .check-row label {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--text);
      }

      .check-row input {
        width: auto;
      }

      button {
        border: 0;
        border-radius: 6px;
        padding: 10px 12px;
        color: #fff;
        background: var(--accent);
        font: inherit;
        font-weight: 700;
        cursor: pointer;
      }

      button:hover {
        background: var(--accent-strong);
      }

      button:disabled {
        cursor: not-allowed;
        opacity: 0.6;
      }

      .secondary {
        color: var(--text);
        background: #ecece6;
      }

      .secondary:hover {
        background: #dfdfd8;
      }

      .actions {
        display: flex;
        gap: 8px;
      }

      .output {
        min-height: 520px;
        display: grid;
        grid-template-rows: auto 1fr auto;
        gap: 12px;
      }

      .output-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }

      .status {
        min-height: 18px;
        color: var(--muted);
        font-size: 13px;
      }

      .status.error {
        color: var(--danger);
      }

      pre {
        margin: 0;
        min-height: 360px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 12px;
        background: #fbfbf8;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 13px;
        line-height: 1.5;
      }

      @media (max-width: 860px) {
        main {
          grid-template-columns: 1fr;
        }

        .header {
          align-items: flex-start;
          flex-direction: column;
        }
      }
    </style>
  </head>
  <body>
    <main>
      <header class="header">
        <div>
          <h1>Agent Test</h1>
          <p class="subtle">本地开发页，直接调用 <code>/api/v1/chat</code>。</p>
        </div>
        <p class="subtle" id="endpoint"></p>
      </header>

      <section class="panel">
        <form class="form-grid" id="agent-form">
          <label>
            Agent
            <input id="agent" value="general_chat" placeholder="general_chat / comment_mention" />
          </label>

          <div class="row">
            <label>
              Source
              <input id="source" value="direct_chat" placeholder="direct_chat" />
            </label>
            <label>
              Channel
              <input id="channel" value="dev_agent_test" placeholder="dev_agent_test" />
            </label>
          </div>

          <div class="row">
            <label>
              Temperature
              <input id="temperature" type="number" min="0" max="2" step="0.1" value="0.6" />
            </label>
            <label>
              Max tokens
              <input id="max-tokens" type="number" min="1" step="1" placeholder="可选" />
            </label>
          </div>

          <label>
            Message
            <textarea id="message" required>解释一下傅里叶变换在电子信息知识体系里的位置。</textarea>
          </label>

          <label>
            Context JSON
            <textarea id="context" placeholder='{"thread_id":123}'></textarea>
          </label>

          <div class="check-row">
            <label>
              <input id="stream" type="checkbox" checked />
              Stream
            </label>
            <div class="actions">
              <button class="secondary" id="clear" type="button">清空</button>
              <button id="submit" type="submit">发送</button>
            </div>
          </div>
        </form>
      </section>

      <section class="panel output">
        <div class="output-head">
          <div>
            <h1>Response</h1>
            <p class="status" id="status"></p>
          </div>
        </div>
        <pre id="response"></pre>
        <details>
          <summary>Request payload</summary>
          <pre id="request-preview"></pre>
        </details>
      </section>
    </main>

    <script>
      const endpoint = `${window.location.origin}/api/v1/chat`;
      document.getElementById("endpoint").textContent = endpoint;

      const form = document.getElementById("agent-form");
      const responseBox = document.getElementById("response");
      const requestPreview = document.getElementById("request-preview");
      const statusEl = document.getElementById("status");
      const submitButton = document.getElementById("submit");
      const clearButton = document.getElementById("clear");

      const query = new URLSearchParams(window.location.search);
      const presets = {
        agent: "agent",
        source: "source",
        channel: "channel",
        message: "message"
      };
      for (const [parameter, elementId] of Object.entries(presets)) {
        const value = query.get(parameter);
        if (value !== null) {
          document.getElementById(elementId).value = value;
        }
      }
      if (query.get("stream") === "false") {
        document.getElementById("stream").checked = false;
      }

      function readPayload() {
        const payload = {
          agent: document.getElementById("agent").value.trim() || undefined,
          source: document.getElementById("source").value.trim() || undefined,
          channel: document.getElementById("channel").value.trim() || undefined,
          message: document.getElementById("message").value.trim(),
          stream: document.getElementById("stream").checked
        };

        const temperature = document.getElementById("temperature").value;
        if (temperature !== "") {
          payload.temperature = Number(temperature);
        }

        const maxTokens = document.getElementById("max-tokens").value;
        if (maxTokens !== "") {
          payload.max_tokens = Number(maxTokens);
        }

        const contextText = document.getElementById("context").value.trim();
        if (contextText) {
          payload.context = JSON.parse(contextText);
        }

        Object.keys(payload).forEach((key) => {
          if (payload[key] === undefined) {
            delete payload[key];
          }
        });
        return payload;
      }

      function setStatus(message, isError = false) {
        statusEl.textContent = message || "";
        statusEl.classList.toggle("error", Boolean(isError));
      }

      function parseSseEvents(buffer) {
        const events = buffer.split("\\n\\n");
        return { complete: events.slice(0, -1), rest: events.at(-1) || "" };
      }

      async function sendRequest(payload) {
        responseBox.textContent = "";
        requestPreview.textContent = JSON.stringify(payload, null, 2);
        setStatus("请求中...");
        submitButton.disabled = true;

        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });

          if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.error?.message || errorPayload.message || `HTTP ${response.status}`);
          }

          if (!payload.stream) {
            const result = await response.json();
            responseBox.textContent = JSON.stringify(result, null, 2);
            setStatus("完成");
            return;
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
            const parsed = parseSseEvents(buffer);
            buffer = parsed.rest;

            for (const eventText of parsed.complete) {
              const dataLine = eventText.split("\\n").find((line) => line.startsWith("data:"));
              if (!dataLine) {
                continue;
              }

              const eventPayload = JSON.parse(dataLine.replace(/^data:\\s*/, ""));
              if (eventPayload.error) {
                throw new Error(eventPayload.error.message || "Agent error");
              }
              if (eventPayload.delta) {
                responseBox.textContent += eventPayload.delta;
              }
              if (eventPayload.done) {
                setStatus("完成");
              }
            }

            if (done) {
              break;
            }
          }
        } catch (error) {
          setStatus(error.message, true);
        } finally {
          submitButton.disabled = false;
        }
      }

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        try {
          sendRequest(readPayload());
        } catch (error) {
          setStatus(error.message, true);
        }
      });

      clearButton.addEventListener("click", () => {
        responseBox.textContent = "";
        requestPreview.textContent = "";
        setStatus("");
      });
    </script>
  </body>
</html>
"""


def build_scenario_test_page(
    *,
    title: str,
    description: str,
    agent: str,
    source: str,
    default_message: str,
) -> str:
    """Build a dedicated visual test page with a fixed scenario identity."""

    safe_title = escape(title)
    safe_description = escape(description)
    page = DEV_AGENT_TEST_HTML
    page = page.replace("<title>FREE-BBS Agent Test</title>", f"<title>{safe_title}</title>")
    page = page.replace("<h1>Agent Test</h1>", f"<h1>{safe_title}</h1>")
    page = page.replace(
        "本地开发页，直接调用 <code>/api/v1/chat</code>。",
        f"{safe_description}，直接调用 <code>/api/v1/chat</code>。",
    )
    page = page.replace(
        '<label>\n            Agent\n            <input id="agent" value="general_chat" placeholder="general_chat / comment_mention" />\n          </label>',
        '<input id="agent" type="hidden" value="' + escape(agent, quote=True) + '" />',
    )
    page = page.replace(
        '<input id="source" value="direct_chat" placeholder="direct_chat" />',
        '<input id="source" value="' + escape(source, quote=True) + '" readonly />',
    )
    page = page.replace(
        "解释一下傅里叶变换在电子信息知识体系里的位置。",
        escape(default_message),
    )
    return page
