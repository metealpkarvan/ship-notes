import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ship_notes.cli import main, write_output
from ship_notes.core import NotesError


class OutputTests(unittest.TestCase):
    def test_existing_output_is_preserved_unless_force_is_given(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.md"
            write_output(path, "first\n", False)
            with self.assertRaises(NotesError):
                write_output(path, "second\n", False)
            self.assertEqual(path.read_text(), "first\n")
            write_output(path, "second\n", True)
            self.assertEqual(path.read_text(), "second\n")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_force_refuses_symlink_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "target.md"
            target.write_text("keep")
            alias = Path(folder) / "alias.md"
            try:
                alias.symlink_to(target)
            except OSError:
                self.skipTest("This environment does not permit symbolic links.")
            with self.assertRaises(NotesError):
                write_output(alias, "new", True)
            self.assertEqual(target.read_text(), "keep")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        for args in [("init", "-b", "main"), ("config", "user.name", "Mete"),
                     ("config", "user.email", "demo@example.invalid"), ("config", "commit.gpgsign", "false")]:
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-02T12:00:00Z", GIT_COMMITTER_DATE="2026-01-02T12:00:00Z")
        subprocess.run(["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "feat: hello"], env=env, check=True, capture_output=True)
        self.args = ["--repo", str(self.repo), "--since", "2026-01-01", "--until", "2026-01-07"]

    def tearDown(self):
        self.temp.cleanup()

    def test_stdout_markdown_and_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(self.args), 0)
        self.assertIn("hello", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(self.args + ["--format", "json"]), 0)
        self.assertEqual(len(json.loads(out.getvalue())["commits"]), 1)

    def test_output_file_and_overwrite_error(self):
        path = self.repo / "notes.md"
        self.assertEqual(main(self.args + ["--output", str(path)]), 0)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(self.args + ["--output", str(path)]), 2)
        self.assertIn("already exists", error.getvalue())

    def test_invalid_date_exits_with_input_error(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(self.args + ["--since", "yesterday"]), 2)
        self.assertIn("YYYY-MM-DD", error.getvalue())

    def test_no_matching_commits_is_a_successful_empty_report(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(self.args + ["--author", "Nobody"]), 0)
        self.assertIn("No matching commits", out.getvalue())

    def test_truncated_report_warns_on_stderr(self):
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-03T12:00:00Z", GIT_COMMITTER_DATE="2026-01-03T12:00:00Z")
        subprocess.run(["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "fix: second"], env=env, check=True, capture_output=True)
        out, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
            self.assertEqual(main(self.args + ["--limit", "1"]), 0)
        self.assertIn("incomplete", error.getvalue())
        self.assertIn("commit limit", out.getvalue())


if __name__ == "__main__":
    unittest.main()
