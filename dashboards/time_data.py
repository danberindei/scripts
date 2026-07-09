"""Pure data helpers for the weekly time dashboard. No Streamlit imports."""

import colorsys
import json
import os
from datetime import date
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("TIME_DATA_DIR", Path.home() / "Performek" / "work" / "time"))

# Weekly calendar palette. Intentionally custom pastels; this is not ColorBrewer
# "Paired", and the blocks should stay soft even after multiple palette cycles.
PASTELS = [
    "#B8D8E8", "#CFE8C6", "#F2C6C2", "#F8E7B5",
    "#D9C6F2", "#F6D1DC", "#C7E8D1", "#C9D8F0",
    "#F6EFC0", "#EFC7D6", "#DDD1F0", "#D7E8C8",
]

# Backward-compatible alias for older imports/tests.
PAIRED = PASTELS

LABEL_MAX_CHARS = 22
LABEL_OUTSIDE_THRESHOLD_PX = 16
LABEL_LINE_HEIGHT_PX = 14
MAX_DAY_HEIGHT_PX = 800


def entries_from_day(day: dict) -> list:
    """Return a flat entries list from a day dict in either file format.

    Old format: day has an "entries" list where each entry carries kind, ticket,
    comment, start, end, minutes directly.

    New format: day has "tasks" (list of {name, kind, ticket, worklog_comment})
    and "segments" (list of {task_name, start, end, minutes, note}).  Each
    segment is joined to its task to produce an old-style entry, with "comment"
    filled from the segment's "note" field, plus an extra "task_name" field that
    slug_of uses to merge ticketless segments of the same task into one block.
    """
    if "segments" in day and "tasks" in day:
        task_map = {t["name"]: t for t in day.get("tasks", [])}
        entries = []
        for seg in day.get("segments", []):
            task = task_map.get(seg.get("task_name", ""), {})
            entries.append({
                "start": seg.get("start", ""),
                "end": seg.get("end", ""),
                "minutes": seg.get("minutes") or 0,
                "kind": task.get("kind", "work"),
                "ticket": task.get("ticket"),
                "task_name": seg.get("task_name", ""),
                "comment": seg.get("note", ""),
            })
        return entries
    return day.get("entries", [])


def load_days(data_dir: Path) -> list:
    """Load all day files from data_dir/YYYY/YYYY-MM-DD.json, sorted by date.

    Skips files that are missing a date field or cannot be parsed.
    Returns a list of dicts: {date: date, entries: list}.
    """
    days = []
    for f in sorted(data_dir.glob("*/????-??-??.json")):
        try:
            day = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        d_str = day.get("date")
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        days.append({"date": d, "entries": entries_from_day(day)})
    days.sort(key=lambda x: x["date"])
    return days


def load_sprints(data_dir: Path) -> dict:
    """Load sprint files from data_dir/YYYY/sprints/*.json across all year dirs.

    Returns a dict with:
        sprints         - list of sprint dicts sorted by start date
        subjects        - merged {ticket_key -> summary} map across all sprint files
        has_sprint_data - True if any sprint files were found
    """
    sprints = []
    subjects = {}
    for sprint_dir in sorted(data_dir.glob("*/sprints")):
        if not sprint_dir.is_dir():
            continue
        for f in sorted(sprint_dir.glob("*.json")):
            if f.name == "no-sprint.json":
                continue
            try:
                sprint = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            sprints.append(sprint)
            subjects.update(sprint.get("tickets", {}))
    sprints.sort(key=lambda s: (s.get("start") or ""))
    return {
        "sprints": sprints,
        "subjects": subjects,
        "has_sprint_data": bool(sprints),
    }


def sprints_for_date(d: date, sprints: list) -> list:
    """Return a list of all sprint dicts covering date d (start-inclusive, end-exclusive)."""
    matches = []
    for sprint in sprints:
        start_str = sprint.get("start")
        end_str = sprint.get("end")
        if not start_str or not end_str:
            continue
        try:
            start = date.fromisoformat(start_str)
            end = date.fromisoformat(end_str)
        except ValueError:
            continue
        if start <= d < end:
            matches.append(sprint)
    return matches


def sprint_for_date(d: date, sprints: list):
    """Return the sprint dict covering date d (start-inclusive, end-exclusive), or None."""
    matches = sprints_for_date(d, sprints)
    return matches[0] if matches else None


def slug_of(entry: dict) -> tuple:
    """Return (slug, display_label) for an entry.

    Slug is the ticket key when ticket is set, otherwise the task name
    (falling back to the comment) so identical tasks merge into one block.
    Display label is the ticket key as-is, or the task name/comment
    truncated to LABEL_MAX_CHARS with an ellipsis appended.
    """
    ticket = entry.get("ticket")
    if ticket:
        return ticket, ticket
    name = entry.get("task_name") or entry.get("comment") or ""
    if len(name) > LABEL_MAX_CHARS:
        display = name[:LABEL_MAX_CHARS] + "..."
    else:
        display = name
    return name, display


def week_of(d: date) -> tuple:
    """Return (ISO year, ISO week number) for date d. Weeks run Monday-Sunday."""
    iso = d.isocalendar()
    return iso.year, iso.week


def _entry_category(entry: dict) -> str:
    """Return 'personal', 'ticket', or 'ticketless' for an entry."""
    if entry.get("kind", "work") == "personal":
        return "personal"
    if entry.get("ticket"):
        return "ticket"
    return "ticketless"


def group_week(
    days: list,
    include_ticket: bool = True,
    include_ticketless: bool = True,
    include_personal: bool = False,
) -> dict:
    """Group entries by day and (slug, kind), summing minutes.

    Returns {date: {(slug, kind): {minutes, entries, display_label}}}.
    Each entry falls into one of three categories (ticket, ticketless, personal);
    entries whose category flag is False are excluded.
    A ticket with both work and meeting entries in a day yields two separate groups.
    """
    allowed = set()
    if include_ticket:
        allowed.add("ticket")
    if include_ticketless:
        allowed.add("ticketless")
    if include_personal:
        allowed.add("personal")

    result = {}
    for day in days:
        d = day["date"]
        day_groups = {}
        for entry in day.get("entries", []):
            if _entry_category(entry) not in allowed:
                continue
            kind = entry.get("kind", "work")
            slug, display_label = slug_of(entry)
            key = (slug, kind)
            if key not in day_groups:
                day_groups[key] = {"minutes": 0, "entries": [], "display_label": display_label}
            day_groups[key]["minutes"] += entry.get("minutes") or 0
            day_groups[key]["entries"].append(entry)
        if day_groups:
            result[d] = day_groups
    return result


def _adjust_lightness(hex_color: str, factor: float) -> str:
    """Return a copy of hex_color with HSL lightness scaled by factor."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    lightness = max(0.1, min(0.9, lightness * factor))
    r2, g2, b2 = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(int(r2 * 255), int(g2 * 255), int(b2 * 255))


def color_map(all_days: list) -> dict:
    """Build a stable slug -> color map ranked by total minutes across all_days.

    Colors are assigned from the weekly pastel palette cyclically. Past the first
    palette cycle, only mild lightness shifts are used so later tickets still read
    as pastels instead of drifting into harsh alert colors.
    Deterministic: no randomness, order depends only on total-minute rank.
    """
    totals: dict = {}
    for day in all_days:
        for entry in day.get("entries", []):
            slug, _ = slug_of(entry)
            totals[slug] = totals.get(slug, 0) + (entry.get("minutes") or 0)

    sorted_slugs = sorted(totals.keys(), key=lambda s: -totals[s])

    palette_size = len(PASTELS)
    result = {}
    variant_factors = (1.08, 0.94, 1.14, 0.88, 1.02, 0.98)
    for i, slug in enumerate(sorted_slugs):
        base = PASTELS[i % palette_size]
        cycle = i // palette_size
        if cycle == 0:
            result[slug] = base
        else:
            result[slug] = _adjust_lightness(base, variant_factors[(cycle - 1) % len(variant_factors)])
    return result


def layout_week(week_data: dict, px_per_min: float, display_mode: str = "proportional") -> dict:
    """Compute pixel layout for each day in week_data.

    week_data: {date: {(slug, kind): {minutes, entries, display_label}}}
    px_per_min: shared scale factor applied uniformly across all displayed weeks.
    display_mode: "proportional" or "fixed-line".

    Returns {date: [block_dict, ...]} where each block dict has:
        slug, kind, display_label, minutes, height_px, top_px,
        label_outside, label_top_px, entries
    """
    import math
    result = {}
    for d, day_groups in week_data.items():
        sorted_groups = sorted(day_groups.items(), key=lambda x: -x[1]["minutes"])

        blocks = []
        top = 0.0
        for (slug, kind), group in sorted_groups:
            if display_mode == "fixed-line":
                height = math.ceil(group["minutes"] / 60.0) * LABEL_LINE_HEIGHT_PX
            else:
                height = max(3.0, group["minutes"] * px_per_min)
            
            blocks.append({
                "slug": slug,
                "kind": kind,
                "display_label": group["display_label"],
                "minutes": group["minutes"],
                "height_px": height,
                "top_px": top,
                "label_outside": height < LABEL_OUTSIDE_THRESHOLD_PX,
                "label_top_px": top,
                "entries": group["entries"],
            })
            top += height

        # Resolve outside label positions: greedy top-to-bottom push to avoid overlaps.
        # Block positions (top_px) are not changed; only label_top_px is adjusted.
        prev_label_bottom = 0.0
        for block in blocks:
            if not block["label_outside"]:
                continue
            label_top = max(block["top_px"], prev_label_bottom)
            block["label_top_px"] = label_top
            prev_label_bottom = label_top + LABEL_LINE_HEIGHT_PX

        result[d] = blocks
    return result
