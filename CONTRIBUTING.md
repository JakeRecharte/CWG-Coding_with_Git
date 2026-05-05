# Contributing to CWG DRAFT

## Getting Started

### Prerequisites

- Python 3.10+
- Git

### Local Setup

```bash
pip install -r requirements.txt
```

### Building from Source

```bash

```

### Verify Your Setup

```bash

```

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
| CLI code | ` ` |
| Any change | Full test suite before opening PR |

## CLI Standards

### Output quality
- Clean, minimal output — no unnecessary verbosity
- Consistent formatting across all commands

### Error handling
- No raw stack traces in normal mode
- Use the structured error system (``)
- `` may show detailed output

### Language consistency
- Follow existing CWG command voice and terminology
- Match output patterns of existing commands

## Security Checks

Pull Requests and pushes to `main` run automated security checks: 

- **Dependency review** — flags new dependencies with known vulnerabilities (PRs only)
- **Trivy scanning** — scans the repo filesystem and Docker image for vulnerabilities and misconfigurations
- **Config security** — scans Docker Compose and deployment configs for unsafe exposure (e.g., auth disabled with public port bindings, `0.0.0.0` bindings). Local-only configs that bind to `127.0.0.1` are allowed.

All checks fail on CRITICAL or HIGH severity findings. If a check fails on your PR, inspect the output and either fix the vulnerability or document why it's a false positive.
