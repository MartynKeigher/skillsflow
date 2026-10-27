"""Fetch repositories as shallow git checkouts.

Cloning instead of calling the GitHub contents API keeps the crawl free of API
rate limits and gives the scanner every file in a skill, not just SKILL.md.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

GITHUB_URL = re.compile(r"^(?:https?://|git@)github\.com[/:]([^/\s]+)/([^/\s#?]+?)(?:\.git)?/?$", re.IGNORECASE)
SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def github_slug(url_or_slug: str) -> str | None:
    """`owner/repo` for a GitHub URL or shorthand, else None."""
    value = url_or_slug.strip()
    if SLUG.match(value):
        return value
    m = GITHUB_URL.match(value)
    return f"{m.group(1)}/{m.group(2)}" if m else None


@dataclass
class Checkout:
    slug: str
    path: Path
    commit: str
    ref: str | None
    branch: str | None = None  # the default branch, when `ref` was None


class GitFetcher:
    def __init__(self, cache_dir: Path, timeout: int = 300):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self._done: dict[tuple[str, str | None], Checkout | None] = {}

    def _git(self, *args: str, cwd: Path) -> str:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
        out = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                             text=True, timeout=self.timeout)
        return out.stdout.strip()

    def cached(self, slug: str, ref: str | None = None) -> Checkout | None:
        """A checkout already made that satisfies `ref`, without touching the network."""
        if (slug.lower(), ref) in self._done:
            return self._done[(slug.lower(), ref)]
        for (s, _), co in self._done.items():
            if co and s == slug.lower() and ref in (co.commit, co.branch):
                return co
        return None

    def fetch(self, slug: str, ref: str | None = None) -> Checkout | None:
        """Check out `ref` (a branch, tag or commit; default branch if None). None on failure."""
        key = (slug.lower(), ref)
        if key in self._done:
            return self._done[key]
        dest = self.cache_dir / (slug.replace("/", "__") + (f"@{re.sub(r'[^A-Za-z0-9_.-]', '_', ref)}" if ref else ""))
        checkout = None
        try:
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            self._git("init", "-q", cwd=dest)
            self._git("remote", "add", "origin", f"https://github.com/{slug}.git", cwd=dest)
            self._git("fetch", "-q", "--depth", "1", "origin", ref or "HEAD", cwd=dest)
            self._git("checkout", "-q", "FETCH_HEAD", cwd=dest)
            branch = None
            if ref is None:
                head = self._git("ls-remote", "--symref", "origin", "HEAD", cwd=dest)
                m = re.match(r"ref: refs/heads/(\S+)\s+HEAD", head)
                branch = m.group(1) if m else None
            checkout = Checkout(slug, dest, self._git("rev-parse", "HEAD", cwd=dest), ref, branch)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            log.warning("fetch failed for %s@%s: %s", slug, ref or "HEAD", detail.strip()[:300])
            shutil.rmtree(dest, ignore_errors=True)
        self._done[key] = checkout
        return checkout


class LocalFetcher:
    """Serves checkouts from a directory of `owner__repo` folders. Used by tests."""

    def __init__(self, root: Path):
        self.root = root

    def cached(self, slug: str, ref: str | None = None) -> Checkout | None:
        return None

    def fetch(self, slug: str, ref: str | None = None) -> Checkout | None:
        path = self.root / slug.replace("/", "__")
        return Checkout(slug, path, "0" * 40, ref, "main" if ref is None else None) if path.is_dir() else None
