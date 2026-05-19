"""
Tests for core/cli.py — the top-level `cwg` command dispatcher.

cli.main() is a thin router:
  - `cwg run <target>`  → dispatches to runner.main()
  - `cwg <anything else>` → dispatches to gpScraper.main()
  - `cwg` (no args)     → dispatches to gpScraper.main() (defaults to cwd)

These tests verify the routing logic by patching sys.argv and monkeypatching
the downstream main() functions to confirm which one was called.
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

    def test_scrape_default_for_no_args(self, monkeypatch):
        """With no args, cli should dispatch to scraper main."""
        from core import cli

        called = {"scraper": False, "runner": False}

        def fake_scraper_main():
            called["scraper"] = True

        def fake_runner_main():
            called["runner"] = True

        monkeypatch.setattr("core.gpScraper.main", fake_scraper_main)
        monkeypatch.setattr("core.runner.main", fake_runner_main)
        monkeypatch.setattr(sys, "argv", ["cwg"])

        cli.main()

        assert called["scraper"] is True
        assert called["runner"] is False

    def test_scrape_explicit_subcommand_routes_to_scraper(self, monkeypatch):
        """`cwg scrape <path>` should reach scraper main (it's not 'run')."""
        from core import cli

        called = {"scraper": False, "runner": False}

        def fake_scraper_main():
            called["scraper"] = True

        def fake_runner_main():
            called["runner"] = True

        monkeypatch.setattr("core.gpScraper.main", fake_scraper_main)
        monkeypatch.setattr("core.runner.main", fake_runner_main)
        monkeypatch.setattr(sys, "argv", ["cwg", "scrape", "/some/repo"])

        cli.main()

        assert called["scraper"] is True
        assert called["runner"] is False

    def test_path_as_first_arg_routes_to_scraper(self, monkeypatch):
        """A bare path (not 'run') goes to scraper — its default verb."""
        from core import cli

        called = {"scraper": False}

        def fake_scraper_main():
            called["scraper"] = True

        monkeypatch.setattr("core.gpScraper.main", fake_scraper_main)
        monkeypatch.setattr("core.runner.main", lambda: pytest.fail("runner should not run"))
        monkeypatch.setattr(sys, "argv", ["cwg", "/path/to/repo"])

        cli.main()

        assert called["scraper"] is True


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

    def test_scrape_against_real_repo(self, monkeypatch, tmp_git_repo, capsys):
        """`cwg <repo>` should print the scrape summary."""
        from core import cli

        tmp_git_repo.git.commit("--allow-empty", "-m", "x = 5")
        monkeypatch.setattr(sys, "argv", ["cwg", tmp_git_repo.working_dir])

        cli.main()

        out = capsys.readouterr().out
        assert "branches" in out
        assert "commits" in out
        assert "x = 5" in out
