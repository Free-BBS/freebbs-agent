#!/usr/bin/env python3
"""Generate a standalone HTML page for manually testing NavigationAgent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from freebbs_agent.navigation_dev_page import build_navigation_test_page  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "navigation_agent_test.html",
        help="Generated HTML path.",
    )
    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:5001",
        help="Agent service origin embedded in the standalone page.",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_navigation_test_page(args.api_base_url), encoding="utf-8")
    print(f"Generated: {args.output}")


if __name__ == "__main__":
    main()
