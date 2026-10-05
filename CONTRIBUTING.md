# Contributing

Use Python 3.9+ and Git 2.37+. The package has no runtime dependencies.

```bash
python3 -m unittest discover -v
python3 -m ship_notes --help
```

Tests use disposable repositories with fixed timestamps. Keep regression tests independent of your own Git configuration and machine's timezone. Do not change or backdate commits in the actual project to exercise behavior; use temporary test fixtures.

Keep extraction in `ship_notes/core.py` and command-line behavior in `ship_notes/cli.py`. Preserve read-only repository access, literal author matching, explicit truncation, and output-file protection.

For issues and pull requests, describe the problem, expected output, and checks you ran. Redact private commit subjects and repository URLs from example reports.
