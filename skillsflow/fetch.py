"""Fetch repositories as shallow git checkouts.

Cloning instead of calling the GitHub contents API keeps the crawl free of API
rate limits and gives the scanner every file in a skill, not just SKILL.md.
"""

from __future__ import annotations

import datetime as dt
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
    history: bool = False  # recent commits were fetched, so `added_dates` can answer


class GitFetcher:
    """Shallow checkouts with `history_days` of commits (trees only, no old file contents).

    The history dates when each file was added. A repo with no commits in that window, or a
    fetch that fails with it, falls back to a single commit.
    """

    def __init__(self, cache_dir: Path, timeout: int = 300, history_days: int = 120,
                 remote: str = "https://github.com/{slug}.git"):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.history_days = history_days
        self.remote = remote
        self._done: dict[tuple[str, str | None], Checkout | None] = {}
        self._added: dict[Path, dict[str, str]] = {}

    def _git(self, *args: str, cwd: Path) -> str:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
        out = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                             text=True, timeout=self.timeout)
        return out.stdout.strip()

    def attempted(self, slug: str, ref: str | None = None) -> bool:
        """Whether `fetch` already ran for this slug and ref, or a checkout satisfies it."""
        return (slug.lower(), ref) in self._done or self.cached(slug, ref) is not None

    def cached(self, slug: str, ref: str | None = None) -> Checkout | None:
        """A checkout already made that satisfies `ref`, without touching the network."""
        if (slug.lower(), ref) in self._done:
            return self._done[(slug.lower(), ref)]
        for (s, _), co in list(self._done.items()):
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
            self._git("remote", "add", "origin", self.remote.format(slug=slug), cwd=dest)
            history = False
            if self.history_days > 0:
                since = (dt.date.today() - dt.timedelta(days=self.history_days)).isoformat()
                try:
                    self._git("config", "remote.origin.promisor", "true", cwd=dest)
                    self._git("config", "remote.origin.partialclonefilter", "blob:none", cwd=dest)
                    self._git("fetch", "-q", "--filter=blob:none", f"--shallow-since={since}",
                              "origin", ref or "HEAD", cwd=dest)
                    history = True
                except subprocess.CalledProcessError:
                    self._git("config", "--unset", "remote.origin.promisor", cwd=dest)
                    self._git("config", "--unset", "remote.origin.partialclonefilter", cwd=dest)
            if not history:
                self._git("fetch", "-q", "--depth", "1", "origin", ref or "HEAD", cwd=dest)
            self._git("checkout", "-q", "FETCH_HEAD", cwd=dest)
            branch = None
            if ref is None:
                head = self._git("ls-remote", "--symref", "origin", "HEAD", cwd=dest)
                m = re.match(r"ref: refs/heads/(\S+)\s+HEAD", head)
                branch = m.group(1) if m else None
            checkout = Checkout(slug, dest, self._git("rev-parse", "HEAD", cwd=dest), ref, branch, history)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            log.warning("fetch failed for %s@%s: %s", slug, ref or "HEAD", detail.strip()[:300])
            shutil.rmtree(dest, ignore_errors=True)
        self._done[key] = checkout
        return checkout

    def release_all(self, keep: Checkout | None = None) -> None:
        """Delete every checkout made so far except `keep`. A later `fetch` clones it again.

        A marketplace can point at thousands of repositories, more than a CI runner's disk holds,
        so the crawler releases them as it goes.
        """
        for key, checkout in list(self._done.items()):
            if keep is not None and checkout is not None and checkout.path == keep.path:
                continue
            if checkout is not None:
                shutil.rmtree(checkout.path, ignore_errors=True)
                self._added.pop(checkout.path, None)
            del self._done[key]

    def added_dates(self, checkout: Checkout) -> dict[str, str]:
        """Repo-relative path -> date (YYYY-MM-DD) of the commit that added it, for files added
        inside the history window. Files older than the window are absent."""
        if not checkout.history:
            return {}
        if checkout.path not in self._added:
            shallow_file = checkout.path / ".git" / "shallow"
            boundary = set(shallow_file.read_text().split()) if shallow_file.is_file() else set()
            dates: dict[str, str] = {}
            try:
                out = self._git("log", "--diff-filter=A", "--no-renames", "--name-only",
                                "--format=%x00%H %cs", "HEAD", cwd=checkout.path)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                log.warning("git log failed for %s: %s", checkout.slug, exc)
                out = ""
            # Newest first, so the last date seen for a path is when it was first added. A shallow
            # boundary commit has no parent and lists every file as added, so it is skipped.
            for block in out.split("\0")[1:]:
                header, _, names = block.partition("\n")
                sha, _, date = header.partition(" ")
                if sha in boundary:
                    continue
                for name in names.splitlines():
                    if name:
                        dates[name] = date
            self._added[checkout.path] = dates
        return self._added[checkout.path]


class LocalFetcher:
    """Serves checkouts from a directory of `owner__repo` folders. Used by tests."""

    def __init__(self, root: Path):
        self.root = root
        self._done: set[tuple[str, str | None]] = set()

    def attempted(self, slug: str, ref: str | None = None) -> bool:
        return (slug.lower(), ref) in self._done

    def cached(self, slug: str, ref: str | None = None) -> Checkout | None:
        return self.fetch(slug, ref) if self.attempted(slug, ref) else None

    def added_dates(self, checkout: Checkout) -> dict[str, str]:
        return {}

    def release_all(self, keep: Checkout | None = None) -> None:
        self._done = {k for k in self._done if keep is not None and k == (keep.slug.lower(), keep.ref)}

    def fetch(self, slug: str, ref: str | None = None) -> Checkout | None:
        self._done.add((slug.lower(), ref))
        path = self.root / slug.replace("/", "__")
        return Checkout(slug, path, "0" * 40, ref, "main" if ref is None else None) if path.is_dir() else None
