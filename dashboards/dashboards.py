#!/usr/bin/env python3
"""
Combined dashboards server.

Serves both the agent-usage and time-tracking dashboards from one Streamlit
process, with a sidebar page switcher.

Usage:
  streamlit run dashboards.py

Each page keeps its own st.set_page_config() call; the active page's config wins
for that run. session_state and query params are shared across pages in one
st.navigation app, so each page namespaces its widget keys and params by page
(a_ for agent usage, t_ for time tracking) to avoid cross-page collisions.
"""

import os
import sys

import streamlit as st

# st.Page(...).run() execs each page in a fresh module without adding this
# directory to sys.path, so a page's `from agent_usage_common import ...` would
# fail. Put our own dir on the path so the pages and the shared extractor lib
# resolve regardless of the current working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

st.navigation([
    st.Page("agents-dashboard.py", title="Agent Usage", default=True),
    st.Page("time-dashboard.py", title="Time Tracking"),
    st.Page("weeks-dashboard.py", title="Weekly Calendar"),
]).run()
