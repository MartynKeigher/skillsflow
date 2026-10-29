import datetime as dt
import os
import subprocess

from skillsflow.fetch import GitFetcher
from conftest import write


def git(cwd, *args, days_ago=0):
    when = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def make_repo(root, commits):
    repo = root / "remote" / "acme" / "skills"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "uploadpack.allowFilter", "true")
    for path, days_ago in commits:
        write(repo, path, f"{path}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", path, days_ago=days_ago)
    return repo


def fetcher(tmp_path, **kwargs):
    return GitFetcher(tmp_path / "cache", remote=f"file://{tmp_path}/remote/{{slug}}", **kwargs)


def test_added_dates_inside_the_history_window(tmp_path):
    make_repo(tmp_path, [("old/SKILL.md", 300), ("edge/SKILL.md", 100), ("a/SKILL.md", 60), ("b/SKILL.md", 10)])
    f = fetcher(tmp_path, history_days=120)
    co = f.fetch("acme/skills")
    assert co.history
    dates = f.added_dates(co)
    day = lambda n: (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).date().isoformat()
    assert dates["a/SKILL.md"] == day(60)
    assert dates["b/SKILL.md"] == day(10)
    # Older than the window, or added by the shallow boundary commit: unknown, never a wrong date.
    assert "old/SKILL.md" not in dates
    assert "edge/SKILL.md" not in dates
    assert (co.path / "old" / "SKILL.md").is_file()


def test_repo_younger_than_the_window_dates_its_first_commit(tmp_path):
    make_repo(tmp_path, [("a/SKILL.md", 30), ("b/SKILL.md", 5)])
    f = fetcher(tmp_path, history_days=120)
    assert set(f.added_dates(f.fetch("acme/skills"))) == {"a/SKILL.md", "b/SKILL.md"}


def test_no_recent_commits_falls_back_to_one_commit(tmp_path):
    make_repo(tmp_path, [("a/SKILL.md", 400)])
    f = fetcher(tmp_path, history_days=120)
    co = f.fetch("acme/skills")
    assert co is not None and not co.history
    assert f.added_dates(co) == {}
    assert (co.path / "a" / "SKILL.md").is_file()


def test_history_can_be_turned_off(tmp_path):
    make_repo(tmp_path, [("a/SKILL.md", 5)])
    f = fetcher(tmp_path, history_days=0)
    co = f.fetch("acme/skills")
    assert not co.history and f.added_dates(co) == {}


def test_release_all_deletes_checkouts_and_allows_refetch(tmp_path):
    make_repo(tmp_path, [("a/SKILL.md", 5)])
    f = fetcher(tmp_path)
    co = f.fetch("acme/skills")
    f.release_all()
    assert not co.path.exists()
    assert not f.attempted("acme/skills")
    again = f.fetch("acme/skills")
    assert (again.path / "a" / "SKILL.md").is_file()


def test_release_all_can_keep_one_checkout(tmp_path):
    make_repo(tmp_path, [("a/SKILL.md", 5)])
    f = fetcher(tmp_path)
    co = f.fetch("acme/skills")
    f.release_all(keep=co)
    assert co.path.exists() and f.attempted("acme/skills")
