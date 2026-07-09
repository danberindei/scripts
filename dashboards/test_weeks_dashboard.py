import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "weeks_dashboard_mod", Path(__file__).parent / "weeks-dashboard.py"
)
_mod = importlib.util.module_from_spec(_spec)


def _load_module():
    _spec.loader.exec_module(_mod)
    return _mod


def test_normalize_block_size_rule_keeps_legacy_query_params_working() -> None:
    m = _load_module()
    assert m._normalize_block_size_rule("0") == "min 1"
    assert m._normalize_block_size_rule("1") == "min 1"
    assert m._normalize_block_size_rule("2") == "min 2"
    assert m._normalize_block_size_rule("5") == "min 5"
    assert m._normalize_block_size_rule("jira") == "jira"
    assert m._normalize_block_size_rule("bogus") == "jira"


def test_round_jira_worklog_minutes_matches_canonical_rounder() -> None:
    m = _load_module()
    assert m._round_jira_worklog_minutes(0.5) == 0
    # (raw + 1) rounded to nearest 5: raw=1 -> 0, raw=2 is the smallest that reaches 5.
    assert m._round_jira_worklog_minutes(1) == 0
    assert m._round_jira_worklog_minutes(2) == 5
    assert m._round_jira_worklog_minutes(23) == 25
    assert m._round_jira_worklog_minutes(30) == 30
    # raw > 30 rounds (raw + 3) to nearest 15: 31..34 all land on 30, 35 jumps to 45.
    assert m._round_jira_worklog_minutes(31) == 30
    assert m._round_jira_worklog_minutes(34) == 30
    assert m._round_jira_worklog_minutes(35) == 45
    assert m._round_jira_worklog_minutes(38) == 45
    assert m._round_jira_worklog_minutes(60) == 60


def test_jira_block_size_rule_rounds_group_minutes() -> None:
    m = _load_module()
    week_data = {
        date(2026, 7, 6): {
            ("ENG-1", "work"): {"minutes": 1, "entries": [], "display_label": "ENG-1"},
            ("ENG-2", "work"): {"minutes": 23, "entries": [], "display_label": "ENG-2"},
            ("ENG-3", "work"): {"minutes": 38, "entries": [], "display_label": "ENG-3"},
        }
    }

    adjusted = m._apply_block_size_rule(week_data, "jira")

    assert ("ENG-1", "work") not in adjusted[date(2026, 7, 6)]
    assert adjusted[date(2026, 7, 6)][("ENG-2", "work")]["minutes"] == 25
    assert adjusted[date(2026, 7, 6)][("ENG-3", "work")]["minutes"] == 45


def test_apply_block_size_rule_drops_empty_days() -> None:
    m = _load_module()
    week_data = {
        date(2026, 7, 6): {
            ("ENG-1", "work"): {"minutes": 1, "entries": [], "display_label": "ENG-1"},
            ("ENG-2", "work"): {"minutes": 5, "entries": [], "display_label": "ENG-2"},
        },
        date(2026, 7, 7): {
            ("ENG-3", "work"): {"minutes": 1, "entries": [], "display_label": "ENG-3"},
        },
    }

    filtered = m._apply_block_size_rule(week_data, "jira")

    assert list(filtered.keys()) == [date(2026, 7, 6)]
    assert list(filtered[date(2026, 7, 6)].keys()) == [("ENG-2", "work")]
