from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .agent_utils import AgentInvocation
from .ai_client import AIClientError


IMAGE_BLOCK = re.compile(
    r"```max-image\s*\n(?P<body>\{[\s\S]*?\})\s*\n```",
    re.IGNORECASE,
)
IMAGE_PLACEHOLDER = "[[MAX_IMAGE_0]]"
MAX_PROMPT_LENGTH = 4000
MAX_ALT_LENGTH = 180
ALLOWED_SIZES = {
    "square": "2048x2048",
    "landscape": "2560x1440",
    "portrait": "1440x2560",
}

IMAGE_TOOL_PROMPT = """
你可以在确有必要时调用一次图片生成工具。它适合概念插画、视觉化场景、海报、封面、设计参考，或用户明确要求生成图片的请求；普通问答、公式推导、代码、电路精确原理图和仅靠文字就能清楚说明的内容不要调用。不得为了装饰回答而生图。

需要生图时，在回答中希望图片出现的位置输出且只输出一个以下格式的工具块：
```max-image
{"prompt":"可直接交给图片模型的完整中文提示词","alt":"简洁准确的图片说明","aspect_ratio":"square"}
```
aspect_ratio 只能是 square、landscape 或 portrait。prompt 必须描述画面本身，不要包含工具指令、Markdown 或占位符。工具块之外照常回答。不要声称图片已经生成；系统会执行工具并替换该块。每次回答最多调用一次。
""".strip()


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    alt: str
    size: str


def _with_tool_prompt(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    adjusted = [message.copy() for message in messages]
    for message in adjusted:
        if message["role"] == "system":
            message["content"] = f"{message['content']}\n\n{IMAGE_TOOL_PROMPT}"
            return adjusted
    return [{"role": "system", "content": IMAGE_TOOL_PROMPT}, *adjusted]


def parse_image_request(answer: str) -> tuple[str, ImageRequest | None]:
    matches = list(IMAGE_BLOCK.finditer(answer or ""))
    if len(matches) != 1:
        return answer, None
    match = matches[0]
    try:
        payload = json.loads(match.group("body"))
    except json.JSONDecodeError:
        return answer, None
    if not isinstance(payload, dict) or set(payload) != {"prompt", "alt", "aspect_ratio"}:
        return answer, None
    prompt = payload.get("prompt")
    alt = payload.get("alt")
    aspect_ratio = payload.get("aspect_ratio")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt) > MAX_PROMPT_LENGTH
        or not isinstance(alt, str)
        or not alt.strip()
        or len(alt) > MAX_ALT_LENGTH
        or aspect_ratio not in ALLOWED_SIZES
    ):
        return answer, None
    cleaned = f"{answer[:match.start()]}{IMAGE_PLACEHOLDER}{answer[match.end():]}"
    return cleaned, ImageRequest(prompt.strip(), alt.strip(), ALLOWED_SIZES[aspect_ratio])


def run_with_optional_image(agent, invocation: AgentInvocation, messages) -> dict[str, Any]:
    allowed = (
        invocation.payload.get("allow_image_generation") is True
        and agent.config.image_generation_enabled
        and (
            not invocation.options.stream
            or invocation.payload.get("reasoning_stream") is True
        )
    )
    result = agent.call_llm(
        _with_tool_prompt(messages) if allowed else messages,
        invocation.options,
    )
    if not allowed:
        return result

    answer = str(result.get("answer") or "")
    replaced, request = parse_image_request(answer)
    if request is None:
        return result

    try:
        image = agent.chat_client.generate_image(request.prompt, size=request.size)
    except AIClientError:
        result["answer"] = IMAGE_BLOCK.sub(
            "\n\n> 图片生成暂时不可用，请稍后再试。\n\n", answer, count=1
        ).strip()
        result["image_generation"] = {"status": "failed"}
        return result

    result["answer"] = replaced.strip()
    result["generated_images"] = [
        {
            "placeholder": IMAGE_PLACEHOLDER,
            "alt": request.alt,
            "dataUrl": image["data_url"],
            "model": image["model"],
        }
    ]
    result["image_generation"] = {"status": "completed", "model": image["model"]}
    return result
