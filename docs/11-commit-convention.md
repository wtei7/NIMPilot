# Commit Convention

## Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| Type | Description |
| --- | --- |
| `feat` | Add a new feature |
| `fix` | Fix a bug |
| `docs` | Update documentation |
| `style` | Apply formatting-only changes |
| `refactor` | Refactor without changing behavior |
| `test` | Add or update tests |
| `chore` | Update build, configuration, dependencies, or other maintenance |
| `ci` | Change CI configuration |

### Scope

Use a task number or module name:

- `task-000` through `task-012`: changes for a specific task
- `discover`, `generator`, `benchmark`, `router`, `dashboard`, `api`, `scheduler`: module names
- `config`, `storage`, `utils`: foundation modules

### Subject

- Limit to 50 characters.
- Do not end with a period.
- Use the imperative mood, for example: `add model discovery engine`.
- Korean or English is acceptable for commit subjects.

### Body

- Wrap lines at 72 characters.
- Explain what changed and why; let the code explain how.

### Footer

- Breaking changes: use the `BREAKING CHANGE:` prefix.
- Related issues: use `Closes #123` or `Refs #456`.

## Commit Examples

```
feat(task-000): implement foundation modules

- Define Pydantic-based AppConfig models.
- Implement JsonStorageBackend with atomic writes and thread safety.
- Add the NIMPilotError exception hierarchy.
- Add setup_logging, a retry decorator, and common utility functions.

Complete Task 000 (Foundation).
```

```
feat(task-001): initialize project and Docker environment

- Create the FastAPI application and the /health endpoint.
- Add Dockerfile and docker-compose.yml.
- Configure the Python virtual environment and scripts.
- Add requirements.txt, .env.example, .gitignore, and README.

Complete Task 001 (Project Init).
```

```
feat(task-002): implement NVIDIA NIM model discovery

- Add the DiscoverEngine fetch, parse, and save pipeline.
- Call the NVIDIA API /models endpoint with httpx and retry handling.
- Generate model aliases automatically.
- Infer model capabilities.
- Add tests for aliases, parsing, persistence, fetches, and integration.

Complete Task 002 (Discover Models).
```

## Branch Rules

- `main`: stable, deployable branch
- `feature/<task-number>-<name>`: task-specific feature branch
- `fix/<issue>-<name>`: bug-fix branch

## Pull Request and Release Rules

- Changes may be merged into `main` only through a pull request.
- Pull request titles must follow the Conventional Commits format used for commit messages.
  For example: `feat(router): add fallback policy`
- Every pull request targeting `main` must select exactly one release level in the PR template:
  - `MAJOR`: backward-incompatible API or behavior change
  - `MINOR`: backward-compatible feature addition
  - `PATCH`: backward-compatible bug fix or internal change
- Every PR merged into `main` creates a new `vMAJOR.MINOR.PATCH` tag and GitHub Release based on its selected release level.
- The CI and `PR Format` checks must pass before a PR can be merged into `main`.

## Commit Principles

1. **One commit equals one logical change**
   - Separate commits by task.
   - Put unrelated features in separate commits.

2. **Tests must pass before committing**
   - Run `python -m pytest tests/ -v` and confirm it passes.

3. **Push only when explicitly requested**
   - Keep commits local by default.
   - Push only after user approval.

4. **Do not commit `.venv`, `__pycache__`, or `.env`**
   - These files are listed in `.gitignore`.
