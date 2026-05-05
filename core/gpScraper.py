"""
CWG git scraper (GitPython edition) — reads a repo and extracts the full
program structure the CWG interpreter expects.

Every git construct from the CWG spec is covered:
  commit       → statement / instruction
  branch       → control-flow block  (if/ else/ loop/ fn/ check/)
  merge        → block close, return to parent scope
  tag          → function definition boundary
  cherry-pick  → function call
  revert       → undo / exception handler
  stash        → memory-stack push / pop
"""

import argparse
import re
import sys
import tempfile
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from git import Repo, InvalidGitRepositoryError, NoSuchPathError, GitCommandError
except ImportError:
    print("error: gitpython is required — run: pip install gitpython", file=sys.stderr)
    sys.exit(1)


CWG_CONFIG = ".cwg"
BRANCH_PREFIXES = ("if/", "else/", "loop/", "fn/", "check/")

_URL_RE = re.compile(r"^(https?://|git@|ssh://)", re.I)

_CHERRY_PICK_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,40})\)", re.I)
_REVERT_SHA_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})\.", re.I)
_FN_START_RE = re.compile(r"^fn/(.+)$")
_FN_END_RE = re.compile(r"^end-fn/(.+)$|^end-(.+)$")
_STASH_RE = re.compile(r"stash@\{(\d+)\}: (.+)")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CommitNode:
    sha: str
    message: str
    branch: str
    parents: list[str] = field(default_factory=list)
    author: str = ""
    timestamp: Optional[datetime] = None
    is_merge: bool = False
    is_revert: bool = False
    is_cherry_pick: bool = False
    cherry_pick_src: Optional[str] = None  # original sha when cherry-picked
    revert_src: Optional[str] = None       # original sha when reverted
    tags: list[str] = field(default_factory=list)

    def branch_type(self) -> str:
        for prefix in BRANCH_PREFIXES:
            if self.branch.startswith(prefix):
                return prefix.rstrip("/")
        return "global" if self.branch in ("main", "master") else "unknown"


@dataclass
class FunctionDef:
    """A function delimited by fn/<name> … end-fn/<name> tag pairs."""
    name: str
    start_sha: str
    end_sha: Optional[str] = None
    body_shas: list[str] = field(default_factory=list)


@dataclass
class StashEntry:
    index: int
    message: str
    sha: str


@dataclass
class GpScrapeResult:
    repo_path: str
    is_cwg: bool
    commits: list[CommitNode]
    branches: list[str]
    tags: dict[str, str]          # tag name → sha
    functions: list[FunctionDef]  # fn/<name> tag-delimited function defs
    stash: list[StashEntry]       # stash stack, index 0 = top


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_cwg_repo(repo: Repo) -> bool:
    return (Path(repo.working_dir) / CWG_CONFIG).exists()


def _collect_tags(repo: Repo) -> dict[str, str]:
    return {t.name: t.commit.hexsha for t in repo.tags}


def _sha_to_tags(repo: Repo) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for t in repo.tags:
        result.setdefault(t.commit.hexsha, []).append(t.name)
    return result


def _checkout_all_remote_branches(repo: Repo) -> None:
    """Create local tracking branches for every remote ref after a fresh clone."""
    existing = {b.name for b in repo.branches}
    for ref in repo.remote_refs:
        if ref.name == "origin/HEAD":
            continue
        local_name = ref.name.split("/", 1)[1]  # strip "origin/"
        if local_name not in existing:
            repo.create_head(local_name, ref)
            existing.add(local_name)


def _build_branch_map(repo: Repo) -> dict[str, str]:
    """Map each commit sha → the branch it was first reached on (best effort)."""
    branch_map: dict[str, str] = {}
    for branch in repo.branches:
        for commit in repo.iter_commits(branch):
            if commit.hexsha not in branch_map:
                branch_map[commit.hexsha] = branch.name
    return branch_map


def _detect_cherry_pick(message: str) -> Optional[str]:
    m = _CHERRY_PICK_RE.search(message)
    return m.group(1) if m else None


def _detect_revert(message: str) -> Optional[str]:
    m = _REVERT_SHA_RE.search(message)
    return m.group(1) if m else None


def _read_stash(repo: Repo) -> list[StashEntry]:
    """Read stash entries via the raw git command (GitPython has no native stash API)."""
    entries: list[StashEntry] = []
    try:
        raw = repo.git.stash("list")
    except Exception:
        return entries
    for line in raw.splitlines():
        m = _STASH_RE.match(line)
        if not m:
            continue
        index = int(m.group(1))
        try:
            sha = repo.git.rev_parse(f"stash@{{{index}}}")
        except Exception:
            sha = ""
        entries.append(StashEntry(index=index, message=m.group(2), sha=sha))
    return entries


def _extract_functions(repo: Repo, tag_map: dict[str, str]) -> list[FunctionDef]:
    """
    Find fn/<name> / end-fn/<name> (or end-<name>) tag pairs and collect
    the commits that form the function body.
    """
    starts: dict[str, tuple[str, str]] = {}  # fn_name → (tag, sha)
    ends: dict[str, tuple[str, str]] = {}

    for tag_name, sha in tag_map.items():
        m = _FN_START_RE.match(tag_name)
        if m:
            starts[m.group(1)] = (tag_name, sha)
            continue
        m = _FN_END_RE.match(tag_name)
        if m:
            fn_name = m.group(1) or m.group(2)
            if fn_name:
                ends[fn_name] = (tag_name, sha)

    functions: list[FunctionDef] = []
    for fn_name, (_, start_sha) in starts.items():
        end_sha = ends.get(fn_name, (None, None))[1]
        fn_def = FunctionDef(name=fn_name, start_sha=start_sha, end_sha=end_sha)
        if end_sha:
            try:
                body = list(repo.iter_commits(f"{start_sha}..{end_sha}", reverse=True))
                fn_def.body_shas = [c.hexsha for c in body]
            except Exception:
                pass
        functions.append(fn_def)
    return functions


def _topological_sort(commits: dict[str, CommitNode]) -> list[CommitNode]:
    """Kahn's algorithm — returns commits oldest-first in execution order."""
    in_degree: dict[str, int] = {sha: 0 for sha in commits}
    children: dict[str, list[str]] = {sha: [] for sha in commits}

    for sha, node in commits.items():
        for parent_sha in node.parents:
            if parent_sha in commits:
                in_degree[sha] += 1
                children[parent_sha].append(sha)

    queue = [sha for sha, deg in in_degree.items() if deg == 0]
    result: list[CommitNode] = []

    while queue:
        sha = queue.pop(0)
        result.append(commits[sha])
        for child in children[sha]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape(repo_path: str, require_cwg: bool = False) -> GpScrapeResult:
    """
    Load a git repo and return a GpScrapeResult with the full CWG program structure.

    Args:
        repo_path:   Local path OR a remote URL (https://, git@, ssh://).
                     Remote repos are cloned to a temp directory and cleaned up after.
        require_cwg: Raise ValueError if the repo has no .cwg file.
    """
    tmp_dir: Optional[str] = None
    if _URL_RE.match(repo_path):
        tmp_dir = tempfile.mkdtemp(prefix="cwg_scraper_")
        try:
            repo = Repo.clone_from(repo_path, tmp_dir)
            _checkout_all_remote_branches(repo)
        except GitCommandError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise ValueError(f"could not clone {repo_path!r}: {exc}") from exc
    else:
        try:
            repo = Repo(repo_path, search_parent_directories=True)
        except InvalidGitRepositoryError:
            raise ValueError(f"not a git repository: {repo_path}")
        except NoSuchPathError:
            raise ValueError(f"path does not exist: {repo_path}")

    is_cwg = _is_cwg_repo(repo)
    if require_cwg and not is_cwg:
        raise ValueError(
            f"not a CWG repo (no {CWG_CONFIG} file). Pass --no-strict to load anyway."
        )

    tag_map = _collect_tags(repo)
    sha_tags = _sha_to_tags(repo)
    branch_map = _build_branch_map(repo)
    branches = [b.name for b in repo.branches]

    commits: dict[str, CommitNode] = {}
    for branch in repo.branches:
        for commit in repo.iter_commits(branch):
            if commit.hexsha in commits:
                continue
            msg = commit.message.strip()
            cherry_src = _detect_cherry_pick(msg)
            revert_src = _detect_revert(msg)
            ts = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
            node = CommitNode(
                sha=commit.hexsha,
                message=msg,
                branch=branch_map.get(commit.hexsha, "main"),
                parents=[p.hexsha for p in commit.parents],
                author=str(commit.author),
                timestamp=ts,
                is_merge=len(commit.parents) > 1,
                is_revert=revert_src is not None,
                is_cherry_pick=cherry_src is not None,
                cherry_pick_src=cherry_src,
                revert_src=revert_src,
                tags=sha_tags.get(commit.hexsha, []),
            )
            commits[commit.hexsha] = node

    result = GpScrapeResult(
        repo_path=str(Path(repo.working_dir).resolve()),
        is_cwg=is_cwg,
        commits=_topological_sort(commits),
        branches=branches,
        tags=tag_map,
        functions=_extract_functions(repo, tag_map),
        stash=_read_stash(repo),
    )

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_result(result: GpScrapeResult, verbose: bool = False) -> None:
    cwg_label = "yes" if result.is_cwg else "no (.cwg not found)"
    print(f"repo:      {result.repo_path}")
    print(f"cwg:       {cwg_label}")
    print(f"branches:  {', '.join(result.branches)}")
    print(f"commits:   {len(result.commits)}")
    print(f"tags:      {len(result.tags)}")
    print(f"functions: {len(result.functions)}")
    print(f"stash:     {len(result.stash)}")
    print()

    if result.functions:
        print("functions:")
        for fn in result.functions:
            end = fn.end_sha[:8] if fn.end_sha else "open"
            body = len(fn.body_shas)
            print(f"  fn/{fn.name}  start={fn.start_sha[:8]}  end={end}  ({body} commits)")
        print()

    if result.stash:
        print("stash:")
        for entry in result.stash:
            print(f"  [{entry.index}] {entry.message}")
        print()

    print("commits:")
    for node in result.commits:
        btype = node.branch_type()
        tag_str = f"  [tags: {', '.join(node.tags)}]" if node.tags else ""
        flags = (
            ("  [merge]" if node.is_merge else "")
            + ("  [revert]" if node.is_revert else "")
            + (f"  [cherry-pick ← {node.cherry_pick_src[:8]}]" if node.cherry_pick_src else "")
        )
        ts_str = node.timestamp.strftime("%Y-%m-%d") if node.timestamp else ""
        print(f"  {node.sha[:8]}  [{node.branch}/{btype}]{tag_str}{flags}  {node.author}  {ts_str}")
        if verbose:
            for line in node.message.splitlines():
                print(f"            {line}")
        else:
            first = node.message.splitlines()[0] if node.message else ""
            print(f"            {first}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gpScraper",
        description="CWG GitPython scraper — extract the full program structure from a repo.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="local path or remote URL (https://, git@, ssh://) — default: current directory",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="require a .cwg config file",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="print full commit messages",
    )
    args = parser.parse_args()

    try:
        result = scrape(args.repo, require_cwg=args.strict)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
