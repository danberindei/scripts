#!/usr/bin/env python3
"""
Dump Claude Code token usage across all local projects as a JSONL file.

Output is written to ~/.local/share/agent-usage/claude-usage-START-END.jsonl by default.

Usage:
  claude-usage.py [--start DATETIME] [--end DATETIME] [--project PATTERN] [-o FILE]

DATETIME format: 2026-06-12T10:00 or 2026-06-12 (local time)
PATTERN: substring match against project path
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
DEFAULT_OUTPUT_DIR = Path.home() / ".local" / "share" / "agent-usage"
DEFAULT_OUTPUT_DIR = Path.home() / ".local" / "share" / "agent-usage"
DEFAULT_OUTPUT_STEM = "claude-usage"

PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
PRICING_CACHE = Path.home() / ".cache" / "claude-usage-pricing.json"
PRICING_CACHE_TTL = 7 * 24 * 3600


def load_pricing_db() -> dict:
    if PRICING_CACHE.exists():
        age = time.time() - PRICING_CACHE.stat().st_mtime
        if age < PRICING_CACHE_TTL:
            with open(PRICING_CACHE) as f:
                return json.load(f)

    try:
        with urllib.request.urlopen(PRICING_URL, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        if PRICING_CACHE.exists():
            print(f"Warning: could not fetch pricing ({e}), using stale cache", file=sys.stderr)
            with open(PRICING_CACHE) as f:
                return json.load(f)
        raise SystemExit(f"Error: could not fetch pricing and no cache available: {e}")

    PRICING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRICING_CACHE, "w") as f:
        json.dump(data, f)

    return data


def find_pricing_entry(model: str, db: dict) -> dict:
    model_lower = (model or "").lower()

    if model_lower in db:
        return db[model_lower]

    # Strip suffixes like [1m] that Claude Code appends to model IDs
    stripped = model_lower.split("[")[0].rstrip("-")
    if stripped in db:
        return db[stripped]

    # Find the longest DB key that is a prefix of the model string
    candidates = [k for k in db if k.startswith("claude-") and model_lower.startswith(k)]
    if candidates:
        return db[max(candidates, key=len)]

    return {}


def decode_project_path(dirname: str) -> str:
    # Directory names encode paths: leading/separating slashes become hyphens
    # e.g. -home-dan-Performek-work -> /home/dan/Performek/work
    # We can't perfectly reverse this (hyphens in names are ambiguous),
    # but we try to produce something readable.
    if dirname.startswith("-"):
        return dirname.replace("-", "/", 1).replace("-", "/")
    return dirname


def short_project(path: str) -> str:
    parts = path.rstrip("/").split("/")
    # Return last 2 meaningful path components
    meaningful = [p for p in parts if p]
    return "/".join(meaningful[-2:]) if len(meaningful) >= 2 else path


def calc_cost(event: dict, pricing_db: dict) -> float:
    entry = find_pricing_entry(event["model"], pricing_db)
    return (
        event.get("input", 0) * (entry.get("input_cost_per_token") or 0)
        + event.get("output", 0) * (entry.get("output_cost_per_token") or 0)
        + event.get("cache_write", 0) * (entry.get("cache_creation_input_token_cost") or 0)
        + event.get("cache_read", 0) * (entry.get("cache_read_input_token_cost") or 0)
    )



def parse_dt(s: str, end_of_day: bool = False) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).astimezone()
            if end_of_day and fmt == "%Y-%m-%d":
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s}")


def load_events(config_dir: Path, project_filter: str | None, start: datetime | None, end: datetime | None):
    events = []
    projects_dir = config_dir / "projects"
    if not projects_dir.is_dir():
        return events
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_path = decode_project_path(project_dir.name)
        if project_filter and project_filter.lower() not in project_path.lower():
            continue

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

                        events.append({
                            "ts": ts,
                            "project": project_path,
                            "model": msg.get("model", "unknown"),
                            "input": usage.get("input_tokens", 0),
                            "output": usage.get("output_tokens", 0),
                            "cache_write": usage.get("cache_creation_input_tokens", 0),
                            "cache_read": usage.get("cache_read_input_tokens", 0),
                        })
            except (OSError, PermissionError):
                continue

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

    config_dirs = [Path(d) for d in args.config_dirs] if args.config_dirs else [DEFAULT_CONFIG_DIR]
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    start = parse_dt(args.start) if args.start else parse_dt(today)
    end = parse_dt(args.end, end_of_day=True) if args.end else parse_dt(today, end_of_day=True)

    pricing_db = load_pricing_db()
    output_dir.mkdir(parents=True, exist_ok=True)

    any_events = False
    for config_dir in config_dirs:
        # Derive file prefix from dir name: strip leading dot (e.g. .claude-eng -> claude-eng)
        prefix = config_dir.name.lstrip(".")

        events = load_events(config_dir, args.project, start, end)
        if not events:
            continue
        any_events = True

        by_date = {}
        for e in events:
            by_date.setdefault(e["ts"].strftime("%Y-%m-%d"), []).append(e)

        for date_str, day_events in sorted(by_date.items()):
            out_file = output_dir / f"{prefix}-{date_str}.jsonl"
            with open(out_file, "w") as f:
                for e in day_events:
                    f.write(json.dumps({
                        **e,
                        "ts": e["ts"].isoformat(),
                        "date": date_str,
                        "hour": e["ts"].strftime("%Y-%m-%dT%H:00"),
                        "project_short": short_project(e["project"]),
                        "cost": round(calc_cost(e, pricing_db), 6),
                    }) + "\n")
            print(f"Wrote {len(day_events)} events to {out_file}", file=sys.stderr)

    if not any_events:
        print("No events found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
