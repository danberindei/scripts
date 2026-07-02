#!/usr/bin/env python3
"""
Dump Claude Code token usage across all local projects as a JSONL file.

Output is written to ~/.local/share/agent-usage/claude-START-END.jsonl by default.

Usage:
  claude-usage.py [--start DATETIME] [--end DATETIME] [--project PATTERN] [-o DIR]

DATETIME format: 2026-06-12T10:00 or 2026-06-12 (local time)
PATTERN: substring match against project path
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from agent_usage_common import (
    DEFAULT_OUTPUT_DIR,
    build_project_resolver,
    load_pricing_db,
    parse_dt,
    write_events,
)


def _default_config_dirs() -> list[Path]:
    home = Path.home()
    dirs = sorted(d for d in home.iterdir() if d.name.startswith(".claude") and d.is_dir())
    return dirs or [home / ".claude"]


def decode_project_path(dirname: str) -> str:
    # Directory names encode paths: leading/separating slashes become hyphens
    # e.g. -home-dan-Performek-work -> /home/dan/Performek/work
    # We can't perfectly reverse this (hyphens in names are ambiguous),
    # but we try to produce something readable.
    if dirname.startswith("-"):
        return dirname.replace("-", "/", 1).replace("-", "/")
    return dirname


def load_events(config_dir: Path, project_filter: str | None, start: datetime | None, end: datetime | None):
    events = []
    projects_dir = config_dir / "projects"
    if not projects_dir.is_dir():
        return events
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        # Use the decoded dirname for the filter check and as a fallback; the real cwd
        # is read below from 'user' entries, which don't have the hyphen ambiguity.
        decoded_path = decode_project_path(project_dir.name)
        if project_filter and project_filter.lower() not in decoded_path.lower():
            continue

        actual_cwd = None
        project_events = []
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if actual_cwd is None and entry.get("type") == "user":
                            actual_cwd = entry.get("cwd")

                        if entry.get("type") != "assistant":
                            continue
                        msg = entry.get("message", {})
                        usage = msg.get("usage")
                        if not usage:
                            continue

                        ts_str = entry.get("timestamp")
                        if not ts_str:
                            continue
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone()
                        except ValueError:
                            continue

                        if start and ts < start:
                            continue
                        if end and ts > end:
                            continue

                        project_events.append({
                            "ts": ts,
                            "model": msg.get("model", "unknown"),
                            "input": usage.get("input_tokens", 0),
                            "output": usage.get("output_tokens", 0),
                            "cache_write": usage.get("cache_creation_input_tokens", 0),
                            "cache_read": usage.get("cache_read_input_tokens", 0),
                        })
            except (OSError, PermissionError):
                continue

        project_path = actual_cwd or decoded_path
        for e in project_events:
            e["project"] = project_path
        events.extend(project_events)

    events.sort(key=lambda e: e["ts"])
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="Start date/datetime (local time), default: today")
    parser.add_argument("--end", help="End date/datetime (local time), default: today")
    parser.add_argument("--project", help="Filter by project path substring")
    parser.add_argument("--config-dir", dest="config_dirs", action="append", metavar="DIR",
                        help="Claude config dir to include (default: $CLAUDE_CONFIG_DIR or ~/.claude); repeatable")
    parser.add_argument("--output-dir", "-o", metavar="DIR",
                        help=f"Output directory for per-day JSONL files (default: {DEFAULT_OUTPUT_DIR})")
    args = parser.parse_args()

    config_dirs = [Path(d) for d in args.config_dirs] if args.config_dirs else _default_config_dirs()
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    start = parse_dt(args.start) if args.start else parse_dt(today)
    end = parse_dt(args.end, end_of_day=True) if args.end else parse_dt(today, end_of_day=True)

    pricing_db = load_pricing_db()
    # Resolve each session's raw cwd to its real project (worktrees -> owning repo)
    # here, at write time, so the dashboard reads final project paths verbatim.
    resolve_project = build_project_resolver(output_dir)

    any_events = False
    for config_dir in config_dirs:
        # Derive file prefix from dir name: strip leading dot (e.g. .claude-eng -> claude-eng)
        prefix = config_dir.name.lstrip(".")

        events = load_events(config_dir, args.project, start, end)
        for e in events:
            e["project"] = resolve_project(e["project"])
        if write_events(events, output_dir, prefix, pricing_db):
            any_events = True

    if not any_events:
        print("No events found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
