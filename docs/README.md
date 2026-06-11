<img src="https://raw.githubusercontent.com/JakeRecharte/CWG-Coding_with_Git/main/docs/assets/logo_banner.png" alt="CWG banner" width="1622" height="669">

# Coding With Git

[![PyPI](https://img.shields.io/pypi/v/cwg?cache=2)](https://pypi.org/project/cwg/)
[![Python versions](https://img.shields.io/pypi/pyversions/cwg?cache=2)](https://pypi.org/project/cwg/)
[![License: GPL v3](https://img.shields.io/pypi/l/cwg)](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/LICENSE)

**[Language Reference](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/LANGUAGE.md)** ·
[Installation](#installation) ·
[FAQ](https://github.com/JakeRecharte/CWG-Coding_with_Git/wiki) ·
[Contributing](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/CONTRIBUTING.md) ·
[License](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/LICENSE)

> **Work in progress.** This project is in early draft stage. Syntax and semantics are subject to change.

CWG is a programming language where the source code *is* the git history. Commit messages are statements, branches are control flow blocks, and merges close those blocks. The interpreter walks the commit DAG and executes it as a program.

The goal is to use git as a genuine programming medium. Readable syntax, real execution, built entirely on top of version control primitives.

---

## Concept

| Git construct | Language construct |
|---|---|
| `git commit -m "..."` | Statement / instruction |
| Branch | Conditional block or loop |
| Merge | Close a block, return to parent scope |
| Tag | Function definition |
| `cherry-pick` | Function call |
| `revert` | Exception handler / undo |
| `git stash` | Push to memory stack |
| `git stash pop` | Pop from memory stack |

---

## Installation

CWG is published on PyPI. You need **Python 3.10+** and **Git** installed, then:

```bash
pip install cwg
```

This installs the `cwg` command on your `PATH` and pulls in the runtime dependency (GitPython). No need to clone the repository to use the language.

> Want to work on CWG itself? See [CONTRIBUTING.md](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/CONTRIBUTING.md) for the from-source / editable-install workflow.

---

## Quick Start

Write your first program — a git history that prints `hello world`:

```bash
mkdir hello && cd hello
git init
git commit --allow-empty -m "message = 'hello world'"
git commit --allow-empty -m "print(message)"
cwg run .
# output: hello world
```

`cwg run` accepts a `.cwg` script, a local git repo path, or a remote URL (`https://…`, `git@…`, `ssh://…`).

---

## Language Reference

The full syntax and semantics — control flow, scoping, the execution model, functions, exception handling, and more — live in the
**[Language Reference](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/LANGUAGE.md)**.

A taste of what CWG looks like — a countdown loop, where a branch *is* the loop body:

```bash
git commit -m "i = 10"
git branch while/countdown
  git commit -m "while i > 0:"
  git commit -m "    print(i)"
  git commit -m "    i = i - 1"
git checkout main
git merge while/countdown
git commit -m "print('blastoff')"
# output: 10 9 8 7 6 5 4 3 2 1 blastoff
```

---

## Status

This project is a work in progress. See [CONTRIBUTING.md](https://github.com/JakeRecharte/CWG-Coding_with_Git/blob/main/docs/CONTRIBUTING.md) for how to get involved.
