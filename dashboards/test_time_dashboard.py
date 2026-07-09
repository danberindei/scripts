import importlib.util
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "time_dashboard_mod", Path(__file__).parent / "time-dashboard.py"
)
_mod = importlib.util.module_from_spec(_spec)


def _load_module():
    # Deferred so importing the module (which calls st.set_page_config at import
    # time) doesn't run for tests that only need the pure helpers.
    _spec.loader.exec_module(_mod)
    return _mod


def test_resolve_ticket_explicit_wins() -> None:
    m = _load_module()
    assert m.resolve_ticket("work", "ENG-1") == "ENG-1"


def test_resolve_ticket_meeting_without_ticket_gets_placeholder() -> None:
    m = _load_module()
    assert m.resolve_ticket("meeting", None) == "(meetings)"


def test_resolve_ticket_untracked_work_is_classified_by_comment() -> None:
    m = _load_module()
    assert m.resolve_ticket("work", None, "comms (Slack)") == "(comms)"
    # "notes" is the daily-notes habit and precedes tooling, so a mixed comment counts
    # as notes rather than time-tracker building.
    assert m.resolve_ticket("work", None, "notes & time tracking") == "(notes)"
    assert m.resolve_ticket("work", None, "something else") == "(other)"


def test_resolve_ticket_personal() -> None:
    m = _load_module()
    assert m.resolve_ticket("personal", None) == "(personal)"


def test_classify_untracked_first_match_wins() -> None:
    m = _load_module()
    # Building the time-tracker is tool work: "time-track" now lands in (tooling).
    assert m.classify_untracked("time-tracker tooling") == "(tooling)"
    # A comment with no notes keyword but time-track still reads as tooling.
    assert m.classify_untracked("optimize time-tracker scripts") == "(tooling)"
    assert m.classify_untracked("dev-machine memory/swap investigation") == "(ops)"


def test_attribution_ticketed_vs_ticketless() -> None:
    m = _load_module()
    assert m.attribution_of("ENG-6884") == "ticketed"
    assert m.attribution_of("(comms)") == "ticketless"
    assert m.attribution_of("(meetings)") == "ticketless"


def test_load_entries_flattens_and_converts_hours(tmp_path: Path) -> None:
    m = _load_module()
    year = tmp_path / "2026"
    year.mkdir()
    (year / "2026-06-23.json").write_text(
        '{"date":"2026-06-23","entries":['
        '{"start":"11:00","end":"12:00","minutes":90,"kind":"work","ticket":"ENG-6884","comment":"x"},'
        '{"start":"09:16","end":"09:45","minutes":30,"kind":"meeting","ticket":null,"comment":"standup"}'
        ']}'
    )
    df = m.load_entries(tmp_path)

    assert len(df) == 2
    work = df[df["kind"] == "work"].iloc[0]
    assert work["hours"] == 1.5
    assert work["ticket"] == "ENG-6884"
    meeting = df[df["kind"] == "meeting"].iloc[0]
    assert meeting["ticket"] == "(meetings)"
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_load_entries_empty_dir_returns_empty(tmp_path: Path) -> None:
    m = _load_module()
    assert m.load_entries(tmp_path).empty
