# Repository Guidelines

## Project Structure & Module Organization
- Root directory holds standalone utilities
- `oh-my-zsh/` contains custom theme, aliases, and plugin tweaks; `zsh/` hosts completion helpers for repo scripts; `systemd/` keeps small unit/service files used on the host.
- Keep scripts executable (`chmod +x file`) and runnable from the repo root; prefer relative paths in examples.

## Coding Style & Naming Conventions
- Python: 4-space indents, small helper functions, and stderr logging.
- Shell: target POSIX sh unless a script already declares bash; prefer `set -euo pipefail`, `$(...)`, and quoted variables. Keep command output terse and machine-readable where possible.
- Names favor lower-kebab or snake-case; scope filenames to their action (`find_upstream_branch`, `perfcompare.sh`) and keep shebangs accurate.

## Testing Guidelines
- No unified automated suite; exercise the specific script you touch with representative inputs and capture expected output snippets in the PR description or script comments when behavior is non-obvious.

## Commit & Pull Request Guidelines
- Commit messages are short, imperative, and scoped (`git-rebase-script: improve editor commands`).
