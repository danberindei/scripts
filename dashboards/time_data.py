"""Pure data helpers for the weekly time dashboard. No Streamlit imports."""

import colorsys
import json
import os
from datetime import date
from pathlib import Path

DEFAULT_DATA_DIR = Path(os.environ.get("TIME_DATA_DIR", Path.home() / "Performek" / "work" / "time"))

# ColorBrewer "Paired" qualitative palette (12 colors). Duplicated here to keep
# this module Streamlit-free so it can be imported in tests without a running server.
PAIRED = [
    "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c",
    "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00",
    "#cab2d6", "#6a3d9a", "#ffff99", "#b15928",
]

LABEL_MAX_CHARS = 22
LABEL_OUTSIDE_THRESHOLD_PX = 16
LABEL_LINE_HEIGHT_PX = 14
MAX_DAY_HEIGHT_PX = 800


def load_days(data_dir: Path) -> list:
    """Load all day files from data_dir/YYYY/YYYY-MM-DD.json, sorted by date.

    Skips files that are missing a date field or cannot be parsed.
    Returns a list of dicts: {date: date, entries: list}.
    """
    days = []
    for f in sorted(data_dir.glob("*/*.json")):
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
        days.append({"date": d, "entries": day.get("entries", [])})
    days.sort(key=lambda x: x["date"])
    return days


def load_sprints(data_dir: Path) -> dict:
    """Load sprint files from data_dir/sprints/*.json.

    Returns a dict with:
        sprints         - list of sprint dicts sorted by start date
        subjects        - merged {ticket_key -> summary} map across all sprint files
        has_sprint_data - True if any sprint files were found
    """
    sprint_dir = data_dir / "sprints"
    sprints = []
    subjects = {}
    if sprint_dir.exists():
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


def sprint_for_date(d: date, sprints: list):
    """Return the sprint dict covering date d (start-inclusive, end-exclusive), or None."""
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
            return sprint
    return None


def slug_of(entry: dict) -> tuple:
    """Return (slug, display_label) for an entry.

    Slug is the ticket key when ticket is set, otherwise the comment verbatim so
    identical comments merge into one block. Display label is the ticket key as-is,
    or the comment truncated to LABEL_MAX_CHARS with an ellipsis appended.
    """
    ticket = entry.get("ticket")
    if ticket:
        return ticket, ticket
    comment = entry.get("comment") or ""
    if len(comment) > LABEL_MAX_CHARS:
        display = comment[:LABEL_MAX_CHARS] + "..."
    else:
        display = comment
    return comment, display


def week_of(d: date) -> tuple:
    """Return (ISO year, ISO week number) for date d. Weeks run Monday-Sunday."""
    iso = d.isocalendar()
    return iso.year, iso.week


def group_week(days: list, include_personal: bool) -> dict:
    """Group entries by day and (slug, kind), summing minutes.

    Returns {date: {(slug, kind): {minutes, entries, display_label}}}.
    Personal entries are excluded unless include_personal is True.
    A ticket with both work and meeting entries in a day yields two separate groups.
    """
    result = {}
    for day in days:
        d = day["date"]
        day_groups = {}
        for entry in day.get("entries", []):
            kind = entry.get("kind", "work")
            if kind == "personal" and not include_personal:
                continue
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

    Colors are assigned from PAIRED cyclically. Past the first palette cycle (12
    slugs), lightness is varied so colors remain distinguishable across cycles.
    Deterministic: no randomness, order depends only on total-minute rank.
    """
    totals: dict = {}
    for day in all_days:
        for entry in day.get("entries", []):
            slug, _ = slug_of(entry)
            totals[slug] = totals.get(slug, 0) + (entry.get("minutes") or 0)

    sorted_slugs = sorted(totals.keys(), key=lambda s: -totals[s])

    palette_size = len(PAIRED)
    result = {}
    for i, slug in enumerate(sorted_slugs):
        base = PAIRED[i % palette_size]
        cycle = i // palette_size
        if cycle == 0:
            result[slug] = base
        elif cycle == 1:
            result[slug] = _adjust_lightness(base, 1.45)
        elif cycle == 2:
            result[slug] = _adjust_lightness(base, 0.65)
        else:
            result[slug] = _adjust_lightness(base, 1.0 + 0.18 * (cycle - 3))
    return result


def layout_week(week_data: dict, px_per_min: float) -> dict:
    """Compute pixel layout for each day in week_data.

    week_data: {date: {(slug, kind): {minutes, entries, display_label}}}
    px_per_min: shared scale factor applied uniformly across all displayed weeks.

    Returns {date: [block_dict, ...]} where each block dict has:
        slug, kind, display_label, minutes, height_px, top_px,
        label_outside, label_top_px, entries
    """
    result = {}
    for d, day_groups in week_data.items():
        sorted_groups = sorted(day_groups.items(), key=lambda x: -x[1]["minutes"])

        blocks = []
        top = 0.0
        for (slug, kind), group in sorted_groups:
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
