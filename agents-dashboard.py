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

from agent_usage_common import calc_cost_breakdown, load_pricing_db, short_project

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "agent-usage"
SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_COST_COLS = ["input_cost", "output_cost", "cache_write_cost", "cache_read_cost"]
WORKTREE_MAP_FILE = "paseo-worktrees.jsonl"
WORKTREE_SCRIPT = SCRIPT_DIR / "paseo-worktrees.py"


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

grain_default = qp.get("grain", "Day")
time_grain = st.sidebar.radio("Time granularity", grains, index=grains.index(grain_default) if grain_default in grains else 0)


# --- Persist sidebar filter state to query params ---
# Done here (before any st.stop()) so the URL updates even when no data matches.
# split_by is synced at the bottom since it's defined in the main content area.
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

# --- Cost by project and by model ---
col_left, col_right = st.columns(2)

with col_left:
    by_project_pie = display.groupby("project_short")["cost"].sum().reset_index()
    total_cost = by_project_pie["cost"].sum()
    significant = by_project_pie["cost"] >= total_cost * 0.01
    by_project_pie["project_short"] = by_project_pie["project_short"].where(significant, other="(other)")
    by_project_pie = by_project_pie.groupby("project_short")["cost"].sum().reset_index()
    fig = px.pie(by_project_pie, values="cost", names="project_short")
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

with col_right:
    by_model = display.groupby("model")["cost"].sum().reset_index()
    total_model_cost = by_model["cost"].sum()
    by_model["model"] = by_model["model"].where(by_model["cost"] >= total_model_cost * 0.01, other="(other)")
    by_model = by_model.groupby("model")["cost"].sum().reset_index()
    fig = px.pie(by_model, values="cost", names="model")
    fig.update_traces(textposition="outside", textinfo="label+percent",
                      hovertemplate="$%{value:.3f} (%{percent})<extra></extra>",
                      domain=dict(x=[0.1, 0.9], y=[0.05, 0.9]))
    fig.update_layout(
        title=dict(text="Cost by model", x=0.5, xanchor="center", font=dict(size=14)),
        showlegend=False,
        height=280,
        margin=dict(t=30, b=0, l=0, r=0),
    )
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
    proj_cost = display.groupby("project_short")["cost"].sum()
    top = proj_cost[proj_cost >= proj_cost.sum() * 0.01].index
    breakdown_data = display.copy()
    breakdown_data[grp] = breakdown_data[grp].where(breakdown_data[grp].isin(top), other="(other)")
else:
    grp = "_label"
    proj_cost = display.groupby("project_short")["cost"].sum()
    top = proj_cost[proj_cost >= proj_cost.sum() * 0.01].index
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
