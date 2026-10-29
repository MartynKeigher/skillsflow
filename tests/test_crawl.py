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
    assert hooky["security"]["runs_code_automatically"] == ["hooks", "mcp_servers", "mods", "bin"]
    assert hooky["security"]["risk"] == "high"  # the hook script pipes curl into sh
    assert hooky["description"] == "Has hooks"


def test_plugin_lists_what_runs_automatically(repos):
    auto = crawl(repos).plugins["hooky@acme"]["automatic"]
    assert auto["hooks"] == [{"event": "PostToolUse", "matcher": "Write|Edit", "type": "command",
                              "command": '"${CLAUDE_PLUGIN_ROOT}"/scripts/run.sh', "file": "hooks/hooks.json"}]
    assert auto["mcp_servers"] == [{"name": "db", "type": "stdio", "command": "node ${CLAUDE_PLUGIN_ROOT}/server.js",
                                    "env": ["DB_TOKEN"], "file": ".mcp.json"}]
    assert auto["mods"] == [{"module": "./mods/panel.js", "file": "hooks/hooks.json"}]
    assert auto["bin"] == ["hooky-cli"]
    assert auto["lsp_servers"] == [] and auto["monitors"] == []


def test_plugin_files_leave_out_only_its_own_skills(repos):
    c = crawl(repos)
    hooky = c.plugins["hooky@acme"]
    paths = {f["path"] for f in hooky["files"]}
    assert "skills/own/SKILL.md" not in paths  # listed and scanned with the skill itself
    assert {".claude-plugin/plugin.json", "hooks/hooks.json", "scripts/run.sh", "extras/unloaded/SKILL.md"} <= paths
    assert all(len(f["sha"]) == 40 for f in hooky["files"])
    assert any(f["rule"] == "privilege" and f["file"] == "extras/unloaded/SKILL.md" for f in hooky["security"]["findings"])
    assert hooky["skills"] == ["acme/skills:plugins/hooky/skills/own"]


def test_single_skill_plugin_has_no_files_of_its_own(repos):
    assert crawl(repos).plugins["remote@acme"]["files"] == []


def test_publisher_and_listing(repos):
    c = crawl(repos)
    assert c.plugins["docs@acme"]["publisher"] == "anthropic"
    assert c.plugins["docs@acme"]["listed_by_anthropic"] is True
    # Listed in the trusted marketplace, but made by someone else.
    assert c.plugins["remote@acme"]["publisher"] == "third_party"
    assert c.plugins["remote@acme"]["listed_by_anthropic"] is True
    # Not fetched and not on GitHub: the maker is unknown, so it is never credited to Anthropic.
    assert c.plugins["npm-one@acme"]["publisher"] == "third_party"
    assert c.skills["other/tool"]["publisher"] == "third_party"
    assert c.marketplaces["acme"]["publisher"] == "anthropic"


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


def test_external_sources_are_prefetched_in_parallel_once(repos):
    class Counting(LocalFetcher):
        calls = []

        def fetch(self, slug, ref=None):
            if not self.attempted(slug, ref):
                self.calls.append((slug, ref))
            return super().fetch(slug, ref)

    c = Crawler(Counting(repos), None, trusted_owners=["acme"], workers=4)
    c.crawl_repo("acme/skills")
    assert sorted(Counting.calls) == [("acme/skills", None), ("other/mono", None), ("other/tool", None)]
    assert c.plugins["remote@acme"]["indexed"] and c.plugins["subdir@acme"]["indexed"]


def test_small_batches_index_the_same_plugins(repos):
    full = crawl(repos)
    batched = crawl(repos, batch_size=1)
    assert {k: v["skills"] for k, v in batched.plugins.items()} == {k: v["skills"] for k, v in full.plugins.items()}
    assert batched.errors == full.errors


def test_prefetch_respects_max_external(repos):
    c = crawl(repos, max_external=1)
    assert [c.plugins[p]["indexed"] for p in ("remote@acme", "subdir@acme")] == [True, False]


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


def test_skill_folder_with_a_plugin_manifest_is_flagged_and_never_low(repos):
    import json as _json
    from conftest import write

    write(repos / "acme__skills", "skills/sneaky/SKILL.md", "---\nname: sneaky\ndescription: d\n---\nbody\n")
    write(repos / "acme__skills", "skills/sneaky/.claude-plugin/plugin.json", _json.dumps({"name": "sneaky"}))
    c = crawl(repos)
    sneaky = c.skills["acme/skills:skills/sneaky"]
    assert sneaky["folder_is_plugin"] is True
    assert sneaky["security"]["risk"] == "medium"
    assert c.skills["acme/skills:skills/brand"]["folder_is_plugin"] is False
