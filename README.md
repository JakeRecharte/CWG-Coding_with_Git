# CWG — Coding With Git

> **Work in progress.** This project is in early draft stage. Syntax and semantics are subject to change.

CWG is a programming language where the source code *is* the git history. Commit messages are statements, branches are control flow blocks, and merges close those blocks. The interpreter walks the commit DAG and executes it as a program.

The goal is to use git as a genuine programming medium — readable syntax, real execution, built entirely on top of version control primitives.

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

## Syntax

CWG executes Python syntax inside commit messages. Commit messages must be valid Python statements for the interpreter to recognize and run them.

### Variables

```bash
git commit -m "x = 5"
git commit -m "name = 'world'"
git commit -m "active = True"
git commit -m "x = x + 1"
```

### If / Else

Branches named `if/<name>` and `else/<name>` define conditional blocks. The condition sits in the first commit of the branch.

```bash
git commit -m "if x > 10:"
git branch if/large
  git commit -m "    print('x is large')"
git checkout main
git branch else/small
  git commit -m "    print('x is small')"
git checkout main
git merge if/large
git merge else/small
```

### Loops

Branches named `loop/<name>` define while loops. The first commit in the branch is the `while` condition.

```bash
git commit -m "i = 10"
git branch loop/countdown
  git commit -m "while i > 0:"
  git commit -m "    print(i)"
  git commit -m "    i = i - 1"
git checkout main
git merge loop/countdown
git commit -m "print('blastoff')"
```

### Functions

Functions are defined as tagged commit ranges and called via `cherry-pick`.

```bash
git tag -a "greet" -m "function greet(name):"
git commit -m "    print('hello ' + name)"
git commit -m "    return"
git tag -a "end-greet"

# call the function
git cherry-pick greet
```

---

## Branch Naming Conventions

| Prefix | Purpose |
|---|---|
| `main` / `master` | Global scope |
| `if/<name>` | Conditional true block |
| `else/<name>` | Conditional false block |
| `loop/<name>` | While loop |
| `fn/<name>` | Function definition |
| `check/<name>` | Inline conditional (if/elif/else one-liners) |

---

## Scoping

- `main` holds global scope
- Each branch creates a local scope
- Local scope is discarded after merging unless a value is explicitly returned
- Merging promotes returned values back into global scope

---

## Sample Programs

### Hello World

```bash
git init hello-world
git commit -m "message = 'hello world'"
git commit -m "print(message)"
# output: hello world
```

### Countdown

```bash
git init countdown
git commit -m "i = 10"
git branch loop/countdown
  git commit -m "while i > 0:"
  git commit -m "    print(i)"
  git commit -m "    i = i - 1"
git checkout main
git merge loop/countdown
git commit -m "print('blastoff')"
# output: 10 9 8 7 6 5 4 3 2 1 blastoff
```

### FizzBuzz

```bash
git init fizzbuzz
git commit -m "i = 1"
git branch loop/fizzbuzz
  git commit -m "while i <= 20:"
  git branch check/fizzbuzz
    git commit -m "    if i % 15 == 0: print('FizzBuzz')"
  git checkout loop/fizzbuzz
  git merge check/fizzbuzz
  git branch check/fizz
    git commit -m "    elif i % 3 == 0: print('Fizz')"
  git checkout loop/fizzbuzz
  git merge check/fizz
  git branch check/buzz
    git commit -m "    elif i % 5 == 0: print('Buzz')"
  git checkout loop/fizzbuzz
  git merge check/buzz
  git branch check/default
    git commit -m "    else: print(i)"
  git checkout loop/fizzbuzz
  git merge check/default
  git commit -m "    i = i + 1"
git checkout main
git merge loop/fizzbuzz
```

---

## Data Types

| Type | Example |
|---|---|
| int | `x = 5` |
| float | `pi = 3.14` |
| string | `name = 'alice'` |
| bool | `flag = True` |
| list | `nums = [1, 2, 3]` |

---

## Status

This project is a work in progress. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved.
