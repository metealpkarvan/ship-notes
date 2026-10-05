# Ship Notes

**You did the work. Keep a readable record.** Turn a Git repository's real commits into organized Markdown progress notes.

[![Tests](https://github.com/metealpkarvan/ship-notes/actions/workflows/ci.yml/badge.svg)](https://github.com/metealpkarvan/ship-notes/actions/workflows/ci.yml)

Useful for a Friday recap, a project journal, or a first draft of release notes. Runs locally, reads Git history, and needs no AI service, credentials, or network connection.

## Quick start

Requires **Python 3.9+** and **Git 2.37+**. Python 3.13+ is recommended. Use a repository with at least one commit.

```bash
git clone https://github.com/metealpkarvan/ship-notes.git
cd ship-notes
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .

# Inspect any of your repositories.
ship-notes --repo ~/projects/my-app --days 7
ship-notes --repo ~/projects/my-app --days 7 --output weekly-notes.md
```

On Windows, create the environment with `py -m venv .venv` and activate with `.venv\Scripts\Activate.ps1` in PowerShell.

You can also run directly from this checkout without installing:

```bash
python3 -m ship_notes --repo ../link-loom --days 7
```

## Example

Conventional Commit subjects such as `feat(search): add filters` and `fix: handle empty input` become:

```markdown
## Features

- search: add filters — Mete (abc1234)

## Fixes

- handle empty input — Mete (def5678)
```

Those identifiers are illustrative. [examples/link-loom.md](examples/link-loom.md) is a generated report from the companion project's actual history.

## Handy commands

```bash
# An inclusive date range, using UTC calendar days and committer dates.
ship-notes --since 2026-01-01 --until 2026-01-31

# Your work on another branch; author matching is a literal substring.
ship-notes --ref main --author "Mete" --days 14

# Plain identifiers instead of remote repository links.
ship-notes --no-links --output journal.md

# Machine-readable output for another tool.
ship-notes --format json --output journal.json

# Include merge commits or raise the report size limit.
ship-notes --include-merges --limit 1000

# Replace an existing report intentionally.
ship-notes --output journal.md --force
```

## How it works

The tool resolves the selected revision and reads reachable Git commits. It groups subject prefixes into features, fixes, documentation, tests, refactoring, performance, and maintenance. The `!` marker puts a subject under breaking changes; ordinary messages go into other changes. Contributor counts and commit identifiers provide a trail back to the work.

The default range is **seven UTC calendar days, including today**, rather than the last 168 hours. `--since` overrides the start calculated from `--days`. The last day is inclusive. Committer timestamps decide membership; author timestamps are retained in JSON. Out-of-order timestamps are visited with Git's `--since-as-filter`.

Merge commits are excluded by default. An author filter matches names case-insensitively and does not interpret regex syntax. GitHub and GitLab HTTPS/SSH origins produce commit links; origins containing HTTP credentials and unsupported hosts produce plain hashes. The tool does not contact those hosts.

## Boundaries you can rely on

- Reads committed history only. It does not inspect source contents or include uncommitted work.
- Categories come from subjects, not code analysis. `BREAKING CHANGE` in a commit body is not inspected. Review notes before sharing them.
- Reports include author names, commit subjects, dates, and optional repository links. Use `--no-links` when those URLs should stay private.
- Default output limit: 500 matching commits; configurable from 1 to 10,000. A truncated report is marked in both Markdown/JSON and stderr.
- A Git subprocess times out after 30 seconds. Large histories may need narrower ranges.
- Existing files are preserved unless `--force` is supplied. Forced replacements are atomic and symbolic links are refused.
- Exit status `0` means a report was produced, including an empty or explicitly truncated report. `2` means an input, Git, or file error.

## Development

```bash
python3 -m unittest discover -v
```

No runtime or test dependencies. Tests create temporary Git repositories to verify date boundaries, timezones, author filtering, merge handling, revisions, truncation, and read-only behavior. Other tests verify safe Markdown, remote URL handling, JSON, and output-file protection.

CI checks multiple Python versions and Ubuntu, macOS, and Windows, including package installation and the installed CLI. See [CONTRIBUTING.md](CONTRIBUTING.md).

**Türkçe:** Git commit geçmişinden okunabilir ilerleme notları çıkarır. Haftalık özetler ve proje günlükleri için küçük, yerel çalışan bir komut satırı aracı.

MIT © Mete Alp Karvan
