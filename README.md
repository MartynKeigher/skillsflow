# SkillsFlow

SkillsFlow builds the catalog behind [SkillsHub](https://github.com/MartynKeigher/skillshub), a Mac app for browsing and installing Claude Skills and Claude Code plugins.

There's no single official list of skills, so SkillsFlow makes one. Every day a GitHub Action crawls known repositories and plugin marketplaces, reads each skill, scans its files for risky patterns, and publishes the result as `index.json` on this repo's [latest release](https://github.com/MartynKeigher/skillsflow/releases/latest).

The app downloads it from:

```
https://github.com/MartynKeigher/skillsflow/releases/latest/download/index.json.gz
```

File lists and full security findings are published next to it in 256 `details-<bb>.json` files, so the catalog stays small enough to download daily and ship inside the app. The app fetches the one it needs when you open an item.

## What it collects

- **Skills**: every `SKILL.md` in a crawled repo, with its name, description, files (each with its git hash), the commit it was read at, and how to install it (as a plugin, or by copying the folder into `~/.claude/skills/`).
- **Plugins**: every entry in every crawled `.claude-plugin/marketplace.json`, with its files, the skills it loads, and the exact commands its hooks, MCP servers, LSP servers, monitors, mods and `bin/` executables run.
- **Marketplaces**: name, repo, and the `claude plugin marketplace add` command.
- **Who made it and where it's listed**: whether Anthropic made it, and separately whether it's in one of Anthropic's marketplaces. Most plugins in Anthropic's marketplaces come from partners and other authors.
- **Popularity and freshness**: GitHub stars, a 30-day star history and recent star gain for each repo, the date each skill or plugin was added to its repo (from recent git history), and the date it first appeared in the index.
- **Featured picks**: the hand-picked list in [`featured.yaml`](featured.yaml).
- **Categories**: the marketplace's own category when it has one, otherwise a keyword match.

The full format is in [docs/index-schema.md](docs/index-schema.md).

## Security scan

Skills aren't reviewed before they're published, and they can include scripts that Claude runs. SkillsFlow checks every file in each skill and plugin for patterns such as piping downloads into a shell, reading SSH keys or cloud credentials, editing shell startup files, decoding hidden code, and shipping binaries. Each skill and plugin gets a `low`, `medium` or `high` level:

- **high**: at least one high-severity pattern in code.
- **medium**: a medium-severity pattern, any bundled scripts, or a plugin that runs code automatically (hooks, MCP or LSP servers, monitors, `bin/`).
- **low**: none of the above.

The scan is a heuristic. It flags things for a person to look at; it doesn't prove that anything is safe or malicious. Matches in comments count as low, and matches in Markdown drop one level because prose often warns *against* a pattern.

## Where skills come from

[`sources.yaml`](sources.yaml) lists the seed repos. From there SkillsFlow:

1. Indexes every skill in each seed repo, plus its marketplace if it has one.
2. Follows marketplace entries that point at other GitHub repos (`github`, `url` and `git-subdir` sources) and indexes the plugin found there, fetching several at a time and deleting each batch once it's read. `npm`, `archive` and `command` sources are listed but not crawled.
3. If a token is available, uses GitHub code search to find more repos with `SKILL.md` files or marketplaces, keeping non-fork, non-archived repos above a star threshold.

To add a repo, open a pull request that adds it to `sources.yaml`. To keep one out, add it to `denylist`. To change the featured picks, edit `featured.yaml`.

## Run it locally

Needs Python 3.11+ and git.

```bash
pip install -r requirements-dev.txt
```

```bash
python -m skillsflow build --sources sources.yaml --out dist
```

Useful flags:

- `--offline-metadata`: skip the GitHub API (no stars, no discovery). Handy without a token.
- `--repo owner/name`: crawl an extra repo for this run.
- `--previous path-or-url`: an earlier `index.json`, so first-seen dates, added dates and star history carry over.
- `--featured path`: the featured picks (default: `featured.yaml` next to `--sources`).
- `--cache dir`: where to put checkouts while crawling (default: a temp folder). Each is deleted once it has been read.

Set `GITHUB_TOKEN` to get star counts and discovery.

Run the tests with:

```bash
python -m pytest
```

## Publishing

`.github/workflows/publish-index.yml` runs daily and on demand. It downloads the previous `index.json`, builds a new one, publishes it with its detail files as a release tagged `index-YYYY-MM-DD-HHMM`, and keeps the 30 newest. Add a fine-grained personal access token with public repository read access as the `SKILLSFLOW_TOKEN` secret. It's needed for code-search discovery, and for star counts: the crawl looks up about 2,000 repositories, more than the workflow's own token is allowed per hour. Without it, star counts stop when that limit is reached.

## Credits

Modeled on [CaskFlow](https://github.com/alielsokary/CaskFlow), the data pipeline behind [CaskHub](https://github.com/alielsokary/CaskHub).

## License

MIT
