"""
Shared helpers for the per-agent usage extractors (claude-usage.py, codex-usage.py).

Each extractor reads its own tool's logs, normalizes events to a common schema,
and writes per-date JSONL files into a shared output directory that
agents-dashboard.py reads.

Normalized event schema (the keys every extractor must produce):
  ts          datetime  event timestamp (tz-aware, local)
  project     str       absolute project/working directory path
  model       str       model id
  input       int       uncached input tokens
  output      int       output tokens
  cache_write int       cache creation tokens
  cache_read  int       cache read tokens
"""

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path.home() / ".local" / "share" / "agent-usage"

PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
PRICING_CACHE = Path.home() / ".cache" / "agent-usage-pricing.json"
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

    # Strip suffixes like [1m] that some tools append to model IDs
    stripped = model_lower.split("[")[0].rstrip("-")
    if stripped in db:
        return db[stripped]

    return {}


def calc_cost(event: dict, pricing_db: dict) -> float:
    costs = calc_cost_breakdown(event, pricing_db)
    return sum(costs.values())


def calc_cost_breakdown(event: dict, pricing_db: dict) -> dict:
    entry = find_pricing_entry(event["model"], pricing_db)
    return {
        "input_cost": event.get("input", 0) * (entry.get("input_cost_per_token") or 0),
        "output_cost": event.get("output", 0) * (entry.get("output_cost_per_token") or 0),
        "cache_write_cost": event.get("cache_write", 0) * (entry.get("cache_creation_input_token_cost") or 0),
        "cache_read_cost": event.get("cache_read", 0) * (entry.get("cache_read_input_token_cost") or 0),
    }


def short_project(path: str) -> str:
    parts = path.rstrip("/").split("/")
    # Return last 2 meaningful path components
    meaningful = [p for p in parts if p]
    return "/".join(meaningful[-2:]) if len(meaningful) >= 2 else path


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


def write_events(events: list, output_dir: Path, prefix: str, pricing_db: dict) -> bool:
    """Write normalized events to per-date JSONL files named {prefix}-{date}.jsonl.

    Returns True if any events were written.
    """
    if not events:
        return False

    output_dir.mkdir(parents=True, exist_ok=True)

    by_date = {}
    for e in events:
        by_date.setdefault(e["ts"].strftime("%Y-%m-%d"), []).append(e)

    for date_str, day_events in sorted(by_date.items()):
        out_file = output_dir / f"{prefix}-{date_str}.jsonl"
        with open(out_file, "w") as f:
            for e in day_events:
                cost_breakdown = calc_cost_breakdown(e, pricing_db)
                f.write(json.dumps({
                    **e,
                    **{k: round(v, 6) for k, v in cost_breakdown.items()},
                    "ts": e["ts"].isoformat(),
                    "date": date_str,
                    "hour": e["ts"].strftime("%Y-%m-%dT%H:00"),
                    "project_short": short_project(e["project"]),
                    "cost": round(sum(cost_breakdown.values()), 6),
                }) + "\n")
        print(f"Wrote {len(day_events)} events to {out_file}", file=sys.stderr)

    return True
