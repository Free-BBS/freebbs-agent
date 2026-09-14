"""Native controls for the models offered by the web application's selector."""
import base64
import json
from pathlib import Path

PROFILES = {item["id"]: item for item in json.loads(Path(__file__).with_name("model_catalog.json").read_text())}
import re


def reasoning_options(model, effort):
    profile = PROFILES.get(model)
    if not profile:
        if effort not in (None, "auto"):
            raise ValueError("Selected model does not support this reasoning effort")
        return {}
    # Preserve legacy payloads unless a policy or user choice requires native options.
    if effort is None and model != "glm-5.2":
        return {}
    effort = effort or profile["defaultEffort"]
    if effort not in profile["efforts"]:
        raise ValueError("Selected model does not support this reasoning effort")
    kind = profile["kind"]
    if kind in ("provider", "fixed"):
        return {}
    if kind == "minimax":
        return {"extra_body": {"reasoning_split": True}}
    if kind == "qwen":
        return {"extra_body": {"enable_thinking": effort != "off"}}
    result = {"thinking": {"type": "disabled" if effort == "off" else "enabled"}}
    if kind in ("glm_effort", "deepseek") and effort != "off":
        result["reasoning_effort"] = effort
    return {"extra_body": result}


def validate_images(images):
    if images is None:
        return []
    if not isinstance(images, list) or len(images) > 13:
        raise ValueError("vision_images must contain at most thirteen images")
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("label"), str) or len(image["label"]) > 120:
            raise ValueError("Invalid image label")
        url = image.get("dataUrl")
        if not isinstance(url, str) or len(url) > 1400000 or not re.fullmatch(
                r"data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}", url):
            raise ValueError("Invalid image data URL")
        try:
            base64.b64decode(url.split(",", 1)[1], validate=True)
        except ValueError:
            raise ValueError("Invalid image encoding") from None
    return images


def with_images(messages, images, model):
    if not images:
        return messages
    if not PROFILES.get(model, {}).get("vision"):
        raise ValueError("Selected model does not support image input")
    result = [dict(message) for message in messages]
    for message in reversed(result):
        if message["role"] == "user":
            content = [{"type": "text", "text": message["content"]}]
            for image in images:
                content.extend([{"type": "text", "text": image["label"]},
                                {"type": "image_url", "image_url": {"url": image["dataUrl"]}}])
            message["content"] = content
            return result
    raise ValueError("Image input requires a user message")
