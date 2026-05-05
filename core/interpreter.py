"""
CWG interpreter — branch control-flow engine.

Consumes a GpScrapeResult and executes the CWG program encoded in git history.
Supported constructs: statements, if/else blocks, while loops, check/ inlines, fn/ calls.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Union

from .gpScraper import GpScrapeResult, CommitNode, FunctionDef

_CONDITION_RE = re.compile(r'^(?:if|elif|while)\s+(.+?):\s*$', re.DOTALL)
_CHECK_KW_RE = re.compile(r'^\s*(if|elif|else)\b')
_RETURN_RE = re.compile(r'^return\s+(.+)$')
_REVERT_SUBJECT_RE = re.compile(r'^Revert ".*"$')
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
    if_merge: Optional[CommitNode] = None
    else_merge: Optional[CommitNode] = None


@dataclass
class LoopNode:
    condition: CommitNode
    body: list["ExecNode"] = field(default_factory=list)
    merge: Optional[CommitNode] = None


@dataclass
class CheckChainNode:
    lines: list[str]


@dataclass
class FnCallNode:
    name: str
    body: list[CommitNode]


@dataclass
class RevertNode:
    commit: CommitNode
    target_sha: str
    handler: str  # empty = pure undo; non-empty = exception handler code


ExecNode = Union[StatementNode, IfNode, LoopNode, CheckChainNode, FnCallNode, RevertNode]


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------

def _check_branch_keyword(commits: list[CommitNode]) -> str:
    """Return 'if', 'elif', 'else', or 'other' based on the first commit message."""
    if not commits:
        return "other"
    m = _CHECK_KW_RE.match(commits[0].message.strip())
    return m.group(1) if m else "other"


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
    sha_to_commit: dict[str, CommitNode],
    fn_by_start: dict[str, FunctionDef],
) -> list[ExecNode]:
    nodes: list[ExecNode] = []
    i = 0

    while i < len(commits):
        commit = commits[i]

        if not commit.is_merge:
            if commit.is_cherry_pick and commit.cherry_pick_src in fn_by_start:
                fn_def = fn_by_start[commit.cherry_pick_src]
                body = [sha_to_commit[s] for s in fn_def.body_shas if s in sha_to_commit]
                nodes.append(FnCallNode(fn_def.name, body))
            elif commit.is_revert and commit.revert_src:
                nodes.append(RevertNode(commit, commit.revert_src, _extract_handler(commit.message)))
            else:
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
            true_body = _build_exec_nodes(if_commits[1:], by_branch, sha_to_branch, sha_to_commit, fn_by_start)

            false_body: list[ExecNode] = []
            else_merge = None
            if i + 1 < len(commits) and commits[i + 1].is_merge:
                next_merged = _find_merged_branch(commits[i + 1], current_branch, sha_to_branch)
                if next_merged and next_merged.split("/")[0] == "else":
                    else_commits = by_branch.get(next_merged, [])
                    false_body = _build_exec_nodes(else_commits, by_branch, sha_to_branch, sha_to_commit, fn_by_start)
                    else_merge = commits[i + 1]
                    i += 1  # consume the else merge commit

            if condition:
                nodes.append(IfNode(condition, true_body, false_body, commit, else_merge))

        elif prefix == "loop":
            loop_commits = by_branch.get(merged, [])
            condition = loop_commits[0] if loop_commits else None
            body = _build_exec_nodes(loop_commits[1:], by_branch, sha_to_branch, sha_to_commit, fn_by_start)
            if condition:
                nodes.append(LoopNode(condition, body, commit))

        elif prefix == "check":
            branch_commits = by_branch.get(merged, [])
            kw = _check_branch_keyword(branch_commits)

            if kw == "if":
                chain_lines = [cc.message.strip() for cc in branch_commits]
                while i + 1 < len(commits) and commits[i + 1].is_merge:
                    next_merged = _find_merged_branch(commits[i + 1], current_branch, sha_to_branch)
                    if not next_merged or next_merged.split("/")[0] != "check":
                        break
                    next_commits = by_branch.get(next_merged, [])
                    next_kw = _check_branch_keyword(next_commits)
                    if next_kw not in ("elif", "else"):
                        break
                    chain_lines.extend(cc.message.strip() for cc in next_commits)
                    i += 1
                    if next_kw == "else":
                        break
                nodes.append(CheckChainNode(chain_lines))
            else:
                for cc in branch_commits:
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
    sha_to_commit = {c.sha: c for c in result.commits}
    fn_by_start = {fn.start_sha: fn for fn in result.functions}

    main_name = "main" if "main" in by_branch else "master"
    return _build_exec_nodes(
        by_branch.get(main_name, []), by_branch, sha_to_branch, sha_to_commit, fn_by_start
    )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def _extract_condition(message: str) -> str:
    """Strip 'if '/'while ' keyword and trailing ':' from a condition message."""
    m = _CONDITION_RE.match(message.strip())
    return m.group(1).strip() if m else message.strip().rstrip(":")


def _extract_handler(message: str) -> str:
    """Extract handler code from a revert commit message.

    Lines before 'This reverts commit' are handler code, minus the
    auto-generated 'Revert "..."' subject line git adds.
    """
    lines = []
    for line in message.splitlines():
        if line.strip().lower().startswith("this reverts commit"):
            break
        if _REVERT_SUBJECT_RE.match(line.strip()):
            continue
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def _parse_return(message: str) -> list[str]:
    """Extract variable names from a 'return x, y, z' merge message."""
    m = _RETURN_RE.match(message.strip())
    if not m:
        return []
    return [v.strip() for v in m.group(1).split(",") if v.strip()]


def _promote(branch_scope: dict, parent_scope: dict, return_vars: list[str]) -> None:
    """Copy named variables from branch scope back into parent scope."""
    for var in return_vars:
        if var in branch_scope:
            parent_scope[var] = branch_scope[var]


def _execute(nodes: list[ExecNode], scope: dict, snapshots: dict, errors: dict) -> None:
    for node in nodes:
        if isinstance(node, StatementNode):
            msg = node.commit.message.strip()
            if not msg:
                continue
            snapshots[node.commit.sha] = scope.copy()
            try:
                exec(msg, scope)  # noqa: S102
            except SyntaxError:
                pass  # non-executable commit messages (merge labels, etc.)
            except Exception as e:
                errors[node.commit.sha] = e

        elif isinstance(node, IfNode):
            condition_expr = _extract_condition(node.condition.message)
            try:
                branch_taken = bool(eval(condition_expr, scope))  # noqa: S307
            except Exception:
                branch_taken = False
            branch_scope = scope.copy()
            if branch_taken:
                _execute(node.true_branch, branch_scope, snapshots, errors)
                merge_msg = node.if_merge.message if node.if_merge else ""
            else:
                _execute(node.false_branch, branch_scope, snapshots, errors)
                merge_msg = node.else_merge.message if node.else_merge else ""
            _promote(branch_scope, scope, _parse_return(merge_msg))

        elif isinstance(node, LoopNode):
            condition_expr = _extract_condition(node.condition.message)
            loop_scope = scope.copy()
            return_vars = _parse_return(node.merge.message if node.merge else "")
            for _ in range(_MAX_LOOP_ITERATIONS):
                try:
                    if not bool(eval(condition_expr, loop_scope)):  # noqa: S307
                        break
                except Exception:
                    break
                _execute(node.body, loop_scope, snapshots, errors)
            _promote(loop_scope, scope, return_vars)

        elif isinstance(node, CheckChainNode):
            code = "\n".join(node.lines)
            try:
                exec(code, scope)  # noqa: S102
            except SyntaxError:
                pass
            except Exception:
                pass

        elif isinstance(node, FnCallNode):
            for commit in node.body:
                msg = commit.message.strip()
                if not msg:
                    continue
                try:
                    exec(msg, scope)  # noqa: S102
                except SyntaxError:
                    pass
                except Exception:
                    pass

        elif isinstance(node, RevertNode):
            if node.handler:
                if node.target_sha in errors:
                    try:
                        exec(node.handler, scope)  # noqa: S102
                    except Exception:
                        pass
            else:
                if node.target_sha in snapshots:
                    scope.clear()
                    scope.update(snapshots[node.target_sha])


def run(result: GpScrapeResult, scope: Optional[dict] = None) -> dict:
    """Execute a CWG program and return the final variable scope."""
    if scope is None:
        scope = {}
    _execute(build_exec_tree(result), scope, snapshots={}, errors={})
    return {k: v for k, v in scope.items() if not k.startswith("__")}
