"""GitHub REST API: repository metadata and optional discovery via code search."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)
API = "https://api.github.com"


class GitHub:
    MAX_WAIT = 120  # seconds; a rate limit that resets later than this ends API use for the run

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._repo_cache: dict[str, dict | None] = {}
        self.exhausted = False

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        if self.exhausted:
            return None
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "skillsflow"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429) and exc.headers.get("Retry-After"):
                    time.sleep(min(int(exc.headers["Retry-After"]), 120))
                    continue
                if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
                    wait = int(exc.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time()
                    if wait > self.MAX_WAIT:
                        # Waiting would stall the crawl for up to an hour per request. Carry on
                        # without the API: stars and discovery are missing for the rest of the run.
                        log.warning("GitHub API rate limit reached; resets in %d min. Skipping further API calls.",
                                    wait // 60)
                        self.exhausted = True
                        return None
                    time.sleep(max(1, wait))
                    continue
                log.warning("GitHub API %s returned %s", path, exc.code)
                return None
            except (urllib.error.URLError, TimeoutError) as exc:
                log.warning("GitHub API %s failed: %s", path, exc)
                time.sleep(2 ** attempt)
        return None

    def repo(self, slug: str) -> dict | None:
        key = slug.lower()
        if key not in self._repo_cache:
            data = self._get(f"/repos/{slug}")
            self._repo_cache[key] = None if data is None else {
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "stars": data.get("stargazers_count"),
                "forks": data.get("forks_count"),
                "pushed_at": data.get("pushed_at"),
                "archived": data.get("archived"),
                "fork": data.get("fork"),
                "license": (data.get("license") or {}).get("spdx_id"),
                "default_branch": data.get("default_branch"),
                "topics": data.get("topics") or [],
                "owner_type": (data.get("owner") or {}).get("type"),
            }
        return self._repo_cache[key]

    def search_code_repos(self, query: str, max_results: int = 1000) -> list[str]:
        """Repositories with files matching a code search query. Needs a token."""
        if not self.token:
            log.warning("skipping code search %r: no GITHUB_TOKEN", query)
            return []
        repos: list[str] = []
        for page in range(1, max_results // 100 + 1):
            data = self._get("/search/code", {"q": query, "per_page": 100, "page": page})
            if not data or not data.get("items"):
                break
            for item in data["items"]:
                slug = item["repository"]["full_name"]
                if slug not in repos:
                    repos.append(slug)
            if len(data["items"]) < 100:
                break
            time.sleep(7)  # code search allows about 10 requests a minute
        return repos
