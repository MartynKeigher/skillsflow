# index.json schema (version 1)

`index.json` is one JSON object. `index.pretty.json` is the same data, indented. IDs are stable across runs, so the app can track installs and "first seen" dates by ID.

Fields are only ever added within a schema version, so a reader should ignore fields it doesn't know.

## Who made it and where it's listed

`publisher` and `listed_by_anthropic` answer two different questions, and a client should show them separately:

- `publisher` is who made the item: `anthropic` when the repository its files come from belongs to an owner in `trusted_owners`, otherwise `third_party`. A plugin whose files weren't fetched and whose source isn't a GitHub repository is `third_party`, because its maker is unknown.
- `listed_by_anthropic` is whether the item is in a marketplace whose repository Anthropic owns, such as `claude-plugins-official` or `claude-community`. Most plugins listed there are made by partners and other authors, so this doesn't mean Anthropic made or reviewed it.

`trust` is the older single field. For plugins it is the marketplace's trust level, so a third-party plugin in Anthropic's marketplace reads `official`. Use `publisher` and `listed_by_anthropic` instead.

## Top level

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | `1`. Bumped on breaking changes. |
| `generated_at` | string | UTC ISO 8601 timestamp. |
| `generator` | string | e.g. `skillsflow 0.1.0`. |
| `counts` | object | `skills`, `plugins`, `marketplaces`, `repos`. |
| `categories` | string[] | Every category, in display order. |
| `marketplaces` | Marketplace[] | |
| `plugins` | Plugin[] | |
| `skills` | Skill[] | |
| `repos` | Repo[] | |
| `featured` | Featured[] | Curated picks from `featured.yaml`, in display order. |
| `errors` | object[] | Repos or entries that failed, with `repo` and `error`. |

### Featured

`id` (a skill or plugin ID in this index), `kind` (`skill` or `plugin`), and `note` (a one-line reason, or null). IDs that aren't in the index are left out.

## Skill

| Field | Type | Notes |
|---|---|---|
| `id` | string | `owner/repo:path/to/skill`, or `owner/repo` when `SKILL.md` is at the repo root. |
| `name` | string | Frontmatter `name`, else the folder name. |
| `description` | string | Frontmatter `description` (plus `when_to_use`), else the first line of the body. |
| `license` | string or null | Frontmatter `license`. |
| `repo`, `path`, `commit` | string | Where the skill was read. `path` is `""` at the repo root. |
| `url` | string | GitHub link to the folder at that commit. |
| `frontmatter` | object | Other frontmatter fields, such as `allowed-tools`. |
| `lines` | int | Length of the `SKILL.md` body. |
| `files` | File[] | Every file in the skill folder. |
| `security` | Security | |
| `trust` | `official` or `community` | `official` when the repo owner is in `trusted_owners`. Superseded by `publisher`. |
| `publisher` | `anthropic` or `third_party` | Who made it. See [above](#who-made-it-and-where-its-listed). |
| `listed_by_anthropic` | bool | Whether a plugin that loads this skill is in a marketplace Anthropic owns. |
| `stars`, `repo_pushed_at` | int / string or null | From the GitHub API, when available. Stars are the repository's, shared by every skill in it. |
| `stars_gained` | StarsGained or null | Stars the repository gained recently. See [Repo](#repo). |
| `plugins` | string[] | IDs of plugins that load this skill. |
| `category` | string | |
| `first_seen` | string | `YYYY-MM-DD`, the first day this skill was in the index. |
| `added` | string or null | `YYYY-MM-DD`, when the commit that added its `SKILL.md` was made. Null when that was before the history SkillsFlow reads (about 120 days), so the skill isn't new. Once found, it carries over between runs. |
| `install.plugins` | string[] | `claude plugin install …` commands. Empty if the skill isn't in a plugin. |
| `install.copy` | object | `repo`, `path`, `commit`, and `target` (`~/.claude/skills/<folder>`), for installing the folder directly. |

### File

`path` (relative to the skill or plugin folder), `size` (bytes), `sha` (the git blob SHA-1 of the contents, as `git hash-object` prints it: SHA-1 of `blob <size>\0` followed by the bytes), `kind` (`doc`, `script`, `data`, `asset`, `archive`, `binary`), `executable` (bool).

A client can hash a downloaded or installed file the same way to check it matches the index, or to tell whether a user has edited it.

### Security

| Field | Type | Notes |
|---|---|---|
| `risk` | `low`, `medium`, `high` | See the README for how it's set. |
| `scripts`, `binaries` | int | Counts of script files and binary or archive files. |
| `findings` | Finding[] | At most 5 per rule. |
| `runs_code_automatically` | string[] | Plugins only: any of `hooks`, `mcp_servers`, `lsp_servers`, `monitors`, `mods`, `bin`. |

A Finding has `rule`, `severity`, `summary`, `file`, `line`, `excerpt`, and `context` (`code`, `comment`, `documentation`, `file`).

## Plugin

| Field | Type | Notes |
|---|---|---|
| `id` | string | `name@marketplace`, the same ID `claude plugin install` takes. |
| `name`, `marketplace` | string | |
| `display_name`, `description`, `version`, `author`, `homepage`, `license` | string or null | From the marketplace entry, falling back to `plugin.json`. |
| `category` | string | |
| `marketplace_category` | string or null | The raw category from the marketplace. |
| `tags` | string[] | Entry `tags`/`keywords` plus `plugin.json` `keywords`. |
| `source` | object | `type` (`relative`, `github`, `url`, `git-subdir`, `npm`, `archive`, `command`) and its fields. |
| `install_command` | string | `claude plugin install <id>`. |
| `trust` | string | The marketplace's trust level. Superseded by `publisher` and `listed_by_anthropic`. |
| `publisher` | `anthropic` or `third_party` | Who made it, from the repository its files come from. |
| `listed_by_anthropic` | bool | Whether its marketplace's repository is Anthropic's. |
| `indexed` | bool | Whether SkillsFlow fetched the plugin's files. When `false`, the fields below are empty. |
| `repo`, `path`, `commit` | string | Where the plugin's files were read. |
| `manifest_name` | string | `plugin.json` `name`, which prefixes the plugin's skills (`/manifest-name:skill`). |
| `skills` | string[] | Skill IDs this plugin loads. |
| `files` | File[] | Every file in the plugin folder except those inside the folders of its own `skills`, which each skill lists. Together they are everything Claude Code copies when it installs the plugin. Empty when the plugin is a single skill at its root. |
| `components` | object | `skills`, `commands`, `agents` (counts), and `hooks`, `mcp_servers`, `lsp_servers`, `monitors`, `mods`, `bin` (bools). |
| `automatic` | Automatic or null | What the plugin runs on its own once enabled, read from its files and manifest. |
| `security` | Security or null | Scan of `files`. Combine it with the scan of each of its skills for the plugin's overall risk. |
| `stars`, `stars_gained`, `first_seen` | | As for skills. |
| `added` | string or null | As for skills, from the plugin's `.claude-plugin/plugin.json`, or `SKILL.md` for a single-skill plugin. Null when neither date is known. |

### Automatic

What starts without Claude choosing a skill. Each list holds at most 50 entries, and each `command` at most 500 characters. `file` is where the entry is declared, relative to the plugin folder; inline manifest values read `.claude-plugin/plugin.json`.

| Field | Entries |
|---|---|
| `hooks` | `event`, `matcher` (or null), `type` (`command`, `http`, `prompt`, `agent`, …), `command` (the command line, URL or prompt), `file` |
| `mcp_servers` | `name`, `type` (`stdio`, `http`, `sse`), `command` (command line or URL), `env` (variable names only), `file` |
| `lsp_servers` | `name`, `type`, `command`, `env`, `file` |
| `monitors` | `name`, `command`, `file` |
| `mods` | `module` (JavaScript module that runs inside Claude Code), `file` |
| `bin` | File names in `bin/`, which Claude can run as commands |

## Marketplace

`name`, `repo`, `commit`, `description`, `owner`, `trust`, `publisher` (`anthropic` when the marketplace repository is Anthropic's), `add_command` (`claude plugin marketplace add owner/repo`), and `plugins` (plugin IDs).

## Repo

`slug`, `commit`, and, when the GitHub API is available, `description`, `stars`, `forks`, `pushed_at`, `archived`, `fork`, `license`, `default_branch`, `topics`, `owner_type`.

- `stars_history`: `[[date, stars], ...]`, oldest first, one entry per run for up to 30 runs, carried over from the previous index.
- `stars_gained` (StarsGained or null): `count`, the stars gained since the newest history entry at least 7 days old (or since the oldest entry, when the history is shorter), and `days`, the length of that window. Null until there are two entries. Use it for trending lists; `days` says when the window is shorter than a week.
