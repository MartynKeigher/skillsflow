import json

from skillsflow.components import automatic
from conftest import write


def test_manifest_values_inline_paths_and_lists(tmp_path):
    write(tmp_path, "config/hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "http", "url": "https://example.com/hook"}]}]}}))
    write(tmp_path, "servers.json", json.dumps({"remote": {"type": "http", "url": "https://mcp.example.com"}}))
    manifest = {
        "hooks": ["./config/hooks.json",
                  {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "check", "args": ["--strict"]}]}]}],
        "mcpServers": "${CLAUDE_PLUGIN_ROOT}/servers.json",
        "lspServers": {"gopls": {"command": "gopls", "args": ["serve"]}},
    }
    auto = automatic(tmp_path, manifest, {})
    assert [(h["event"], h["type"], h["command"], h["file"]) for h in auto["hooks"]] == [
        ("Stop", "http", "https://example.com/hook", "config/hooks.json"),
        ("PreToolUse", "command", "check --strict", ".claude-plugin/plugin.json"),
    ]
    assert auto["mcp_servers"] == [{"name": "remote", "type": "http", "command": "https://mcp.example.com",
                                    "env": [], "file": "servers.json"}]
    assert auto["lsp_servers"][0]["command"] == "gopls serve"


def test_flat_mcp_file_and_entry_level_servers(tmp_path):
    write(tmp_path, ".mcp.json", json.dumps({"flat": {"command": "uvx", "args": ["thing"]}}))
    auto = automatic(tmp_path, None, {"mcpServers": {"entry": {"command": "npx", "args": ["-y", "pkg"]}}})
    assert [(s["name"], s["command"]) for s in auto["mcp_servers"]] == [("flat", "uvx thing"), ("entry", "npx -y pkg")]


def test_monitors_manifest_key_replaces_the_default_file(tmp_path):
    write(tmp_path, "monitors/monitors.json", json.dumps([{"name": "default", "command": "tail -F a.log"}]))
    assert [m["name"] for m in automatic(tmp_path, None, {})["monitors"]] == ["default"]
    manifest = {"experimental": {"monitors": [{"name": "inline", "command": "./poll.sh"}]}}
    assert [m["name"] for m in automatic(tmp_path, manifest, {})["monitors"]] == ["inline"]


def test_paths_outside_the_plugin_are_ignored(tmp_path):
    write(tmp_path.parent, "outside.json", json.dumps({"x": {"command": "evil"}}))
    auto = automatic(tmp_path, {"mcpServers": "../outside.json", "hooks": "/etc/hooks.json"}, {})
    assert auto["mcp_servers"] == [] and auto["hooks"] == []


def test_broken_json_is_skipped(tmp_path):
    write(tmp_path, ".mcp.json", "{not json")
    assert automatic(tmp_path, None, {})["mcp_servers"] == []
