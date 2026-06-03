"""
Tests for core/cli.py — the top-level `cwg` command dispatcher.

cli.main() is a thin router with a single user-facing verb:
  - `cwg run [target]` → dispatches to runner.main() (target optional)
  - `cwg` (no args)    → prints usage, exits 0
  - anything else      → prints usage, exits 2

These tests verify the routing logic by patching sys.argv and monkeypatching
the downstream main() function to confirm dispatch.
"""

import sys

import pytest


# ---------------------------------------------------------------------------
# Dispatcher routing tests
# ---------------------------------------------------------------------------

class TestCliDispatch:
    def test_run_subcommand_routes_to_runner(self, monkeypatch, tmp_path):
        """When invoked as `cwg run X`, runner.main() should be called."""
        from core import cli

        called = {"runner": False, "scraper": False, "argv_seen": None}

        def fake_runner_main():
            called["runner"] = True
            called["argv_seen"] = list(sys.argv)

        def fake_scraper_main():
            called["scraper"] = True

        monkeypatch.setattr("core.runner.main", fake_runner_main)
        monkeypatch.setattr("core.gpScraper.main", fake_scraper_main)
        monkeypatch.setattr(sys, "argv", ["cwg", "run", "program.cwg"])

        cli.main()

        assert called["runner"] is True
        assert called["scraper"] is False

    def test_run_subcommand_strips_run_from_argv(self, monkeypatch):
        """After dispatch, runner.main() should see argv with 'run' removed."""
        from core import cli

        observed_argv = []

        def fake_runner_main():
            observed_argv.extend(sys.argv)

        monkeypatch.setattr("core.runner.main", fake_runner_main)
        monkeypatch.setattr(sys, "argv", ["cwg", "run", "program.cwg"])

        cli.main()

        # argv[0] should remain, but 'run' should be gone — runner sees its own target
        assert "run" not in observed_argv[1:]
        assert "program.cwg" in observed_argv

    def test_run_with_no_target_dispatches_to_runner(self, monkeypatch):
        """`cwg run` with no target still routes to runner (defaults to cwd)."""
        from core import cli

        observed_argv = []

        def fake_runner_main():
            observed_argv.extend(sys.argv)

        monkeypatch.setattr("core.runner.main", fake_runner_main)
        monkeypatch.setattr(sys, "argv", ["cwg", "run"])

        cli.main()

        assert observed_argv  # runner was reached
        assert "run" not in observed_argv[1:]

    def test_no_args_prints_usage_and_exits_zero(self, monkeypatch, capsys):
        """Bare `cwg` prints usage and exits 0 — no work performed."""
        from core import cli

        monkeypatch.setattr("core.runner.main", lambda: pytest.fail("runner should not run"))
        monkeypatch.setattr(sys, "argv", ["cwg"])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
        assert "usage: cwg run" in capsys.readouterr().err

    def test_unknown_verb_prints_usage_and_exits_two(self, monkeypatch, capsys):
        """An unrecognized verb (e.g. the old `scrape`) is rejected with exit 2."""
        from core import cli

        monkeypatch.setattr("core.runner.main", lambda: pytest.fail("runner should not run"))
        monkeypatch.setattr(sys, "argv", ["cwg", "scrape", "/some/repo"])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 2
        assert "usage: cwg run" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# End-to-end: actually invoke the binary path through to scope output
# ---------------------------------------------------------------------------

class TestCliEndToEnd:
    """Drive cli.main() with real downstream calls (no mocking)."""

    def test_run_subcommand_executes_cwg_file(self, monkeypatch, tmp_path):
        """`cwg run hello.cwg` should produce program output via the interpreter."""
        from core import cli

        cwg_file = tmp_path / "hello.cwg"
        cwg_file.write_text('\n'.join([
            'git init',
            "git commit -m \"message = 'hello from cli'\"",
            'git commit -m "print(message)"',
        ]))

        monkeypatch.setattr(sys, "argv", ["cwg", "run", str(cwg_file)])

        # Capture stdout from the program
        cli.main()

    def test_run_subcommand_missing_file_exits_nonzero(self, monkeypatch, tmp_path):
        """`cwg run nonexistent` should exit with status 1."""
        from core import cli

        monkeypatch.setattr(sys, "argv", ["cwg", "run", str(tmp_path / "missing.cwg")])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1

    def test_run_against_real_repo(self, monkeypatch, tmp_git_repo, capsys):
        """`cwg run <repo>` executes the repo's git history through the interpreter."""
        from core import cli

        tmp_git_repo.git.commit("--allow-empty", "-m", "print('from repo')")
        monkeypatch.setattr(sys, "argv", ["cwg", "run", tmp_git_repo.working_dir])

        cli.main()

        assert "from repo" in capsys.readouterr().out

    def test_run_no_target_defaults_to_current_repo(self, monkeypatch, tmp_git_repo, capsys):
        """`cwg run` with no target runs the git history of the current directory."""
        from core import cli

        tmp_git_repo.git.commit("--allow-empty", "-m", "print('current repo')")
        monkeypatch.chdir(tmp_git_repo.working_dir)
        monkeypatch.setattr(sys, "argv", ["cwg", "run"])

        cli.main()

        assert "current repo" in capsys.readouterr().out
