#!/usr/bin/env python3
"""One-time migration: resolve stale Paseo worktree paths in stored agent-usage JSONL.

Some historical events were extracted before their worktree appeared in the Paseo
worktree map, so their ``project`` was left as the raw worktree path
(e.g. ``/home/dan/.paseo/worktrees/<hash>/<name>``) instead of the owning repo.
Re-extraction cannot fix these because the Claude source transcripts have since
rotated away, so this rewrites the already-extracted JSONL in place.

For every event whose ``project`` still contains ``/worktrees/<hash>/`` and whose
``<hash>`` maps unambiguously to a single project root in the worktree map, the
``project`` and ``project_short`` fields are rewritten to that root. Files are only
touched when something actually changes.

Usage:
  migrate-worktree-projects.py            # dry run: report what would change
  migrate-worktree-projects.py --apply    # rewrite files in place
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from agent_usage_common import DEFAULT_OUTPUT_DIR, WORKTREE_MAP_FILE, short_project

WORKTREE_RE = re.compile(r"/worktrees/([^/]+)/")


def build_hash_map(data_dir: Path) -> dict:
    """Map each worktree hash token to its project root, only when unambiguous."""
    roots_by_hash = defaultdict(set)
    path = data_dir / WORKTREE_MAP_FILE
    if not path.exists():
        return {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            root = rec.get("projectRoot")
            m = WORKTREE_RE.search(rec.get("cwd", "") + "/")
            if root and m:
                roots_by_hash[m.group(1)].add(root)
    return {h: next(iter(roots)) for h, roots in roots_by_hash.items() if len(roots) == 1}


def migrate_file(path: Path, hash_map: dict, apply: bool) -> tuple:
    """Return (changed_events, unresolved_hashes) for one JSONL file, rewriting if apply."""
    lines_out = []
    changed = 0
    unresolved = defaultdict(int)
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                lines_out.append(line)
                continue
            rec = json.loads(stripped)
            m = WORKTREE_RE.search(str(rec.get("project", "")))
            if m:
                root = hash_map.get(m.group(1))
                if root:
                    rec["project"] = root
                    rec["project_short"] = short_project(root)
                    changed += 1
                    lines_out.append(json.dumps(rec) + "\n")
                    continue
                unresolved[m.group(1)] += 1
            lines_out.append(line)
    if apply and changed:
        path.write_text("".join(lines_out))
    return changed, unresolved


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="rewrite files in place (default: dry run)")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                    help=f"agent-usage data dir (default: {DEFAULT_OUTPUT_DIR})")
    args = ap.parse_args()

    hash_map = build_hash_map(args.data_dir)
    if not hash_map:
        print(f"No worktree map found under {args.data_dir}; nothing to do.", file=sys.stderr)
        return
    print(f"Resolvable worktree hashes: {', '.join(f'{h} -> {r}' for h, r in sorted(hash_map.items()))}")

    total_changed = 0
    total_unresolved = defaultdict(int)
    for path in sorted(args.data_dir.glob("claude*.jsonl")):
        changed, unresolved = migrate_file(path, hash_map, args.apply)
        for h, n in unresolved.items():
            total_unresolved[h] += n
        if changed:
            total_changed += changed
            verb = "Rewrote" if args.apply else "Would rewrite"
            print(f"  {verb} {changed:5d} events in {path.name}")

    verb = "Rewrote" if args.apply else "Would rewrite"
    print(f"{verb} {total_changed} events total.")
    if total_unresolved:
        print("Still unresolved (hash not unambiguous in worktree map):")
        for h, n in sorted(total_unresolved.items(), key=lambda x: -x[1]):
            print(f"  {n:5d}  {h}")
    if not args.apply and total_changed:
        print("Dry run only. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
