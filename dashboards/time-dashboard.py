#!/usr/bin/env python3
"""
Time-tracking dashboard.

Reads the per-day time-tracking JSON files (one file per day, each with an
``entries`` list of ``{start, end, minutes, kind, ticket, comment}``) and charts
hours worked over time, split by the dimensions you choose.

Usage:
  streamlit run time-dashboard.py
"""

import json
import os
import re
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DEFAULT_DATA_DIR = Path(os.environ.get("TIME_DATA_DIR", Path.home() / "Performek" / "work" / "time"))

# ColorBrewer "Paired" qualitative palette (matches agents-dashboard.py) for the
# ticket/kind slices and stacked bars.
PAIRED = [
    "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c",
    "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00",
    "#cab2d6", "#6a3d9a", "#ffff99", "#b15928",
]

# A real Jira ticket looks like ENG-1234; anything else is a "(...)" placeholder.
TICKET_RE = re.compile(r"^[A-Z]+-\d+$")

# Labels for non-work entries whose ticket field is null. Meetings fall back to the
# day's meeting_ticket (handled in the loader) before reaching these.
NULL_TICKET_LABELS = {
    "meeting": "(meetings)",
    "personal": "(personal)",
}

# Keyword sub-buckets for work entries that carry no ticket, so the overhead isn't
# one opaque "(untracked)" slice. First match wins, so keep specific groups ahead of
# broad ones (e.g. "time-track" tooling reads as workspace, not generic tooling).
UNTRACKED_BUCKETS = [
    ("(comms)", ("comms", "slack", "gmail", "email")),
    ("(workspace/notes)", ("time-track", "time track", "notes", "workspace", "admin", "recollection")),
    ("(tooling)", ("dashboard", "kitty", "opensearch", "token", "monitor", "skill", "idea-jira", "plugin", "tool")),
    ("(env/setup)", ("paseo", "ide", "intellij", "terminal", "setup", "config")),
    ("(ops)", ("memory", "swap", "deploy", "oper")),
]

DIM_OPTIONS = ["kind", "ticket", "attribution"]


def classify_untracked(comment: str) -> str:
    """Bucket a ticketless work entry by keywords in its comment."""
    c = (comment or "").lower()
    for label, keywords in UNTRACKED_BUCKETS:
        if any(k in c for k in keywords):
            return label
    return "(other)"


def resolve_ticket(kind: str, ticket, meeting_ticket, comment: str = "") -> str:
    """Pick a grouping label for an entry's ticket.

    Explicit ticket wins; a meeting with no ticket rolls up to the day's
    meeting_ticket; ticketless work is classified into an overhead sub-bucket;
    other kinds get a kind-based placeholder.
    """
    if ticket:
        return ticket
    if kind == "meeting" and meeting_ticket:
        return meeting_ticket
    if kind == "work":
        return classify_untracked(comment)
    return NULL_TICKET_LABELS.get(kind, "(untracked)")


def attribution_of(ticket_label: str) -> str:
    """Ticketed if the resolved label is a real ticket, else ticketless overhead."""
    return "ticketed" if TICKET_RE.match(ticket_label) else "ticketless"


@st.cache_data
def load_entries(data_dir: Path) -> pd.DataFrame:
    """Flatten every day's JSON into one row per entry.

    Skips the *-worklog-*.md and *.md timeline files; only *.json days are read.

    Cached here (not in a wrapper) so edits to this parsing logic bust the cache;
    st.cache_data keys on the decorated function's own source, not its callees.
    """
    rows = []
    for f in sorted(data_dir.glob("*/*.json")):
        try:
            day = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        date = day.get("date")
        meeting_ticket = day.get("meeting_ticket")
        for e in day.get("entries", []):
            kind = e.get("kind", "work")
            minutes = e.get("minutes") or 0
            comment = e.get("comment", "")
            ticket = resolve_ticket(kind, e.get("ticket"), meeting_ticket, comment)
            rows.append({
                "date": date,
                "kind": kind,
                "ticket": ticket,
                "attribution": attribution_of(ticket),
                "minutes": minutes,
                "hours": minutes / 60.0,
                "comment": comment,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def main() -> None:
    st.set_page_config(page_title="Time Tracking", layout="wide")
    st.title("Time Tracking Dashboard")

    df = load_entries(DEFAULT_DATA_DIR)

    if df.empty:
        st.error(f"No time-tracking JSON found under {DEFAULT_DATA_DIR}")
        st.stop()

    # --- Sidebar filters ---
    st.sidebar.header("Filters")

    min_date = df["date"].min().date()
    max_date = df["date"].max().date()
    all_kinds = sorted(df["kind"].unique())
    all_tickets = sorted(df["ticket"].unique())

    qp = st.query_params

    def _qp_date(key, fallback):
        try:
            from datetime import date as _d
            return _d.fromisoformat(qp[key])
        except (KeyError, ValueError):
            return fallback

    def _qp_list(key, valid):
        vals = [v for v in qp.get_all(key) if v in valid]
        return vals or None

    dc1, dc2 = st.sidebar.columns(2)
    default_start = max(min_date, max_date - timedelta(days=30))
    start_date = dc1.date_input("Start date", value=_qp_date("start", default_start),
                                min_value=min_date, max_value=max_date)
    end_date = dc2.date_input("End date", value=_qp_date("end", max_date),
                              min_value=min_date, max_value=max_date)

    # Same widget/label/vocabulary as agents-dashboard.py's grain control, so the two
    # pages feel consistent and can share the "grain" query param. Time entries are
    # day-grained, so only the 1w/1d subset is meaningful here. Read defensively: a
    # finer grain the other page set (e.g. 1h) isn't a valid option, so fall back to 1d.
    grain_opts = ["1w", "1d"]
    grain_default = qp.get("grain", "1d")
    if grain_default not in grain_opts:
        grain_default = "1d"
    grain = st.sidebar.select_slider("Time granularity", options=grain_opts, value=grain_default)

    selected_kinds = st.sidebar.multiselect("Kind", all_kinds, default=_qp_list("kind", all_kinds) or all_kinds)
    selected_tickets = st.sidebar.multiselect("Ticket (leave empty for all)", all_tickets,
                                              default=_qp_list("ticket", all_tickets) or [])

    # --- Filter ---
    mask = ((df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
            & (df["kind"].isin(selected_kinds)))
    if selected_tickets:
        mask &= df["ticket"].isin(selected_tickets)
    display = df[mask].copy()

    # --- Persist sidebar state to query params ---
    _sidebar_desired = {
        "start": str(start_date),
        "end": str(end_date),
        "grain": grain,
        "kind": list(selected_kinds) if selected_kinds != all_kinds else [],
        "ticket": selected_tickets,
    }
    for _k, _v in _sidebar_desired.items():
        _current = sorted(qp.get_all(_k))
        _target = sorted(_v if isinstance(_v, list) else [_v])
        if _current != _target:
            st.query_params[_k] = _v

    if display.empty:
        st.warning("No entries match the current filters.")
        st.stop()

    # Bucket timestamp: start-of-week for the weekly grain, else the day itself.
    if grain == "1w":
        display["bucket"] = display["date"].dt.to_period("W").dt.start_time
    else:
        display["bucket"] = display["date"]

    # --- Summary metrics ---
    by_kind = display.groupby("kind")["hours"].sum()
    n_days = display["date"].dt.date.nunique()
    work_hours = by_kind.get("work", 0.0)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total hours", f"{display['hours'].sum():.1f}")
    c2.metric("Work", f"{work_hours:.1f}")
    c3.metric("Meetings", f"{by_kind.get('meeting', 0.0):.1f}")
    c4.metric("Days tracked", f"{n_days}")
    c5.metric("Avg work / day", f"{(work_hours / n_days if n_days else 0):.1f}")

    st.divider()

    # --- Hours over time, split by chosen dimensions ---
    st.subheader("Hours over time")

    split_dims_default = [d for d in qp.get_all("split_dims") if d in DIM_OPTIONS] or ["kind"]
    split_dims = st.multiselect("Split by", DIM_OPTIONS, default=split_dims_default,
                                max_selections=len(DIM_OPTIONS), key="split_dims")

    group_cols = ["bucket"] + split_dims
    chart_data = display.groupby(group_cols)["hours"].sum().reset_index()
    # A categorical y-axis of date strings forces one labeled row per bucket; a
    # continuous date axis auto-thins ticks (~weekly) and leaves weekend gaps.
    chart_data["bucket_label"] = chart_data["bucket"].dt.strftime("%Y-%m-%d")
    bucket_order = [b.strftime("%Y-%m-%d") for b in sorted(chart_data["bucket"].unique())]

    if not split_dims:
        color_col = None
    elif len(split_dims) == 1:
        color_col = split_dims[0]
    else:
        chart_data["_label"] = chart_data[split_dims].apply(lambda row: " / ".join(row.astype(str)), axis=1)
        color_col = "_label"

    fig = px.bar(chart_data, x="hours", y="bucket_label", color=color_col, orientation="h",
                 color_discrete_sequence=PAIRED,
                 category_orders={"bucket_label": bucket_order},
                 labels={"hours": "Hours", "bucket_label": "", color_col or "": ""})
    if color_col:
        fig.update_traces(hovertemplate="<b>%{fullData.name}</b><br>%{y}<br>%{x:.1f} h<extra></extra>")
    else:
        fig.update_traces(hovertemplate="%{y}<br>%{x:.1f} h<extra></extra>")
    # ~28px per bucket so every day/week label has room; floor keeps small ranges sane.
    # Force a category axis: Plotly otherwise auto-types the ISO date strings as a
    # date axis and thins the ticks (and dtick on a date axis is in milliseconds).
    fig.update_layout(height=max(400, len(bucket_order) * 28),
                      yaxis=dict(type="category"))
    st.plotly_chart(fig, use_container_width=True)

    # --- Pivoted view: split dimension on the x-axis, time buckets stacked ---
    if color_col:
        st.subheader("Hours by category, pivoted over time")
        pivoted = chart_data.copy()
        # Order the time buckets chronologically so the stacked segments and legend
        # read oldest-to-newest, then label them as plain date strings.
        bucket_order = [b.strftime("%Y-%m-%d") for b in sorted(pivoted["bucket"].unique())]
        pivoted["bucket_label"] = pivoted["bucket"].dt.strftime("%Y-%m-%d")
        # Sort categories by total hours so the biggest contributors sit together.
        cat_order = (pivoted.groupby(color_col)["hours"].sum()
                     .sort_values(ascending=False).index.tolist())
        fig2 = px.bar(
            pivoted, x="hours", y=color_col, color="bucket_label", orientation="h",
            color_discrete_sequence=PAIRED,
            category_orders={color_col: cat_order, "bucket_label": bucket_order},
            labels={"hours": "Hours", color_col: "", "bucket_label": ""},
        )
        fig2.update_traces(hovertemplate="<b>%{y}</b><br>%{fullData.name}<br>%{x:.1f} h<extra></extra>")
        # ~28px per category so every ticket/kind label stays visible.
        fig2.update_layout(height=max(400, len(cat_order) * 28))
        st.plotly_chart(fig2, use_container_width=True)

    # --- Persist split_dims ---
    if sorted(qp.get_all("split_dims")) != sorted(split_dims):
        st.query_params["split_dims"] = split_dims


if __name__ == "__main__":
    main()
