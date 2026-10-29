"""Command line entry point: `python -m skillsflow build ...`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

from .build import build
from .fetch import GitFetcher
from .github import GitHub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skillsflow", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="crawl sources and write the index")
    b.add_argument("--sources", type=Path, default=Path("sources.yaml"))
    b.add_argument("--out", type=Path, default=Path("dist"))
    b.add_argument("--cache", type=Path, default=None, help="where to put checkouts while crawling; each is deleted once read (default: a temp dir)")
    b.add_argument("--previous", help="path or URL of the last index.json, to keep first-seen dates and star history")
    b.add_argument("--featured", type=Path, default=None, help="featured picks (default: featured.yaml next to --sources)")
    b.add_argument("--release-repo", help="owner/repo the index is published to, for the details URL")
    b.add_argument("--release-tag", help="release tag the index is published under, for the details URL")
    b.add_argument("--repo", action="append", default=[], help="crawl an extra owner/repo (repeatable)")
    b.add_argument("--offline-metadata", action="store_true", help="skip the GitHub API (no stars, no discovery)")
    b.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    github = None if args.offline_metadata else GitHub()
    try:
        with tempfile.TemporaryDirectory(prefix="skillsflow-") as tmp:
            fetcher = GitFetcher(args.cache or Path(tmp))
            index = build(args.sources, args.out, fetcher, github, previous=args.previous, extra_repos=args.repo,
                          featured_path=args.featured, release_repo=args.release_repo,
                          release_tag=args.release_tag)
    except Exception as exc:
        if os.environ.get("GITHUB_ACTIONS"):
            # Annotations are readable through the API even when the raw log isn't.
            print(f"::error title=skillsflow build failed::{type(exc).__name__}: {exc}".replace("\n", " "))
        raise
    c = index["counts"]
    if os.environ.get("GITHUB_ACTIONS"):
        for err in index["errors"][:10]:
            print(f"::warning title=skillsflow::{err}".replace("\n", " "))
    print(f"wrote {args.out}/index.json: {c['skills']} skills, {c['plugins']} plugins, "
          f"{c['marketplaces']} marketplaces, {len(index['errors'])} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
