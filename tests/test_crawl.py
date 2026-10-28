from skillsflow.crawl import Crawler
from skillsflow.fetch import LocalFetcher, github_slug


def crawl(repos, **kwargs):
    crawler = Crawler(LocalFetcher(repos), None, trusted_owners=["acme"], **kwargs)
    crawler.crawl_repo("acme/skills")
    return crawler


def test_github_slug():
    assert github_slug("https://github.com/a/b.git") == "a/b"
    assert github_slug("git@github.com:a/b.git") == "a/b"
    assert github_slug("a/b") == "a/b"
    assert github_slug("https://gitlab.com/a/b.git") is None


def test_indexes_every_skill_in_a_crawled_repo(repos):
    c = crawl(repos)
    assert {"acme/skills:skills/pdf", "acme/skills:skills/brand", "acme/skills:skills/unlisted"} <= set(c.skills)
    pdf = c.skills["acme/skills:skills/pdf"]
    assert pdf["name"] == "pdf"
    assert pdf["trust"] == "official"
    assert pdf["security"]["scripts"] == 1
    assert {f["path"] for f in pdf["files"]} == {"SKILL.md", "scripts/fill.py"}


def test_root_entry_with_skills_loads_only_those(repos):
    c = crawl(repos)
    docs = c.plugins["docs@acme"]
    assert docs["skills"] == ["acme/skills:skills/pdf", "acme/skills:skills/brand"]
    assert docs["install_command"] == "claude plugin install docs@acme"
    assert c.skills["acme/skills:skills/unlisted"]["plugins"] == []
    assert c.skills["acme/skills:skills/pdf"]["plugins"] == ["docs@acme"]


def test_plugin_hooks_are_flagged(repos):
    hooky = crawl(repos).plugins["hooky@acme"]
    assert hooky["components"]["hooks"] is True
    assert hooky["security"]["runs_code_automatically"] == ["hooks"]
    assert hooky["security"]["risk"] == "high"  # the hook script pipes curl into sh
    assert hooky["description"] == "Has hooks"


def test_follows_external_github_source(repos):
    c = crawl(repos)
    remote = c.plugins["remote@acme"]
    assert remote["indexed"] is True
    assert remote["skills"] == ["other/tool"]  # SKILL.md at the plugin root
    assert c.skills["other/tool"]["trust"] == "community"


def test_git_subdir_indexes_only_the_plugin_path(repos):
    c = crawl(repos)
    assert c.plugins["subdir@acme"]["skills"] == ["other/mono:pkgs/thing/skills/thing"]
    assert "other/mono:unrelated" not in c.skills


def test_unfollowed_and_unsupported_sources_are_listed_but_not_indexed(repos):
    c = crawl(repos, follow_external=False)
    assert c.plugins["remote@acme"]["indexed"] is False
    assert c.plugins["npm-one@acme"]["source"]["type"] == "npm"
    assert c.plugins["npm-one@acme"]["indexed"] is False


def test_path_escape_is_not_followed(repos):
    c = crawl(repos)
    assert c.plugins["escape@acme"]["indexed"] is False


def test_denylist(repos):
    c = crawl(repos, denylist=["other/tool"])
    assert c.plugins["remote@acme"]["indexed"] is False
    assert "other/tool" not in c.skills


def test_marketplace_record(repos):
    mp = crawl(repos).marketplaces["acme"]
    assert mp["add_command"] == "claude plugin marketplace add acme/skills"
    assert len(mp["plugins"]) == 6


def test_frontmatter_dates_are_json_safe(repos):
    import json
    from conftest import write

    write(repos / "acme__skills", "skills/dated/SKILL.md",
          "---\nname: dated\ndescription: d\nupdated: 2026-01-02\ntags: [a, 2026-01-03]\n---\nbody\n")
    skill = crawl(repos).skills["acme/skills:skills/dated"]
    assert skill["frontmatter"] == {"updated": "2026-01-02", "tags": ["a", "2026-01-03"]}
    json.dumps(skill)


def test_one_bad_repo_does_not_stop_the_crawl(repos, monkeypatch):
    c = Crawler(LocalFetcher(repos), None)
    monkeypatch.setattr(c, "_crawl_repo", lambda slug: (_ for _ in ()).throw(RuntimeError("boom")))
    c.crawl_repo("acme/skills")
    assert c.errors == [{"repo": "acme/skills", "error": "RuntimeError: boom"}]
