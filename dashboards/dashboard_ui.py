"""Small Streamlit helpers shared by the dashboard pages.

Kept separate from agent_usage_common.py so the headless extractors that import that
module don't pull in Streamlit.
"""

from datetime import date as _date

import streamlit as st

# ColorBrewer "Paired" qualitative palette (12 colors, light/dark pairs). Plotly
# doesn't ship this one, so define it explicitly. Used for pie slices and stacked bars.
PAIRED = [
    "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c",
    "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00",
    "#cab2d6", "#6a3d9a", "#ffff99", "#b15928",
]


def qp_date(key, fallback):
    """Read a date query param by key, returning fallback on missing or invalid value."""
    try:
        return _date.fromisoformat(st.query_params[key])
    except (KeyError, ValueError):
        return fallback


def qp_list(key, valid):
    """Read a list query param, returning only values in valid, or None if empty."""
    vals = st.query_params.get_all(key)
    return [v for v in vals if v in valid] or None


def seed_widget_state(key, seed):
    """Seed a widget-backed session_state entry once, on first render only.

    A widget fed value=/default=/index= that is recomputed from the query params on
    every rerun fights the query-param write-back: each interaction reruns, the arg is
    recomputed from the just-written param, and the widget snaps back mid-change (the
    choppiness). Binding the widget with key= and seeding session_state a single time
    lets the widget own its state so changes stick.
    """
    if key not in st.session_state:
        st.session_state[key] = seed


def persist_query_params(spec):
    """Mirror current widget state into the URL query params, writing only on change.

    ``spec`` maps query-param name -> current value (str or list[str]). Writing only
    when the value actually differs keeps the URL shareable without spurious reruns.
    """
    for key, value in spec.items():
        current = sorted(st.query_params.get_all(key))
        target = sorted(value if isinstance(value, list) else [value])
        if current != target:
            st.query_params[key] = value
