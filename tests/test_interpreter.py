"""
Tests for core/interpreter.py

Constructs CommitNode / GpScrapeResult objects manually so no real git repo
is needed. Commits must be supplied in topological (oldest-first) order.
"""

import pytest
from datetime import datetime, timezone

from core.gpScraper import CommitNode, GpScrapeResult, FunctionDef, StashEntry
from core.interpreter import (
    run,
    build_exec_tree,
    StatementNode,
    IfNode,
    WhileNode,
    CheckChainNode,
    FnCallNode,
    RevertNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(sha, message, branch, parents=None, is_merge=False,
            is_cherry_pick=False, cherry_pick_src=None,
            is_revert=False, revert_src=None):
    return CommitNode(
        sha=sha,
        message=message,
        branch=branch,
        parents=parents or [],
        author="test",
        timestamp=datetime.now(tz=timezone.utc),
        is_merge=is_merge,
        is_revert=is_revert,
        is_cherry_pick=is_cherry_pick,
        cherry_pick_src=cherry_pick_src,
        revert_src=revert_src,
        tags=[],
    )


def _result(commits):
    branches = list(dict.fromkeys(c.branch for c in commits))  # preserve order, dedup
    return GpScrapeResult(
        repo_path="test",
        is_cwg=True,
        commits=commits,
        branches=branches,
        tags={},
        functions=[],
        stash=[],
    )


# ---------------------------------------------------------------------------
# Tree structure tests
# ---------------------------------------------------------------------------

class TestBuildExecTree:
    def test_plain_statements_produce_statement_nodes(self):
        commits = [
            _commit("c1", "x = 1", "main"),
            _commit("c2", "y = 2", "main", ["c1"]),
        ]
        tree = build_exec_tree(_result(commits))
        assert len(tree) == 2
        assert all(isinstance(n, StatementNode) for n in tree)

    def test_if_else_produces_if_node(self):
        # main: c1 → merge(if) → merge(else)
        # if/b:  c2(condition) → c3(body)
        # else/b: c4(body)
        c1 = _commit("c1", "x = 10", "main")
        c2 = _commit("c2", "if x > 5:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 1", "if/b", ["c2"])
        c4 = _commit("c4", "y = 2", "else/b", ["c1"])
        c5 = _commit("c5", "Merge if/b", "main", ["c1", "c3"], is_merge=True)
        c6 = _commit("c6", "Merge else/b", "main", ["c5", "c4"], is_merge=True)

        tree = build_exec_tree(_result([c1, c2, c4, c3, c5, c6]))

        assert len(tree) == 2  # StatementNode(c1) + IfNode
        assert isinstance(tree[0], StatementNode)
        assert isinstance(tree[1], IfNode)
        assert len(tree[1].true_branch) == 1
        assert len(tree[1].false_branch) == 1

    def test_if_without_else_produces_empty_false_branch(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x > 0:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 99", "if/b", ["c2"])
        c4 = _commit("c4", "Merge if/b", "main", ["c1", "c3"], is_merge=True)

        tree = build_exec_tree(_result([c1, c2, c3, c4]))

        if_node = tree[1]
        assert isinstance(if_node, IfNode)
        assert len(if_node.true_branch) == 1
        assert if_node.false_branch == []

    def test_while_produces_while_node(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "while i > 0:", "while/count", ["c1"])
        c3 = _commit("c3", "i = i - 1", "while/count", ["c2"])
        c4 = _commit("c4", "Merge while/count", "main", ["c1", "c3"], is_merge=True)

        tree = build_exec_tree(_result([c1, c2, c3, c4]))

        assert len(tree) == 2
        assert isinstance(tree[1], WhileNode)
        assert len(tree[1].body) == 1


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestRun:
    def test_simple_assignment(self):
        commits = [_commit("c1", "x = 42", "main")]
        assert run(_result(commits))["x"] == 42

    def test_sequential_statements(self):
        commits = [
            _commit("c1", "x = 5", "main"),
            _commit("c2", "x = x + 1", "main", ["c1"]),
        ]
        assert run(_result(commits))["x"] == 6

    def test_if_true_branch_taken(self):
        c1 = _commit("c1", "x = 10", "main")
        c2 = _commit("c2", "if x > 5:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 1", "if/b", ["c2"])
        c4 = _commit("c4", "y = 2", "else/b", ["c1"])
        c5 = _commit("c5", "return y", "main", ["c1", "c3"], is_merge=True)
        c6 = _commit("c6", "return y", "main", ["c5", "c4"], is_merge=True)

        scope = run(_result([c1, c2, c4, c3, c5, c6]))
        assert scope["y"] == 1

    def test_if_false_branch_taken(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x > 5:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 1", "if/b", ["c2"])
        c4 = _commit("c4", "y = 2", "else/b", ["c1"])
        c5 = _commit("c5", "return y", "main", ["c1", "c3"], is_merge=True)
        c6 = _commit("c6", "return y", "main", ["c5", "c4"], is_merge=True)

        scope = run(_result([c1, c2, c4, c3, c5, c6]))
        assert scope["y"] == 2

    def test_if_no_else_condition_false_is_noop(self):
        c1 = _commit("c1", "y = 0", "main")
        c2 = _commit("c2", "if y > 10:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 99", "if/b", ["c2"])
        c4 = _commit("c4", "Merge if/b", "main", ["c1", "c3"], is_merge=True)

        scope = run(_result([c1, c2, c3, c4]))
        assert scope["y"] == 0

    def test_while_counts_down(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "while i > 0:", "while/count", ["c1"])
        c3 = _commit("c3", "i = i - 1", "while/count", ["c2"])
        c4 = _commit("c4", "return i", "main", ["c1", "c3"], is_merge=True)

        scope = run(_result([c1, c2, c3, c4]))
        assert scope["i"] == 0

    def test_while_body_executes_correct_number_of_times(self):
        c1 = _commit("c1", "i = 4", "main")
        c2 = _commit("c2", "count = 0", "main", ["c1"])
        c3 = _commit("c3", "while i > 0:", "while/l", ["c2"])
        c4 = _commit("c4", "count = count + 1", "while/l", ["c3"])
        c5 = _commit("c5", "i = i - 1", "while/l", ["c4"])
        c6 = _commit("c6", "return i, count", "main", ["c2", "c5"], is_merge=True)

        scope = run(_result([c1, c2, c3, c4, c5, c6]))
        assert scope["count"] == 4
        assert scope["i"] == 0

    def test_while_never_entered_when_condition_false(self):
        c1 = _commit("c1", "i = 0", "main")
        c2 = _commit("c2", "while i > 0:", "while/l", ["c1"])
        c3 = _commit("c3", "i = i - 1", "while/l", ["c2"])
        c4 = _commit("c4", "Merge while/l", "main", ["c1", "c3"], is_merge=True)

        scope = run(_result([c1, c2, c3, c4]))
        assert scope["i"] == 0

    def test_statement_after_while_executes(self):
        c1 = _commit("c1", "i = 2", "main")
        c2 = _commit("c2", "while i > 0:", "while/l", ["c1"])
        c3 = _commit("c3", "i = i - 1", "while/l", ["c2"])
        c4 = _commit("c4", "Merge while/l", "main", ["c1", "c3"], is_merge=True)
        c5 = _commit("c5", "done = True", "main", ["c4"])

        scope = run(_result([c1, c2, c3, c4, c5]))
        assert scope["done"] is True

    def test_non_executable_commit_messages_are_skipped(self):
        commits = [
            _commit("c1", "x = 1", "main"),
            _commit("c2", "fix typo in readme", "main", ["c1"]),
            _commit("c3", "x = x + 1", "main", ["c2"]),
        ]
        scope = run(_result(commits))
        assert scope["x"] == 2

    def test_scope_does_not_expose_dunder_keys(self):
        commits = [_commit("c1", "x = 1", "main")]
        scope = run(_result(commits))
        assert all(not k.startswith("__") for k in scope)

    def test_run_accepts_initial_scope(self):
        commits = [_commit("c1", "x = x + 10", "main")]
        scope = run(_result(commits), scope={"x": 5})
        assert scope["x"] == 15

    def test_print_output(self, capsys):
        commits = [
            _commit("c1", "message = 'hello world'", "main"),
            _commit("c2", "print(message)", "main", ["c1"]),
        ]
        run(_result(commits))
        assert capsys.readouterr().out.strip() == "hello world"


class TestCheckChain:
    # Builds an if/elif/.../else chain using consecutive check/ merges.
    # Each check/ branch holds a single one-liner commit.
    # main: c1 → merge(check/a) → merge(check/b) → merge(check/c) → merge(check/d)

    def _fizz_commits(self, i_val):
        c1 = _commit("c1", f"i = {i_val}", "main")
        c2 = _commit("c2", "if i % 15 == 0: result = 'FizzBuzz'", "check/a", ["c1"])
        c3 = _commit("c3", "elif i % 3 == 0: result = 'Fizz'", "check/b", ["c1"])
        c4 = _commit("c4", "elif i % 5 == 0: result = 'Buzz'", "check/c", ["c1"])
        c5 = _commit("c5", "else: result = str(i)", "check/d", ["c1"])
        m1 = _commit("m1", "Merge check/a", "main", ["c1", "c2"], is_merge=True)
        m2 = _commit("m2", "Merge check/b", "main", ["m1", "c3"], is_merge=True)
        m3 = _commit("m3", "Merge check/c", "main", ["m2", "c4"], is_merge=True)
        m4 = _commit("m4", "Merge check/d", "main", ["m3", "c5"], is_merge=True)
        return [c1, c2, c3, c4, c5, m1, m2, m3, m4]

    def test_tree_produces_check_chain_node(self):
        tree = build_exec_tree(_result(self._fizz_commits(15)))
        assert len(tree) == 2
        assert isinstance(tree[0], StatementNode)
        assert isinstance(tree[1], CheckChainNode)
        assert len(tree[1].lines) == 4

    def test_if_branch_taken(self):
        scope = run(_result(self._fizz_commits(15)))
        assert scope["result"] == "FizzBuzz"

    def test_first_elif_branch_taken(self):
        scope = run(_result(self._fizz_commits(3)))
        assert scope["result"] == "Fizz"

    def test_second_elif_branch_taken(self):
        scope = run(_result(self._fizz_commits(5)))
        assert scope["result"] == "Buzz"

    def test_else_branch_taken(self):
        scope = run(_result(self._fizz_commits(7)))
        assert scope["result"] == "7"

    def test_if_elif_without_else(self):
        # Chain with no else — no match leaves variable unset
        c1 = _commit("c1", "i = 7", "main")
        c2 = _commit("c2", "if i % 3 == 0: result = 'Fizz'", "check/a", ["c1"])
        c3 = _commit("c3", "elif i % 5 == 0: result = 'Buzz'", "check/b", ["c1"])
        m1 = _commit("m1", "Merge check/a", "main", ["c1", "c2"], is_merge=True)
        m2 = _commit("m2", "Merge check/b", "main", ["m1", "c3"], is_merge=True)
        scope = run(_result([c1, c2, c3, m1, m2]))
        assert "result" not in scope


class TestFnCall:
    # Function body lives on a fn/ branch (not executed directly).
    # A cherry-pick commit on main whose cherry_pick_src matches the
    # function's start_sha triggers a FnCallNode.

    def _fn_result(self, body_commits, fn_def, main_commits):
        all_commits = body_commits + main_commits
        branches = list(dict.fromkeys(c.branch for c in all_commits))
        return GpScrapeResult(
            repo_path="test",
            is_cwg=True,
            commits=all_commits,
            branches=branches,
            tags={},
            functions=[fn_def],
            stash=[],
        )

    def test_tree_produces_fn_call_node(self):
        b1 = _commit("b1", "x = 99", "fn/set")
        fn_def = FunctionDef(name="set", start_sha="f0", end_sha="b1", body_shas=["b1"])
        c1 = _commit("c1", "x = 0", "main")
        call = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="f0")
        tree = build_exec_tree(self._fn_result([b1], fn_def, [c1, call]))
        assert len(tree) == 2
        assert isinstance(tree[1], FnCallNode)
        assert tree[1].name == "set"

    def test_fn_body_executes_in_scope(self):
        b1 = _commit("b1", "x = 99", "fn/set")
        fn_def = FunctionDef(name="set", start_sha="f0", end_sha="b1", body_shas=["b1"])
        c1 = _commit("c1", "x = 0", "main")
        call = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="f0")
        scope = run(self._fn_result([b1], fn_def, [c1, call]))
        assert scope["x"] == 99

    def test_fn_called_multiple_times(self):
        b1 = _commit("b1", "n = n + 1", "fn/inc")
        fn_def = FunctionDef(name="inc", start_sha="f0", end_sha="b1", body_shas=["b1"])
        c1 = _commit("c1", "n = 0", "main")
        call1 = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                        is_cherry_pick=True, cherry_pick_src="f0")
        call2 = _commit("cp2", "(cherry picked from commit f0)", "main", ["cp1"],
                        is_cherry_pick=True, cherry_pick_src="f0")
        scope = run(self._fn_result([b1], fn_def, [c1, call1, call2]))
        assert scope["n"] == 2

    def test_fn_multi_statement_body(self):
        b1 = _commit("b1", "a = x * 2", "fn/double")
        b2 = _commit("b2", "b = a + 1", "fn/double", ["b1"])
        fn_def = FunctionDef(name="double", start_sha="f0", end_sha="b2", body_shas=["b1", "b2"])
        c1 = _commit("c1", "x = 5", "main")
        call = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="f0")
        scope = run(self._fn_result([b1, b2], fn_def, [c1, call]))
        assert scope["a"] == 10
        assert scope["b"] == 11

    def test_non_matching_cherry_pick_is_statement(self):
        # cherry_pick_src that doesn't match any function → StatementNode, message is exec'd normally
        c1 = _commit("c1", "x = 1", "main")
        call = _commit("cp1", "x = x + 1", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="deadbeef")
        result = GpScrapeResult(
            repo_path="test", is_cwg=True,
            commits=[c1, call], branches=["main"],
            tags={}, functions=[], stash=[],
        )
        scope = run(result)
        assert scope["x"] == 2

    def test_fn_reads_parent_scope_variable(self):
        b1 = _commit("b1", "result = x * 2", "fn/double")
        fn_def = FunctionDef(name="double", start_sha="f0", end_sha="b1", body_shas=["b1"])
        c1 = _commit("c1", "x = 7", "main")
        call = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="f0")
        scope = run(self._fn_result([b1], fn_def, [c1, call]))
        assert scope["result"] == 14

    def test_fn_called_before_variable_exists_does_not_crash(self):
        b1 = _commit("b1", "result = undefined_var + 1", "fn/use")
        fn_def = FunctionDef(name="use", start_sha="f0", end_sha="b1", body_shas=["b1"])
        c1 = _commit("c1", "x = 0", "main")
        call = _commit("cp1", "(cherry picked from commit f0)", "main", ["c1"],
                       is_cherry_pick=True, cherry_pick_src="f0")
        scope = run(self._fn_result([b1], fn_def, [c1, call]))
        assert "result" not in scope


# ---------------------------------------------------------------------------
# Scoping tests
# ---------------------------------------------------------------------------

class TestScoping:
    def test_if_branch_does_not_leak_unreturned_variables(self):
        c1 = _commit("c1", "x = 10", "main")
        c2 = _commit("c2", "if x > 5:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 99", "if/b", ["c2"])
        c4 = _commit("c4", "Merge if/b", "main", ["c1", "c3"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4]))
        assert "y" not in scope

    def test_while_does_not_leak_unreturned_variables(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "while i > 0:", "while/l", ["c1"])
        c3 = _commit("c3", "temp = i * 2", "while/l", ["c2"])
        c4 = _commit("c4", "i = i - 1", "while/l", ["c3"])
        c5 = _commit("c5", "return i", "main", ["c1", "c4"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4, c5]))
        assert scope["i"] == 0
        assert "temp" not in scope

    def test_if_partial_return_only_promotes_named_vars(self):
        c1 = _commit("c1", "x = 0", "main")
        c2 = _commit("c2", "if x == 0:", "if/b", ["c1"])
        c3 = _commit("c3", "x = 1", "if/b", ["c2"])
        c4 = _commit("c4", "y = 2", "if/b", ["c3"])
        c5 = _commit("c5", "return x", "main", ["c1", "c4"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4, c5]))
        assert scope["x"] == 1
        assert "y" not in scope

    def test_while_partial_return_only_promotes_named_vars(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "while i > 0:", "while/l", ["c1"])
        c3 = _commit("c3", "temp = i * 10", "while/l", ["c2"])
        c4 = _commit("c4", "i = i - 1", "while/l", ["c3"])
        c5 = _commit("c5", "return i", "main", ["c1", "c4"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4, c5]))
        assert scope["i"] == 0
        assert "temp" not in scope

    def test_else_starts_from_parent_scope_not_post_if(self):
        # condition is false so if/ never runs
        # else/ should see the original x=5, not anything if/ would have set
        c1 = _commit("c1", "x = 5", "main")
        c2 = _commit("c2", "if x > 10:", "if/b", ["c1"])
        c3 = _commit("c3", "x = 100", "if/b", ["c2"])
        c4 = _commit("c4", "result = x", "else/b", ["c1"])
        c5 = _commit("c5", "return x", "main", ["c1", "c3"], is_merge=True)
        c6 = _commit("c6", "return result", "main", ["c5", "c4"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4, c5, c6]))
        assert scope["result"] == 5

    def test_return_nonexistent_variable_does_not_crash(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x > 0:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 1", "if/b", ["c2"])
        c4 = _commit("c4", "return z", "main", ["c1", "c3"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4]))
        assert "z" not in scope


# ---------------------------------------------------------------------------
# Nested structure tests
# ---------------------------------------------------------------------------

class TestNestedStructures:
    def test_while_containing_check_chain(self):
        c1 = _commit("c1", "i = 1", "main")
        c2 = _commit("c2", "results = []", "main", ["c1"])
        lc1 = _commit("lc1", "while i <= 3:", "while/l", ["c2"])
        cc1 = _commit("cc1", "if i % 3 == 0: results.append('Fizz')", "check/a")
        cc2 = _commit("cc2", "else: results.append(str(i))", "check/b")
        lm1 = _commit("lm1", "Merge check/a", "while/l", ["lc1", "cc1"], is_merge=True)
        lm2 = _commit("lm2", "Merge check/b", "while/l", ["lm1", "cc2"], is_merge=True)
        lc2 = _commit("lc2", "i = i + 1", "while/l", ["lm2"])
        m1 = _commit("m1", "return i, results", "main", ["c2", "lc2"], is_merge=True)
        scope = run(_result([c1, c2, lc1, cc1, cc2, lm1, lm2, lc2, m1]))
        assert scope["results"] == ["1", "2", "Fizz"]

    def test_if_inside_while(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "total = 0", "main", ["c1"])
        lc1 = _commit("lc1", "while i > 0:", "while/l", ["c2"])
        ic1 = _commit("ic1", "if i > 1:", "if/b", ["lc1"])
        ic2 = _commit("ic2", "total = total + i", "if/b", ["ic1"])
        lm1 = _commit("lm1", "return total", "while/l", ["lc1", "ic2"], is_merge=True)
        lc2 = _commit("lc2", "i = i - 1", "while/l", ["lm1"])
        m1 = _commit("m1", "return i, total", "main", ["c2", "lc2"], is_merge=True)
        scope = run(_result([c1, c2, lc1, ic1, ic2, lm1, lc2, m1]))
        # i=3: 3>1 → total+=3=3, i=2
        # i=2: 2>1 → total+=2=5, i=1
        # i=1: 1>1 false → total unchanged, i=0
        assert scope["total"] == 5
        assert scope["i"] == 0

    def test_sequential_whiles(self):
        c1 = _commit("c1", "a = 0", "main")
        c2 = _commit("c2", "b = 0", "main", ["c1"])
        l1c1 = _commit("l1c1", "while a < 3:", "while/first", ["c2"])
        l1c2 = _commit("l1c2", "a = a + 1", "while/first", ["l1c1"])
        m1 = _commit("m1", "return a", "main", ["c2", "l1c2"], is_merge=True)
        l2c1 = _commit("l2c1", "while b < a:", "while/second", ["m1"])
        l2c2 = _commit("l2c2", "b = b + 1", "while/second", ["l2c1"])
        m2 = _commit("m2", "return b", "main", ["m1", "l2c2"], is_merge=True)
        scope = run(_result([c1, c2, l1c1, l1c2, m1, l2c1, l2c2, m2]))
        assert scope["a"] == 3
        assert scope["b"] == 3

    def test_statement_between_two_if_blocks(self):
        c1 = _commit("c1", "x = 0", "main")
        c2 = _commit("c2", "if x == 0:", "if/a", ["c1"])
        c3 = _commit("c3", "x = 1", "if/a", ["c2"])
        m1 = _commit("m1", "return x", "main", ["c1", "c3"], is_merge=True)
        c4 = _commit("c4", "y = x + 10", "main", ["m1"])
        c5 = _commit("c5", "if y > 5:", "if/b", ["c4"])
        c6 = _commit("c6", "result = True", "if/b", ["c5"])
        m2 = _commit("m2", "return result", "main", ["c4", "c6"], is_merge=True)
        scope = run(_result([c1, c2, c3, m1, c4, c5, c6, m2]))
        assert scope["x"] == 1
        assert scope["y"] == 11
        assert scope["result"] is True


# ---------------------------------------------------------------------------
# Additional tree structure tests
# ---------------------------------------------------------------------------

class TestTreeStructure:
    def test_if_node_stores_merge_commits(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x > 0:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 1", "if/b", ["c2"])
        c4 = _commit("c4", "y = 2", "else/b", ["c1"])
        c5 = _commit("c5", "return y", "main", ["c1", "c3"], is_merge=True)
        c6 = _commit("c6", "return y", "main", ["c5", "c4"], is_merge=True)
        tree = build_exec_tree(_result([c1, c2, c4, c3, c5, c6]))
        if_node = tree[1]
        assert isinstance(if_node, IfNode)
        assert if_node.if_merge is not None
        assert if_node.if_merge.sha == "c5"
        assert if_node.else_merge is not None
        assert if_node.else_merge.sha == "c6"

    def test_while_node_stores_merge_commit(self):
        c1 = _commit("c1", "i = 3", "main")
        c2 = _commit("c2", "while i > 0:", "while/l", ["c1"])
        c3 = _commit("c3", "i = i - 1", "while/l", ["c2"])
        c4 = _commit("c4", "return i", "main", ["c1", "c3"], is_merge=True)
        tree = build_exec_tree(_result([c1, c2, c3, c4]))
        while_node = tree[1]
        assert isinstance(while_node, WhileNode)
        assert while_node.merge is not None
        assert while_node.merge.sha == "c4"

    def test_master_branch_treated_as_main(self):
        commits = [
            _commit("c1", "x = 1", "master"),
            _commit("c2", "x = x + 1", "master", ["c1"]),
        ]
        assert run(_result(commits))["x"] == 2


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_while_max_iterations_guard(self):
        c1 = _commit("c1", "x = 0", "main")
        c2 = _commit("c2", "while True:", "while/inf", ["c1"])
        c3 = _commit("c3", "x = x + 1", "while/inf", ["c2"])
        c4 = _commit("c4", "return x", "main", ["c1", "c3"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4]))
        assert scope["x"] == 10_000

    def test_while_condition_uses_parent_variable(self):
        c1 = _commit("c1", "limit = 3", "main")
        c2 = _commit("c2", "i = 0", "main", ["c1"])
        c3 = _commit("c3", "while i < limit:", "while/l", ["c2"])
        c4 = _commit("c4", "i = i + 1", "while/l", ["c3"])
        c5 = _commit("c5", "return i", "main", ["c2", "c4"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4, c5]))
        assert scope["i"] == 3

    def test_if_condition_syntax_error_does_not_crash(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x >>>:", "if/b", ["c1"])
        c3 = _commit("c3", "y = 99", "if/b", ["c2"])
        c4 = _commit("c4", "return y", "main", ["c1", "c3"], is_merge=True)
        scope = run(_result([c1, c2, c3, c4]))
        assert "y" not in scope

    def test_if_with_empty_true_body_does_not_crash(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "if x > 0:", "if/b", ["c1"])
        m1 = _commit("m1", "Merge if/b", "main", ["c1", "c2"], is_merge=True)
        scope = run(_result([c1, c2, m1]))
        assert scope["x"] == 1

    def test_check_chain_modifies_parent_scope_directly(self):
        c1 = _commit("c1", "x = 5", "main")
        c2 = _commit("c2", "if x > 3: y = 100", "check/a", ["c1"])
        m1 = _commit("m1", "Merge check/a", "main", ["c1", "c2"], is_merge=True)
        scope = run(_result([c1, c2, m1]))
        assert scope["y"] == 100


# ---------------------------------------------------------------------------
# Revert tests
# ---------------------------------------------------------------------------

def _revert_commit(sha, target_sha, branch, parents=None, handler=""):
    """Build a revert CommitNode with the standard git revert message format."""
    if handler:
        message = f"{handler}\n\nThis reverts commit {target_sha}."
    else:
        message = f'Revert "original"\n\nThis reverts commit {target_sha}.'
    return _commit(sha, message, branch, parents=parents,
                   is_revert=True, revert_src=target_sha)


class TestRevert:
    def test_revert_produces_revert_node(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "x = 99", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"])
        tree = build_exec_tree(_result([c1, c2, r1]))
        assert isinstance(tree[2], RevertNode)
        assert tree[2].target_sha == "c2"
        assert tree[2].handler == ""

    def test_pure_undo_restores_scope(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "x = 99", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"])
        scope = run(_result([c1, c2, r1]))
        assert scope["x"] == 1

    def test_undo_nonexistent_target_is_noop(self):
        c1 = _commit("c1", "x = 1", "main")
        r1 = _revert_commit("r1", "deadbeef", "main", ["c1"])
        scope = run(_result([c1, r1]))
        assert scope["x"] == 1

    def test_handler_runs_when_target_raised_error(self):
        c1 = _commit("c1", "x = 0", "main")
        c2 = _commit("c2", "result = 1 / x", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"], handler="result = -1")
        scope = run(_result([c1, c2, r1]))
        assert scope["result"] == -1

    def test_handler_is_noop_when_target_succeeded(self):
        c1 = _commit("c1", "x = 2", "main")
        c2 = _commit("c2", "result = 1 / x", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"], handler="result = -1")
        scope = run(_result([c1, c2, r1]))
        assert scope["result"] == 0.5
        assert scope["result"] != -1

    def test_handler_produces_revert_node_with_code(self):
        c1 = _commit("c1", "x = 0", "main")
        c2 = _commit("c2", "result = 1 / x", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"], handler="result = -1")
        tree = build_exec_tree(_result([c1, c2, r1]))
        assert isinstance(tree[2], RevertNode)
        assert tree[2].handler == "result = -1"

    def test_undo_multiple_commits_back(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "x = 2", "main", ["c1"])
        c3 = _commit("c3", "x = 3", "main", ["c2"])
        r1 = _revert_commit("r1", "c2", "main", ["c3"])
        scope = run(_result([c1, c2, c3, r1]))
        assert scope["x"] == 1

    def test_statements_after_revert_execute_on_restored_scope(self):
        c1 = _commit("c1", "x = 1", "main")
        c2 = _commit("c2", "x = 99", "main", ["c1"])
        r1 = _revert_commit("r1", "c2", "main", ["c2"])
        c3 = _commit("c3", "y = x + 10", "main", ["r1"])
        scope = run(_result([c1, c2, r1, c3]))
        assert scope["x"] == 1
        assert scope["y"] == 11
