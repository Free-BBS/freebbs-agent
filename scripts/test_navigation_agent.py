#!/usr/bin/env python3
"""Run smoke-test utterances against a live FREE-BBS navigation agent."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CASES = (
    "我想找信号与系统的课程资料",
    "最近有什么讲座和课程通知？",
    "这道傅里叶变换习题卡住了，想去讨论区请教同学",
    "我想找一个 FPGA 项目和队友",
    "帮我看看自己的学习进度和薄弱点",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    args = parser.parse_args()
    endpoint = f"{args.base_url.rstrip('/')}/api/v1/chat"

    for message in CASES:
        body = json.dumps({"agent": "navigation", "message": message}).encode()
        request = Request(endpoint, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
        except (HTTPError, URLError) as exc:
            raise SystemExit(f"Request failed: {exc}") from exc
        targets = ", ".join(route["module"] for route in result["routes"])
        print(f"[{result['intent']:<18}] {message} -> {targets}")


if __name__ == "__main__":
    main()
