#!/usr/bin/env python3
"""
Maintain a mapping of Paseo worktrees to their real projects.

Paseo creates worktrees under $PASEO_HOME/worktrees/<hash>/<name>. Agents that
run inside a worktree record that opaque path as their working directory, so in
the usage dashboard they show up detached from their real project. This script
reads Paseo's workspace/project registries and appends each new worktree to a
JSONL file mapping its cwd to the owning project, so the dashboard can remap them
back.

The file is append-only: a worktree's cwd -> project mapping never changes once
created, so each run scans the existing cwds (a cheap line read, no full parse or
reserialize) and appends only worktrees it hasn't seen yet. Both active and
archived worktrees are captured; archived ones are needed to map old sessions
whose worktree has since been cleaned up.

Only immutable fields are recorded (cwd, workspaceId, projectId, projectRoot,
projectName, createdAt). Mutable worktree state (branch, archived status) is
deliberately omitted so a recorded line never goes stale.

Usage:
  paseo-worktrees.py                 # append any new worktrees to the default file
  paseo-worktrees.py -o FILE         # write to a different location
  paseo-worktrees.py --paseo-home D  # read a different Paseo home
"""

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_PASEO_HOME = Path(os.environ.get("PASEO_HOME") or (Path.home() / ".paseo"))
DEFAULT_OUTPUT = Path.home() / ".local" / "share" / "agent-usage" / "paseo-worktrees.jsonl"


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def iter_worktrees(paseo_home: Path):
    """Yield one mapping record per worktree workspace."""
    projects = {p["projectId"]: p for p in load_json(paseo_home / "projects" / "projects.json")}
    workspaces = load_json(paseo_home / "projects" / "workspaces.json")

    for w in workspaces:
        if w.get("kind") != "worktree":
            continue
        project = projects.get(w["projectId"], {})
        yield {
            "cwd": w["cwd"],
            "workspaceId": w.get("workspaceId"),
            "projectId": w.get("projectId"),
            "projectRoot": project.get("rootPath"),
            "projectName": project.get("displayName"),
            "createdAt": w.get("createdAt"),
        }


def existing_cwds(output: Path) -> set:
    """Read just the cwd of each already-recorded worktree (no full parse of values)."""
    seen = set()
    if not output.exists():
        return seen
    with open(output) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["cwd"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Append new Paseo worktree -> project mappings to a JSONL file.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output JSONL file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--paseo-home", type=Path, default=DEFAULT_PASEO_HOME,
                        help=f"Paseo home directory (default: {DEFAULT_PASEO_HOME})")
    args = parser.parse_args()

    try:
        seen = existing_cwds(args.output)
        new = [wt for wt in iter_worktrees(args.paseo_home) if wt["cwd"] not in seen]
    except FileNotFoundError as e:
        print(f"Error: cannot read Paseo registries: {e}", file=sys.stderr)
        return 1

    if new:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "a") as f:
            for wt in new:
                f.write(json.dumps(wt) + "\n")

    print(f"Appended {len(new)} new worktrees ({len(seen)} already recorded) to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
