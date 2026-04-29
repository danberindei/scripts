#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path


def parse_iso_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_date(value: str) -> date:
    return parse_iso_timestamp(value).astimezone().date()


def file_started_on_date(path: Path, target: date) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                ts = obj.get("timestamp")
                if ts:
                    return local_date(ts) == target
    except (OSError, json.JSONDecodeError):
        return False
    return False


def prompt_from_user_message(obj: dict) -> str:
    content = obj.get("message", {}).get("content", [])
    if not content or not isinstance(content, list):
        return ""

    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text", "").strip()
            if text:
                parts.append(text)
    return " ".join(parts).replace("\n", " ").strip()


def prompt_from_last_prompt(obj: dict) -> str:
    return str(obj.get("lastPrompt", "")).replace("\n", " ").strip()


def summarize_assistant_message(msg: dict) -> tuple[str, list[str]]:
    tools: list[str] = []
    summaries: list[str] = []

    for part in msg.get("content", []):
        if not isinstance(part, dict):
            continue

        kind = part.get("type")

        if kind == "text":
            text = part.get("text", "").strip()
            if text:
                summaries.append(text)
        elif kind == "thinking":
            thinking = part.get("thinking", "").strip()
            if thinking:
                summaries.append(f"thinking: {thinking}")
        elif kind == "tool_use":
            tool = part.get("name")
            if tool:
                tools.append(str(tool))

    return " ".join(summaries).strip(), tools


def truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def one_line(value: str) -> str:
    return " ".join(value.split())


def session_label(path: Path) -> str:
    try:
        return path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_session_file(path: Path, target_date: date) -> list[dict]:
    if not file_started_on_date(path, target_date):
        return []

    session = session_label(path)
    last_prompt = ""
    seen: dict[str, dict] = {}

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return []

    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = obj.get("type")
            if kind == "last-prompt":
                candidate = prompt_from_last_prompt(obj)
                if candidate:
                    last_prompt = candidate
                continue

            if kind == "user":
                candidate = prompt_from_user_message(obj)
                if candidate:
                    last_prompt = candidate
                continue

            if kind != "assistant":
                continue

            msg = obj.get("message", {})
            request_id = msg.get("requestId") or msg.get("id") or f"line-{line_no}"
            usage = msg.get("usage", {})

            input_tokens = int(usage.get("input_tokens", 0) or 0)
            cache_create_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
            cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)

            weighted_total = (
                input_tokens
                + (2 * cache_create_tokens)
                + (0.1 * cache_read_tokens)
                + (5 * output_tokens)
            )

            note, tools = summarize_assistant_message(msg)
            record = seen.get(str(request_id))
            if record is None:
                seen[str(request_id)] = {
                    "session": session,
                    "request_id": str(request_id),
                    "prompt": last_prompt or "-",
                    "input": input_tokens,
                    "cache_write": cache_create_tokens,
                    "cache_read": cache_read_tokens,
                    "output": output_tokens,
                    "total": weighted_total,
                    "tools": Counter(tools),
                    "note": note or "-",
                }
            else:
                record["input"] = max(record["input"], input_tokens)
                record["cache_write"] = max(record["cache_write"], cache_create_tokens)
                record["cache_read"] = max(record["cache_read"], cache_read_tokens)
                record["output"] = max(record["output"], output_tokens)
                record["total"] = max(record["total"], weighted_total)
                record["tools"].update(tools)
                if record["note"] == "-" and note:
                    record["note"] = note

    return list(seen.values())


def merge_session_summary(summary: dict, row: dict) -> None:
    summary["turns"] += 1
    summary["input"] += row["input"]
    summary["cache_write"] += row["cache_write"]
    summary["cache_read"] += row["cache_read"]
    summary["output"] += row["output"]
    summary["total"] += row["total"]
    summary["tools"].update(row["tools"])

    if row["total"] > summary["top_total"]:
        summary["top_total"] = row["total"]
        summary["prompt"] = row["prompt"]
        summary["note"] = row["note"]


def make_categories(row: dict) -> str:
    return one_line(
        f"input={row['input']} "
        f"cache_write={row['cache_write']} "
        f"cache_read={row['cache_read']} "
        f"output={row['output']}"
    )


def print_turns(rows: list[dict], top: int) -> None:
    print("### Top turns")
    print("| total | session | prompt | token categories | tools | note |")
    print("|---:|---|---|---|---|---|")

    for row in rows[:top]:
        tools = ",".join([name for name, _ in row["tools"].most_common(6)]) or "-"
        print(
            "| {total:.1f} | {session} | {prompt} | {categories} | {tools} | {note} |".format(
                total=row["total"],
                session=truncate(row["session"], 42).replace("|", "\\|"),
                prompt=truncate(row["prompt"], 72).replace("|", "\\|"),
                categories=make_categories(row).replace("|", "\\|"),
                tools=tools.replace("|", ","),
                note=truncate(one_line(row["note"]), 110).replace("|", "\\|"),
            )
        )


def print_sessions(rows: list[dict], top: int) -> None:
    print()
    print("### Top sessions")
    print("| total | session | turns | prompt | token categories | tools | note |")
    print("|---:|---|---:|---|---|---|---|")

    for row in rows[:top]:
        tools = ",".join([name for name, _ in row["tools"].most_common(6)]) or "-"
        categories = one_line(
            f"input={row['input']} "
            f"cache_write={row['cache_write']} "
            f"cache_read={row['cache_read']} "
            f"output={row['output']}"
        )
        print(
            "| {total:.1f} | {session} | {turns} | {prompt} | {categories} | {tools} | {note} |".format(
                total=row["total"],
                session=truncate(row["session"], 42).replace("|", "\\|"),
                turns=row["turns"],
                prompt=truncate(row["prompt"], 72).replace("|", "\\|"),
                categories=categories.replace("|", "\\|"),
                tools=tools.replace("|", ","),
                note=truncate(one_line(row["note"]), 110).replace("|", "\\|"),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Show top Claude turns and sessions for a day")
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help="Claude projects root to scan (repeatable; default: ~/.claude/projects and ~/.claude-eng/projects)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Local date to report (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="How many rows to print (default: 20)",
    )
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else datetime.now().astimezone().date()
    roots = [Path(root).expanduser() for root in (args.root or [str(Path.home() / ".claude" / "projects"), str(Path.home() / ".claude-eng" / "projects")])]

    turn_rows: list[dict] = []
    sessions: dict[str, dict] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            rows = scan_session_file(path, target_date)
            if not rows:
                continue

            turn_rows.extend(rows)

            for row in rows:
                session = row["session"]
                summary = sessions.get(session)
                if summary is None:
                    summary = {
                        "session": session,
                        "turns": 0,
                        "input": 0,
                        "cache_write": 0,
                        "cache_read": 0,
                        "output": 0,
                        "total": 0.0,
                        "top_total": -1.0,
                        "prompt": "-",
                        "note": "-",
                        "tools": Counter(),
                    }
                    sessions[session] = summary
                merge_session_summary(summary, row)

    turn_rows.sort(key=lambda item: item["total"], reverse=True)
    session_rows = sorted(sessions.values(), key=lambda item: item["total"], reverse=True)

    print_turns(turn_rows, args.top)
    print_sessions(session_rows, args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
