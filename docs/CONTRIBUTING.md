# Contributing to CWG DRAFT

## Getting Started

### Prerequisites

- Python 3.10+
- Git

### Local Setup

Install the runtime dependency (`gitpython`):

```bash
pip install -r requirements.txt
```

For development, prefer an editable install (next section) so the `cwg` console script is wired up.

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
| Interpreter / scope / control flow (`core/interpreter.py`) | `pytest tests/test_interpreter.py` |
| `.cwg` runner or scraper (`core/runner.py`, `core/gpScraper.py`) | `pytest tests/` |
| CLI dispatch (`core/cli.py`) | `cwg run <sample.cwg>` against a known-good program |
| Any change | Full `pytest tests/` before opening PR |

Tests construct `CommitNode` / `GpScrapeResult` objects directly — no real git repo is required to run the suite.

## CLI Standards

### Output quality
- Clean, minimal output — no unnecessary verbosity
- Consistent formatting across all commands (`cwg run`, `cwg scrape`)
- Program output (e.g. `print(...)` from a CWG program) goes to stdout; CLI diagnostics go to stderr

### Error handling
- No raw Python stack traces in normal mode — surface a one-line message and exit non-zero (see `core/cli.py` and `core/runner.py` for the dispatch path that prints `error: …` to stderr and exits `1`)
- Distinguish *user errors* (missing file, bad URL, malformed `.cwg`) from *interpreter errors* (a CWG program raised at runtime). User errors should fail fast at the CLI; runtime errors inside a program are caught by the interpreter and may be handled by a `git revert --edit` exception handler
- Catch-and-swallow blocks inside `core/interpreter.py` exist for non-executable commit messages (merge labels, free-form text) and must remain silent — do not log or print from them

### Language consistency
- Follow existing CWG command voice and terminology — match the vocabulary used in `README.md` (commit = statement, branch = block, merge = close-block, tag = function, cherry-pick = call, revert = undo / exception handler)
- Match output patterns of existing commands; do not introduce new flag styles without updating `core/cli.py` and `core/runner.py` together

## Security Checks

Pull Requests and pushes to `main` run automated security checks: 

- **Dependency review** — flags new dependencies with known vulnerabilities (PRs only)
- **Trivy scanning** — scans the repo filesystem and Docker image for vulnerabilities and misconfigurations
- **Config security** — scans Docker Compose and deployment configs for unsafe exposure (e.g., auth disabled with public port bindings, `0.0.0.0` bindings). Local-only configs that bind to `127.0.0.1` are allowed.

All checks fail on CRITICAL or HIGH severity findings. If a check fails on your PR, inspect the output and either fix the vulnerability or document why it's a false positive.
