"""Git extraction and deterministic rendering. Never modifies the source repository."""

import html
import json
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlsplit


class NotesError(Exception):
    """A user-facing input or Git error."""


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    author: str
    authored_at: str
    committed_at: str


@dataclass(frozen=True)
class Report:
    repository: str
    ref: str
    start: str
    end: str
    commits: List[Commit]
    remote_url: Optional[str]
    truncated: bool


CATEGORIES = (
    "Breaking changes", "Features", "Fixes", "Documentation", "Tests",
    "Refactoring", "Performance", "Maintenance", "Other changes",
)
TYPE_CATEGORIES = {
    "feat": "Features", "fix": "Fixes", "docs": "Documentation", "test": "Tests",
    "refactor": "Refactoring", "perf": "Performance", "build": "Maintenance",
    "ci": "Maintenance", "chore": "Maintenance", "style": "Maintenance",
    "revert": "Maintenance",
}
CONVENTIONAL = re.compile(r"^([a-z]+)(?:\(([^)]+)\))?(!)?:\s*(.+)$", re.IGNORECASE)


def git(repo: Path, *arguments: str, optional: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "-c", "log.showSignature=false", *arguments],
            check=False, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except FileNotFoundError as error:
        raise NotesError("Git is not installed or is not on PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise NotesError("Git did not finish within 30 seconds. Try a smaller date range.") from error
    if result.returncode:
        if optional:
            return ""
        # Git's raw stderr can contain paths or configuration; keep errors bounded.
        raise NotesError("Git could not read this repository or revision. Check --repo and --ref.")
    return result.stdout


def parse_day(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise NotesError("Dates must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise NotesError("Date is not a valid calendar day.") from error


def date_window(since: Optional[str], until: Optional[str], days: int, today: Optional[date] = None):
    if not 1 <= days <= 36500:
        raise NotesError("--days must be between 1 and 36500.")
    end = parse_day(until) if until else today or datetime.now(timezone.utc).date()
    try:
        start = parse_day(since) if since else end - timedelta(days=days - 1)
    except OverflowError as error:
        raise NotesError("Date range extends before year 1.") from error
    if start > end:
        raise NotesError("--since must be on or before --until.")
    if end == date.max:
        raise NotesError("--until must be earlier than 9999-12-31.")
    return start, end


def remote_web_url(remote: str) -> Optional[str]:
    remote = remote.strip()
    ssh = re.fullmatch(r"git@([^:]+):(.+)", remote)
    if ssh:
        remote = "https://" + ssh.group(1) + "/" + ssh.group(2)
    try:
        if remote.startswith("ssh://git@"):
            parsed = urlsplit(remote)
            remote = "https://" + (parsed.hostname or "") + parsed.path
        parsed = urlsplit(remote)
    except ValueError:
        return None
    # Commit links are supported only for hosts with a known /commit/<SHA> route.
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("github.com", "gitlab.com"):
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path.removesuffix(".git").rstrip("/")
    if len(path.strip("/").split("/")) < 2:
        return None
    return "https://" + parsed.hostname + quote(path, safe="/%")


def parse_log(output: str) -> List[Commit]:
    if not output.strip():
        return []
    fields = output.split("\0")
    # The format ends every record with NUL and git adds a record newline.
    if fields[-1].strip():
        raise NotesError("Git returned an unexpected history format.")
    fields.pop()
    if len(fields) % 5:
        raise NotesError("Git returned an unexpected history format.")
    commits = []
    for index in range(0, len(fields), 5):
        sha, subject, author, authored_at, committed_at = fields[index:index + 5]
        sha = sha.strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            raise NotesError("Git returned an invalid commit identifier.")
        commits.append(Commit(sha, subject, author, authored_at, committed_at))
    return commits


def collect(repo: Path, ref: str, start: date, end: date, limit: int = 500,
            author: Optional[str] = None, include_merges: bool = False, links: bool = True) -> Report:
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise NotesError("--repo must be an existing directory containing a Git repository.")
    if not 1 <= limit <= 10000:
        raise NotesError("--limit must be between 1 and 10000.")
    root = git(repo, "rev-parse", "--show-toplevel").strip()
    # Resolve user input before passing it to log; option-like revisions stay data.
    sha = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()
    after = datetime.combine(start, time.min, timezone.utc).isoformat()
    before = datetime.combine(end + timedelta(days=1), time.min, timezone.utc).isoformat()
    arguments = ["log", "--format=%H%x00%s%x00%an%x00%aI%x00%cI%x00", "--date-order",
                 "--since-as-filter=" + after, "--until=" + before, sha, "--"]
    if not include_merges:
        arguments.insert(1, "--no-merges")
    # --since-as-filter visits all reachable commits, including out-of-order dates.
    commits = parse_log(git(repo, *arguments))
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    start_inclusive = datetime.combine(start, time.min, timezone.utc)
    # Git's upper-bound filter is inclusive. Enforce an exact exclusive next-day
    # boundary using committer timestamps so midnight is never double-counted.
    commits = [commit for commit in commits
               if start_inclusive <= datetime.fromisoformat(commit.committed_at.replace("Z", "+00:00")) < end_exclusive
               and (author is None or author.casefold() in commit.author.casefold())]
    truncated = len(commits) > limit
    commits = commits[:limit]
    remote = git(repo, "config", "--get", "remote.origin.url", optional=True) if links else ""
    return Report(Path(root).name, ref, start.isoformat(), end.isoformat(), commits,
                  remote_web_url(remote) if links else None, truncated)


def classify(subject: str):
    match = CONVENTIONAL.match(subject)
    if not match:
        return "Other changes", subject
    kind, scope, breaking, text = match.groups()
    category = "Breaking changes" if breaking else TYPE_CATEGORIES.get(kind.lower(), "Other changes")
    return category, (scope + ": " if scope else "") + text


def markdown_escape(text: str) -> str:
    # Commit text is untrusted input. Remove control characters and neutralize HTML,
    # Markdown syntax, headings, link injection, and image syntax.
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_{}\[\]<>()#+.!|~\-])", r"\\\1", text)


def render_markdown(report: Report) -> str:
    authors = Counter(commit.author for commit in report.commits)
    text = "# Ship Notes — " + markdown_escape(report.repository) + "\n\n"
    commit_label = "commit" if len(report.commits) == 1 else "commits"
    author_label = "contributor" if len(authors) == 1 else "contributors"
    text += f"{report.start} → {report.end} · UTC calendar days · {len(report.commits)} {commit_label} · {len(authors)} {author_label}\n\n"
    text += "Revision: " + markdown_escape(report.ref) + "\n\n"
    if report.truncated:
        text += "> This report reached its commit limit. Increase --limit to include the full period.\n\n"
    if not report.commits:
        text += "No matching commits in this period.\n"
        return text
    grouped = {category: [] for category in CATEGORIES}
    for commit in report.commits:
        category, title = classify(commit.subject)
        grouped[category].append((commit, title))
    for category, entries in grouped.items():
        if not entries:
            continue
        text += "## " + category + "\n\n"
        for commit, title in entries:
            short = commit.sha[:7]
            reference = "`" + short + "`"
            if report.remote_url:
                route = "/-/commit/" if urlsplit(report.remote_url).hostname == "gitlab.com" else "/commit/"
                reference = "[" + short + "](" + report.remote_url + route + quote(commit.sha) + ")"
            text += "- " + markdown_escape(title) + " — " + markdown_escape(commit.author) + " (" + reference + ")\n"
        text += "\n"
    text += "## Contributors\n\n"
    for name, count in sorted(authors.items(), key=lambda item: (-item[1], item[0].casefold())):
        text += "- " + markdown_escape(name) + f": {count} commit{'s' if count != 1 else ''}\n"
    text += "\n_Generated from commit subjects. Categories reflect message prefixes; review before sharing._\n"
    return text


def render_json(report: Report) -> str:
    data = asdict(report)
    data["timezone"] = "UTC"
    data["date_basis"] = "committer"
    for commit in data["commits"]:
        commit["category"], commit["title"] = classify(commit["subject"])
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
