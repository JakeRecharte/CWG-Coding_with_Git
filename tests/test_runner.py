"""
Tests for cwg/runner.py — the .cwg file parser and run_file dispatcher.

These tests cover three concerns:
  1. CWGRunner.load() correctly parses .cwg files into CommitNode graphs
  2. run_file() routes .cwg files / local repos / URLs to the right backend
  3. _is_git_repo() and _URL_RE detect inputs correctly
"""

import sys
from pathlib import Path

import pytest

from cwg.runner import CWGRunner, run_file, _is_git_repo, _URL_RE, main as runner_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_cwg(tmp_path, content):
    path = tmp_path / "program.cwg"
    path.write_text(content)
    return str(path)


# ---------------------------------------------------------------------------
# CWGRunner.load — parsing tests
# ---------------------------------------------------------------------------

class TestCWGRunnerLoad:
    def test_parses_single_commit(self, tmp_path):
        path = _write_cwg(tmp_path, 'git init\ngit commit -m "x = 5"\n')
        result = CWGRunner().load(path)
        assert len(result.commits) == 1
        assert result.commits[0].message == "x = 5"

    def test_parses_sequential_commits(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 1"',
            'git commit -m "x = x + 1"',
            'git commit -m "y = x * 2"',
        ]))
        result = CWGRunner().load(path)
        assert [c.message for c in result.commits] == ["x = 1", "x = x + 1", "y = x * 2"]

    def test_commits_chain_parents(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "a"',
            'git commit -m "b"',
            'git commit -m "c"',
        ]))
        result = CWGRunner().load(path)
        assert result.commits[0].parents == []
        assert result.commits[1].parents == [result.commits[0].sha]
        assert result.commits[2].parents == [result.commits[1].sha]

    def test_branch_creates_new_branch_and_switches(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 1"',
            'git branch if/large',
            'git commit -m "y = 2"',
        ]))
        result = CWGRunner().load(path)
        branches = {c.branch for c in result.commits}
        assert branches == {"main", "if/large"}

    def test_checkout_switches_branch(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "a"',
            'git branch if/b',
            'git commit -m "b"',
            'git checkout main',
            'git commit -m "c"',
        ]))
        result = CWGRunner().load(path)
        by_branch = {}
        for c in result.commits:
            by_branch.setdefault(c.branch, []).append(c.message)
        assert by_branch["main"] == ["a", "c"]
        assert by_branch["if/b"] == ["b"]

    def test_merge_creates_merge_commit(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 1"',
            'git branch if/b',
            'git commit -m "y = 2"',
            'git checkout main',
            'git merge if/b',
        ]))
        result = CWGRunner().load(path)
        merges = [c for c in result.commits if c.is_merge]
        assert len(merges) == 1
        assert merges[0].branch == "main"

    def test_merge_with_explicit_message_preserves_it(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 1"',
            'git branch while/l',
            'git commit -m "while x > 0:"',
            'git commit -m "    x = x - 1"',
            'git checkout main',
            'git merge while/l -m "return x"',
        ]))
        result = CWGRunner().load(path)
        merges = [c for c in result.commits if c.is_merge]
        assert merges[0].message == "return x"

    def test_merge_without_message_uses_default(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 1"',
            'git branch if/b',
            'git commit -m "y = 2"',
            'git checkout main',
            'git merge if/b',
        ]))
        result = CWGRunner().load(path)
        merges = [c for c in result.commits if c.is_merge]
        assert merges[0].message == "Merge if/b"

    def test_non_git_lines_are_ignored(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            '# This is a comment',
            '',
            'echo hello',
            'git init',
            '# another comment',
            'git commit -m "x = 1"',
            'not a git line',
        ]))
        result = CWGRunner().load(path)
        assert len(result.commits) == 1
        assert result.commits[0].message == "x = 1"

    def test_commit_messages_with_quotes_parse_correctly(self, tmp_path):
        # shlex handles nested quotes — single quotes inside double-quoted -m arg
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            "git commit -m \"name = 'alice'\"",
        ]))
        result = CWGRunner().load(path)
        assert result.commits[0].message == "name = 'alice'"

    def test_empty_file_produces_empty_result(self, tmp_path):
        path = _write_cwg(tmp_path, '')
        result = CWGRunner().load(path)
        assert result.commits == []

    def test_only_git_init_produces_no_commits(self, tmp_path):
        path = _write_cwg(tmp_path, 'git init\n')
        result = CWGRunner().load(path)
        assert result.commits == []

    def test_repo_path_reflects_absolute_file_location(self, tmp_path):
        path = _write_cwg(tmp_path, 'git init\n')
        result = CWGRunner().load(path)
        assert result.repo_path == str(Path(path).resolve())

    def test_is_cwg_flag_is_true(self, tmp_path):
        # CWGRunner always marks the result as a CWG repo (it parsed a .cwg file)
        path = _write_cwg(tmp_path, 'git init\ngit commit -m "x = 1"\n')
        result = CWGRunner().load(path)
        assert result.is_cwg is True

    def test_branches_list_contains_all_used_branches(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "a"',
            'git branch while/l',
            'git commit -m "while True:"',
            'git checkout main',
            'git branch if/b',
            'git commit -m "if x:"',
        ]))
        result = CWGRunner().load(path)
        assert set(result.branches) == {"main", "while/l", "if/b"}

    def test_topological_order_oldest_first(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "a"',
            'git commit -m "b"',
            'git commit -m "c"',
        ]))
        result = CWGRunner().load(path)
        # parent always appears before child
        seen = set()
        for c in result.commits:
            for p in c.parents:
                assert p in seen, f"{c.message}'s parent must come first"
            seen.add(c.sha)


# ---------------------------------------------------------------------------
# End-to-end: load + interpret
# ---------------------------------------------------------------------------

class TestRunFileEndToEnd:
    """Drive a .cwg file all the way through to a final scope dict."""

    def test_hello_world(self, tmp_path, capsys):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            "git commit -m \"message = 'hello world'\"",
            'git commit -m "print(message)"',
        ]))
        run_file(path)
        assert capsys.readouterr().out.strip() == "hello world"

    def test_simple_arithmetic_program(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 5"',
            'git commit -m "y = x * 2"',
            'git commit -m "z = y + 1"',
        ]))
        # run_file calls run() which returns the final scope
        from cwg.runner import CWGRunner
        from cwg.interpreter import run as interp_run
        scope = interp_run(CWGRunner().load(path))
        assert scope["z"] == 11

    def test_if_else_program(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "x = 10"',
            'git branch if/big',
            'git commit -m "if x > 5:"',
            'git commit -m "    result = 1"',
            'git checkout main',
            'git branch else/small',
            'git commit -m "    result = 2"',
            'git checkout main',
            'git merge if/big -m "return result"',
            'git merge else/small -m "return result"',
        ]))
        from cwg.runner import CWGRunner
        from cwg.interpreter import run as interp_run
        scope = interp_run(CWGRunner().load(path))
        assert scope["result"] == 1

    def test_while_loop_program(self, tmp_path):
        path = _write_cwg(tmp_path, '\n'.join([
            'git init',
            'git commit -m "i = 3"',
            'git branch while/down',
            'git commit -m "while i > 0:"',
            'git commit -m "    i = i - 1"',
            'git checkout main',
            'git merge while/down -m "return i"',
        ]))
        from cwg.runner import CWGRunner
        from cwg.interpreter import run as interp_run
        scope = interp_run(CWGRunner().load(path))
        assert scope["i"] == 0


# ---------------------------------------------------------------------------
# run_file dispatch
# ---------------------------------------------------------------------------

class TestRunFileDispatch:
    def test_local_git_repo_routes_to_scrape(self, tmp_git_repo):
        # Commit something so scrape() has data to work with
        tmp_git_repo.git.commit("--allow-empty", "-m", "x = 42")
        from cwg.interpreter import run as interp_run
        from cwg.gpScraper import scrape
        # run_file should produce the same final scope as direct scrape+run
        result_via_run_file = run_file(tmp_git_repo.working_dir)
        result_direct = interp_run(scrape(tmp_git_repo.working_dir))
        assert result_via_run_file == result_direct

    def test_cwg_file_routes_to_runner(self, tmp_path):
        path = _write_cwg(tmp_path, 'git init\ngit commit -m "x = 7"\n')
        scope = run_file(path)
        assert scope["x"] == 7

    def test_path_with_trailing_slash_on_repo(self, tmp_git_repo):
        tmp_git_repo.git.commit("--allow-empty", "-m", "x = 1")
        scope = run_file(tmp_git_repo.working_dir + "/")
        assert scope["x"] == 1


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

class TestDetectionHelpers:
    def test_is_git_repo_true_for_real_repo(self, tmp_git_repo):
        assert _is_git_repo(tmp_git_repo.working_dir) is True

    def test_is_git_repo_false_for_plain_dir(self, tmp_path):
        assert _is_git_repo(str(tmp_path)) is False

    def test_is_git_repo_false_for_nonexistent_path(self, tmp_path):
        assert _is_git_repo(str(tmp_path / "nope")) is False

    def test_url_re_matches_https(self):
        assert _URL_RE.match("https://github.com/x/y.git") is not None

    def test_url_re_matches_http(self):
        assert _URL_RE.match("http://example.com/repo.git") is not None

    def test_url_re_matches_ssh(self):
        assert _URL_RE.match("ssh://git@host/repo.git") is not None

    def test_url_re_matches_git_at(self):
        assert _URL_RE.match("git@github.com:x/y.git") is not None

    def test_url_re_rejects_local_path(self):
        assert _URL_RE.match("/tmp/foo") is None
        assert _URL_RE.match("./bar") is None
        assert _URL_RE.match("relative/path") is None


# ---------------------------------------------------------------------------
# main() CLI entry — error paths
# ---------------------------------------------------------------------------

class TestRunnerMain:
    def test_missing_target_exits_nonzero(self, monkeypatch, capsys, tmp_path):
        nonexistent = str(tmp_path / "does_not_exist.cwg")
        monkeypatch.setattr(sys, "argv", ["cwg run", nonexistent])
        with pytest.raises(SystemExit) as exc_info:
            runner_main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "not found" in err
        assert nonexistent in err

    def test_existing_cwg_file_runs_without_error(self, monkeypatch, tmp_path):
        path = _write_cwg(tmp_path, 'git init\ngit commit -m "x = 1"\n')
        monkeypatch.setattr(sys, "argv", ["cwg run", path])
        # Should not raise
        runner_main()
