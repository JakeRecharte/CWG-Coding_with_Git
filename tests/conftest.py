"""
Shared pytest fixtures for CWG tests.

`tmp_git_repo` builds a real git repo in a tempdir using GitPython. Tests
that need to exercise gpScraper.scrape() or runner.run_file() against actual
git history use this fixture rather than constructing CommitNode objects
manually.
"""

import pytest
from git import Repo


@pytest.fixture
def tmp_git_repo(tmp_path):
    """A freshly-initialised git repo on branch `main` with author config set."""
    repo = Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as cfg:
        cfg.set_value("user", "email", "test@cwg.example")
        cfg.set_value("user", "name", "CWG Test")
        cfg.set_value("commit", "gpgsign", "false")
    return repo


@pytest.fixture
def cwg_repo(tmp_git_repo):
    """A tmp_git_repo with a `.cwg` sentinel file committed on main."""
    sentinel = tmp_git_repo.working_dir + "/.cwg"
    open(sentinel, "w").close()
    tmp_git_repo.index.add([".cwg"])
    tmp_git_repo.index.commit("init cwg")
    return tmp_git_repo
