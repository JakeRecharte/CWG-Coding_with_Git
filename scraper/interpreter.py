"""
CWG interpreter — branch control-flow engine.

Consumes a GpScrapeResult and executes the CWG program encoded in git history.
Supported constructs: statements, if/else blocks, while loops, check/ inlines.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Union

from .gpScraper import GpScrapeResult, CommitNode

_CONDITION_RE = re.compile(r'^(?:if|elif|while)\s+(.+?):\s*$', re.DOTALL)
_MAX_LOOP_ITERATIONS = 10_000


# ---------------------------------------------------------------------------
# Execution tree
# ---------------------------------------------------------------------------

@dataclass
class StatementNode:
    commit: CommitNode


@dataclass
class IfNode:
    condition: CommitNode
    true_branch: list["ExecNode"] = field(default_factory=list)
    false_branch: list["ExecNode"] = field(default_factory=list)


@dataclass
class LoopNode:
    condition: CommitNode
    body: list["ExecNode"] = field(default_factory=list)


ExecNode = Union[StatementNode, IfNode, LoopNode]


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------

def _build_sha_to_branch(by_branch: dict[str, list[CommitNode]]) -> dict[str, str]:
    return {c.sha: branch for branch, commits in by_branch.items() for c in commits}


def _find_merged_branch(
    merge_commit: CommitNode,
    current_branch: str,
    sha_to_branch: dict[str, str],
) -> Optional[str]:
    for parent_sha in merge_commit.parents:
        b = sha_to_branch.get(parent_sha)
        if b and b != current_branch:
            return b
    return None


def _build_exec_nodes(
    commits: list[CommitNode],
    by_branch: dict[str, list[CommitNode]],
    sha_to_branch: dict[str, str],
) -> list[ExecNode]:
    nodes: list[ExecNode] = []
    i = 0

    while i < len(commits):
        commit = commits[i]

        if not commit.is_merge:
            nodes.append(StatementNode(commit))
            i += 1
            continue

        current_branch = commit.branch
        merged = _find_merged_branch(commit, current_branch, sha_to_branch)

        if merged is None:
            i += 1
            continue

        prefix = merged.split("/")[0]

        if prefix == "if":
            if_commits = by_branch.get(merged, [])
            condition = if_commits[0] if if_commits else None
            true_body = _build_exec_nodes(if_commits[1:], by_branch, sha_to_branch)

            false_body: list[ExecNode] = []
            if i + 1 < len(commits) and commits[i + 1].is_merge:
                next_merged = _find_merged_branch(commits[i + 1], current_branch, sha_to_branch)
                if next_merged and next_merged.split("/")[0] == "else":
                    else_commits = by_branch.get(next_merged, [])
                    false_body = _build_exec_nodes(else_commits, by_branch, sha_to_branch)
                    i += 1  # consume the else merge commit

            if condition:
                nodes.append(IfNode(condition, true_body, false_body))

        elif prefix == "loop":
            loop_commits = by_branch.get(merged, [])
            condition = loop_commits[0] if loop_commits else None
            body = _build_exec_nodes(loop_commits[1:], by_branch, sha_to_branch)
            if condition:
                nodes.append(LoopNode(condition, body))

        elif prefix == "check":
            # Inline one-liner statements (e.g. "if i % 3 == 0: print('Fizz')")
            for cc in by_branch.get(merged, []):
                nodes.append(StatementNode(cc))

        # fn/, stash, and other constructs are out of scope for this section

        i += 1

    return nodes


def build_exec_tree(result: GpScrapeResult) -> list[ExecNode]:
    """Build an execution tree from a scraped CWG repo."""
    by_branch: dict[str, list[CommitNode]] = {}
    for c in result.commits:
        by_branch.setdefault(c.branch, []).append(c)

    sha_to_branch = _build_sha_to_branch(by_branch)

    main_name = "main" if "main" in by_branch else "master"
    return _build_exec_nodes(by_branch.get(main_name, []), by_branch, sha_to_branch)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def _extract_condition(message: str) -> str:
    """Strip 'if '/'while ' keyword and trailing ':' from a condition message."""
    m = _CONDITION_RE.match(message.strip())
    return m.group(1).strip() if m else message.strip().rstrip(":")


def _execute(nodes: list[ExecNode], scope: dict) -> None:
    for node in nodes:
        if isinstance(node, StatementNode):
            msg = node.commit.message.strip()
            if not msg:
                continue
            try:
                exec(msg, scope)  # noqa: S102
            except SyntaxError:
                pass  # non-executable commit messages (merge labels, etc.)
            except Exception:
                pass

        elif isinstance(node, IfNode):
            condition_expr = _extract_condition(node.condition.message)
            try:
                branch_taken = bool(eval(condition_expr, scope))  # noqa: S307
            except Exception:
                branch_taken = False
            _execute(node.true_branch if branch_taken else node.false_branch, scope)

        elif isinstance(node, LoopNode):
            condition_expr = _extract_condition(node.condition.message)
            for _ in range(_MAX_LOOP_ITERATIONS):
                try:
                    if not bool(eval(condition_expr, scope)):  # noqa: S307
                        break
                except Exception:
                    break
                _execute(node.body, scope)


def run(result: GpScrapeResult, scope: Optional[dict] = None) -> dict:
    """Execute a CWG program and return the final variable scope."""
    if scope is None:
        scope = {}
    _execute(build_exec_tree(result), scope)
    return {k: v for k, v in scope.items() if not k.startswith("__")}
