#!/usr/bin/env python3
"""
Dump Codex CLI token usage across all local sessions as JSONL files.

Output is written to ~/.local/share/agent-usage/codex-START-END.jsonl by default.

Usage:
  codex-usage.py [--start DATETIME] [--end DATETIME] [--project PATTERN] [-o DIR]

DATETIME format: 2026-06-12T10:00 or 2026-06-12 (local time)
PATTERN: substring match against project path

Codex records rollout sessions as JSONL under ~/.codex*/sessions/YYYY/MM/DD/ and,
once a session ends, under ~/.codex*/archived_sessions/. Each token_count event
carries a cumulative total_token_usage and a per-turn last_token_usage; Codex
emits each one twice, so consecutive duplicates (same cumulative total) are
skipped.
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


DEFAULT_CODEX_GLOB = str(Path.home() / ".codex*")


def find_default_codex_dirs() -> list[Path]:
    return sorted(p for p in Path.home().glob(".codex*") if p.is_dir())


def load_session_events(jsonl_file: Path, project_filter: str | None,
                        start: datetime | None, end: datetime | None):
    events = []
    cwd = None
    model = "unknown"
    prev_total = None
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

                etype = entry.get("type")
                payload = entry.get("payload", {})

                if etype == "session_meta":
                    cwd = payload.get("cwd", cwd)
                    continue
                if etype == "turn_context":
                    cwd = payload.get("cwd", cwd)
                    model = payload.get("model", model)
                    continue
                if etype != "event_msg" or payload.get("type") != "token_count":
                    continue

                info = payload.get("info")
                if not info:
                    continue

                total = info.get("total_token_usage", {})
                # Codex emits each token_count twice; skip the duplicate.
                total_tokens = total.get("total_tokens")
                if total_tokens == prev_total:
                    continue
                prev_total = total_tokens

                last = info.get("last_token_usage", {})
                input_tokens = last.get("input_tokens", 0)
                cached = last.get("cached_input_tokens", 0)
                output_tokens = last.get("output_tokens", 0)
                if not (input_tokens or cached or output_tokens):
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

                project = cwd or "unknown"
                if project_filter and project_filter.lower() not in project.lower():
                    continue

                events.append({
                    "ts": ts,
                    "project": project,
                    "model": model,
                    # input_tokens is the full input incl. cached; split it out
                    # so cached tokens are priced at the cache-read rate.
                    "input": max(input_tokens - cached, 0),
                    "output": output_tokens,
                    "cache_write": 0,
                    "cache_read": cached,
                })
    except (OSError, PermissionError):
        pass
    return events


def session_id_of(jsonl_file: Path) -> str:
    # rollout-<timestamp>-<uuid>.jsonl -> <uuid>
    stem = jsonl_file.stem
    parts = stem.split("-")
    if len(parts) >= 5:
        return "-".join(parts[-5:])
    return stem


def load_events(codex_dirs: list[Path], project_filter: str | None,
                start: datetime | None, end: datetime | None):
    events = []
    seen_sessions = set()
    search_dirs = []
    for codex_dir in codex_dirs:
        search_dirs += [codex_dir / "sessions", codex_dir / "archived_sessions"]
    files = []
    for d in search_dirs:
        if d.is_dir():
            files.extend(sorted(d.rglob("*.jsonl")))

    for jsonl_file in files:
        sid = session_id_of(jsonl_file)
        if sid in seen_sessions:
            continue
        seen_sessions.add(sid)
        events.extend(load_session_events(jsonl_file, project_filter, start, end))

    events.sort(key=lambda e: e["ts"])
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="Start date/datetime (local time), default: today")
    parser.add_argument("--end", help="End date/datetime (local time), default: today")
    parser.add_argument("--project", help="Filter by project path substring")
    parser.add_argument("--codex-dir", metavar="DIR", action="append", dest="codex_dirs",
                        help=f"Codex home dir (default: all {DEFAULT_CODEX_GLOB} dirs); may be repeated")
    parser.add_argument("--output-dir", "-o", metavar="DIR",
                        help=f"Output directory for per-day JSONL files (default: {DEFAULT_OUTPUT_DIR})")
    args = parser.parse_args()

    codex_dirs = [Path(d) for d in args.codex_dirs] if args.codex_dirs else find_default_codex_dirs()
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    start = parse_dt(args.start) if args.start else parse_dt(today)
    end = parse_dt(args.end, end_of_day=True) if args.end else parse_dt(today, end_of_day=True)

    pricing_db = load_pricing_db()
    # Resolve each session's raw cwd to its real project (worktrees -> owning repo)
    # here, at write time, so the dashboard reads final project paths verbatim.
    resolve_project = build_project_resolver(output_dir)

    events = load_events(codex_dirs, args.project, start, end)
    for e in events:
        e["project"] = resolve_project(e["project"])
    if not write_events(events, output_dir, "codex", pricing_db):
        print("No events found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
