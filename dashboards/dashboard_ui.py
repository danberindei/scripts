"""Small Streamlit helpers shared by the dashboard pages.

Kept separate from agent_usage_common.py so the headless extractors that import that
module don't pull in Streamlit.

Sidebar/filter state persists in one browser localStorage store rather than the URL
query params it replaced: query params were per-page-prefixed and lost when switching
between the pages of this st.navigation app, while localStorage is shared across pages
and survives reloads.
"""

import json
from datetime import date as _date

import streamlit as st
from streamlit_local_storage import LocalStorage

# ColorBrewer "Paired" qualitative palette (12 colors, light/dark pairs). Plotly
# doesn't ship this one, so define it explicitly. Used for pie slices and stacked bars.
PAIRED = [
    "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c",
    "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00",
    "#cab2d6", "#6a3d9a", "#ffff99", "#b15928",
]

# All pages write their settings into this single browser localStorage store.
_STORE_KEY = "dashboards_settings"


def _store():
    """Return the shared localStorage handle for the current run.

    LocalStorage.__init__ blocks on a browser round-trip only when _STORE_KEY is
    absent from st.session_state; once the browser has posted the stored values back
    it caches them in session_state and later constructions reuse that dict without
    blocking. The first run of a browser session therefore waits briefly for the
    stored settings, and headless tests that pre-seed st.session_state[_STORE_KEY]
    never hit the blocking path.
    """
    return LocalStorage(key=_STORE_KEY)


def get_str(key, default):
    """Read a stored string setting, or default when it is unset."""
    value = _store().getItem(key)
    return default if value is None else value


def get_date(key, fallback):
    """Read a stored ISO date setting, or fallback on a missing or invalid value."""
    try:
        return _date.fromisoformat(_store().getItem(key))
    except (TypeError, ValueError):
        return fallback


def get_list(key, valid):
    """Read a stored list setting filtered to values in ``valid``.

    Returns None when nothing is stored, and [] when an empty list was stored, so
    callers can distinguish an explicit empty selection from an unset one.
    """
    value = _store().getItem(key)
    if value is None:
        return None
    try:
        items = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    return [v for v in items if v in valid]


def seed_widget_state(key, seed):
    """Seed a widget-backed session_state entry once, on first render only.

    A widget fed value=/default=/index= that is recomputed from stored settings on
    every rerun fights the write-back: each interaction reruns, the arg is recomputed
    from the just-written store, and the widget snaps back mid-change (the choppiness).
    Binding the widget with key= and seeding session_state a single time lets the
    widget own its state so changes stick.
    """
    if key not in st.session_state:
        st.session_state[key] = seed


def repaint_on_page_entry(page_key):
    """Force one rerun when a page is entered, to clear a stuck loading skeleton.

    Streamlit sometimes leaves its loading skeleton painted after a page's first
    full render finishes; the same elements repaint cleanly on a rerun (what a
    manual rerun does by hand). This is a multi-page st.navigation app, so the
    active page is tracked in shared session_state: exactly one rerun fires per
    entry -- including navigating back to a page -- while widget-driven reruns
    within a page do not re-trigger it.

    Call this at the END of a page, after its content has rendered: the clean
    repaint needs the first render to already exist.
    """
    if st.session_state.get("_active_page") != page_key:
        st.session_state["_active_page"] = page_key
        st.rerun()


def persist(spec):
    """Mirror current widget state into browser localStorage, writing only on change.

    ``spec`` maps setting name -> current value (str or list[str]). Lists are stored
    JSON-encoded. Writing only when the stored value actually differs avoids needless
    component round-trips and reruns.
    """
    store = _store()
    for key, value in spec.items():
        target = json.dumps(value) if isinstance(value, list) else str(value)
        if store.getItem(key) != target:
            store.setItem(key, target, key=f"{_STORE_KEY}_set_{key}")
