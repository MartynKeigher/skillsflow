"""Build the catalog: read sources, crawl, enrich, and write the index files."""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.request
from pathlib import Path

import yaml

from . import SCHEMA_VERSION, __version__, categorize
from .crawl import Crawler

log = logging.getLogger(__name__)


def load_sources(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("repos", [])
    data.setdefault("settings", {})
    data.setdefault("trusted_owners", ["anthropics"])
    data.setdefault("denylist", [])
    data.setdefault("discovery", {})
    return data


def load_previous(location: str | None) -> dict | None:
    """The last published index, a local path or URL. Used to keep first-seen dates."""
    if not location:
        return None
    try:
        if location.startswith(("http://", "https://")):
            with urllib.request.urlopen(location, timeout=60) as resp:
                return json.load(resp)
        return json.loads(Path(location).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("no previous index from %s: %s", location, exc)
        return None


def discover(github, discovery: dict) -> list[str]:
    """Find repositories that contain skills or marketplaces with GitHub code search."""
    if not discovery.get("enabled"):
        return []
    found: list[str] = []
    for query in discovery.get("queries", []):
        for slug in github.search_code_repos(query, discovery.get("max_results_per_query", 1000)):
            if slug not in found:
                found.append(slug)
    min_stars = discovery.get("min_stars", 0)
    kept = []
    for slug in found:
        meta = github.repo(slug)
        if meta is None or meta.get("fork") or meta.get("archived"):
            continue
        if (meta.get("stars") or 0) >= min_stars:
            kept.append(slug)
    kept.sort(key=lambda s: -(github.repo(s) or {}).get("stars", 0))
    return kept[: discovery.get("max_repos", 300)]


def enrich(crawler: Crawler, previous: dict | None, today: str) -> None:
    seen = {}
    if previous:
        for kind in ("skills", "plugins"):
            for item in previous.get(kind, []):
                if item.get("first_seen"):
                    seen[(kind, item["id"])] = item["first_seen"]
    for plugin in crawler.plugins.values():
        plugin["first_seen"] = seen.get(("plugins", plugin["id"]), today)
        if plugin["category"] is None:
            plugin["category"] = categorize.categorize(plugin["name"], plugin.get("description") or "")
        if plugin.get("repo"):
            repo = crawler.repos.get(plugin["repo"].lower(), {})
            plugin["stars"] = repo.get("stars")
    for skill in crawler.skills.values():
        skill["first_seen"] = seen.get(("skills", skill["id"]), today)
        plugin_cats = [crawler.plugins[p]["marketplace_category"] for p in skill["plugins"]
                       if crawler.plugins[p].get("marketplace_category")]
        skill["category"] = categorize.categorize(skill["name"], skill["description"],
                                                  plugin_cats[0] if plugin_cats else None)
        skill["install"] = {
            "plugins": [crawler.plugins[p]["install_command"] for p in skill["plugins"]],
            "copy": {"repo": skill["repo"], "path": skill["path"], "commit": skill["commit"],
                     "target": f"~/.claude/skills/{skill['path'].rsplit('/', 1)[-1] or skill['name']}"},
        }


def build(sources_path: Path, out_dir: Path, fetcher, github, previous: str | None = None,
          extra_repos: list[str] | None = None) -> dict:
    sources = load_sources(sources_path)
    settings = sources["settings"]
    crawler = Crawler(
        fetcher, github,
        trusted_owners=sources["trusted_owners"],
        follow_external=settings.get("follow_external", True),
        max_external=settings.get("max_external_repos", 300),
        denylist=sources["denylist"],
    )
    repos = list(dict.fromkeys(list(sources["repos"]) + (extra_repos or [])))
    if github is not None:
        repos += [r for r in discover(github, sources["discovery"]) if r not in repos]
    for i, slug in enumerate(repos, 1):
        log.info("[%d/%d] %s", i, len(repos), slug)
        crawler.crawl_repo(slug)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    enrich(crawler, load_previous(previous), now.date().isoformat())

    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "generator": f"skillsflow {__version__}",
        "counts": {"skills": len(crawler.skills), "plugins": len(crawler.plugins),
                   "marketplaces": len(crawler.marketplaces), "repos": len(crawler.repos)},
        "categories": categorize.all_categories(),
        "marketplaces": sorted(crawler.marketplaces.values(), key=lambda m: m["name"]),
        "plugins": sorted(crawler.plugins.values(), key=lambda p: p["id"]),
        "skills": sorted(crawler.skills.values(), key=lambda s: s["id"]),
        "repos": sorted(crawler.repos.values(), key=lambda r: r["slug"].lower()),
        "errors": crawler.errors,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (out_dir / "index.pretty.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "SUMMARY.md").write_text(summary_markdown(index), encoding="utf-8")
    return index


def summary_markdown(index: dict) -> str:
    c = index["counts"]
    risk = {"low": 0, "medium": 0, "high": 0}
    for s in index["skills"]:
        risk[s["security"]["risk"]] += 1
    by_cat: dict[str, int] = {}
    for s in index["skills"]:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1
    new = [s for s in index["skills"] if s["first_seen"] == index["generated_at"][:10]]
    lines = [
        f"# SkillsFlow index {index['generated_at'][:10]}",
        "",
        f"- **{c['skills']}** skills, **{c['plugins']}** plugins, **{c['marketplaces']}** marketplaces from **{c['repos']}** repositories",
        f"- Security: {risk['high']} high, {risk['medium']} medium, {risk['low']} low",
        f"- New today: {len(new)}",
        f"- Errors: {len(index['errors'])}",
        "",
        "| Category | Skills |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "",
    ]
    return "\n".join(lines)
