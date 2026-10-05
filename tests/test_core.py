import json
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ship_notes.core import (
    Commit, NotesError, Report, classify, collect, date_window, git, markdown_escape,
    parse_day, parse_log, remote_web_url, render_json, render_markdown,
)


class DateTests(unittest.TestCase):
    def test_default_window_is_seven_inclusive_days(self):
        self.assertEqual(date_window(None, None, 7, date(2026, 3, 8)), (date(2026, 3, 2), date(2026, 3, 8)))

    def test_one_day_window(self):
        self.assertEqual(date_window(None, "2026-03-08", 1), (date(2026, 3, 8), date(2026, 3, 8)))

    def test_explicit_start_overrides_days(self):
        self.assertEqual(date_window("2026-01-01", "2026-01-03", 7), (date(2026, 1, 1), date(2026, 1, 3)))

    def test_rejects_invalid_date_and_ranges(self):
        for value in ["2026-02-30", "01/01/2026", "20260101", "today"]:
            with self.subTest(value=value), self.assertRaises(NotesError):
                parse_day(value)
        for since, until, days in [("2026-02-01", "2026-01-01", 1), (None, None, 0),
                                   (None, None, 36501), (None, "0001-01-01", 7),
                                   (None, "9999-12-31", 1)]:
            with self.subTest(since=since, until=until, days=days), self.assertRaises(NotesError):
                date_window(since, until, days)


class RenderTests(unittest.TestCase):
    def report(self, commits=None, remote="https://github.com/demo/project", truncated=False):
        commits = commits if commits is not None else [
            Commit("a" * 40, "feat(search): add filters", "Mete", "2026-01-02T12:00:00Z", "2026-01-02T12:00:00Z"),
            Commit("b" * 40, "fix: handle empty input", "Mete", "2026-01-03T12:00:00Z", "2026-01-03T12:00:00Z"),
        ]
        return Report("demo", "main", "2026-01-01", "2026-01-07", commits, remote, truncated)

    def test_conventional_categories_and_scopes(self):
        self.assertEqual(classify("feat(api): add endpoint"), ("Features", "api: add endpoint"))
        self.assertEqual(classify("fix!: remove legacy option"), ("Breaking changes", "remove legacy option"))
        self.assertEqual(classify("ci: run checks"), ("Maintenance", "run checks"))
        self.assertEqual(classify("DOCS: usage"), ("Documentation", "usage"))
        self.assertEqual(classify("a normal message"), ("Other changes", "a normal message"))
        self.assertEqual(classify("custom: update"), ("Other changes", "update"))

    def test_markdown_groups_and_links_real_commits(self):
        text = render_markdown(self.report())
        self.assertIn("## Features", text)
        self.assertIn("## Fixes", text)
        self.assertIn("Mete: 2 commits", text)
        self.assertIn("https://github.com/demo/project/commit/" + "a" * 40, text)
        self.assertIn("2 commits · 1 contributor", text)

    def test_markdown_without_remote_uses_plain_hashes(self):
        self.assertIn("`aaaaaaa`", render_markdown(self.report(remote=None)))

    def test_gitlab_links_use_correct_route(self):
        self.assertIn("/-/commit/", render_markdown(self.report(remote="https://gitlab.com/team/project")))

    def test_escapes_untrusted_messages_and_names(self):
        bad = Commit("c" * 40, 'fix: <img src=x> [click](bad)\x1b', '*name*', "", "")
        text = render_markdown(self.report([bad]))
        self.assertNotIn("<img", text)
        self.assertNotIn("[click](bad)", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("\\*name\\*", text)
        self.assertEqual(markdown_escape("# x\n<script>"), "\\# x &lt;script&gt;")

    def test_empty_period_is_explicit(self):
        text = render_markdown(self.report([]))
        self.assertIn("No matching commits", text)
        self.assertNotIn("## Features", text)

    def test_truncation_is_visible(self):
        self.assertIn("reached its commit limit", render_markdown(self.report(truncated=True)))

    def test_json_is_machine_readable_with_date_basis(self):
        data = json.loads(render_json(self.report()))
        self.assertEqual(data["date_basis"], "committer")
        self.assertEqual(data["timezone"], "UTC")
        self.assertEqual(data["commits"][0]["category"], "Features")
        self.assertEqual(data["commits"][0]["sha"], "a" * 40)

    def test_supported_remote_formats(self):
        for remote in ["git@github.com:demo/project.git", "https://github.com/demo/project.git",
                       "ssh://git@github.com/demo/project.git"]:
            with self.subTest(remote=remote):
                self.assertEqual(remote_web_url(remote), "https://github.com/demo/project")

    def test_remote_credentials_and_unknown_routes_are_not_exported(self):
        for remote in ["https://user:token@github.com/demo/project.git", "/local/path", "file:///tmp/repo",
                       "https://github.com/demo/project?token=secret", "https://example.com/demo/project",
                       "ssh://git@[broken", "https://github.com/one"]:
            with self.subTest(remote=remote):
                self.assertIsNone(remote_web_url(remote))

    def test_remote_path_cannot_inject_markdown(self):
        self.assertEqual(remote_web_url("https://github.com/demo/proj)ect"), "https://github.com/demo/proj%29ect")

    def test_log_parser_handles_record_newlines_and_unicode(self):
        raw = "\0".join(["a" * 40, "feat: çay", "Mete", "2026-01-01T12:00:00Z", "2026-01-01T12:00:00Z", "\n"])
        self.assertEqual(parse_log(raw)[0].subject, "feat: çay")
        self.assertEqual(parse_log(""), [])
        for broken in ["truncated", "x\0y\0", "\0".join(["bad-sha", "title", "name", "date", "date", "\n"])]:
            with self.subTest(broken=broken), self.assertRaises(NotesError):
                parse_log(broken)


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "sample"
        self.repo.mkdir()
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Mete")
        self.run_git("config", "user.email", "demo@example.invalid")
        self.run_git("config", "commit.gpgsign", "false")

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, env=env).stdout

    def commit(self, subject, when, author="Mete", authored=None):
        env = dict(os.environ, GIT_AUTHOR_DATE=authored or when, GIT_COMMITTER_DATE=when,
                   GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL="demo@example.invalid")
        self.run_git("commit", "--allow-empty", "-m", subject, env=env)

    def collect(self, **kwargs):
        return collect(self.repo, kwargs.pop("ref", "HEAD"), date(2026, 1, 1), date(2026, 1, 7), **kwargs)

    def test_inclusive_utc_boundaries_and_committer_date_basis(self):
        self.commit("before", "2025-12-31T23:59:59Z")
        self.commit("feat: start", "2026-01-01T00:00:00Z")
        self.commit("fix: last", "2026-01-07T23:59:59Z", authored="2025-06-01T12:00:00Z")
        self.commit("after", "2026-01-08T00:00:00Z")
        self.assertEqual([entry.subject for entry in self.collect().commits], ["fix: last", "feat: start"])

    def test_timezone_offset_is_converted_to_utc(self):
        self.commit("outside", "2026-01-01T01:00:00+03:00")
        self.commit("inside", "2026-01-08T02:00:00+03:00")
        self.assertEqual([entry.subject for entry in self.collect().commits], ["inside"])

    def test_out_of_order_dates_are_not_skipped(self):
        self.commit("in range", "2026-01-03T12:00:00Z")
        self.commit("old timestamp on new commit", "2025-10-01T12:00:00Z")
        self.assertEqual([entry.subject for entry in self.collect().commits], ["in range"])

    def test_author_is_a_literal_case_insensitive_substring(self):
        self.commit("one", "2026-01-01T12:00:00Z", author="Mete [dev]")
        self.commit("two", "2026-01-02T12:00:00Z", author="Ada")
        self.assertEqual(len(self.collect(author="[DEV]").commits), 1)
        self.assertEqual(len(self.collect(author=".*").commits), 0)

    def test_limit_is_explicit_and_detects_incomplete_reports(self):
        for day in range(1, 4):
            self.commit(str(day), f"2026-01-0{day}T12:00:00Z")
        report = self.collect(limit=2)
        self.assertEqual(len(report.commits), 2)
        self.assertTrue(report.truncated)
        self.assertFalse(self.collect(limit=3).truncated)

    def test_can_inspect_another_branch_and_a_subdirectory(self):
        self.commit("base", "2026-01-01T12:00:00Z")
        self.run_git("branch", "original")
        self.commit("later", "2026-01-02T12:00:00Z")
        self.assertEqual(len(self.collect(ref="original").commits), 1)
        folder = self.repo / "nested"
        folder.mkdir()
        self.assertEqual(collect(folder, "HEAD", date(2026, 1, 1), date(2026, 1, 7)).repository, "sample")

    def test_never_modifies_working_tree(self):
        self.commit("initial", "2026-01-01T12:00:00Z")
        (self.repo / "private.txt").write_text("uncommitted content", encoding="utf-8")
        before = self.run_git("status", "--porcelain")
        self.collect()
        self.assertEqual(self.run_git("status", "--porcelain"), before)
        self.assertEqual((self.repo / "private.txt").read_text(), "uncommitted content")

    def test_remote_can_be_omitted(self):
        self.commit("one", "2026-01-01T12:00:00Z")
        self.run_git("remote", "add", "origin", "git@github.com:demo/project.git")
        self.assertEqual(self.collect().remote_url, "https://github.com/demo/project")
        self.assertIsNone(self.collect(links=False).remote_url)

    def test_merge_commits_excluded_unless_requested(self):
        self.commit("base", "2026-01-01T12:00:00Z")
        self.run_git("checkout", "-b", "topic")
        self.commit("feature", "2026-01-02T12:00:00Z")
        self.run_git("checkout", "main")
        self.commit("main work", "2026-01-03T12:00:00Z")
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-04T12:00:00Z", GIT_COMMITTER_DATE="2026-01-04T12:00:00Z")
        self.run_git("merge", "--no-ff", "topic", "-m", "merge topic", env=env)
        self.assertEqual(len(self.collect().commits), 3)
        self.assertEqual(len(self.collect(include_merges=True).commits), 4)

    def test_option_like_ref_cannot_become_a_git_option(self):
        self.commit("one", "2026-01-01T12:00:00Z")
        with self.assertRaises(NotesError):
            self.collect(ref="--all")

    def test_missing_repository_and_invalid_limit(self):
        with self.assertRaises(NotesError):
            collect(self.repo / "missing", "HEAD", date(2026, 1, 1), date(2026, 1, 7))
        with self.assertRaises(NotesError):
            self.collect(limit=0)


class GitFailureTests(unittest.TestCase):
    def test_missing_git_has_clear_error(self):
        with patch("ship_notes.core.subprocess.run", side_effect=FileNotFoundError), self.assertRaisesRegex(NotesError, "not installed"):
            git(Path("."), "status")

    def test_git_timeout_has_clear_error(self):
        with patch("ship_notes.core.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)), self.assertRaisesRegex(NotesError, "30 seconds"):
            git(Path("."), "status")


if __name__ == "__main__":
    unittest.main()
