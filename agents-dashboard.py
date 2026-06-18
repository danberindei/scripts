#!/usr/bin/env python3
"""
Agent token usage dashboard.

Usage:
  streamlit run agents-dashboard.py
"""

import json
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agent_usage_common import calc_cost_breakdown, load_pricing_db

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "agent-usage"
SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_COST_COLS = ["input_cost", "output_cost", "cache_write_cost", "cache_read_cost"]


def run_extractors(data_dir: Path, start: str, end: str):
    """Run every *-usage.py extractor next to this dashboard over [start, end].

    Returns a list of (script_name, ok, message) tuples.
    """
    results = []
    for script in sorted(SCRIPT_DIR.glob("*-usage.py")):
        proc = subprocess.run(
            [sys.executable, str(script), "--start", start, "--end", end, "-o", str(data_dir)],
            capture_output=True, text=True,
        )
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        results.append((script.name, proc.returncode == 0, msg[-1] if msg else ""))
    return results

st.set_page_config(page_title="Agent Usage", layout="wide")
st.title("Agent Usage Dashboard")


@st.cache_data
def load_data(data_dir: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(data_dir.glob("*.jsonl")):
        # The worktree map shares this directory but isn't usage data.
        if f.name == WORKTREE_MAP_FILE:
            continue
        # Filenames are {provider}-{YYYY}-{MM}-{DD}.jsonl; strip the date suffix.
        provider = f.stem.rsplit("-", 3)[0]
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    row["provider"] = provider
                    rows.append(row)
                except json.JSONDecodeError:
                    continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    local_tz = datetime.now().astimezone().tzinfo
    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601", utc=True).dt.tz_convert(local_tz).dt.tz_localize(None)
    df["date"] = df["ts"].dt.floor("D")
    df["hour"] = df["ts"].dt.floor("h")
    df["minute"] = df["ts"].dt.floor("min")

    missing_cost_cols = [col for col in TOKEN_COST_COLS if col not in df.columns]
    if missing_cost_cols:
        pricing_db = load_pricing_db()
        cost_rows = [calc_cost_breakdown(row, pricing_db) for row in df.to_dict("records")]
        cost_df = pd.DataFrame(cost_rows)
        for col in TOKEN_COST_COLS:
            df[col] = cost_df[col]

    return df


# --- Load ---
df = load_data(DEFAULT_DATA_DIR)

if df.empty:
    st.error(f"No data found in {DEFAULT_DATA_DIR}")
    today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    if st.button(f"Run extractors for {today_str}"):
        with st.spinner("Running extractors..."):
            results = run_extractors(DEFAULT_DATA_DIR, today_str, today_str)
        for name, ok, msg in results:
            (st.success if ok else st.warning)(f"{name}: {msg or ('ok' if ok else 'failed')}")
        load_data.clear()
        st.rerun()
    st.stop()

# --- Sidebar ---
st.sidebar.header("Filters")

min_ts = df["ts"].min().to_pydatetime()
max_ts = df["ts"].max().to_pydatetime()
providers = sorted(df["provider"].unique())
all_projects = sorted(df["project_short"].unique())
grains = ["Day", "Hour", "Minute"]

qp = st.query_params

def _qp_date(key, fallback):
    try:
        from datetime import date as _d
        return _d.fromisoformat(qp[key])
    except (KeyError, ValueError):
        return fallback

def _qp_list(key, valid):
    vals = qp.get_all(key)
    return [v for v in vals if v in valid] or None

def _parse_ts(s):
    try:
        ts = pd.Timestamp(s)
        return None if ts is pd.NaT else ts.to_pydatetime()
    except Exception:
        return None

today = datetime.now().astimezone().date()
date_max = max(max_ts.date(), today)

dc1, dc2 = st.sidebar.columns(2)
start_date = dc1.date_input("Start date", value=_qp_date("start", min_ts.date()), min_value=min_ts.date(), max_value=date_max)
end_date = dc2.date_input("End date", value=_qp_date("end", max_ts.date()), min_value=min_ts.date(), max_value=date_max)

if st.sidebar.button("Refresh data"):
    with st.spinner("Running extractors..."):
        st.session_state["refresh_results"] = run_extractors(DEFAULT_DATA_DIR, str(start_date), str(end_date))
    load_data.clear()
    st.rerun()

refresh_results = st.session_state.pop("refresh_results", None)
if refresh_results:
    for name, ok, msg in refresh_results:
        (st.sidebar.success if ok else st.sidebar.warning)(f"{name}: {msg or ('ok' if ok else 'failed')}")

providers_off = set(qp.get_all("provider_off"))
selected_providers = st.sidebar.multiselect("Provider", providers, default=[s for s in providers if s not in providers_off])
selected_projects = st.sidebar.multiselect("Project (leave empty for all)", all_projects, default=_qp_list("project", all_projects) or [])

grain_default = qp.get("grain", "Day")
time_grain = st.sidebar.radio("Time granularity", grains, index=grains.index(grain_default) if grain_default in grains else 0)
top_n = st.sidebar.slider("Top N projects", 5, 30, int(qp.get("top_n", 15)))

# Zoom state (set by horizontal chart selection, persisted in query params)
zoom_start = _parse_ts(qp.get("zoom_start"))
zoom_end = _parse_ts(qp.get("zoom_end"))

st.sidebar.divider()
if zoom_start and zoom_end:
    st.sidebar.caption(f"Zoom: {zoom_start.strftime('%Y-%m-%d %H:%M')} – {zoom_end.strftime('%Y-%m-%d %H:%M')}")
    if st.sidebar.button("Clear zoom"):
        del st.query_params["zoom_start"]
        del st.query_params["zoom_end"]
        st.rerun()
else:
    st.sidebar.caption("Drag horizontally on the chart to zoom.")

# --- Persist sidebar filter state to query params ---
# Done here (before any st.stop()) so the URL updates even when no data matches.
# split_by is synced at the bottom since it's defined in the main content area.
_sidebar_desired = {
    "start": str(start_date),
    "end": str(end_date),
    "grain": time_grain,
    "top_n": str(top_n),
    "provider_off": [s for s in providers if s not in selected_providers],
    "project": selected_projects,
}
for _k, _v in _sidebar_desired.items():
    _current = sorted(qp.get_all(_k))
    _target = sorted(_v if isinstance(_v, list) else [_v])
    if _current != _target:
        st.query_params[_k] = _v

# --- Filter ---
start_ts = datetime.combine(start_date, time(0, 0))
end_ts = datetime.combine(end_date, time(23, 59, 59, 999999))

mask = (df["ts"] >= start_ts) & (df["ts"] <= end_ts) & (df["provider"].isin(selected_providers))
if selected_projects:
    mask &= df["project_short"].isin(selected_projects)
filtered = df[mask]

if filtered.empty:
    st.warning("No events match the current filters.")
    st.stop()

# Zoom applied as secondary filter — all charts and metrics follow it
if zoom_start and zoom_end:
    zm = (filtered["ts"] >= zoom_start) & (filtered["ts"] <= zoom_end)
    display = filtered[zm] if zm.any() else filtered
else:
    display = filtered

time_col = {"Day": "date", "Hour": "hour", "Minute": "minute"}[time_grain]

# --- Summary metrics ---
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total cost", f"${display['cost'].sum():.2f}")
c2.metric("Events", f"{len(display):,}")
c3.metric("Input tokens", f"{display['input'].sum():,.0f}")
c4.metric("Output tokens", f"{display['output'].sum():,.0f}")
c5.metric("Cache read tokens", f"{display['cache_read'].sum():,.0f}")

st.divider()

# --- Cost over time (drag horizontally to zoom) ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Cost over time")
    by_time_source = filtered.groupby([time_col, "provider"])["cost"].sum().reset_index()
    fig = px.line(by_time_source, x=time_col, y="cost", color="provider",
                  labels={"cost": "Cost ($)", time_col: ""})
    fig.update_layout(dragmode="select", selectdirection="h")
    fig.update_yaxes(autorange=True)
    if zoom_start and zoom_end:
        fig.update_xaxes(range=[zoom_start, zoom_end])

    event = st.plotly_chart(fig, on_select="rerun", use_container_width=True, key="cost_time")
    if event and event.selection and event.selection.box:
        box = event.selection.box[0]
        if "x" in box and len(box["x"]) >= 2:
            x0, x1 = sorted(pd.Timestamp(v) for v in box["x"])
            new_zs = x0.strftime("%Y-%m-%dT%H:%M:%S")
            new_ze = x1.strftime("%Y-%m-%dT%H:%M:%S")
            if new_zs != qp.get("zoom_start") or new_ze != qp.get("zoom_end"):
                st.query_params["zoom_start"] = new_zs
                st.query_params["zoom_end"] = new_ze
                st.rerun()

with col_right:
    st.subheader("Cost by model")
    by_model = display.groupby("model")["cost"].sum().reset_index()
    fig = px.pie(by_model, values="cost", names="model")
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- Cost by project ---
st.subheader(f"Top {top_n} projects by cost")
by_project = display.groupby(["project_short", "provider"])["cost"].sum().reset_index()
top_projects = by_project.groupby("project_short")["cost"].sum().nlargest(top_n).index
by_project_top = by_project[by_project["project_short"].isin(top_projects)]
fig = px.bar(by_project_top, x="cost", y="project_short", color="provider", orientation="h",
             labels={"cost": "Cost ($)", "project_short": ""})
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- Cost breakdown over time ---
st.subheader("Cost breakdown over time")
split_options = ["Provider", "Project", "Provider + Project"]
split_default = qp.get("split", "Provider")
split_by = st.radio(
    "Split by", split_options,
    index=split_options.index(split_default) if split_default in split_options else 0,
    horizontal=True,
    key="split_by",
)

if split_by == "Provider":
    grp = "provider"
    breakdown_data = display.copy()
elif split_by == "Project":
    grp = "project_short"
    top = display.groupby("project_short")["cost"].sum().nlargest(top_n).index
    breakdown_data = display.copy()
    breakdown_data[grp] = breakdown_data[grp].where(breakdown_data[grp].isin(top), other="(other)")
else:
    grp = "_label"
    top = display.groupby("project_short")["cost"].sum().nlargest(top_n).index
    breakdown_data = display.copy()
    proj = breakdown_data["project_short"].where(breakdown_data["project_short"].isin(top), other="(other)")
    breakdown_data[grp] = proj + " / " + breakdown_data["provider"]

by_time_grp = breakdown_data.groupby([time_col, grp])["cost"].sum().reset_index()
fig = px.bar(by_time_grp, x=time_col, y="cost", color=grp,
             labels={"cost": "Cost ($)", time_col: "", grp: ""})
st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- Token breakdown over time ---
st.subheader("Token breakdown over time (cost-weighted)")
token_cost_by_time = display.groupby(time_col)[TOKEN_COST_COLS].sum().reset_index()
token_cost_melted = token_cost_by_time.melt(
    id_vars=time_col,
    value_vars=TOKEN_COST_COLS,
    var_name="token_type",
    value_name="cost",
)
token_cost_melted["token_type"] = token_cost_melted["token_type"].str.replace("_cost", "", regex=False)
fig = px.bar(token_cost_melted, x=time_col, y="cost", color="token_type",
             labels={"cost": "Cost ($)", time_col: ""})
st.plotly_chart(fig, use_container_width=True)

# --- Persist split_by to query params ---
# (sidebar params are synced earlier, before any st.stop())
if qp.get("split") != split_by:
    st.query_params["split"] = split_by
