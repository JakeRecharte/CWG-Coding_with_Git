# Contributing to CWG DRAFT

## Getting Started

### Prerequisites

- Python 3.10+
- Git

### Local Setup

Dependencies (`gitpython`) are declared in `pyproject.toml`, so an editable install pulls them in automatically. Prefer the editable install (next section) so the `cwg` console script is also wired up.

### Building from Source

Install the package in editable mode so the `cwg` command-line entry point (defined in `pyproject.toml`) is registered and points at your working copy:

```bash
pip install -e .
```

### Verify Your Setup

Run the test suite and exercise the CLI against a sample program:

```bash
pytest tests/
cwg run path/to/program.cwg
```

`cwg run` accepts a `.cwg` script, a local git repo path, or a remote URL (`https://…`, `git@…`, `ssh://…`).

## Development Workflow

1. Create a branch from `main`
2. Make your changes
3. Run tests locally
4. Open a PR using the template
5. Ensure CI passes before merge

## Branch Naming

```
feat/<name>
fix/<name>
docs/<name>
refactor/<name>
test/<name>
ci/<name>
chore/<name>
```

## Commit Format

Use conventional commit prefixes:

```
feat:      New feature
fix:       Bug fix
docs:      Documentation only
refactor:  Code change that neither fixes a bug nor adds a feature
test:      Adding or updating tests
ci:        CI/CD changes
chore:     Maintenance, dependencies, tooling
```

Breaking changes: use `feat!:` or `fix!:` prefix.

## Testing

| What changed | Run |
|---|---|
| Interpreter / scope / control flow (`cwg/interpreter.py`) | `pytest tests/test_interpreter.py` |
| `.cwg` runner or scraper (`cwg/runner.py`, `cwg/gpScraper.py`) | `pytest tests/` |
| CLI dispatch (`cwg/cli.py`) | `cwg run <sample.cwg>` against a known-good program |
| Any change | Full `pytest tests/` before opening PR |

Tests construct `CommitNode` / `GpScrapeResult` objects directly — no real git repo is required to run the suite.

## CLI Standards

### Output quality
- Clean, minimal output — no unnecessary verbosity
- Consistent formatting across all commands (`cwg run`, `cwg scrape`)
- Program output (e.g. `print(...)` from a CWG program) goes to stdout; CLI diagnostics go to stderr

### Error handling
- No raw Python stack traces in normal mode — surface a one-line message and exit non-zero (see `cwg/cli.py` and `cwg/runner.py` for the dispatch path that prints `error: …` to stderr and exits `1`)
- Distinguish *user errors* (missing file, bad URL, malformed `.cwg`) from *interpreter errors* (a CWG program raised at runtime). User errors should fail fast at the CLI; runtime errors inside a program are caught by the interpreter and may be handled by a `git revert --edit` exception handler
- Catch-and-swallow blocks inside `cwg/interpreter.py` exist for non-executable commit messages (merge labels, free-form text) and must remain silent — do not log or print from them

### Language consistency
- Follow existing CWG command voice and terminology — match the vocabulary used in `README.md` (commit = statement, branch = block, merge = close-block, tag = function, cherry-pick = call, revert = undo / exception handler)
- Match output patterns of existing commands; do not introduce new flag styles without updating `cwg/cli.py` and `cwg/runner.py` together

## Continuous Integration

Every Pull Request (and push to `main`) runs the test suite via
[`tests.yml`](../.github/workflows/tests.yml) across all supported Python
versions (3.10–3.14). CI must pass before a PR is merged.

[Dependabot](../.github/dependabot.yml) opens weekly PRs to keep the Python
dependencies and GitHub Actions up to date.

## Security Checks

Pull Requests run automated dependency security checks via
[`security.yml`](../.github/workflows/security.yml):

- **Dependency review** — flags any dependency a PR adds or bumps to a version with a known vulnerability (PRs only).
- **pip-audit** — audits the project's declared dependencies against the [PyPA Advisory Database](https://github.com/pypa/advisory-database). Also runs on a weekly schedule so newly disclosed vulnerabilities are caught even when dependencies aren't changing.

Dependency review fails on HIGH or CRITICAL findings; pip-audit fails on any
known vulnerability. If a check fails on your PR, inspect the output and either
update the dependency or document why it's a false positive.
