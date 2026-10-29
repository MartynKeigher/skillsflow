"""Heuristic security scan of a skill or plugin directory.

Skills are not reviewed before publication, and they can ship scripts that Claude
runs. This scan does not prove a skill safe; it surfaces what a person should look
at before installing.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

SCRIPT_EXTENSIONS = {
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".go", ".rs",
    ".swift", ".applescript", ".scpt", ".lua",
}
BINARY_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bin", ".app", ".pkg", ".dmg", ".jar", ".wasm", ".node"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl", ".mcpb", ".dxt"}
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".bmp", ".tiff", ".svg",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".pdf", ".mp3", ".wav", ".mp4", ".mov",
    ".docx", ".xlsx", ".pptx", ".xsd",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_SCAN_BYTES = 512 * 1024
MAX_FINDINGS_PER_RULE = 5
COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", ";", "rem ", "REM ")
DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    summary: str
    pattern: re.Pattern


def _r(id: str, severity: str, summary: str, pattern: str) -> Rule:
    return Rule(id, severity, summary, re.compile(pattern, re.IGNORECASE))


RULES = [
    _r("pipe-to-shell", "high", "Downloads code and pipes it straight into a shell",
       r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b|\biex\b.*\b(iwr|Invoke-WebRequest)\b|\b(iwr|Invoke-WebRequest)\b.*\|\s*iex\b"),
    _r("destructive-delete", "high", "Recursively deletes the home or root directory",
       r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(--no-preserve-root\s+)?(/|~|\$HOME|\"\$HOME\")(\s|$|/\*)"),
    _r("persistence", "high", "Modifies startup files or schedules itself to run",
       r"\bcrontab\b|\blaunchctl\s+(load|bootstrap)\b|LaunchAgents|LaunchDaemons|>>?\s*[\"']?(~|\$HOME|\$\{HOME\})/\.(bashrc|zshrc|bash_profile|profile|zprofile)\b|\bsystemctl\s+enable\b|Startup\\\\|CurrentVersion\\\\Run"),
    _r("credential-access", "high", "Reads SSH keys, cloud credentials or the system keychain",
       r"\.ssh/(id_|authorized_keys)|\.aws/credentials|\.netrc\b|\.docker/config\.json|\bsecurity\s+find-(generic|internet)-password\b|\.config/gh/hosts|Login Data|\bkeyring\.get_password\b"),
    _r("env-dump", "medium", "Reads the whole environment, which can contain API keys",
       r"\bprintenv\s*($|[|>])|(^|[;&|]\s*)env\s*($|[|>])|\bos\.environ\.(items|copy)\s*\(|dict\(\s*os\.environ\s*\)|json\.dumps\(\s*os\.environ|JSON\.stringify\(\s*process\.env\s*\)|Object\.(entries|keys)\(\s*process\.env\s*\)|\bGet-ChildItem\s+env:"),
    _r("obfuscation", "medium", "Decodes or evaluates hidden code at runtime",
       r"\bbase64\s+(-d|--decode)\b|\bb64decode\b|\batob\s*\(|\beval\s*\(|\bexec\s*\(\s*(compile|base64|bytes|__import__)|String\.fromCharCode|(\\x[0-9a-f]{2}){12,}"),
    _r("remote-download", "medium", "Fetches files or code from the internet",
       r"\b(curl|wget)\s+(-[a-zA-Z]+\s+)*['\"]?https?://|\bInvoke-WebRequest\b|\biwr\b\s+https?://|\bgit\s+clone\b"),
    _r("network-code", "medium", "Makes network requests from code",
       r"\brequests\.(get|post|put|delete|request)\s*\(|\burllib\.request\b|\bhttp\.client\b|\bfetch\s*\(\s*['\"`]https?://|\baxios\b|\bsocket\.socket\s*\(|\bnet\.connect\b|\bURLSession\b"),
    _r("privilege", "medium", "Requests elevated permissions or loosens file permissions",
       r"\bsudo\s+\w|\bchmod\s+(-R\s+)?(777|\+s|u\+s)\b|\bchown\s+-R\b|\bdoas\s+\w"),
    _r("package-install", "low", "Installs packages, which run their own install scripts",
       r"\b(pip3?|uv\s+pip|pipx)\s+install\b|\bnpm\s+(i|install|ci)\b|\bbrew\s+install\b|\bapt(-get)?\s+install\b|\bgem\s+install\b|\bcargo\s+install\b"),
]

# Case-sensitive on purpose: environment-variable names, not the word "password" in prose.
RULES.append(Rule("secret-names", "low", "Refers to API keys or tokens by environment variable name",
                  re.compile(r"\b[A-Z][A-Z0-9]*_(API_KEY|SECRET|SECRET_KEY|TOKEN|ACCESS_KEY|PASSWORD)\b|\b(API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN)\b")))


def git_blob_sha(path: Path) -> str:
    """The SHA-1 git gives the file's contents, so a client can check its own copy against the index."""
    h = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def classify_file(path: Path, head: bytes) -> str:
    ext = path.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return "binary"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in ASSET_EXTENSIONS:
        return "asset"
    if ext in SCRIPT_EXTENSIONS or head.startswith(b"#!"):
        return "script"
    if _is_binary(head):
        return "binary"
    if ext in {".md", ".markdown", ".txt", ".rst"}:
        return "doc"
    return "data"


def scan_directory(root: Path, *, exclude: set[str] = frozenset()) -> dict:
    """Scan every file under `root` and return the files list and findings.

    `exclude` holds root-relative directories to skip, such as skills scanned on their own.
    """
    files: list[dict] = []
    findings: list[dict] = []
    per_rule: dict[str, int] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS
                             and (d if here == "." else f"{here}/{d}") not in exclude)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            rel = full.relative_to(root).as_posix()
            size = full.stat().st_size
            with open(full, "rb") as fh:
                head = fh.read(MAX_SCAN_BYTES)
            kind = classify_file(full, head)
            executable = os.access(full, os.X_OK) and kind != "doc"
            files.append({"path": rel, "size": size, "sha": git_blob_sha(full), "kind": kind,
                          "executable": executable})
            if kind in ("binary", "archive"):
                summary = ("Ships a compiled or binary file that cannot be reviewed as text" if kind == "binary"
                           else "Ships an archive whose contents are not scanned")
                findings.append({"rule": f"{kind}-file", "severity": "medium", "summary": summary,
                                 "file": rel, "line": None, "excerpt": None, "context": "file"})
                continue
            if kind == "asset":
                continue
            text = head.decode("utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                for rule in RULES:
                    if per_rule.get(rule.id, 0) >= MAX_FINDINGS_PER_RULE:
                        continue
                    if rule.pattern.search(line):
                        per_rule[rule.id] = per_rule.get(rule.id, 0) + 1
                        findings.append({"rule": rule.id, "severity": _severity(rule.severity, kind, line),
                                         "summary": rule.summary, "file": rel, "line": lineno,
                                         "excerpt": line.strip()[:200], "context": _context(kind, line)})
    return {"files": files, "findings": findings}


def _context(kind: str, line: str) -> str:
    if kind == "doc":
        return "documentation"
    if kind == "script" and line.lstrip().startswith(COMMENT_PREFIXES) and not line.lstrip().startswith("#!"):
        return "comment"
    return "code"


def _severity(severity: str, kind: str, line: str) -> str:
    """Comments don't run, so they drop to low. Markdown is read by Claude as instructions,
    so it stays relevant but drops one level, since prose often warns *against* a pattern."""
    context = _context(kind, line)
    if context == "comment":
        return "low"
    if context == "documentation":
        return DOWNGRADE[severity]
    return severity


def risk_level(findings: list[dict], files: list[dict]) -> str:
    """Overall level: the worst finding, raised to medium if the skill ships scripts."""
    level = "low"
    for f in findings:
        if SEVERITY_ORDER[f["severity"]] > SEVERITY_ORDER[level]:
            level = f["severity"]
    if level == "low" and any(f["kind"] == "script" for f in files):
        level = "medium"
    return level


def summarize(scan: dict) -> dict:
    files, findings = scan["files"], scan["findings"]
    return {
        "risk": risk_level(findings, files),
        "scripts": sum(1 for f in files if f["kind"] == "script"),
        "binaries": sum(1 for f in files if f["kind"] in ("binary", "archive")),
        "findings": findings,
    }
