#!/usr/bin/env bash
# Rewrite a branch history to remove all `Co-authored-by:` footer lines.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: remove-co-authors-from-branch.sh --branch <name> --base <ref>
EOF
}

branch=""
base=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      branch="${2:-}"
      shift 2
      ;;
    --base)
      base="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$branch" || -z "$base" ]]; then
  echo "Error: --branch and --base are required." >&2
  usage >&2
  exit 1
fi

root_dir="$(git rev-parse --show-toplevel)"
cd "$root_dir"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to rewrite history with a dirty working tree." >&2
  exit 1
fi

git rev-parse --verify "$base^{commit}" >/dev/null
git rev-parse --verify "$branch^{commit}" >/dev/null

if ! git merge-base --is-ancestor "$base" "$branch"; then
  echo "Expected '$base' to be an ancestor of '$branch'." >&2
  exit 1
fi

echo "Rewriting commits on $branch after $base to remove Co-authored-by lines..."

git filter-repo --force --refs "$base..$branch" \
  --message-callback 'import re; return re.sub(rb"^Co-authored-by:.*\n", b"", message, flags=re.MULTILINE)'

echo "Done. Force-push $branch when you are ready to publish the rewritten history."
