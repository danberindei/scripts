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
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from plotly.colors import sample_colorscale

from agent_usage_common import calc_cost_breakdown, load_pricing_db, short_project

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "agent-usage"
SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_COST_COLS = ["input_cost", "output_cost", "cache_write_cost", "cache_read_cost"]
WORKTREE_MAP_FILE = "paseo-worktrees.jsonl"
WORKTREE_SCRIPT = SCRIPT_DIR / "paseo-worktrees.py"

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


@lru_cache(maxsize=512)
def _git_root(path: str) -> str:
    """Return the nearest git root at or above path, or path itself if not in a repo."""
    p = Path(path)
    while p != p.parent:
        if (p / ".git").exists():
            return str(p)
        p = p.parent
    return path


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


def load_worktree_map(data_dir: Path) -> dict:
    """Map each Paseo worktree cwd to its owning project.

    The mapping script is append-only and cheap, so run it on every load to pick
    up new worktrees, then read the JSONL into a {cwd: record} dict.
    """
    path = data_dir / WORKTREE_MAP_FILE
    if WORKTREE_SCRIPT.exists():
        subprocess.run(
            [sys.executable, str(WORKTREE_SCRIPT), "-o", str(path)],
            capture_output=True, text=True,
        )
    mapping = {}
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cwd = rec["cwd"]
                    mapping[cwd] = rec
                    # decode_project_path() encodes '/' and '.' as '-', then decodes by
                    # replacing all '-' with '/'. Dots in dir names (e.g. ".paseo" ->
                    # "//paseo") and hyphens in worktree names become wrong path
                    # components. Compute that broken form and index it too so
                    # resolve() finds the record via exact match for old JSONL files.
                    broken = cwd.replace("/", "-").replace(".", "-").replace("-", "/", 1).replace("-", "/")
                    if broken != cwd:
                        mapping.setdefault(broken, rec)
                except (json.JSONDecodeError, KeyError):
                    continue
    return mapping

def _decode_project_path(dirname: str) -> str:
    if dirname.startswith("-"):
        return dirname.replace("-", "/", 1).replace("-", "/")
    return dirname


def _build_cwd_corrections(stale_paths: set) -> dict:
    """For each stale decoded path, find the matching Claude project dir and return its real cwd."""
    corrections = {}
    remaining = set(stale_paths)
    for config_dir in sorted(d for d in Path.home().iterdir() if d.name.startswith(".claude") and d.is_dir()):
        projects_dir = config_dir / "projects"
        if not projects_dir.is_dir():
            continue
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir() or not remaining:
                continue
            decoded = _decode_project_path(project_dir.name)
            if decoded not in remaining:
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                try:
                    with open(jsonl_file) as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if entry.get("type") == "user":
                                cwd = entry.get("cwd")
                                if cwd:
                                    corrections[decoded] = cwd
                                break
                except (OSError, PermissionError):
                    continue
                if decoded in corrections:
                    break
            remaining.discard(decoded)
    return corrections


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

    # Fix stale project paths in old JSONL files: any stored path that doesn't exist
    # on the filesystem was produced by the lossy decode_project_path() heuristic.
    # For each such path find the matching Claude project dir (its dirname decodes to
    # the same string) and read the real cwd from a 'user' conversation entry.
    if "project" in df.columns:
        stale = {p for p in df["project"].unique()
                 if isinstance(p, str) and not p.startswith("/tmp/") and not Path(p).exists()}
        if stale:
            corrections = _build_cwd_corrections(stale)
            if corrections:
                df["project"] = df["project"].map(lambda p: corrections.get(p, p))

    # Remap Paseo worktree paths to their real project, then recompute the short label.
    worktree_map = load_worktree_map(data_dir)
    if worktree_map and "project" in df.columns:
        # A worktree's hash dir (.../worktrees/<hash>/<name>) is per-project, so a
        # recorded sibling resolves worktrees that Paseo has since pruned from its
        # registry. Only keep hash keys that map unambiguously to one project root.
        by_hash = {}
        for cwd, rec in worktree_map.items():
            root = rec.get("projectRoot")
            if not root:
                continue
            by_hash.setdefault(cwd.rsplit("/", 1)[0], set()).add(root)
        by_hash = {h: next(iter(roots)) for h, roots in by_hash.items() if len(roots) == 1}

        def resolve(p):
            if not isinstance(p, str):
                return p
            rec = worktree_map.get(p)
            if rec and rec.get("projectRoot"):
                return _git_root(rec["projectRoot"])
            # Strip project-internal worktree directories (.worktrees/ and .claude/worktrees/)
            for wt_dir in ("/.worktrees/", "/.claude/worktrees/"):
                idx = p.rfind(wt_dir)
                if idx >= 0:
                    return _git_root(p[:idx])
            if p.startswith("/tmp/"):
                return "/tmp"
            return _git_root(by_hash.get(p.rsplit("/", 1)[0], p))

        df["project"] = df["project"].map(resolve)
        df["project_short"] = df["project"].map(lambda p: short_project(p) if isinstance(p, str) else p)

    local_tz = datetime.now().astimezone().tzinfo
    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601", utc=True).dt.tz_convert(local_tz).dt.tz_localize(None)

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

dc1, dc2 = st.sidebar.columns(2)
start_date = dc1.date_input("Start date", value=_qp_date("start", today - timedelta(days=7)), min_value=min_ts.date(), max_value=date_max)
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

_range_key = (str(start_date), str(end_date))
if "time_grain" not in st.session_state:
    _g = qp.get("grain", "1d")
    st.session_state["time_grain"] = _g if _g in grains else "1d"
    st.session_state["_grain_range_key"] = _range_key

# Auto-pick a readable grain only when the date range changes; manual grain
# changes are always respected. Uses the theoretical bucket count over the span
# (an upper bound on the actual data points), which keeps this deterministic and
# independent of filtering.
_span_min = ((end_date - start_date).days + 1) * MINUTES_PER_DAY
_grain_points = lambda g: _span_min / GRAIN_MINUTES[g]
if st.session_state.get("_grain_range_key") != _range_key:
    st.session_state["_grain_range_key"] = _range_key
    current_grain = st.session_state["time_grain"]
    idx = grains.index(current_grain)
    # _grain_points is monotonic in the grain index, so the fitting grains form a
    # contiguous range: keep the current grain if it fits, else clamp toward the band.
    band = [i for i, g in enumerate(grains) if 2 <= _grain_points(g) <= MAX_BUCKETS]
    if band:
        # Clamp is a no-op when idx is already in band.
        st.session_state["time_grain"] = grains[min(max(idx, band[0]), band[-1])]
    else:
        st.session_state["time_grain"] = "1m" if _grain_points("1m") < 2 else "1w"
time_grain = st.sidebar.select_slider("Time granularity", options=grains, key="time_grain")


# --- Persist sidebar filter state to query params ---
# Done here (before any st.stop()) so the URL updates even when no data matches.
# split_dims is synced at the bottom since it's defined in the main content area.
_sidebar_desired = {
    "start": str(start_date),
    "end": str(end_date),
    "grain": time_grain,
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
    st.plotly_chart(fig, use_container_width=True)

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
    st.plotly_chart(fig, use_container_width=True)

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
    st.plotly_chart(fig, use_container_width=True)

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


split_dims_default = [d for d in qp.get_all("split_dims") if d in DIM_OPTIONS] or ["provider", "project"]
split_dims = st.multiselect(
    "Split by",
    DIM_OPTIONS,
    default=split_dims_default,
    max_selections=3,
    key="split_dims",
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
st.plotly_chart(fig, use_container_width=True)

# --- Persist split_dims to query params ---
_desired_split_dims = sorted(split_dims)
if sorted(qp.get_all("split_dims")) != _desired_split_dims:
    st.query_params["split_dims"] = split_dims
