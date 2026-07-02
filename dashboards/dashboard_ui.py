"""Small Streamlit helpers shared by the dashboard pages.

Kept separate from agent_usage_common.py so the headless extractors that import that
module don't pull in Streamlit.
"""

import streamlit as st


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
