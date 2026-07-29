#!/usr/bin/env python3
"""
Weekly calendar view for time tracking data.

Renders one section per selected week as a custom HTML/CSS/JS calendar table.
Each day column shows stacked colored blocks proportional to minutes, with
labels inside tall blocks and outside (with leader lines) for short ones.

Usage:
  streamlit run weeks-dashboard.py
"""

import html
import json
import math
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from dashboard_ui import get_date, get_str, persist, repaint_on_page_entry, seed_widget_state
from time_data import (
    DEFAULT_DATA_DIR,
    LABEL_LINE_HEIGHT_PX,
    LABEL_OUTSIDE_THRESHOLD_PX,
    MAX_DAY_HEIGHT_PX,
    color_map,
    group_week,
    layout_week,
    load_days,
    load_sprints,
    load_workstreams,
    slug_of,
    sprint_for_date,
    sprints_for_date,
    week_of,
)

WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BLOCK_SIZE_RULES = ["min 1", "min 2", "min 5", "jira"]
DEFAULT_BLOCK_SIZE_RULE = "jira"


def _round_jira_worklog_minutes(raw_minutes: float) -> int:
    """Match the canonical Jira worklog rounder used when posting worklogs.

    Verbatim copy of round_worklog_minutes in
    ~/Performek/work/scripts/worklog_rounding.py (kept in sync by hand; this
    dashboard has no import path to that script). Rounding rule:
    - raw < 1 min: drops to 0 (the only value ever dropped).
    - 1 <= raw <= 30 min: round(raw + 1) to the nearest 5 min.
    - raw > 30 min: round(raw + 3) to the nearest 15 min, so 31..34 -> 30 and
      35+ -> 45.
    """
    if raw_minutes < 1:
        return 0
    if raw_minutes <= 30:
        return 5 * math.ceil((raw_minutes + 1) / 5 - 0.5)
    return 15 * math.ceil((raw_minutes + 3) / 15 - 0.5)


def _normalize_block_size_rule(value) -> str:
    if value in BLOCK_SIZE_RULES:
        return value
    legacy_map = {
        "0": "min 1",
        "1": "min 1",
        "2": "min 2",
        "5": "min 5",
    }
    return legacy_map.get(str(value), DEFAULT_BLOCK_SIZE_RULE)


def _block_minimum_minutes(rule: str) -> int:
    rule = _normalize_block_size_rule(rule)
    return int(rule.split()[1])


def _apply_block_size_rule(week_data: dict, block_size_rule: str) -> dict:
    rule = _normalize_block_size_rule(block_size_rule)
    adjusted_week = {}
    for day, day_groups in week_data.items():
        adjusted_groups = {}
        for key, value in day_groups.items():
            raw_minutes = value["minutes"]
            if rule == "jira":
                rounded_minutes = _round_jira_worklog_minutes(raw_minutes)
                if rounded_minutes <= 0:
                    continue
                adjusted_value = dict(value)
                adjusted_value["minutes"] = rounded_minutes
            else:
                if raw_minutes < _block_minimum_minutes(rule):
                    continue
                adjusted_value = value
            adjusted_groups[key] = adjusted_value
        if adjusted_groups:
            adjusted_week[day] = adjusted_groups
    return adjusted_week


def _fmt_hhmm(minutes) -> str:
    minutes = int(minutes)
    h = minutes // 60
    m = minutes % 60
    return f"{h}:{m:02d}"


def _week_monday(isoyear: int, isoweek: int) -> date:
    return date.fromisocalendar(isoyear, isoweek, 1)


def _week_dates(isoyear: int, isoweek: int) -> list:
    monday = _week_monday(isoyear, isoweek)
    return [monday + timedelta(days=i) for i in range(7)]


def _week_label(isoyear: int, isoweek: int, sprint_data: dict) -> str:
    """Build the week header base without the hours total: 'W27: Jun 29 - Jul 05 - ENG Sprint 212'."""
    monday = _week_monday(isoyear, isoweek)
    sunday = monday + timedelta(days=6)
    m_abbr = MONTH_ABBR[monday.month - 1]
    s_abbr = MONTH_ABBR[sunday.month - 1]
    start_fmt = f"{m_abbr} {monday.day}"
    end_fmt = f"{s_abbr} {sunday.day}"

    sprint_names = []
    sprints = sprint_data.get("sprints", [])
    seen = set()
    for i in range(7):
        d = monday + timedelta(days=i)
        found_sprints = sprints_for_date(d, sprints)
        for s in found_sprints:
            if s.get("name") and s["name"] not in seen:
                sprint_names.append(s["name"])
                seen.add(s["name"])
    sprint_part = " - " + " / ".join(sprint_names) if sprint_names else ""

    return f"W{isoweek}: {start_fmt} - {end_fmt}{sprint_part}"


def _build_week_html(
    week_dates_list: list,
    layout: dict,
    colors: dict,
    subjects: dict,
    max_bar_height_px: float,
    display_mode: str = "proportional",
    day_totals: dict = None,
    workstreams: dict = None,
) -> tuple:
    """Build HTML string and required iframe height for one week section.

    week_dates_list: list of date objects (Mon-Sun).
    layout: {date: [block_dict, ...]} from layout_week().
    colors: {slug: hex_color} from color_map().
    subjects: {ticket_key: summary} from sprint data.
    workstreams: {ticket_key: label} from workstream data, shown in tooltips.
    max_bar_height_px: the shared vertical scale for this render.

    Returns (html_str, iframe_height_px).
    """
    # Determine which weekend columns to hide (both Sat+Sun empty).
    sat = week_dates_list[5]
    sun = week_dates_list[6]
    hide_weekend = sat not in layout and sun not in layout

    active_dates = week_dates_list[:5] if hide_weekend else week_dates_list

    # Compute the actual content height needed.
    max_content_h = max_bar_height_px

    iframe_height = int(max_content_h) + 60  # 40px header + 20px padding

    day_cols_html = []
    for d in active_dates:
        blocks = layout.get(d, [])
        wd = d.isocalendar().weekday - 1  # 0=Mon
        day_name = WEEKDAY_ABBR[wd]
        date_str = f"{d.month}/{d.day}"

        if day_totals is not None:
            day_total_min = day_totals.get(d, 0)
        else:
            day_total_min = sum(b["minutes"] for b in blocks)
        total_str = _fmt_hhmm(day_total_min) if day_total_min else "-"

        bar_html_parts = []

        for block in blocks:
            slug = block["slug"]
            kind = block["kind"]
            h_px = block["height_px"]
            top = block["top_px"]
            color = colors.get(slug, "#aaaaaa")
            label = block["display_label"]
            mins_str = _fmt_hhmm(block["minutes"])

            # Build tooltip data.
            entry_list = []
            for e in block["entries"]:
                entry_list.append({
                    "start": e.get("start", ""),
                    "end": e.get("end", ""),
                    "minutes": e.get("minutes") or 0,
                    "comment": e.get("comment") or "",
                    "decision": e.get("decision") or "",
                })
            subject = subjects.get(slug, "")
            workstream = (workstreams or {}).get(slug, "")
            tip_data = {
                "slug": slug,
                "subject": subject,
                "workstream": workstream,
                "total_min": block["minutes"],
                "entries": entry_list,
            }
            tip_attr = html.escape(json.dumps(tip_data), quote=True)

            extra_class = f" {kind}" if kind in ("meeting", "personal") else ""
            personal_style = " filter:saturate(0.2) brightness(0.95);" if kind == "personal" else ""

            inner = (
                f'<span class="inner-label">'
                f'{html.escape(label)} &middot; {mins_str}'
                f'</span>'
            )

            # Determine width for the color fill: proportional to hour in fixed-line mode.
            fill_width = "100%"
            if display_mode == "fixed-line" and block["minutes"] < 60:
                fill_width = f"{(block['minutes'] / 60.0 * 100):.1f}%"

            fill_extra_class = " meeting-fill" if kind == "meeting" else ""

            bar_html_parts.append(
                f'<div class="block{extra_class}" '
                f'style="top:{top:.1f}px;height:{h_px:.1f}px;width:100%;background:transparent;" '
                f'data-tip="{tip_attr}">'
                f'<div class="block-fill{fill_extra_class}" style="width:{fill_width};height:100%;background:{color};{personal_style}"></div>'
                f'{inner}</div>'
            )

        svg_html = ""

        day_cols_html.append(f"""
<div class="day-col">
  <div class="day-header">
    <div class="day-date">{day_name} {date_str}</div>
    <div class="day-total">{total_str}</div>
  </div>
  <div class="day-body" style="height:{max_bar_height_px:.0f}px">
    <div class="bar-area">{''.join(bar_html_parts)}</div>
    {svg_html}
    <div class="gutter-area"></div>
  </div>
</div>""")

    week_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 12px; color: #333; background: transparent; height: 100%; position: relative; }}
.week-days {{ display: flex; gap: 1px; align-items: flex-start; }}
.day-col {{ flex: 1; min-width: 0; }}
.day-header {{ text-align: center; padding: 4px 2px 8px; line-height: 1.3; }}
.day-date {{ font-weight: 600; font-size: 11px; }}
.day-total {{ color: #777; font-size: 10px; }}
.day-body {{ position: relative; }}
.bar-area {{ position: absolute; left: 0; width: 100%; top: 0; bottom: 0; }}
.block {{ position: absolute; overflow: visible; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.2); }}
.block-fill {{ position: absolute; left: 0; top: 0; pointer-events: none; }}
.block-fill.meeting-fill::after {{ content: ''; position: absolute; inset: 0; background: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0,0,0,0.1) 4px, rgba(0,0,0,0.1) 8px); pointer-events: none; }}
.inner-label {{ position: absolute; left: 3px; right: 3px; top: 50%; transform: translateY(-50%); font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; color: #333; }}
#wk-detail-popup {{ position: absolute; top:0; left:0; right:0; bottom:0; background: rgba(0,0,0,0.4); display: none; z-index: 10000; justify-content: center; align-items: center; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
.detail-card {{ background: #fff; color: #333; padding: 20px; border-radius: 8px; max-width: 400px; width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.3); position: relative; }}
.detail-close {{ position: absolute; top: 10px; right: 10px; cursor: pointer; font-weight: bold; font-size: 18px; color: #999; }}
.detail-header h2 {{ margin: 0 0 5px 0; font-size: 16px; }}
.detail-slug {{ font-size: 11px; color: #777; margin-bottom: 10px; }}
.detail-workstream {{ font-size: 11px; color: #b8860b; margin-top: -6px; margin-bottom: 10px; }}
.detail-total {{ font-weight: 600; margin-bottom: 15px; font-size: 13px; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
.entry-row {{ display: flex; gap: 10px; font-size: 12px; margin-bottom: 4px; }}
.entry-time {{ color: #666; min-width: 80px; }}
.entry-duration {{ font-weight: 600; min-width: 40px; }}
.entry-comment {{ color: #444; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.decision-row {{ font-size: 11px; color: #777; padding-left: 90px; margin-bottom: 8px; font-style: italic; }}
.leader-svg {{ position: absolute; left: 0; top: 0; width: 100%; overflow: visible; pointer-events: none; z-index: 2; }}
.gutter-area {{ display: none; }}
.outer-label {{ display: none; }}
#wk-tooltip {{ position: fixed; background: #1e1e2e; color: #cdd6f4; padding: 8px 10px; border-radius: 5px; font-size: 11px; max-width: 340px; pointer-events: none; z-index: 9999; display: none; line-height: 1.5; box-shadow: 0 2px 10px rgba(0,0,0,0.35); word-break: break-word; }}
#wk-tooltip b {{ color: #89b4fa; }}
#wk-tooltip .entry-line {{ color: #a6adc8; font-size: 10px; }}
#wk-tooltip .decision-line {{ color: #7f849c; font-size: 10px; padding-left: 10px; }}
#wk-tooltip .subject-line {{ color: #a6e3a1; font-size: 10px; }}
#wk-tooltip .workstream-line {{ color: #f9e2af; font-size: 10px; }}
#wk-tooltip .missing-line {{ color: #f38ba8; font-size: 10px; font-style: italic; }}
</style>
</head>
<body>
<div id="wk-tooltip"></div>
<div id="wk-detail-popup"></div>
<div class="week-days">
{''.join(day_cols_html)}
</div>
<script>
(function() {{
  var tip = document.getElementById('wk-tooltip');
  var popup = document.getElementById('wk-detail-popup');

  function esc(s) {{
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}

  function fmtDur(m) {{
    var s = Math.round((Number(m) || 0) * 60);
    var h = Math.floor(s / 3600), mn = Math.floor((s % 3600) / 60), sec = s % 60;
    var out = '';
    if (h) out += h + 'h';
    if (mn || h) out += mn + 'm';
    return out + sec + 's';
  }}

  function buildTip(d) {{
    var subject = d.subject ? esc(d.subject) : null;
    var slug = esc(d.slug);
    var header = subject ? '<b>' + subject + '</b> (' + slug + ')' : '<b>' + slug + '</b>';
    var tip = header + ' &middot; ' + fmtDur(d.total_min);
    if (d.workstream) {{
      tip += '<div class="workstream-line">' + esc(d.workstream) + '</div>';
    }}
    return tip;
  }}

  function buildDetail(d) {{
    var subject = d.subject ? esc(d.subject) : null;
    var slug = esc(d.slug);
    var title = subject || slug;
    var subtitle = subject ? '<div class="detail-slug">' + slug + '</div>' : '';
    if (d.workstream) {{
      subtitle += '<div class="detail-workstream">' + esc(d.workstream) + '</div>';
    }}
    var rows = '';
    for (var i = 0; i < d.entries.length; i++) {{
      var e = d.entries[i];
      var range = e.start && e.end ? esc(e.start) + '-' + esc(e.end) : '';
      rows += '<div class="entry-row">'
        + '<span class="entry-time">' + range + '</span>'
        + '<span class="entry-duration">' + fmtDur(e.minutes) + '</span>'
        + '<span class="entry-comment">' + esc(e.comment) + '</span>'
        + '</div>';
      if (e.decision) {{
        rows += '<div class="decision-row">&#8627; ' + esc(e.decision) + '</div>';
      }}
    }}
    return '<div class="detail-card">'
      + '<span class="detail-close" id="wk-detail-close">&times;</span>'
      + '<div class="detail-header"><h2>' + esc(title) + '</h2>' + subtitle + '</div>'
      + '<div class="detail-total">Total: ' + fmtDur(d.total_min) + '</div>'
      + rows
      + '</div>';
  }}

  function hideDetail() {{
    popup.style.display = 'none';
    popup.innerHTML = '';
  }}

  function showDetail(d) {{
    tip.style.display = 'none';
    popup.innerHTML = buildDetail(d);
    popup.style.display = 'flex';
    document.getElementById('wk-detail-close').addEventListener('click', hideDetail);
  }}

  popup.addEventListener('click', function(e) {{
    if (e.target === popup) hideDetail();
  }});

  function position(e) {{
    var cx = e.clientX, cy = e.clientY;
    var gap = 14;
    var tw = tip.offsetWidth;
    var th = tip.offsetHeight;
    var x = (cx + gap + tw < window.innerWidth - 4) ? cx + gap : cx - gap - tw;
    var y = (cy + gap + th < window.innerHeight - 4) ? cy + gap : cy - gap - th;
    if (x < 4) x = 4;
    if (y < 4) y = 4;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }}

  document.querySelectorAll('.block').forEach(function(el) {{
    el.addEventListener('mouseenter', function(e) {{
      var d = JSON.parse(el.dataset.tip);
      tip.innerHTML = buildTip(d);
      tip.style.display = 'block';
      position(e);
    }});
    el.addEventListener('mousemove', position);
    el.addEventListener('mouseleave', function() {{
      tip.style.display = 'none';
    }});
    el.addEventListener('click', function(e) {{
      var d = JSON.parse(el.dataset.tip);
      showDetail(d);
      e.stopPropagation();
    }});
  }});
}})();
</script>
</body>
</html>"""

    return week_html, iframe_height


def _legend_rows(all_days: list, selected_week_keys: list, colors: dict, subjects: dict) -> list:
    """Build legend rows for the selected weeks, ordered by total minutes descending."""
    selected_set = set(selected_week_keys)
    slug_mins: dict = {}
    for day in all_days:
        if week_of(day["date"]) not in [tuple(int(x) for x in k.split("-W")) for k in selected_set]:
            continue
        for entry in day.get("entries", []):
            if entry.get("kind") == "personal":
                continue
            slug, disp = slug_of(entry)
            if slug not in slug_mins:
                slug_mins[slug] = {"minutes": 0, "display_label": disp}
            slug_mins[slug]["minutes"] += entry.get("minutes") or 0
    rows = sorted(slug_mins.items(), key=lambda x: -x[1]["minutes"])
    result = []
    for slug, info in rows:
        result.append({
            "slug": slug,
            "display_label": info["display_label"],
            "minutes": info["minutes"],
            "color": colors.get(slug, "#aaa"),
            "subject": subjects.get(slug, ""),
        })
    return result


def main():
    st.set_page_config(page_title="Weekly Calendar", layout="wide")
    st.title("Weekly Calendar")

    all_days = load_days(DEFAULT_DATA_DIR)
    if not all_days:
        st.error(f"No time-tracking JSON found under {DEFAULT_DATA_DIR}")
        st.stop()

    sprint_data = load_sprints(DEFAULT_DATA_DIR)
    workstreams = load_workstreams(DEFAULT_DATA_DIR)
    if not sprint_data["has_sprint_data"]:
        st.caption(
            "Sprint data has not been backfilled yet. "
            "Run: python3 /home/dan/Performek/work/scripts/update-sprint-data.py --backfill-dates"
        )

    colors = color_map(all_days)

    # Build the list of weeks that have data, newest first.
    week_day_map: dict = {}
    for day in all_days:
        wk = week_of(day["date"])
        week_day_map.setdefault(wk, []).append(day)

    # ISO week key format: "YYYY-W{week}" e.g. "2026-W27"
    all_week_keys = sorted(
        [f"{y}-W{w}" for y, w in week_day_map.keys()],
        reverse=True,
    )

    week_key_to_iso = {
        f"{y}-W{w}": (y, w) for y, w in week_day_map.keys()
    }

    week_labels = {
        wk_key: _week_label(*week_key_to_iso[wk_key], sprint_data)
        for wk_key in all_week_keys
    }

    # Sidebar controls - all state via w_-prefixed keys + query params.

    sprints_list = sprint_data.get("sprints", [])

    # Deduplicate sprints by name, keeping the last occurrence (most up-to-date).
    seen_sprint_names: dict = {}
    for s in sprints_list:
        if s.get("name") and s.get("start") and s.get("end"):
            seen_sprint_names[s["name"]] = s
    unique_sprints = sorted(seen_sprint_names.values(), key=lambda s: s["start"])
    sprint_by_name = {s["name"]: s for s in unique_sprints}

    today = date.today()
    current_sprints = sprints_for_date(today, unique_sprints)
    if current_sprints:
        default_start = min(date.fromisoformat(s["start"]) for s in current_sprints)
        default_end = max(date.fromisoformat(s["end"]) - timedelta(days=1) for s in current_sprints)
    else:
        default_start = today - timedelta(days=today.weekday())
        default_end = today

    seed_start = get_date("w_start", default_start)
    seed_end = get_date("w_end", default_end)
    seed_widget_state("w_date_range", (seed_start, seed_end))

    if "w_selected_sprints" not in st.session_state:
        st.session_state["w_selected_sprints"] = {s["name"] for s in current_sprints}

    date_range = st.sidebar.date_input("Date range", key="w_date_range")
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        range_start, range_end = date_range[0], date_range[1]
    else:
        range_start = range_end = date_range[0] if date_range else default_start

    # Sprint shortcut buttons: last 3 per project, newest-first in a row.
    # Clicking toggles selection; the date range becomes the union of selected sprints.
    def toggle_sprint(name):
        sel = st.session_state["w_selected_sprints"]
        if name in sel:
            sel.discard(name)
        else:
            sel.add(name)
        if sel:
            starts = [date.fromisoformat(sprint_by_name[n]["start"]) for n in sel if n in sprint_by_name]
            ends = [date.fromisoformat(sprint_by_name[n]["end"]) - timedelta(days=1) for n in sel if n in sprint_by_name]
            st.session_state["w_date_range"] = (min(starts), max(ends))

    sprint_groups: dict = {}
    for s in unique_sprints:
        name = s.get("name", "")
        prefix = name.split(" Sprint ")[0] if " Sprint " in name else name
        sprint_groups.setdefault(prefix, []).append(s)

    with st.sidebar:
        for group in sprint_groups.values():
            recent = group[-3:]
            cols = st.columns(len(recent))
            for i, sprint in enumerate(reversed(recent)):
                name = sprint["name"]
                label = name.replace(" Sprint", "")
                is_sel = name in st.session_state["w_selected_sprints"]
                with cols[i]:
                    st.button(
                        label,
                        type="primary" if is_sel else "secondary",
                        on_click=toggle_sprint,
                        args=(name,),
                        key=f"w_sprint_btn_{name}",
                        use_container_width=True,
                    )

    selected_week_keys = [
        wk_key for wk_key in all_week_keys
        if _week_monday(*week_key_to_iso[wk_key]) <= range_end
        and _week_monday(*week_key_to_iso[wk_key]) + timedelta(days=6) >= range_start
    ]

    seed_widget_state("w_ticket", get_str("w_ticket", "1") == "1")
    include_ticket = st.sidebar.checkbox("Ticket", key="w_ticket")

    seed_widget_state("w_ticketless", get_str("w_ticketless", "1") == "1")
    include_ticketless = st.sidebar.checkbox("Ticketless", key="w_ticketless")

    seed_widget_state("w_personal", get_str("w_personal", "0") == "1")
    include_personal = st.sidebar.checkbox("Personal", key="w_personal")

    block_size_rule_seed = _normalize_block_size_rule(
        get_str("w_block_size_rule", get_str("w_min_size", None))
    )
    seed_widget_state("w_block_size_rule", block_size_rule_seed)
    block_size_rule = st.sidebar.select_slider("Block size rules", options=BLOCK_SIZE_RULES, key="w_block_size_rule")

    seed_widget_state("w_mode", get_str("w_mode", "fixed-line"))
    display_mode = st.sidebar.radio("Display Mode", ["proportional", "fixed-line"], key="w_mode")

    persist({
        "w_start": str(range_start),
        "w_end": str(range_end),
        "w_ticket": "1" if include_ticket else "0",
        "w_ticketless": "1" if include_ticketless else "0",
        "w_personal": "1" if include_personal else "0",
        "w_block_size_rule": block_size_rule,
        "w_mode": display_mode,
    })

    if not selected_week_keys:
        st.info("No weeks with data in the selected date range.")
        st.stop()

    # Compute shared vertical scale from the tallest day across all selected weeks.
    max_day_minutes = 0
    for wk_key in selected_week_keys:
        iso = week_key_to_iso[wk_key]
        days_this_week = week_day_map.get(iso, [])
        wk_data = _apply_block_size_rule(
            group_week(days_this_week, include_ticket, include_ticketless, include_personal),
            block_size_rule,
        )

        for d_groups in wk_data.values():
            day_total = sum(g["minutes"] for g in d_groups.values())
            if day_total > max_day_minutes:
                max_day_minutes = day_total

    if max_day_minutes == 0:
        st.warning("No blocks to show: the selected block size rule dropped every block in this range.")
        st.stop()

    if display_mode == "fixed-line":
        px_per_min = LABEL_LINE_HEIGHT_PX / 60.0

        # Find the day that has the most total rounded-up height
        max_rounded_height = 0
        for wk_key in selected_week_keys:
            iso = week_key_to_iso[wk_key]
            days_this_week = week_day_map.get(iso, [])
            wk_data = _apply_block_size_rule(
                group_week(days_this_week, include_ticket, include_ticketless, include_personal),
                block_size_rule,
            )

            for d_groups in wk_data.values():
                day_rounded_h = sum(math.ceil(g["minutes"] / 60.0) * LABEL_LINE_HEIGHT_PX for g in d_groups.values())
                if day_rounded_h > max_rounded_height:
                    max_rounded_height = day_rounded_h
        max_bar_height_px = max_rounded_height
    else:
        px_per_min = min(1.0, MAX_DAY_HEIGHT_PX / max_day_minutes) if max_day_minutes else 1.0
        max_bar_height_px = max_day_minutes * px_per_min

    # Render each selected week, newest first.
    for wk_key in selected_week_keys:
        iso = week_key_to_iso[wk_key]
        isoyear, isoweek = iso

        days_this_week = week_day_map.get(iso, [])
        wk_data = _apply_block_size_rule(
            group_week(days_this_week, include_ticket, include_ticketless, include_personal),
            block_size_rule,
        )

        # Compute daily totals for the header based on the filtered data.
        day_totals = {d: sum(g["minutes"] for g in groups.values()) for d, groups in wk_data.items()}
        total_h = sum(day_totals.values()) / 60.0
        st.subheader(f"{week_labels[wk_key]} ({total_h:.1f}h)")

        wk_layout = layout_week(wk_data, px_per_min, display_mode)
        wk_dates = _week_dates(isoyear, isoweek)

        week_html, iframe_height = _build_week_html(
            wk_dates,
            wk_layout,
            colors,
            sprint_data["subjects"],
            max_bar_height_px,
            display_mode,
            day_totals=day_totals,
            workstreams=workstreams,
        )
        components.html(week_html, height=iframe_height, scrolling=False)

    repaint_on_page_entry("weeks")


if __name__ == "__main__":
    main()
