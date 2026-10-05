"""Command-line entry point for ship-notes."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .core import NotesError, collect, date_window, render_json, render_markdown


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Turn real Git commits into tidy progress notes. Read-only, offline, no AI service.")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository or a directory inside it (default: current directory)")
    result.add_argument("--ref", default="HEAD", help="Branch, tag, or revision to inspect (default: HEAD)")
    result.add_argument("--days", type=int, default=7, help="Number of UTC calendar days ending at --until (default: 7)")
    result.add_argument("--since", help="First included UTC day, YYYY-MM-DD; overrides --days")
    result.add_argument("--until", help="Last included UTC day, YYYY-MM-DD (default: today)")
    result.add_argument("--author", help="Case-insensitive substring of author name, not a regex")
    result.add_argument("--include-merges", action="store_true", help="Include merge commits (excluded by default)")
    result.add_argument("--no-links", action="store_true", help="Omit remote URLs and use plain commit IDs")
    result.add_argument("--limit", type=int, default=500, help="Maximum commits in report, 1–10000 (default: 500)")
    result.add_argument("--format", choices=("markdown", "json"), default="markdown")
    result.add_argument("--output", type=Path, help="Write to a new file instead of stdout; use --force to replace")
    result.add_argument("--force", action="store_true", help="Allow replacing an existing output file")
    return result


def write_output(path: Path, text: str, force: bool) -> None:
    path = path.expanduser()
    if not force:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as file:
                file.write(text)
        except FileExistsError as error:
            raise NotesError("Output file already exists. Choose a new path or use --force.") from error
        return
    if path.is_symlink():
        raise NotesError("Refusing to overwrite a symbolic link.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        start, end = date_window(args.since, args.until, args.days)
        report = collect(args.repo, args.ref, start, end, args.limit, args.author,
                         args.include_merges, not args.no_links)
        text = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output:
            write_output(args.output, text, args.force)
        else:
            sys.stdout.write(text)
        if report.truncated:
            print("ship-notes: commit limit reached; report is incomplete. Increase --limit.", file=sys.stderr)
        return 0
    except (NotesError, OSError, ValueError) as error:
        print("ship-notes: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
