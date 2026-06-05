"""
Tests for cwg/gpScraper.py — the git → GpScrapeResult layer.

These tests build small real git repos in tempdirs (via the tmp_git_repo
fixture) and exercise scrape() end-to-end. They also cover internal helpers
(cherry-pick / revert / topo sort / function extraction) in isolation.
"""

import os
import re
from pathlib import Path

import pytest

from cwg.gpScraper import (
    scrape,
    CommitNode,
    GpScrapeResult,
    FunctionDef,
    StashEntry,
    BRANCH_PREFIXES,
    CWG_CONFIG,
    _detect_cherry_pick,
    _detect_revert,
    _topological_sort,
    _is_cwg_repo,
    _URL_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(repo, message):
    """Make an empty commit on the current branch."""
    repo.git.commit("--allow-empty", "-m", message)
    return repo.head.commit.hexsha


def _new_branch(repo, name):
    """Create and check out a new branch from the current HEAD."""
    repo.git.checkout("-b", name)


def _checkout(repo, name):
    repo.git.checkout(name)


def _merge(repo, branch_name, message=None):
    args = ["--no-ff", branch_name]
    if message:
        args += ["-m", message]
    else:
        args += ["-m", f"Merge {branch_name}"]
    repo.git.merge(*args)


# ---------------------------------------------------------------------------
# scrape() — happy path tests
# ---------------------------------------------------------------------------

class TestScrapeBasic:
    def test_single_commit_repo(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 5")
        result = scrape(tmp_git_repo.working_dir)
        assert len(result.commits) == 1
        assert result.commits[0].message == "x = 5"

    def test_sequential_commits_preserve_order(self, tmp_git_repo):
        _commit(tmp_git_repo, "a")
        _commit(tmp_git_repo, "b")
        _commit(tmp_git_repo, "c")
        result = scrape(tmp_git_repo.working_dir)
        assert [c.message for c in result.commits] == ["a", "b", "c"]

    def test_commits_have_correct_branch(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        result = scrape(tmp_git_repo.working_dir)
        assert result.commits[0].branch == "main"

    def test_repo_path_is_absolute(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        result = scrape(tmp_git_repo.working_dir)
        assert os.path.isabs(result.repo_path)

    def test_branches_list_contains_main(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        result = scrape(tmp_git_repo.working_dir)
        assert "main" in result.branches

    def test_returns_GpScrapeResult_type(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        result = scrape(tmp_git_repo.working_dir)
        assert isinstance(result, GpScrapeResult)
        assert all(isinstance(c, CommitNode) for c in result.commits)


# ---------------------------------------------------------------------------
# scrape() — branch construct tests
# ---------------------------------------------------------------------------

class TestScrapeBranches:
    def test_if_branch_and_merge(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 10")
        _new_branch(tmp_git_repo, "if/big")
        _commit(tmp_git_repo, "if x > 5:")
        _commit(tmp_git_repo, "    y = 1")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "if/big")

        result = scrape(tmp_git_repo.working_dir)
        if_commits = [c for c in result.commits if c.branch == "if/big"]
        assert len(if_commits) == 2
        merges = [c for c in result.commits if c.is_merge]
        assert len(merges) == 1

    def test_while_branch_priority_claims_commits(self, tmp_git_repo):
        # while/ should claim its commits even though main also has them in DAG
        _commit(tmp_git_repo, "i = 3")
        _new_branch(tmp_git_repo, "while/down")
        _commit(tmp_git_repo, "while i > 0:")
        _commit(tmp_git_repo, "    i = i - 1")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "while/down")

        result = scrape(tmp_git_repo.working_dir)
        while_commits = [c for c in result.commits if c.branch == "while/down"]
        assert len(while_commits) == 2

    def test_for_branch_recognised(self, tmp_git_repo):
        _commit(tmp_git_repo, "total = 0")
        _new_branch(tmp_git_repo, "for/sum")
        _commit(tmp_git_repo, "for i in [1, 2, 3]:")
        _commit(tmp_git_repo, "    total = total + i")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "for/sum", "return total")

        result = scrape(tmp_git_repo.working_dir)
        for_commits = [c for c in result.commits if c.branch == "for/sum"]
        assert len(for_commits) == 2

    def test_check_branch_recognised(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 5")
        _new_branch(tmp_git_repo, "check/a")
        _commit(tmp_git_repo, "if x > 0: y = 1")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "check/a")

        result = scrape(tmp_git_repo.working_dir)
        check_commits = [c for c in result.commits if c.branch == "check/a"]
        assert len(check_commits) == 1

    def test_merge_commit_is_flagged(self, tmp_git_repo):
        _commit(tmp_git_repo, "a")
        _new_branch(tmp_git_repo, "if/b")
        _commit(tmp_git_repo, "b")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "if/b")

        result = scrape(tmp_git_repo.working_dir)
        merges = [c for c in result.commits if c.is_merge]
        assert len(merges) == 1
        assert merges[0].branch == "main"


# ---------------------------------------------------------------------------
# scrape() — cherry-pick / revert / function definition tests
# ---------------------------------------------------------------------------

class TestScrapeSpecialCommits:
    def test_cherry_pick_detected(self, tmp_git_repo):
        _commit(tmp_git_repo, "a")
        _new_branch(tmp_git_repo, "fn/greet")
        src_sha = _commit(tmp_git_repo, "print('hi')")
        _checkout(tmp_git_repo, "main")
        # -x adds the "(cherry picked from commit <sha>)" trailer the scraper detects;
        # --allow-empty is required because the source is a CWG-style empty commit.
        tmp_git_repo.git.cherry_pick("-x", "--allow-empty", src_sha)

        result = scrape(tmp_git_repo.working_dir)
        picks = [c for c in result.commits if c.is_cherry_pick]
        assert len(picks) == 1
        assert picks[0].cherry_pick_src == src_sha

    def test_revert_detected(self, tmp_git_repo):
        # Revert tests use a real file change because this git version doesn't
        # support `git revert --allow-empty`. Scraper detection works on the
        # commit message format ("This reverts commit X.") regardless of
        # whether the underlying commit has a diff.
        wd = tmp_git_repo.working_dir
        Path(wd, "data.txt").write_text("v1")
        tmp_git_repo.index.add(["data.txt"])
        tmp_git_repo.index.commit("x = 1")
        Path(wd, "data.txt").write_text("v2")
        tmp_git_repo.index.add(["data.txt"])
        target_sha = tmp_git_repo.index.commit("x = 99").hexsha
        tmp_git_repo.git.revert("--no-edit", target_sha)

        result = scrape(tmp_git_repo.working_dir)
        reverts = [c for c in result.commits if c.is_revert]
        assert len(reverts) == 1
        assert reverts[0].revert_src == target_sha

    def test_fn_tag_pair_extracts_function_def(self, tmp_git_repo):
        # fn/greet ... end-fn/greet tag pair on the fn/ branch
        _commit(tmp_git_repo, "init")
        _new_branch(tmp_git_repo, "fn/greet")
        start_sha = _commit(tmp_git_repo, "print('hello')")
        end_sha = _commit(tmp_git_repo, "return")
        tmp_git_repo.create_tag("fn/greet", ref=start_sha)
        tmp_git_repo.create_tag("end-fn/greet", ref=end_sha)

        result = scrape(tmp_git_repo.working_dir)
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "greet"
        assert fn.start_sha == start_sha
        assert fn.end_sha == end_sha

    def test_function_without_end_tag_has_no_body(self, tmp_git_repo):
        _commit(tmp_git_repo, "init")
        _new_branch(tmp_git_repo, "fn/incomplete")
        sha = _commit(tmp_git_repo, "print('partial')")
        tmp_git_repo.create_tag("fn/incomplete", ref=sha)

        result = scrape(tmp_git_repo.working_dir)
        fn = next(f for f in result.functions if f.name == "incomplete")
        assert fn.end_sha is None
        assert fn.body_shas == []

    def test_tags_populated_on_commits(self, tmp_git_repo):
        sha = _commit(tmp_git_repo, "x = 1")
        tmp_git_repo.create_tag("v1", ref=sha)

        result = scrape(tmp_git_repo.working_dir)
        tagged = [c for c in result.commits if "v1" in c.tags]
        assert len(tagged) == 1


# ---------------------------------------------------------------------------
# scrape() — .cwg sentinel and strict mode
# ---------------------------------------------------------------------------

class TestScrapeCwgConfig:
    def test_non_cwg_repo_has_is_cwg_false(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        result = scrape(tmp_git_repo.working_dir)
        assert result.is_cwg is False

    def test_cwg_repo_has_is_cwg_true(self, cwg_repo):
        result = scrape(cwg_repo.working_dir)
        assert result.is_cwg is True

    def test_strict_mode_rejects_non_cwg_repo(self, tmp_git_repo):
        _commit(tmp_git_repo, "x = 1")
        with pytest.raises(ValueError, match="not a CWG repo"):
            scrape(tmp_git_repo.working_dir, require_cwg=True)

    def test_strict_mode_accepts_cwg_repo(self, cwg_repo):
        # Should not raise
        result = scrape(cwg_repo.working_dir, require_cwg=True)
        assert result.is_cwg is True


# ---------------------------------------------------------------------------
# scrape() — error paths
# ---------------------------------------------------------------------------

class TestScrapeErrors:
    def test_nonexistent_path_raises_value_error(self, tmp_path):
        bogus = str(tmp_path / "does_not_exist")
        with pytest.raises(ValueError, match="path does not exist|not a git repository"):
            scrape(bogus)

    def test_plain_dir_raises_value_error(self, tmp_path):
        # tmp_path exists but is not a git repo
        with pytest.raises(ValueError, match="not a git repository"):
            scrape(str(tmp_path))


# ---------------------------------------------------------------------------
# Detection helpers (unit-level)
# ---------------------------------------------------------------------------

class TestDetectCherryPick:
    def test_extracts_sha_from_standard_format(self):
        msg = "x = 1\n\n(cherry picked from commit abc1234deadbeef0123456789)"
        assert _detect_cherry_pick(msg) == "abc1234deadbeef0123456789"

    def test_extracts_short_sha(self):
        msg = "(cherry picked from commit abc1234)"
        assert _detect_cherry_pick(msg) == "abc1234"

    def test_returns_none_when_absent(self):
        assert _detect_cherry_pick("just a regular commit") is None

    def test_case_insensitive(self):
        msg = "(Cherry Picked From Commit abc1234)"
        assert _detect_cherry_pick(msg) == "abc1234"


class TestDetectRevert:
    def test_extracts_sha_from_standard_format(self):
        msg = 'Revert "original"\n\nThis reverts commit abc1234deadbeef.'
        assert _detect_revert(msg) == "abc1234deadbeef"

    def test_returns_none_when_absent(self):
        assert _detect_revert("regular commit") is None

    def test_case_insensitive(self):
        msg = "this REVERTS commit abc1234."
        assert _detect_revert(msg) == "abc1234"


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def _node(self, sha, parents=None):
        from datetime import datetime, timezone
        return CommitNode(
            sha=sha, message="", branch="main",
            parents=parents or [], author="t",
            timestamp=datetime.now(tz=timezone.utc),
            tags=[],
        )

    def test_linear_chain(self):
        a = self._node("a")
        b = self._node("b", ["a"])
        c = self._node("c", ["b"])
        ordered = _topological_sort({"a": a, "b": b, "c": c})
        assert [n.sha for n in ordered] == ["a", "b", "c"]

    def test_parent_always_before_child(self):
        a = self._node("a")
        b = self._node("b", ["a"])
        c = self._node("c", ["a"])
        d = self._node("d", ["b", "c"])
        ordered = _topological_sort({"a": a, "b": b, "c": c, "d": d})
        positions = {n.sha: i for i, n in enumerate(ordered)}
        assert positions["a"] < positions["b"]
        assert positions["a"] < positions["c"]
        assert positions["b"] < positions["d"]
        assert positions["c"] < positions["d"]

    def test_empty_input(self):
        assert _topological_sort({}) == []

    def test_disconnected_components(self):
        a = self._node("a")
        b = self._node("b")  # no relationship to a
        ordered = _topological_sort({"a": a, "b": b})
        assert len(ordered) == 2

    def test_unknown_parents_are_ignored(self):
        # A parent not in the dict shouldn't break topo sort
        a = self._node("a", ["external"])
        ordered = _topological_sort({"a": a})
        assert [n.sha for n in ordered] == ["a"]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_branch_prefixes_includes_all_constructs(self):
        assert "if/" in BRANCH_PREFIXES
        assert "else/" in BRANCH_PREFIXES
        assert "while/" in BRANCH_PREFIXES
        assert "for/" in BRANCH_PREFIXES
        assert "fn/" in BRANCH_PREFIXES
        assert "check/" in BRANCH_PREFIXES

    def test_cwg_config_constant_is_dot_cwg(self):
        assert CWG_CONFIG == ".cwg"

    def test_url_re_matches_url_schemes(self):
        assert _URL_RE.match("https://example.com")
        assert _URL_RE.match("http://example.com")
        assert _URL_RE.match("ssh://git@host/x")
        assert _URL_RE.match("git@github.com:x/y")
        assert _URL_RE.match("/local/path") is None


# ---------------------------------------------------------------------------
# CommitNode.branch_type
# ---------------------------------------------------------------------------

class TestCommitNodeBranchType:
    def _make(self, branch):
        from datetime import datetime, timezone
        return CommitNode(
            sha="x", message="", branch=branch, parents=[],
            author="t", timestamp=datetime.now(tz=timezone.utc), tags=[],
        )

    def test_main_is_global(self):
        assert self._make("main").branch_type() == "global"

    def test_master_is_global(self):
        assert self._make("master").branch_type() == "global"

    def test_if_branch(self):
        assert self._make("if/big").branch_type() == "if"

    def test_else_branch(self):
        assert self._make("else/small").branch_type() == "else"

    def test_while_branch(self):
        assert self._make("while/count").branch_type() == "while"

    def test_for_branch(self):
        assert self._make("for/sum").branch_type() == "for"

    def test_fn_branch(self):
        assert self._make("fn/greet").branch_type() == "fn"

    def test_check_branch(self):
        assert self._make("check/a").branch_type() == "check"

    def test_unknown_branch(self):
        assert self._make("feature/x").branch_type() == "unknown"


# ---------------------------------------------------------------------------
# End-to-end: scrape + interpret
# ---------------------------------------------------------------------------

class TestScrapeInterpretRoundTrip:
    """Build a git repo, scrape it, run the interpreter, check the scope."""

    def test_simple_program(self, tmp_git_repo):
        from cwg.interpreter import run as interp_run
        _commit(tmp_git_repo, "x = 5")
        _commit(tmp_git_repo, "y = x * 2")
        scope = interp_run(scrape(tmp_git_repo.working_dir))
        assert scope["y"] == 10

    def test_while_loop_program(self, tmp_git_repo):
        from cwg.interpreter import run as interp_run
        _commit(tmp_git_repo, "i = 3")
        _new_branch(tmp_git_repo, "while/down")
        _commit(tmp_git_repo, "while i > 0:")
        _commit(tmp_git_repo, "    i = i - 1")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "while/down", "return i")

        scope = interp_run(scrape(tmp_git_repo.working_dir))
        assert scope["i"] == 0

    def test_for_loop_program(self, tmp_git_repo):
        from cwg.interpreter import run as interp_run
        _commit(tmp_git_repo, "total = 0")
        _new_branch(tmp_git_repo, "for/sum")
        _commit(tmp_git_repo, "for i in [1, 2, 3, 4]:")
        _commit(tmp_git_repo, "    total = total + i")
        _checkout(tmp_git_repo, "main")
        _merge(tmp_git_repo, "for/sum", "return total")

        scope = interp_run(scrape(tmp_git_repo.working_dir))
        assert scope["total"] == 10
