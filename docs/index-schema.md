# index.json schema (version 1)

`index.json` is one JSON object. `index.pretty.json` is the same data, indented. IDs are stable across runs, so the app can track installs and "first seen" dates by ID.

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
| `errors` | object[] | Repos or entries that failed, with `repo` and `error`. |

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
| `trust` | `official` or `community` | `official` when the repo owner is in `trusted_owners`. |
| `stars`, `repo_pushed_at` | int / string or null | From the GitHub API, when available. |
| `plugins` | string[] | IDs of plugins that load this skill. |
| `category` | string | |
| `first_seen` | string | `YYYY-MM-DD`. |
| `install.plugins` | string[] | `claude plugin install …` commands. Empty if the skill isn't in a plugin. |
| `install.copy` | object | `repo`, `path`, `commit`, and `target` (`~/.claude/skills/<folder>`), for installing the folder directly. |

### File

`path` (relative to the skill folder), `size` (bytes), `kind` (`doc`, `script`, `data`, `asset`, `archive`, `binary`), `executable` (bool).

### Security

| Field | Type | Notes |
|---|---|---|
| `risk` | `low`, `medium`, `high` | See the README for how it's set. |
| `scripts`, `binaries` | int | Counts of script files and binary or archive files. |
| `findings` | Finding[] | At most 5 per rule. |
| `runs_code_automatically` | string[] | Plugins only: any of `hooks`, `mcp_servers`, `lsp_servers`, `monitors`, `bin`. |

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
| `trust` | string | The marketplace's trust level. |
| `indexed` | bool | Whether SkillsFlow fetched the plugin's files. When `false`, the fields below are empty. |
| `repo`, `path`, `commit` | string | Where the plugin's files were read. |
| `manifest_name` | string | `plugin.json` `name`, which prefixes the plugin's skills (`/manifest-name:skill`). |
| `skills` | string[] | Skill IDs this plugin loads. |
| `components` | object | `skills`, `commands`, `agents` (counts), and `hooks`, `mcp_servers`, `lsp_servers`, `monitors`, `bin` (bools). |
| `security` | Security or null | Scan of the plugin's files outside its skill folders. |
| `stars`, `first_seen` | | As for skills. |

## Marketplace

`name`, `repo`, `commit`, `description`, `owner`, `trust`, `add_command` (`claude plugin marketplace add owner/repo`), and `plugins` (plugin IDs).

## Repo

`slug`, `commit`, and, when the GitHub API is available, `description`, `stars`, `forks`, `pushed_at`, `archived`, `fork`, `license`, `default_branch`, `topics`, `owner_type`.
