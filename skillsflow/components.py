"""What a plugin runs without Claude choosing to: hooks, MCP and LSP servers, monitors, mods
and bin/ executables, read from the files and manifest keys Claude Code loads them from.

The commands are listed so a person can read exactly what will run before installing.
"""

from __future__ import annotations

import json
import logging
import posixpath
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ENTRIES = 50
MAX_TEXT = 500
ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"


def _text(value) -> str:
    return str(value)[:MAX_TEXT]


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _rel_path(raw: str) -> str | None:
    """A plugin-root-relative path, or None if it leaves the root."""
    p = raw.strip().replace(ROOT_VAR, ".").strip('"')
    if p.startswith("/") or "\\" in p:
        return None
    p = posixpath.normpath(p)
    if p == ".." or p.startswith("../"):
        return None
    return p


def _load(root: Path, rel: str) -> object | None:
    path = root / rel
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None


def _sources(root: Path, default: str | None, *declared, replaces_default: bool = False):
    """(data, file) pairs: the default file if present, then each manifest or entry value,
    which is an inline object, a path to a JSON file, or a list of those."""
    pairs = []
    has_declared = any(d is not None for d in declared)
    if default and not (replaces_default and has_declared):
        data = _load(root, default)
        if data is not None:
            pairs.append((data, default))
    for value in declared:
        for item in _as_list(value):
            if isinstance(item, str):
                rel = _rel_path(item)
                data = _load(root, rel) if rel else None
                if data is not None:
                    pairs.append((data, rel))
            elif isinstance(item, (dict, list)):
                pairs.append((item, ".claude-plugin/plugin.json"))
    return pairs


def _command_line(spec: dict) -> str:
    parts = [str(spec.get("command") or "")] + [str(a) for a in _as_list(spec.get("args"))]
    return _text(" ".join(p for p in parts if p))


def _hooks(root: Path, manifest: dict, entry: dict) -> tuple[list[dict], list[dict]]:
    hooks, mods = [], []
    for data, file in _sources(root, "hooks/hooks.json", manifest.get("hooks"), entry.get("hooks")):
        if not isinstance(data, dict):
            continue
        for module in _as_list(data.get("modules")):
            mods.append({"module": _text(module if isinstance(module, str) else json.dumps(module)), "file": file})
        events = data["hooks"] if isinstance(data.get("hooks"), dict) else data
        for event, groups in events.items():
            if event == "modules" or not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for hook in _as_list(group.get("hooks")):
                    if not isinstance(hook, dict):
                        continue
                    kind = str(hook.get("type") or "command")
                    if kind == "command":
                        action = _command_line(hook)
                    else:
                        action = _text(hook.get("url") or hook.get("prompt") or hook.get("tool")
                                       or hook.get("agent") or json.dumps(hook))
                    hooks.append({"event": str(event), "matcher": group.get("matcher"), "type": kind,
                                  "command": action, "file": file})
    return hooks[:MAX_ENTRIES], mods[:MAX_ENTRIES]


def _servers(pairs, wrapper: str | None) -> list[dict]:
    servers = []
    for data, file in pairs:
        if not isinstance(data, dict):
            continue
        table = data[wrapper] if wrapper and isinstance(data.get(wrapper), dict) else data
        for name, spec in table.items():
            if not isinstance(spec, dict):
                continue
            url = spec.get("url")
            kind = spec.get("type") or ("http" if url else "stdio")
            servers.append({"name": str(name), "type": str(kind),
                            "command": _text(url) if url else _command_line(spec),
                            "env": sorted(str(k) for k in (spec.get("env") or {})),
                            "file": file})
    return servers[:MAX_ENTRIES]


def _monitors(root: Path, manifest: dict) -> list[dict]:
    declared = (manifest.get("experimental") or {}).get("monitors")
    if declared is None:
        declared = manifest.get("monitors")
    monitors = []
    for data, file in _sources(root, "monitors/monitors.json", declared, replaces_default=True):
        for spec in _as_list(data):
            if isinstance(spec, dict):
                monitors.append({"name": str(spec.get("name") or ""), "command": _command_line(spec), "file": file})
    return monitors[:MAX_ENTRIES]


def automatic(root: Path, manifest: dict | None, entry: dict) -> dict:
    """Everything the plugin starts on its own once it is enabled."""
    m = manifest or {}
    hooks, mods = _hooks(root, m, entry)
    bin_dir = root / "bin"
    return {
        "hooks": hooks,
        "mcp_servers": _servers(_sources(root, ".mcp.json", m.get("mcpServers"), entry.get("mcpServers")), "mcpServers"),
        "lsp_servers": _servers(_sources(root, ".lsp.json", m.get("lspServers"), entry.get("lspServers")), None),
        "monitors": _monitors(root, m),
        "mods": mods,
        "bin": sorted(p.name for p in bin_dir.iterdir() if p.is_file())[:MAX_ENTRIES] if bin_dir.is_dir() else [],
    }
