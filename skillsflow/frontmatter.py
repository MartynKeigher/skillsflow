"""Parse the YAML frontmatter at the top of a SKILL.md file."""

from __future__ import annotations

import yaml


def parse(text: str) -> tuple[dict, str]:
    """Return (fields, body).

    Mirrors Claude Code: frontmatter counts only when the first line is `---`,
    and YAML that fails to parse yields no fields rather than an error.
    """
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError:
                return {}, body
            return (data if isinstance(data, dict) else {}), body
    return {}, text


def first_line(body: str) -> str:
    """First non-empty line of the body, used when `description` is missing."""
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""
