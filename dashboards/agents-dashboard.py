#!/usr/bin/env python3
"""
Agent token usage dashboard.

Usage:
  streamlit run agents-dashboard.py
"""

import json
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from plotly.colors import sample_colorscale

from agent_usage_common import WORKTREE_MAP_FILE
from dashboard_ui import persist_query_params, seed_widget_state

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "agent-usage"
SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_COST_COLS = ["input_cost", "output_cost", "cache_write_cost", "cache_read_cost"]

# Each provider gets one ColorBrewer single-hue sequential scale; the keys within a
# provider (projects or models) are sampled as evenly-spaced swatches from that
# scale. These scales are perceptually tuned, so the shades read as one color family
# without hand-rolled HLS math.
PROVIDER_SCALES = [
    px.colors.sequential.Blues,
    px.colors.sequential.Oranges,
    px.colors.sequential.Greens,
    px.colors.sequential.Reds,
    px.colors.sequential.Purples,
    px.colors.sequential.BuPu,
    px.colors.sequential.YlGn,
    px.colors.sequential.Greys,
]
# Sample within this sub-range of each scale to avoid the near-white and near-black
# extremes at the ends.
_SCALE_LO = 0.35
_SCALE_HI = 0.85

# ColorBrewer "Paired" qualitative palette (12 colors, light/dark pairs). Plotly
# doesn't ship this one, so define it explicitly. Used for the pie slices.
PAIRED = [
    "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c",
    "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00",
    "#cab2d6", "#6a3d9a", "#ffff99", "#b15928",
]


def provider_scale_map(providers):
    """Assign each provider (sorted) a stable sequential scale, shared across charts."""
    ordered = sorted(providers)
    return {p: PROVIDER_SCALES[i % len(PROVIDER_SCALES)] for i, p in enumerate(ordered)}


def _provider_shades(scale, n):
    """Return n colors sampled evenly from a sequential scale, light to dark."""
    if n == 1:
        return sample_colorscale(scale, [0.6])
    positions = [_SCALE_LO + (_SCALE_HI - _SCALE_LO) * i / (n - 1) for i in range(n)]
    return sample_colorscale(scale, positions)


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

    # project and project_short are resolved by the extractors at write time, so the
    # rows are read as-is here.
    df = pd.DataFrame(rows)

    local_tz = datetime.now().astimezone().tzinfo
    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601", utc=True).dt.tz_convert(local_tz).dt.tz_localize(None)

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
MINUTES_PER_DAY = 24 * 60
# Cap on the number of bars the "cost over time" chart auto-picks a grain for.
MAX_BUCKETS = MINUTES_PER_DAY
grains = ["1w", "1d", "1h", "30m", "15m", "5m", "1m"]
GRAIN_MINUTES = {"1w": 10080, "1d": MINUTES_PER_DAY, "1h": 60, "30m": 30, "15m": 15, "5m": 5, "1m": 1}

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

today = datetime.now().astimezone().date()
date_max = max(max_ts.date(), today)

# Every control is bound to session_state via key= and seeded once from the query
# params, rather than fed value=/default=/index= each rerun. A recomputed arg fights the
# query-param write-back below (the widget snaps back mid-change), the choppiness the
# grain slider showed. Keys/params are a_-prefixed and page-specific: this app is one
# st.navigation instance whose session_state and query params are shared across pages,
# so unprefixed names would collide with the time page.
dc1, dc2 = st.sidebar.columns(2)
seed_widget_state("a_start", _qp_date("a_start", today - timedelta(days=7)))
seed_widget_state("a_end", _qp_date("a_end", max_ts.date()))
start_date = dc1.date_input("Start date", min_value=min_ts.date(), max_value=date_max, key="a_start")
end_date = dc2.date_input("End date", min_value=min_ts.date(), max_value=date_max, key="a_end")

if st.sidebar.button("Refresh data"):
    with st.spinner("Running extractors..."):
        st.session_state["refresh_results"] = run_extractors(DEFAULT_DATA_DIR, str(start_date), str(end_date))
    load_data.clear()
    st.rerun()

refresh_results = st.session_state.pop("refresh_results", None)
if refresh_results:
    for name, ok, msg in refresh_results:
        (st.sidebar.success if ok else st.sidebar.warning)(f"{name}: {msg or ('ok' if ok else 'failed')}")

# The query param stores the OFF providers, so the widget's session_state (the ON set)
# is seeded as the complement.
seed_widget_state("a_provider", [s for s in providers if s not in set(qp.get_all("a_provider_off"))])
selected_providers = st.sidebar.multiselect("Provider", providers, key="a_provider")
seed_widget_state("a_project", _qp_list("a_project", all_projects) or [])
selected_projects = st.sidebar.multiselect("Project (leave empty for all)", all_projects, key="a_project")

_range_key = (str(start_date), str(end_date))
if "a_grain" not in st.session_state:
    _g = qp.get("a_grain", "1d")
    st.session_state["a_grain"] = _g if _g in grains else "1d"
    st.session_state["a_grain_range_key"] = _range_key

# Auto-pick a readable grain only when the date range changes; manual grain
# changes are always respected. Uses the theoretical bucket count over the span
# (an upper bound on the actual data points), which keeps this deterministic and
# independent of filtering. This programmatic override sets session_state before the
# widget renders, which is compatible with the key= binding.
_span_min = ((end_date - start_date).days + 1) * MINUTES_PER_DAY
_grain_points = lambda g: _span_min / GRAIN_MINUTES[g]
if st.session_state.get("a_grain_range_key") != _range_key:
    st.session_state["a_grain_range_key"] = _range_key
    current_grain = st.session_state["a_grain"]
    idx = grains.index(current_grain)
    # _grain_points is monotonic in the grain index, so the fitting grains form a
    # contiguous range: keep the current grain if it fits, else clamp toward the band.
    band = [i for i, g in enumerate(grains) if 2 <= _grain_points(g) <= MAX_BUCKETS]
    if band:
        # Clamp is a no-op when idx is already in band.
        st.session_state["a_grain"] = grains[min(max(idx, band[0]), band[-1])]
    else:
        st.session_state["a_grain"] = "1m" if _grain_points("1m") < 2 else "1w"
time_grain = st.sidebar.select_slider("Time granularity", options=grains, key="a_grain")


# --- Persist sidebar filter state to query params ---
# Done here (before any st.stop()) so the URL updates even when no data matches.
# split_dims is synced at the bottom since it's defined in the main content area.
persist_query_params({
    "a_start": str(start_date),
    "a_end": str(end_date),
    "a_grain": time_grain,
    "a_provider_off": [s for s in providers if s not in selected_providers],
    "a_project": selected_projects,
})

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

display = filtered.copy()

# Shared provider->scale mapping so the pies and the cost-over-time bars use the
# same hue per provider.
scale_of_provider = provider_scale_map(display["provider"].unique())

grain_map = {
    "1d": "D",
    "1h": "h",
    "30m": "30min",
    "15m": "15min",
    "5m": "5min",
    "1m": "min",
}
if time_grain == "1w":
    display["time_grain_ts"] = display["ts"].dt.to_period("W").dt.to_timestamp()
else:
    display["time_grain_ts"] = display["ts"].dt.floor(grain_map[time_grain])
time_col = "time_grain_ts"

# --- Summary metrics ---
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total cost", f"${display['cost'].sum():.2f}")
c2.metric("Events", f"{len(display):,}")
c3.metric("Input tokens", f"{display['input'].sum():,.0f}")
c4.metric("Output tokens", f"{display['output'].sum():,.0f}")
c5.metric("Cache read tokens", f"{display['cache_read'].sum():,.0f}")

st.divider()

# --- Cost by project, provider, and model ---
col_left, col_mid, col_right = st.columns(3)

with col_left:
    by_project_pie = display.groupby("project_short")["cost"].sum().reset_index()
    total_cost = by_project_pie["cost"].sum()
    significant = by_project_pie["cost"] >= total_cost * 0.01
    by_project_pie["project_short"] = by_project_pie["project_short"].where(significant, other="(other)")
    by_project_pie = by_project_pie.groupby("project_short")["cost"].sum().reset_index()
    fig = px.pie(by_project_pie, values="cost", names="project_short",
                 color_discrete_sequence=PAIRED)
    fig.update_traces(textposition="outside", textinfo="label+percent",
                      hovertemplate="$%{value:.3f} (%{percent})<extra></extra>",
                      rotation=90,
                      domain=dict(x=[0.1, 0.9], y=[0.05, 0.9]))
    fig.update_layout(
        title=dict(text="Cost by project", x=0.5, xanchor="center", font=dict(size=14)),
        showlegend=False,
        height=280,
        margin=dict(t=30, b=0, l=0, r=0),
    )
    st.plotly_chart(fig, width="stretch")

with col_mid:
    by_provider = display.groupby("provider")["cost"].sum().reset_index()
    provider_colors = {
        p: _provider_shades(scale_of_provider[p], 1)[0] for p in by_provider["provider"]
    }
    fig = px.pie(by_provider, values="cost", names="provider",
                 color="provider", color_discrete_map=provider_colors)
    fig.update_traces(textposition="outside", textinfo="label+percent",
                      hovertemplate="$%{value:.3f} (%{percent})<extra></extra>",
                      rotation=90,
                      domain=dict(x=[0.1, 0.9], y=[0.05, 0.9]))
    fig.update_layout(
        title=dict(text="Cost by provider", x=0.5, xanchor="center", font=dict(size=14)),
        showlegend=False,
        height=280,
        margin=dict(t=30, b=0, l=0, r=0),
    )
    st.plotly_chart(fig, width="stretch")

with col_right:
    by_model = display.groupby("model")["cost"].sum().reset_index()
    total_model_cost = by_model["cost"].sum()
    by_model["model"] = by_model["model"].where(by_model["cost"] >= total_model_cost * 0.01, other="(other)")
    by_model = by_model.groupby("model")["cost"].sum().reset_index()
    fig = px.pie(by_model, values="cost", names="model",
                 color_discrete_sequence=PAIRED)
    fig.update_traces(textposition="outside", textinfo="label+percent",
                      hovertemplate="$%{value:.3f} (%{percent})<extra></extra>",
                      rotation=90,
                      domain=dict(x=[0.1, 0.9], y=[0.05, 0.9]))
    fig.update_layout(
        title=dict(text="Cost by model", x=0.5, xanchor="center", font=dict(size=14)),
        showlegend=False,
        height=280,
        margin=dict(t=30, b=0, l=0, r=0),
    )
    st.plotly_chart(fig, width="stretch")

st.divider()

# --- Unified cost over time ---
st.subheader("Cost over time")

DIM_OPTIONS = ["project", "provider", "model", "token type"]
DIM_COLS = {
    "project": "project_short",
    "provider": "provider",
    "model": "model",
}
TOKEN_TYPE_LABELS = {
    "input_cost": "input",
    "output_cost": "output",
    "cache_write_cost": "cache_write",
    "cache_read_cost": "cache_read",
}


seed_widget_state("a_split_dims", [d for d in qp.get_all("a_split_dims") if d in DIM_OPTIONS] or ["provider", "project"])
split_dims = st.multiselect(
    "Split by",
    DIM_OPTIONS,
    max_selections=3,
    key="a_split_dims",
)

chart_data = display.copy()

if "project" in split_dims:
    proj_cost = display.groupby("project_short")["cost"].sum()
    top_projects = proj_cost[proj_cost >= proj_cost.sum() * 0.01].index
    chart_data["project_short"] = chart_data["project_short"].where(
        chart_data["project_short"].isin(top_projects), other="(other)"
    )

extra_dim_cols = [DIM_COLS[d] for d in split_dims if d in DIM_COLS]

if "token type" in split_dims:
    id_vars = [time_col] + extra_dim_cols
    chart_data = chart_data[id_vars + TOKEN_COST_COLS].melt(
        id_vars=id_vars,
        value_vars=TOKEN_COST_COLS,
        var_name="_token_type",
        value_name="cost",
    )
    chart_data["_token_type"] = chart_data["_token_type"].map(TOKEN_TYPE_LABELS)
    group_cols = [time_col] + extra_dim_cols + ["_token_type"]
    label_cols = extra_dim_cols + ["_token_type"]
else:
    group_cols = [time_col] + extra_dim_cols
    label_cols = extra_dim_cols

chart_data = chart_data.groupby(group_cols)["cost"].sum().reset_index()

if len(label_cols) == 0:
    color_col = None
elif len(label_cols) == 1:
    color_col = label_cols[0]
else:
    chart_data["_label"] = chart_data[label_cols].apply(
        lambda row: " / ".join(row.astype(str)), axis=1
    )
    color_col = "_label"

# When provider is combined with other dims, give each provider one hue family and
# a distinct shade per sub-label so related series read as shades of one color.
color_map = None
label_order = None
if color_col == "_label" and "provider" in label_cols:
    sub_cols = [c for c in label_cols if c != "provider"]
    providers_in_chart = sorted(chart_data["provider"].unique())
    combos = chart_data[["provider", "_label"] + sub_cols].drop_duplicates()
    color_map = {}
    label_order = []
    for prov in providers_in_chart:
        subs = combos[combos["provider"] == prov].sort_values("_label")
        shades = _provider_shades(scale_of_provider[prov], len(subs))
        for shade, (_, row) in zip(shades, subs.iterrows()):
            color_map[row["_label"]] = shade
            label_order.append(row["_label"])

fig = px.bar(
    chart_data, x=time_col, y="cost", color=color_col,
    color_discrete_map=color_map or {},
    category_orders={color_col: label_order} if label_order else {},
    labels={"cost": "Cost ($)", time_col: "", color_col or "": ""},
)
if color_col:
    fig.update_traces(hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>$%{y:.4f}<extra></extra>")
else:
    fig.update_traces(hovertemplate="%{x}<br>$%{y:.4f}<extra></extra>")
st.plotly_chart(fig, width="stretch")

# --- Persist split_dims to query params ---
persist_query_params({"a_split_dims": split_dims})
