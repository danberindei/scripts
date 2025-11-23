# Repository Guidelines

## Project Structure & Module Organization
- Root directory holds standalone utilities in Python, shell, Perl, and JS; common tasks include Git workflows (`git-rebase-script`, `gh-open`, `find_upstream_branch`), log parsing, and JVM/Maven helpers (`jbuild`, `btest`).
- Shared build logic lives in `build_functions.py`; keep wrapper scripts aligned when adjusting Maven flags or logging behavior.
- `oh-my-zsh/` contains custom theme, aliases, and plugin tweaks; `zsh/` hosts completion helpers for repo scripts; `systemd/` keeps small unit/service files used on the host.
- Keep scripts executable (`chmod +x file`) and runnable from the repo root; prefer relative paths in examples so they work in any environment.

## Build, Test, and Development Commands
- Most tools are direct executables; use `./git-rebase-script --help` or `./gh-open --help` to check options before changing behavior.
- Build helpers expect a Maven workspace path: `PROJECT_DIR=/path/to/project ./jbuild server -DskipTests` to sync and build; `PROJECT_DIR=/path/to/project ./btest` to run the same flow with tests emphasized.
- Quick sanity checks: `python -m compileall .` for Python syntax, `shellcheck disable-unused-dnf-repos.sh` (if installed) for new shell changes. Run scripts against a disposable Git repo or sample logs to validate behavior.

## Coding Style & Naming Conventions
- Python: 4-space indents, small helper functions, and stderr logging with the existing `"###"` prefix; keep dependencies to the standard library.
- Shell: target POSIX sh unless a script already declares bash; prefer `set -euo pipefail`, `$(...)`, and quoted variables. Keep command output terse and machine-readable where possible.
- Names favor lower-kebab or snake-case; scope filenames to their action (`find_upstream_branch`, `perfcompare.sh`) and keep shebangs accurate.

## Testing Guidelines
- No unified automated suite; exercise the specific script you touch with representative inputs and capture expected output snippets in the PR description or script comments when behavior is non-obvious.
- For Maven wrappers, run a dry build on a small module first, and verify temp output goes under `../logs` only when explicitly needed.

## Commit & Pull Request Guidelines
- Commit messages are short, imperative, and often scoped (`git-rebase-script: improve editor commands`); mirror that style.
- In PRs or patches, state the problem, the commands used to validate, side effects on Git repos or Maven workspaces, and any env vars required. Link related issues and add screenshots for UI-facing helpers (e.g., GNOME notifier scripts).
