import json

from skillsflow.build import build
from skillsflow.fetch import LocalFetcher


def test_build_writes_index_and_keeps_first_seen(repos, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\ntrusted_owners: [acme]\n")
    previous = tmp_path / "prev.json"
    previous.write_text(json.dumps({"skills": [{"id": "acme/skills:skills/pdf", "first_seen": "2026-01-01"}]}))
    out = tmp_path / "dist"
    index = build(sources, out, LocalFetcher(repos), None, previous=str(previous))

    on_disk = json.loads((out / "index.json").read_text())
    assert on_disk["counts"] == index["counts"]
    assert index["schema_version"] == 2
    skills = {s["id"]: s for s in index["skills"]}
    assert skills["acme/skills:skills/pdf"]["first_seen"] == "2026-01-01"
    assert skills["acme/skills:skills/brand"]["first_seen"] == index["generated_at"][:10]
    # The plugin's marketplace category wins over keywords.
    assert skills["acme/skills:skills/brand"]["category"] == "Productivity"
    assert skills["acme/skills:skills/unlisted"]["install"]["plugins"] == []
    assert skills["acme/skills:skills/pdf"]["install"]["copy"]["target"] == "~/.claude/skills/pdf"
    assert (out / "SUMMARY.md").read_text().startswith("# SkillsFlow index")


def test_featured_picks_keep_order_and_skip_unknown_ids(repos, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\ntrusted_owners: [acme]\n")
    (tmp_path / "featured.yaml").write_text(
        "featured:\n  - id: hooky@acme\n    note: Hooks done right\n  - id: gone@acme\n  - acme/skills:skills/pdf\n")
    index = build(sources, tmp_path / "dist", LocalFetcher(repos), None)
    assert index["featured"] == [
        {"id": "hooky@acme", "kind": "plugin", "note": "Hooks done right"},
        {"id": "acme/skills:skills/pdf", "kind": "skill", "note": None},
    ]


def test_skills_are_listed_by_anthropic_through_their_plugins(repos, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\ntrusted_owners: [acme]\n")
    skills = {s["id"]: s for s in build(sources, tmp_path / "dist", LocalFetcher(repos), None)["skills"]}
    assert skills["acme/skills:skills/pdf"]["listed_by_anthropic"] is True
    assert skills["acme/skills:skills/unlisted"]["listed_by_anthropic"] is False
    assert skills["other/tool"]["listed_by_anthropic"] is True
    assert skills["other/tool"]["publisher"] == "third_party"


def test_added_dates_carry_over_from_the_previous_index(repos, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\n")
    previous = tmp_path / "prev.json"
    previous.write_text(json.dumps({"skills": [{"id": "acme/skills:skills/pdf", "added": "2026-08-01"}],
                                    "plugins": [{"id": "hooky@acme", "added": "2026-07-01"}]}))
    index = build(sources, tmp_path / "dist", LocalFetcher(repos), None, previous=str(previous))
    skills = {s["id"]: s for s in index["skills"]}
    assert skills["acme/skills:skills/pdf"]["added"] == "2026-08-01"
    assert skills["acme/skills:skills/brand"]["added"] is None
    assert {p["id"]: p for p in index["plugins"]}["hooky@acme"]["added"] == "2026-07-01"


def test_star_history_and_gain():
    from skillsflow.build import stars_gained, star_history

    history = star_history({"stars": 130}, {"stars_history": [["2026-10-01", 50], ["2026-10-20", 100],
                                                              ["2026-10-25", 120], ["2026-10-28", 999]]},
                           "2026-10-28")
    # Today's earlier value is replaced, not duplicated.
    assert history == [["2026-10-01", 50], ["2026-10-20", 100], ["2026-10-25", 120], ["2026-10-28", 130]]
    assert stars_gained(history, "2026-10-28") == {"count": 30, "days": 8}
    # Less than a week of history: the window is as long as the history.
    assert stars_gained([["2026-10-26", 10], ["2026-10-28", 14]], "2026-10-28") == {"count": 4, "days": 2}
    assert stars_gained([["2026-10-28", 14]], "2026-10-28") is None
    # No stars this run (no API): history carries over unchanged.
    assert star_history({"stars": None}, {"stars_history": [["2026-10-27", 5]]}, "2026-10-28") == [["2026-10-27", 5]]


def test_star_history_is_capped():
    from skillsflow.build import HISTORY_DAYS, star_history

    old = [[f"2026-09-{d:02d}", d] for d in range(1, 31)]
    history = star_history({"stars": 99}, {"stars_history": old}, "2026-10-28")
    assert len(history) == HISTORY_DAYS and history[-1] == ["2026-10-28", 99]


def test_details_move_to_shards_and_the_catalog_keeps_a_summary(repos, tmp_path):
    import gzip

    from skillsflow.build import detail_bucket

    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\ntrusted_owners: [acme]\n")
    out = tmp_path / "dist"
    build(sources, out, LocalFetcher(repos), None, release_repo="o/r", release_tag="index-1")
    index = json.loads((out / "index.json").read_text())
    assert json.loads(gzip.decompress((out / "index.json.gz").read_bytes())) == index
    assert index["details"] == {"buckets": 256,
                                "url": "https://github.com/o/r/releases/download/index-1/details-{bucket}.json"}
    hooky = {p["id"]: p for p in index["plugins"]}["hooky@acme"]
    assert "files" not in hooky and "findings" not in hooky["security"]
    assert hooky["security"]["rules"]["pipe-to-shell"]["severity"] == "high"
    assert hooky["security"]["rules"]["pipe-to-shell"]["count"] == 1
    assert hooky["automatic"]["hooks"]  # what runs automatically stays in the catalog
    assert len(list((out / "details").glob("details-*.json"))) == 256
    shard = json.loads((out / "details" / f"details-{detail_bucket('hooky@acme')}.json").read_text())
    detail = shard["items"]["hooky@acme"]
    assert shard["schema_version"] == 2
    assert any(f["path"] == "scripts/run.sh" and len(f["sha"]) == 40 for f in detail["files"])
    assert any(f["rule"] == "pipe-to-shell" and f["excerpt"] for f in detail["findings"])
    assert detail["commit"] == hooky["commit"]
    pdf = json.loads((out / "details" / f"details-{detail_bucket('acme/skills:skills/pdf')}.json").read_text())
    assert {f["path"] for f in pdf["items"]["acme/skills:skills/pdf"]["files"]} == {"SKILL.md", "scripts/fill.py"}


def test_details_url_is_null_without_a_release(repos, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text("repos:\n  - acme/skills\n")
    assert build(sources, tmp_path / "dist", LocalFetcher(repos), None)["details"]["url"] is None


def test_detail_bucket_is_two_hex_digits_of_sha1():
    import hashlib

    from skillsflow.build import detail_bucket

    assert detail_bucket("hooky@acme") == hashlib.sha1(b"hooky@acme").hexdigest()[:2]
