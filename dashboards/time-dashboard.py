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

from dashboard_ui import PAIRED, persist_query_params, qp_date, qp_list, seed_widget_state
from time_data import entries_from_day

DEFAULT_DATA_DIR = Path(os.environ.get("TIME_DATA_DIR", Path.home() / "Performek" / "work" / "time"))

# A real Jira ticket looks like ENG-1234; anything else is a "(...)" placeholder.
TICKET_RE = re.compile(r"^[A-Z]+-\d+$")

# Labels for non-work entries whose ticket field is null.
NULL_TICKET_LABELS = {
    "meeting": "(meetings)",
    "personal": "(personal)",
}

# Keyword sub-buckets for work entries that carry no ticket, so the overhead isn't
# one opaque "(untracked)" slice. First match wins. Building the time-tracker is tool
# work, so "time-track"/"time track" live in (tooling); (notes) is the daily-notes
# habit only. (notes) precedes (tooling) so an entry mentioning both notes and time
# tracking counts as the habit, while pure time-tracker building lands in tooling.
UNTRACKED_BUCKETS = [
    ("(comms)", ("comms", "slack", "gmail", "email")),
    ("(notes)", ("notes",)),
    ("(tooling)", ("time-track", "time track", "dashboard", "kitty", "opensearch", "token", "monitor", "skill", "idea-jira", "plugin", "tool")),
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


def resolve_ticket(kind: str, ticket, comment: str = "") -> str:
    """Pick a grouping label for an entry's ticket.

    Explicit ticket wins; ticketless work is classified into an overhead
    sub-bucket; other kinds get a kind-based placeholder.
    """
    if ticket:
        return ticket
    if kind == "work":
        return classify_untracked(comment)
    return NULL_TICKET_LABELS.get(kind, "(untracked)")


def attribution_of(ticket_label: str) -> str:
    """Ticketed if the resolved label is a real ticket, else ticketless overhead."""
    return "ticketed" if TICKET_RE.match(ticket_label) else "ticketless"


def stacked_bar(data, cat_col, cat_order, stack_col, stack_order, horizontal):
    """Build a stacked bar chart whose x/y axes swap with the orientation toggle.

    ``cat_col`` is the primary axis (one bar per value, ordered by ``cat_order``);
    ``stack_col`` is the stacked series/color (or None for single-color bars).
    Horizontal puts ``cat_col`` on y and hours on x; vertical swaps them. Horizontal
    mode grows ~28px per bar so long label lists stay legible; vertical uses a fixed
    height. The category axis is forced categorical so ISO date labels aren't auto-typed
    as a date axis and thinned.
    """
    orders = {cat_col: cat_order}
    labels = {"hours": "Hours", cat_col: ""}
    if stack_col:
        labels[stack_col] = ""
        # Only pin the stack order when one is given; px chokes on a None order value.
        if stack_order is not None:
            orders[stack_col] = stack_order
    if horizontal:
        x, y, orient = "hours", cat_col, "h"
    else:
        x, y, orient = cat_col, "hours", "v"
    fig = px.bar(data, x=x, y=y, color=stack_col, orientation=orient,
                 color_discrete_sequence=PAIRED, category_orders=orders, labels=labels)
    cat_ref, hrs_ref = ("%{y}", "%{x:.1f}") if horizontal else ("%{x}", "%{y:.1f}")
    if stack_col:
        fig.update_traces(hovertemplate=f"<b>%{{fullData.name}}</b><br>{cat_ref}<br>{hrs_ref} h<extra></extra>")
    else:
        fig.update_traces(hovertemplate=f"{cat_ref}<br>{hrs_ref} h<extra></extra>")
    if horizontal:
        fig.update_layout(height=max(400, len(cat_order) * 28), yaxis=dict(type="category"))
    else:
        fig.update_layout(height=500, xaxis=dict(type="category"))
    return fig


@st.cache_data
def load_entries(data_dir: Path) -> pd.DataFrame:
    """Flatten every day's JSON into one row per entry.

    Skips the *-worklog-*.md and *.md timeline files; only *.json days are read.

    Cached here (not in a wrapper) so edits to this parsing logic bust the cache;
    st.cache_data keys on the decorated function's own source, not its callees.
    """
    rows = []
    for f in sorted(data_dir.glob("*/????-??-??.json")):
        try:
            day = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        date = day.get("date")
        for e in entries_from_day(day):
            kind = e.get("kind", "work")
            minutes = e.get("minutes") or 0
            comment = e.get("comment", "")
            ticket = resolve_ticket(kind, e.get("ticket"), comment)
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

    # Every control is bound to session_state via key= and seeded once from the query
    # params, rather than fed value=/default= each rerun. A recomputed value= fights the
    # query-param write-back below (the widget snaps back mid-change), which is the
    # choppiness the grain slider showed. Keys/params are t_-prefixed and page-specific:
    # this app is one st.navigation instance whose session_state and query params are
    # shared across pages, so unprefixed names would collide with the agents page (whose
    # split-by options and finer grains aren't valid here).
    dc1, dc2 = st.sidebar.columns(2)
    default_start = max(min_date, max_date - timedelta(days=7))
    seed_widget_state("t_start", qp_date("t_start", default_start))
    seed_widget_state("t_end", qp_date("t_end", max_date))
    start_date = dc1.date_input("Start date", min_value=min_date, max_value=max_date, key="t_start")
    end_date = dc2.date_input("End date", min_value=min_date, max_value=max_date, key="t_end")

    # Time entries are day-grained, so only the 1w/1d subset is meaningful here.
    grain_opts = ["1w", "1d"]
    _g = st.query_params.get("t_grain", "1d")
    seed_widget_state("t_grain", _g if _g in grain_opts else "1d")
    grain = st.sidebar.select_slider("Time granularity", options=grain_opts, key="t_grain")

    # Default to every kind except "personal" so the charts open on work-relevant time.
    seed_widget_state("t_kind", qp_list("t_kind", all_kinds) or [k for k in all_kinds if k != "personal"])
    selected_kinds = st.sidebar.multiselect("Kind", all_kinds, key="t_kind")
    seed_widget_state("t_ticket", qp_list("t_ticket", all_tickets) or [])
    selected_tickets = st.sidebar.multiselect("Ticket (leave empty for all)", all_tickets, key="t_ticket")

    # --- Filter ---
    mask = ((df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
            & (df["kind"].isin(selected_kinds)))
    if selected_tickets:
        mask &= df["ticket"].isin(selected_tickets)
    display = df[mask].copy()

    # --- Persist sidebar state to query params ---
    persist_query_params({
        "t_start": str(start_date),
        "t_end": str(end_date),
        "t_grain": grain,
        "t_kind": selected_kinds,
        "t_ticket": selected_tickets,
    })

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

    # --- Hours split by chosen dimensions; both charts share one axis-orientation toggle ---
    ctrl1, ctrl2 = st.columns([3, 2])
    seed_widget_state("t_split_dims", [d for d in st.query_params.get_all("t_split_dims") if d in DIM_OPTIONS] or ["ticket"])
    split_dims = ctrl1.multiselect("Split by", DIM_OPTIONS, max_selections=len(DIM_OPTIONS), key="t_split_dims")

    orient_opts = ["Horizontal", "Vertical"]
    _o = st.query_params.get("t_orient", "Horizontal")
    seed_widget_state("t_orient", _o if _o in orient_opts else "Horizontal")
    orient = ctrl2.radio("Bar orientation", orient_opts, key="t_orient", horizontal=True)
    horizontal = orient == "Horizontal"

    group_cols = ["bucket"] + split_dims
    chart_data = display.groupby(group_cols)["hours"].sum().reset_index()
    chart_data["bucket_label"] = chart_data["bucket"].dt.strftime("%Y-%m-%d")
    # Order the time buckets chronologically so segments/rows read oldest-to-newest.
    bucket_order = [b.strftime("%Y-%m-%d") for b in sorted(chart_data["bucket"].unique())]

    if not split_dims:
        color_col = None
    elif len(split_dims) == 1:
        color_col = split_dims[0]
    else:
        chart_data["_label"] = chart_data[split_dims].apply(lambda row: " / ".join(row.astype(str)), axis=1)
        color_col = "_label"

    # Chart 1: time buckets are the primary axis, split categories stacked.
    st.subheader("Hours over time")
    fig = stacked_bar(chart_data, "bucket_label", bucket_order, color_col, None, horizontal)
    st.plotly_chart(fig, width="stretch")

    # Chart 2: split categories are the primary axis, time buckets stacked.
    if color_col:
        st.subheader("Hours by category, pivoted over time")
        pivoted = chart_data.copy()
        # Sort categories by total hours so the biggest contributors sit together.
        cat_totals = pivoted.groupby(color_col)["hours"].sum().sort_values(ascending=False)
        # Cap the number of category bars; roll the long tail into one bucket so the
        # chart stays readable without silently dropping hours from the totals.
        MAX_CATS = 40
        if len(cat_totals) > MAX_CATS:
            keep = set(cat_totals.index[:MAX_CATS])
            n_rolled = len(cat_totals) - MAX_CATS
            roll_label = f"(+{n_rolled} smaller)"
            pivoted[color_col] = pivoted[color_col].where(pivoted[color_col].isin(keep), roll_label)
            # Collapsing several categories into roll_label can create duplicate rows
            # within a bucket, so re-aggregate before plotting.
            pivoted = pivoted.groupby(["bucket", "bucket_label", color_col], as_index=False)["hours"].sum()
            cat_order = cat_totals.index[:MAX_CATS].tolist() + [roll_label]
            st.caption(f"Showing top {MAX_CATS} categories; {n_rolled} smaller rolled into {roll_label}.")
        else:
            cat_order = cat_totals.index.tolist()
        fig2 = stacked_bar(pivoted, color_col, cat_order, "bucket_label", bucket_order, horizontal)
        st.plotly_chart(fig2, width="stretch")

    # --- Persist split_dims and orientation ---
    persist_query_params({"t_split_dims": split_dims, "t_orient": orient})
    if st.query_params.get("orient") != orient:
        st.query_params["orient"] = orient


if __name__ == "__main__":
    main()
