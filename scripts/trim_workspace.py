#!/usr/bin/env python3
"""Trim upstream Aya workspace metadata for AppOpt Aya Lite."""

from __future__ import annotations

import re
import sys
from pathlib import Path


MEMBERS = '''members = [
    "aya",
    "aya-obj",
]
'''


def replace_array_assignment(text: str, key: str, replacement: str) -> str:
    pattern = re.compile(rf"(?ms)^{re.escape(key)}\s*=\s*\[.*?\]\s*")
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"没有在 Cargo.toml 中找到 {key} 数组")
    return text


def remove_array_assignment(text: str, key: str) -> str:
    pattern = re.compile(rf"(?ms)^{re.escape(key)}\s*=\s*\[.*?\]\s*")
    return pattern.sub("", text)


def main() -> int:
    if len(sys.argv) != 3:
        print("用法: trim_workspace.py <upstream Cargo.toml> <output Cargo.toml>", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    text = source.read_text(encoding="utf-8")

    if "[workspace]" not in text:
        raise SystemExit("上游 Cargo.toml 缺少 [workspace]")

    text = replace_array_assignment(text, "members", MEMBERS)
    text = remove_array_assignment(text, "default-members")
    text = text.replace('repository = "https://github.com/aya-rs/aya"', 'repository = "https://github.com/cinitdev/AppOpt-aya-lite"')

    output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

