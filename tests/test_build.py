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
    assert index["schema_version"] == 1
    skills = {s["id"]: s for s in index["skills"]}
    assert skills["acme/skills:skills/pdf"]["first_seen"] == "2026-01-01"
    assert skills["acme/skills:skills/brand"]["first_seen"] == index["generated_at"][:10]
    # The plugin's marketplace category wins over keywords.
    assert skills["acme/skills:skills/brand"]["category"] == "Productivity"
    assert skills["acme/skills:skills/unlisted"]["install"]["plugins"] == []
    assert skills["acme/skills:skills/pdf"]["install"]["copy"]["target"] == "~/.claude/skills/pdf"
    assert (out / "SUMMARY.md").read_text().startswith("# SkillsFlow index")
