"""
CWG .cwg file runner — parses a git-command script and executes it through
the CWG interpreter without needing a real git repository.
"""

import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .gpScraper import CommitNode, GpScrapeResult
from .interpreter import run


class CWGRunner:
    """Parses a .cwg file into a CommitNode graph and runs the interpreter."""

    def __init__(self):
        self.commits: dict[str, CommitNode] = {}
        self.branch_tips: dict[str, Optional[str]] = {}
        self.current_branch = "main"
        self.counter = 0
        self.branches: list[str] = []

    def _new_sha(self) -> str:
        self.counter += 1
        return f"c{self.counter:04d}"

    def _tip(self) -> Optional[str]:
        return self.branch_tips.get(self.current_branch)

    def _add_commit(self, message: str, is_merge: bool = False,
                    extra_parents: Optional[list[str]] = None) -> str:
        sha = self._new_sha()
        parents: list[str] = []
        t = self._tip()
        if t:
            parents.append(t)
        if extra_parents:
            parents.extend(extra_parents)
        node = CommitNode(
            sha=sha, message=message, branch=self.current_branch,
            parents=parents, author="CWG",
            timestamp=datetime.now(tz=timezone.utc),
            is_merge=is_merge, tags=[],
        )
        self.commits[sha] = node
        self.branch_tips[self.current_branch] = sha
        return sha

    def _checkout_new(self, name: str) -> None:
        self.branches.append(name)
        self.branch_tips[name] = self._tip()
        self.current_branch = name

    def _checkout(self, name: str) -> None:
        self.current_branch = name

    def _merge(self, branch_name: str, message: str) -> str:
        other_tip = self.branch_tips.get(branch_name)
        curr_tip = self._tip()
        extra = [other_tip] if other_tip and other_tip != curr_tip else []
        return self._add_commit(message, is_merge=True, extra_parents=extra)

    def _topological_sort(self) -> list[CommitNode]:
        in_deg = {s: 0 for s in self.commits}
        children: dict[str, list[str]] = {s: [] for s in self.commits}
        for sha, node in self.commits.items():
            for p in node.parents:
                if p in self.commits:
                    in_deg[sha] += 1
                    children[p].append(sha)
        queue = [s for s, d in in_deg.items() if d == 0]
        ordered: list[CommitNode] = []
        while queue:
            sha = queue.pop(0)
            ordered.append(self.commits[sha])
            for child in children[sha]:
                in_deg[child] -= 1
                if in_deg[child] == 0:
                    queue.append(child)
        return ordered

    def load(self, cwg_path: str) -> GpScrapeResult:
        """Parse a .cwg file and return a GpScrapeResult ready for the interpreter."""
        with open(cwg_path) as f:
            for line in f:
                line = line.strip()
                if not line.startswith("git"):
                    continue
                parts = shlex.split(line)
                verb = parts[1]

                if verb == "init":
                    self.current_branch = "main"
                    self.branch_tips["main"] = None
                    self.branches = ["main"]

                elif verb == "commit" and "-m" in parts:
                    idx = parts.index("-m")
                    self._add_commit(parts[idx + 1])

                elif verb == "branch" and len(parts) == 3:
                    self._checkout_new(parts[2])

                elif verb == "checkout" and len(parts) >= 3:
                    self._checkout(parts[2])

                elif verb == "merge" and len(parts) >= 3:
                    branch = parts[2]
                    msg = parts[parts.index("-m") + 1] if "-m" in parts else f"Merge {branch}"
                    self._merge(branch, msg)

        return GpScrapeResult(
            repo_path=str(Path(cwg_path).resolve()),
            is_cwg=True,
            commits=self._topological_sort(),
            branches=self.branches,
            tags={}, functions=[], stash=[],
        )


_URL_RE = re.compile(r"^(https?://|git@|ssh://)", re.I)


def _is_git_repo(path: str) -> bool:
    return (Path(path) / ".git").is_dir()


def run_file(target: str) -> dict:
    """Run a CWG program from a .cwg file, local git repo, or remote URL."""
    if _URL_RE.match(target) or _is_git_repo(target):
        from .gpScraper import scrape
        return run(scrape(target))
    return run(CWGRunner().load(target))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="cwg run",
        description="Execute a CWG program from a .cwg file, local repo, or remote URL.",
    )
    parser.add_argument(
        "target",
        help=".cwg file path, local git repo path, or remote URL (https://…)",
    )
    args = parser.parse_args()

    target = args.target
    if not (_URL_RE.match(target) or _is_git_repo(target) or Path(target).exists()):
        print(f"error: not found: {target}", file=sys.stderr)
        sys.exit(1)

    run_file(target)
