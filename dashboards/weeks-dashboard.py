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

from dashboard_ui import persist_query_params, qp_list, seed_widget_state
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
    slug_of,
    sprint_for_date,
    week_of,
)

WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_hhmm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h}:{m:02d}"


def _week_monday(isoyear: int, isoweek: int) -> date:
    return date.fromisocalendar(isoyear, isoweek, 1)


def _week_dates(isoyear: int, isoweek: int) -> list:
    monday = _week_monday(isoyear, isoweek)
    return [monday + timedelta(days=i) for i in range(7)]


def _week_label(isoyear: int, isoweek: int, all_days: list, sprint_data: dict) -> str:
    """Build the week selector label: 'W27: Jun 29 - Jul 05 (32.4h) - ENG Sprint 212'."""
    monday = _week_monday(isoyear, isoweek)
    sunday = monday + timedelta(days=6)
    m_abbr = MONTH_ABBR[monday.month - 1]
    s_abbr = MONTH_ABBR[sunday.month - 1]
    start_fmt = f"{m_abbr} {monday.day}"
    end_fmt = f"{s_abbr} {sunday.day}"

    week_days_set = {monday + timedelta(days=i) for i in range(7)}
    total_min = 0
    for day in all_days:
        if day["date"] not in week_days_set:
            continue
        for entry in day.get("entries", []):
            if entry.get("kind") != "personal":
                total_min += entry.get("minutes") or 0
    total_h = total_min / 60.0

    sprint_names = []
    sprints = sprint_data.get("sprints", [])
    seen = set()
    for d in [monday, sunday]:
        s = sprint_for_date(d, sprints)
        if s and s.get("name") and s["name"] not in seen:
            sprint_names.append(s["name"])
            seen.add(s["name"])
    sprint_part = " - " + " / ".join(sprint_names) if sprint_names else ""

    return f"W{isoweek}: {start_fmt} - {end_fmt} ({total_h:.1f}h){sprint_part}"


def _build_week_html(
    week_dates_list: list,
    layout: dict,
    colors: dict,
    subjects: dict,
    max_bar_height_px: float,
    display_mode: str = "proportional",
) -> tuple:
    """Build HTML string and required iframe height for one week section.

    week_dates_list: list of date objects (Mon-Sun).
    layout: {date: [block_dict, ...]} from layout_week().
    colors: {slug: hex_color} from color_map().
    subjects: {ticket_key: summary} from sprint data.
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

    iframe_height = int(max_content_h) + 80  # 40px header + 40px padding

    day_cols_html = []
    for d in active_dates:
        blocks = layout.get(d, [])
        wd = d.isocalendar().weekday - 1  # 0=Mon
        day_name = WEEKDAY_ABBR[wd]
        date_str = f"{d.month}/{d.day}"

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
            tip_data = {
                "slug": slug,
                "subject": subject,
                "total": mins_str,
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
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 12px; color: #333; background: transparent; }}
.week-days {{ display: flex; gap: 1px; align-items: flex-start; }}
.day-col {{ flex: 1; min-width: 0; }}
.day-header {{ text-align: center; padding: 4px 2px 8px; line-height: 1.3; }}
.day-date {{ font-weight: 600; font-size: 11px; }}
.day-total {{ color: #777; font-size: 10px; }}
.day-body {{ position: relative; }}
.bar-area {{ position: absolute; left: 0; width: 100%; top: 0; bottom: 0; }}
.block {{ position: absolute; overflow: visible; cursor: default; border-bottom: 1px solid rgba(255,255,255,0.2); }}
.block-fill {{ position: absolute; left: 0; top: 0; pointer-events: none; }}
.block-fill.meeting-fill::after {{ content: ''; position: absolute; inset: 0; background: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0,0,0,0.1) 4px, rgba(0,0,0,0.1) 8px); pointer-events: none; }}
.inner-label {{ position: absolute; left: 3px; right: 3px; top: 50%; transform: translateY(-50%); font-size: 9px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; color: #333; }}
.leader-svg {{ position: absolute; left: 0; top: 0; width: 100%; overflow: visible; pointer-events: none; z-index: 2; }}
.gutter-area {{ display: none; }}
.outer-label {{ display: none; }}
#wk-tooltip {{ position: fixed; background: #1e1e2e; color: #cdd6f4; padding: 8px 10px; border-radius: 5px; font-size: 11px; max-width: 340px; pointer-events: none; z-index: 9999; display: none; line-height: 1.5; box-shadow: 0 2px 10px rgba(0,0,0,0.35); word-break: break-word; }}
#wk-tooltip b {{ color: #89b4fa; }}
#wk-tooltip .entry-line {{ color: #a6adc8; font-size: 10px; }}
#wk-tooltip .decision-line {{ color: #7f849c; font-size: 10px; padding-left: 10px; }}
#wk-tooltip .subject-line {{ color: #a6e3a1; font-size: 10px; }}
#wk-tooltip .missing-line {{ color: #f38ba8; font-size: 10px; font-style: italic; }}
</style>
</head>
<body>
<div id="wk-tooltip"></div>
<div class="week-days">
{''.join(day_cols_html)}
</div>
<script>
(function() {{
  var tip = document.getElementById('wk-tooltip');

  function esc(s) {{
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}

  function fmtMin(m) {{
    var h = Math.floor(m / 60), mn = m % 60;
    return h + ':' + (mn < 10 ? '0' : '') + mn;
  }}

  function buildTip(d) {{
    var html = '<b>' + esc(d.slug) + '</b> &middot; ' + esc(d.total);
    if (d.subject) {{
      html += '<br><span class="subject-line">' + esc(d.subject) + '</span>';
    }} else if (d.slug.match(/^[A-Z]+-\\d+$/)) {{
      html += '<br><span class="missing-line">subject not cached in sprint file</span>';
    }}
    for (var i = 0; i < d.entries.length; i++) {{
      var e = d.entries[i];
      var range = e.start && e.end ? e.start + '-' + e.end + ' &middot; ' : '';
      html += '<br><span class="entry-line">' + range + fmtMin(e.minutes) + 'm';
      if (e.comment) html += ' &middot; ' + esc(e.comment);
      html += '</span>';
      if (e.decision) {{
        html += '<br><span class="decision-line">&#8627; ' + esc(e.decision) + '</span>';
      }}
    }}
    return html;
  }}

  function position(e) {{
    var x = e.clientX + 14, y = e.clientY + 14;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    var r = tip.getBoundingClientRect();
    if (r.bottom > window.innerHeight - 8) {{
      tip.style.top = (e.clientY - r.height - 14) + 'px';
      r = tip.getBoundingClientRect();
    }}
    if (r.top < 8) tip.style.top = '8px';

    if (r.right > window.innerWidth - 8) {{
      tip.style.left = (e.clientX - r.width - 14) + 'px';
      r = tip.getBoundingClientRect();
    }}
    if (r.left < 8) tip.style.left = '8px';
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
    if not sprint_data["has_sprint_data"]:
        st.caption(
            "Sprint data has not been backfilled yet. "
            "Run: python3 scripts/update-sprint-data.py --backfill-from-time"
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
        wk_key: _week_label(*week_key_to_iso[wk_key], all_days, sprint_data)
        for wk_key in all_week_keys
    }

    # Sidebar controls - all state via w_-prefixed keys + query params.
    st.sidebar.header("Weeks")

    default_weeks = [all_week_keys[0]] if all_week_keys else []
    seed_widget_state("w_weeks", qp_list("w_weeks", all_week_keys) or default_weeks)
    selected_week_keys = st.sidebar.multiselect(
        "Select weeks",
        options=all_week_keys,
        format_func=lambda k: week_labels.get(k, k),
        key="w_weeks",
    )

    seed_widget_state("w_ticket", st.query_params.get("w_ticket", "1") == "1")
    include_ticket = st.sidebar.checkbox("Ticket", key="w_ticket")

    seed_widget_state("w_ticketless", st.query_params.get("w_ticketless", "1") == "1")
    include_ticketless = st.sidebar.checkbox("Ticketless", key="w_ticketless")

    seed_widget_state("w_personal", st.query_params.get("w_personal", "0") == "1")
    include_personal = st.sidebar.checkbox("Personal", key="w_personal")

    seed_widget_state("w_min_size", int(st.query_params.get("w_min_size", "0")))
    min_size = st.sidebar.slider("Min block size (min)", 0, 60, 0, key="w_min_size")

    seed_widget_state("w_mode", st.query_params.get("w_mode", "proportional"))
    display_mode = st.sidebar.radio("Display Mode", ["proportional", "fixed-line"], key="w_mode")

    persist_query_params({
        "w_weeks": selected_week_keys,
        "w_ticket": "1" if include_ticket else "0",
        "w_ticketless": "1" if include_ticketless else "0",
        "w_personal": "1" if include_personal else "0",
        "w_min_size": str(min_size),
        "w_mode": display_mode,
    })

    if not selected_week_keys:
        st.info("Select one or more weeks from the sidebar.")
        st.stop()

    # Compute shared vertical scale from the tallest day across all selected weeks.
    max_day_minutes = 0
    for wk_key in selected_week_keys:
        iso = week_key_to_iso[wk_key]
        days_this_week = week_day_map.get(iso, [])
        wk_data = group_week(days_this_week, include_ticket, include_ticketless, include_personal)
        
        # Filter by minimum size for scale calculation
        if min_size > 0:
            wk_data = {
                d: {k: v for k, v in day_groups.items() if v["minutes"] >= min_size}
                for d, day_groups in wk_data.items()
            }
            # Remove empty days
            wk_data = {d: g for d, g in wk_data.items() if g}

        for d_groups in wk_data.values():
            day_total = sum(g["minutes"] for g in d_groups.values())
            if day_total > max_day_minutes:
                max_day_minutes = day_total

    if max_day_minutes == 0:
        st.warning("No data in the selected weeks.")
        st.stop()

    if display_mode == "fixed-line":
        px_per_min = LABEL_LINE_HEIGHT_PX / 60.0
        
        # Find the day that has the most total rounded-up height
        max_rounded_height = 0
        for wk_key in selected_week_keys:
            iso = week_key_to_iso[wk_key]
            days_this_week = week_day_map.get(iso, [])
            wk_data = group_week(days_this_week, include_ticket, include_ticketless, include_personal)
            if min_size > 0:
                wk_data = {d: {k: v for k, v in g.items() if v["minutes"] >= min_size} for d, g in wk_data.items()}
            
            for d_groups in wk_data.values():
                day_rounded_h = sum(math.ceil(g["minutes"] / 60.0) * LABEL_LINE_HEIGHT_PX for g in d_groups.values())
                if day_rounded_h > max_rounded_height:
                    max_rounded_height = day_rounded_h
        max_bar_height_px = max_rounded_height
    else:
        px_per_min = min(1.0, MAX_DAY_HEIGHT_PX / max_day_minutes)
        max_bar_height_px = max_day_minutes * px_per_min

    # Legend popover.
    legend_rows = _legend_rows(all_days, selected_week_keys, colors, sprint_data["subjects"])
    with st.popover("Legend"):
        for row in legend_rows:
            swatch = f'<span style="display:inline-block;width:12px;height:12px;background:{row["color"]};border-radius:2px;margin-right:6px;vertical-align:middle"></span>'
            label = html.escape(row["display_label"])
            subj = f' - {html.escape(row["subject"])}' if row["subject"] else ""
            mins = _fmt_hhmm(row["minutes"])
            st.markdown(
                f'{swatch}<b>{label}</b>{subj} &nbsp; {mins}',
                unsafe_allow_html=True,
            )
        st.caption("Meetings: diagonal stripe overlay. Personal: desaturated (shown only when toggle is on).")

    # Render each selected week, newest first.
    for wk_key in selected_week_keys:
        iso = week_key_to_iso[wk_key]
        isoyear, isoweek = iso
        st.subheader(week_labels[wk_key])

        days_this_week = week_day_map.get(iso, [])
        wk_data = group_week(days_this_week, include_ticket, include_ticketless, include_personal)
        
        if min_size > 0:
            wk_data = {
                d: {k: v for k, v in day_groups.items() if v["minutes"] >= min_size}
                for d, day_groups in wk_data.items()
            }
            wk_data = {d: g for d, g in wk_data.items() if g}
            
        wk_layout = layout_week(wk_data, px_per_min, display_mode)
        wk_dates = _week_dates(isoyear, isoweek)

        week_html, iframe_height = _build_week_html(
            wk_dates,
            wk_layout,
            colors,
            sprint_data["subjects"],
            max_bar_height_px,
            display_mode,
        )
        components.html(week_html, height=iframe_height, scrolling=False)


if __name__ == "__main__":
    main()
