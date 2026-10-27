from skillsflow import frontmatter


def test_parses_fields_and_body():
    fields, body = frontmatter.parse("---\nname: x\ndescription: does x\n---\n# Title\nbody")
    assert fields == {"name": "x", "description": "does x"}
    assert body.startswith("# Title")


def test_requires_dashes_on_first_line():
    fields, body = frontmatter.parse("\n---\nname: x\n---\n")
    assert fields == {}


def test_bad_yaml_yields_no_fields():
    fields, body = frontmatter.parse("---\nname: [unclosed\n---\nhello")
    assert fields == {}
    assert body == "hello"


def test_first_line_skips_heading_marks():
    assert frontmatter.first_line("\n\n## Hello there\nmore") == "Hello there"
