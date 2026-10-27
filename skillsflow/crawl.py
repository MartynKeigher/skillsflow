"""Walk repositories and marketplaces and collect skill and plugin records."""

from __future__ import annotations

import json
import logging
import posixpath
from pathlib import Path

from . import categorize, frontmatter, security
from .fetch import Checkout, github_slug

log = logging.getLogger(__name__)

SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_SKILL_MD_BYTES = 256 * 1024


def _norm(rel: str) -> str | None:
    """Normalize a `./`-relative path; None if it is absolute or escapes the root."""
    if rel.startswith("/") or "\\" in rel:
        return None
    p = posixpath.normpath(rel.strip() or ".")
    if p == ".." or p.startswith("../"):
        return None
    return "" if p == "." else p


def _join(*parts: str) -> str:
    return posixpath.join(*[p for p in parts if p]) if any(parts) else ""


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None


def _author_name(author) -> str | None:
    if isinstance(author, dict):
        return author.get("name")
    return author if isinstance(author, str) else None


class Crawler:
    def __init__(self, fetcher, github=None, *, trusted_owners=("anthropics",), follow_external=True,
                 max_external=300, denylist=()):
        self.fetcher = fetcher
        self.github = github
        self.trusted_owners = {o.lower() for o in trusted_owners}
        self.follow_external = follow_external
        self.max_external = max_external
        self.denylist = {d.lower() for d in denylist}
        self.skills: dict[str, dict] = {}
        self.plugins: dict[str, dict] = {}
        self.marketplaces: dict[str, dict] = {}
        self.repos: dict[str, dict] = {}
        self.errors: list[dict] = []
        self._external_fetches = 0

    # -- repositories ---------------------------------------------------------

    def crawl_repo(self, slug: str) -> None:
        """Index every skill in a repository, plus its marketplace if it has one."""
        if slug.lower() in self.denylist:
            return
        checkout = self.fetcher.fetch(slug)
        if checkout is None:
            self.errors.append({"repo": slug, "error": "fetch failed"})
            return
        self._note_repo(checkout)
        for skill_dir in self._find_skill_dirs(checkout.path):
            self._skill(checkout, skill_dir)
        mp_file = checkout.path / ".claude-plugin" / "marketplace.json"
        if mp_file.is_file():
            self._marketplace(checkout, mp_file)

    def _note_repo(self, checkout: Checkout) -> dict:
        key = checkout.slug.lower()
        if key not in self.repos:
            meta = self.github.repo(checkout.slug) if self.github else None
            self.repos[key] = {"slug": meta["full_name"] if meta and meta.get("full_name") else checkout.slug,
                               "commit": checkout.commit, **{k: v for k, v in (meta or {}).items() if k != "full_name"}}
        return self.repos[key]

    def _find_skill_dirs(self, root: Path, start: str = "") -> list[str]:
        base = root / start if start else root
        found = []
        for path in sorted(base.rglob("SKILL.md")):
            rel_parts = path.relative_to(root).parts
            if any(part in SKIP_DIRS for part in rel_parts[:-1]) or path.is_symlink():
                continue
            found.append(posixpath.join(*rel_parts[:-1]) if len(rel_parts) > 1 else "")
        return found

    # -- skills ---------------------------------------------------------------

    def _skill(self, checkout: Checkout, rel_dir: str) -> str | None:
        skill_id = f"{checkout.slug}:{rel_dir}" if rel_dir else checkout.slug
        if skill_id in self.skills:
            return skill_id
        directory = checkout.path / rel_dir
        md = directory / "SKILL.md"
        if not md.is_file() or md.stat().st_size > MAX_SKILL_MD_BYTES:
            return None
        fields, body = frontmatter.parse(md.read_text(encoding="utf-8", errors="replace"))
        dir_name = posixpath.basename(rel_dir) if rel_dir else checkout.slug.split("/")[1]
        name = str(fields.get("name") or dir_name).strip()
        description = str(fields.get("description") or frontmatter.first_line(body)).strip()
        if fields.get("when_to_use"):
            description = f"{description} {str(fields['when_to_use']).strip()}".strip()
        scan = security.scan_directory(directory)
        owner = checkout.slug.split("/")[0].lower()
        repo = self._note_repo(checkout)
        self.skills[skill_id] = {
            "id": skill_id,
            "name": name,
            "description": description,
            "license": fields.get("license") if isinstance(fields.get("license"), str) else None,
            "repo": checkout.slug,
            "path": rel_dir,
            "commit": checkout.commit,
            "url": f"https://github.com/{checkout.slug}/tree/{checkout.commit}/{rel_dir}".rstrip("/"),
            "frontmatter": {k: fields[k] for k in sorted(fields) if k not in ("name", "description")
                            and isinstance(fields[k], (str, int, float, bool, list))},
            "lines": body.count("\n") + 1,
            "files": scan["files"],
            "security": security.summarize(scan),
            "trust": "official" if owner in self.trusted_owners else "community",
            "stars": repo.get("stars"),
            "repo_pushed_at": repo.get("pushed_at"),
            "plugins": [],
            "category": None,
        }
        return skill_id

    # -- marketplaces and plugins ---------------------------------------------

    def _marketplace(self, checkout: Checkout, mp_file: Path) -> None:
        data = _read_json(mp_file)
        if not data or not isinstance(data.get("plugins"), list) or not data.get("name"):
            self.errors.append({"repo": checkout.slug, "error": "invalid marketplace.json"})
            return
        name = str(data["name"])
        if name in self.marketplaces:
            self.errors.append({"repo": checkout.slug, "error": f"duplicate marketplace name {name!r}"})
            return
        owner = checkout.slug.split("/")[0].lower()
        self.marketplaces[name] = {
            "name": name,
            "repo": checkout.slug,
            "commit": checkout.commit,
            "description": data.get("description") or (data.get("metadata") or {}).get("description"),
            "owner": _author_name(data.get("owner")),
            "add_command": f"claude plugin marketplace add {checkout.slug}",
            "trust": "official" if owner in self.trusted_owners else "community",
            "plugins": [],
        }
        plugin_root = (data.get("metadata") or {}).get("pluginRoot")
        for entry in data["plugins"]:
            if isinstance(entry, dict) and entry.get("name") and "source" in entry:
                try:
                    self._plugin(checkout, name, entry, plugin_root)
                except Exception as exc:  # one bad entry must not sink the marketplace
                    log.exception("plugin %s@%s failed", entry.get("name"), name)
                    self.errors.append({"repo": checkout.slug, "plugin": entry.get("name"), "error": str(exc)})

    def _resolve_source(self, checkout: Checkout, source, plugin_root: str | None):
        """Return (checkout or None, path in it or None, descriptor for the index)."""
        if isinstance(source, str):
            raw = source
            if "/" not in source and source not in (".", "") and plugin_root:
                raw = _join(plugin_root, source)
            rel = _norm(raw)
            return checkout, rel, {"type": "relative", "path": source}
        if not isinstance(source, dict):
            return None, None, {"type": "invalid"}
        kind = source.get("source")
        ref = source.get("sha") or source.get("ref")
        if kind == "github":
            slug, path = source.get("repo"), ""
        elif kind == "url":
            slug, path = github_slug(source.get("url", "")), ""
        elif kind == "git-subdir":
            slug, path = github_slug(source.get("url", "")), _norm(source.get("path", ""))
        else:
            return None, None, {"type": kind or "invalid"}
        descriptor = {"type": kind, "repo": slug or source.get("url"), "path": path or None,
                      "ref": source.get("ref"), "sha": source.get("sha")}
        if not slug or path is None or slug.lower() in self.denylist:
            return None, None, descriptor
        if slug.lower() == checkout.slug.lower() and ref in (None, checkout.ref, checkout.commit, checkout.branch):
            return checkout, path, descriptor
        cached = self.fetcher.cached(slug, ref)
        if cached is not None:
            return cached, path, descriptor
        if not self.follow_external or self._external_fetches >= self.max_external:
            return None, None, descriptor
        self._external_fetches += 1
        target = self.fetcher.fetch(slug, ref)
        if target is None:
            self.errors.append({"repo": slug, "error": f"fetch failed at {ref or 'HEAD'}"})
        return target, path, descriptor

    def _plugin(self, mp_checkout: Checkout, marketplace: str, entry: dict, plugin_root: str | None) -> None:
        name = str(entry["name"])
        plugin_id = f"{name}@{marketplace}"
        target, rel_root, source = self._resolve_source(mp_checkout, entry["source"], plugin_root)
        record = {
            "id": plugin_id,
            "name": name,
            "marketplace": marketplace,
            "display_name": entry.get("displayName"),
            "description": entry.get("description"),
            "version": entry.get("version"),
            "author": _author_name(entry.get("author")),
            "homepage": entry.get("homepage"),
            "category": categorize.from_marketplace(entry.get("category")),
            "marketplace_category": entry.get("category"),
            "tags": [str(t) for t in _as_list(entry.get("tags")) + _as_list(entry.get("keywords"))],
            "source": source,
            "install_command": f"claude plugin install {plugin_id}",
            "trust": self.marketplaces[marketplace]["trust"],
            "indexed": False,
            "skills": [],
            "components": None,
            "security": None,
        }
        if target is not None and rel_root is not None and (target.path / rel_root).is_dir():
            self._fill_plugin(record, target, rel_root, entry,
                              root_listing=isinstance(entry["source"], str) and rel_root == "")
        self.plugins[plugin_id] = record
        self.marketplaces[marketplace]["plugins"].append(plugin_id)

    def _plugin_skill_dirs(self, root: Path, rel_root: str, entry: dict, manifest: dict | None,
                           root_listing: bool) -> list[str]:
        """Skill directories a plugin loads, following Claude Code's rules."""
        entry_paths = [p for p in _as_list(entry.get("skills")) if isinstance(p, str)]
        manifest_paths = [p for p in _as_list((manifest or {}).get("skills")) if isinstance(p, str)]
        listed = entry_paths + manifest_paths
        candidates: list[str] = []
        # An entry whose source is the marketplace root and that lists skills loads only those.
        if not (root_listing and entry_paths):
            candidates.append("skills")
        candidates += listed
        dirs: list[str] = []
        for cand in candidates:
            rel = _norm(cand)
            if rel is None:
                continue
            d = root / rel_root / rel if rel else root / rel_root
            if (d / "SKILL.md").is_file():
                dirs.append(_join(rel_root, rel))
            elif d.is_dir():
                for child in sorted(d.iterdir()):
                    if child.is_dir() and (child / "SKILL.md").is_file():
                        dirs.append(_join(rel_root, rel, child.name))
        if not dirs and not listed and (root / rel_root / "SKILL.md").is_file():
            dirs.append(rel_root)  # a plugin with SKILL.md at its root is one skill
        return list(dict.fromkeys(dirs))

    def _fill_plugin(self, record: dict, checkout: Checkout, rel_root: str, entry: dict, root_listing: bool) -> None:
        root = checkout.path / rel_root
        manifest = _read_json(root / ".claude-plugin" / "plugin.json") if (root / ".claude-plugin" / "plugin.json").is_file() else None
        m = manifest or {}
        for key in ("description", "version", "homepage", "display_name"):
            src_key = "displayName" if key == "display_name" else key
            if not record[key] and m.get(src_key):
                record[key] = m[src_key]
        record["author"] = record["author"] or _author_name(m.get("author"))
        record["license"] = m.get("license")
        record["tags"] = list(dict.fromkeys(record["tags"] + [str(k) for k in _as_list(m.get("keywords"))]))
        record["manifest_name"] = m.get("name") or record["name"]
        record["repo"] = checkout.slug
        record["path"] = rel_root
        record["commit"] = checkout.commit
        self._note_repo(checkout)

        for skill_dir in self._plugin_skill_dirs(checkout.path, rel_root, entry, manifest, root_listing):
            skill_id = self._skill(checkout, skill_dir)
            if skill_id:
                record["skills"].append(skill_id)
                self.skills[skill_id]["plugins"].append(record["id"])

        def count_md(sub: str) -> int:
            d = root / sub
            return sum(1 for _ in d.rglob("*.md")) if d.is_dir() else 0

        hooks = (root / "hooks" / "hooks.json").is_file() or bool(m.get("hooks")) or bool(entry.get("hooks"))
        mcp = (root / ".mcp.json").is_file() or bool(m.get("mcpServers")) or bool(entry.get("mcpServers"))
        record["components"] = {
            "skills": len(record["skills"]),
            "commands": count_md("commands") if not (m.get("commands") or entry.get("commands")) else len(_as_list(m.get("commands") or entry.get("commands"))),
            "agents": count_md("agents") if not (m.get("agents") or entry.get("agents")) else len(_as_list(m.get("agents") or entry.get("agents"))),
            "hooks": hooks,
            "mcp_servers": mcp,
            "lsp_servers": (root / ".lsp.json").is_file() or bool(m.get("lspServers")) or bool(entry.get("lspServers")),
            "monitors": (root / "monitors" / "monitors.json").is_file() or bool((m.get("experimental") or {}).get("monitors")),
            "bin": (root / "bin").is_dir(),
        }
        record["indexed"] = True

        # Hooks, MCP servers, monitors and bin/ run code without Claude choosing a skill, so the
        # plugin's own files are scanned too, apart from skills which carry their own scan.
        if any(self.skills[s]["path"] == rel_root for s in record["skills"]):
            files, findings = [], []  # the plugin is a single skill, already scanned
        else:
            # Every skill folder under the root is skipped: this plugin's own skills carry their
            # own scan, and skills it doesn't load never run.
            skill_dirs = {posixpath.relpath(d, rel_root) if rel_root else d
                          for d in self._find_skill_dirs(checkout.path, rel_root)}
            scan = security.scan_directory(root, exclude=skill_dirs)
            files, findings = scan["files"], scan["findings"]
        summary = security.summarize({"files": files, "findings": findings})
        runs_code = [k for k in ("hooks", "mcp_servers", "lsp_servers", "monitors", "bin") if record["components"][k]]
        if runs_code and summary["risk"] == "low":
            summary["risk"] = "medium"
        summary["runs_code_automatically"] = runs_code
        record["security"] = summary
