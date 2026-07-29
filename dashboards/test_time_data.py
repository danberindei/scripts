"""Tests for time_data.py helpers."""

import json
from datetime import date
from pathlib import Path

import pytest

from time_data import (
    LABEL_LINE_HEIGHT_PX,
    LABEL_MAX_CHARS,
    LABEL_OUTSIDE_THRESHOLD_PX,
    PASTELS,
    PAIRED,
    _adjust_lightness,
    color_map,
    entries_from_day,
    group_week,
    layout_week,
    load_days,
    load_sprints,
    load_workstreams,
    slug_of,
    sprint_for_date,
    week_of,
)


# --- slug_of ---

def test_slug_of_ticketed_entry():
    entry = {"ticket": "ENG-6775", "comment": "ignored"}
    slug, label = slug_of(entry)
    assert slug == "ENG-6775"
    assert label == "ENG-6775"


def test_slug_of_null_ticket_returns_comment_verbatim():
    comment = "comms (general)"  # 15 chars, under LABEL_MAX_CHARS
    entry = {"ticket": None, "comment": comment}
    slug, label = slug_of(entry)
    assert slug == comment
    assert label == comment


def test_slug_of_null_ticket_display_label_truncated():
    long_comment = "a" * 30
    entry = {"ticket": None, "comment": long_comment}
    slug, label = slug_of(entry)
    assert slug == long_comment
    assert label == "a" * LABEL_MAX_CHARS + "..."
    assert len(label) == LABEL_MAX_CHARS + 3


def test_slug_of_comment_at_exact_max_not_truncated():
    comment = "x" * LABEL_MAX_CHARS
    slug, label = slug_of({"ticket": None, "comment": comment})
    assert label == comment
    assert "..." not in label


def test_slug_of_missing_comment_uses_empty_string():
    slug, label = slug_of({"ticket": None})
    assert slug == ""
    assert label == ""


# --- week_of ---

def test_week_of_monday():
    assert week_of(date(2026, 6, 29)) == (2026, 27)


def test_week_of_sunday():
    assert week_of(date(2026, 7, 5)) == (2026, 27)


def test_week_of_year_boundary_jan1_2026():
    # 2026-01-01 is Thursday of ISO week 1 of 2026
    assert week_of(date(2026, 1, 1)) == (2026, 1)


def test_week_of_year_boundary_dec28_2026():
    # 2026-12-28 is a Monday; ISO week 53 or 1 depending on year
    d = date(2026, 12, 28)
    iso = d.isocalendar()
    assert week_of(d) == (iso.year, iso.week)


def test_week_of_year_boundary_dec31_cross():
    # 2015-12-31 belongs to week 1 of 2016
    assert week_of(date(2015, 12, 31)) == (2015, 53)
    # 2016-01-04 is week 1 of 2016
    assert week_of(date(2016, 1, 4)) == (2016, 1)


# --- group_week ---

def _day(d, entries):
    return {"date": d, "entries": entries}


def _entry(ticket, comment, kind, minutes):
    return {"ticket": ticket, "comment": comment, "kind": kind, "minutes": minutes}


def test_group_week_slug_kind_split():
    d = date(2026, 6, 29)
    days = [_day(d, [
        _entry("ENG-1", "", "work", 60),
        _entry("ENG-1", "", "meeting", 30),
    ])]
    result = group_week(days, include_personal=False)
    assert d in result
    assert ("ENG-1", "work") in result[d]
    assert ("ENG-1", "meeting") in result[d]
    assert result[d][("ENG-1", "work")]["minutes"] == 60
    assert result[d][("ENG-1", "meeting")]["minutes"] == 30


def test_group_week_personal_excluded_by_default():
    d = date(2026, 6, 29)
    days = [_day(d, [
        _entry(None, "gym", "personal", 45),
        _entry("ENG-1", "", "work", 60),
    ])]
    result = group_week(days, include_personal=False)
    assert ("gym", "personal") not in result.get(d, {})
    assert ("ENG-1", "work") in result[d]


def test_group_week_personal_included_with_flag():
    d = date(2026, 6, 29)
    days = [_day(d, [_entry(None, "gym", "personal", 45)])]
    result = group_week(days, include_personal=True)
    assert ("gym", "personal") in result[d]


def test_group_week_identical_comments_merge():
    d = date(2026, 6, 29)
    days = [_day(d, [
        _entry(None, "comms (general)", "work", 10),
        _entry(None, "comms (general)", "work", 15),
    ])]
    result = group_week(days, include_personal=False)
    key = ("comms (general)", "work")
    assert key in result[d]
    assert result[d][key]["minutes"] == 25
    assert len(result[d][key]["entries"]) == 2


def test_group_week_multiple_days():
    d1 = date(2026, 6, 29)
    d2 = date(2026, 6, 30)
    days = [
        _day(d1, [_entry("ENG-1", "", "work", 60)]),
        _day(d2, [_entry("ENG-2", "", "work", 90)]),
    ]
    result = group_week(days, include_personal=False)
    assert d1 in result
    assert d2 in result


# --- color_map ---

def test_color_map_deterministic():
    d = date(2026, 6, 29)
    days = [_day(d, [
        _entry("ENG-1", "", "work", 100),
        _entry("ENG-2", "", "work", 50),
    ])]
    c1 = color_map(days)
    c2 = color_map(days)
    assert c1 == c2


def test_color_map_ranked_by_total_minutes():
    d = date(2026, 6, 29)
    days = [_day(d, [
        _entry("ENG-LOW", "", "work", 10),
        _entry("ENG-HIGH", "", "work", 200),
    ])]
    colors = color_map(days)
    # ENG-HIGH gets the first palette entry (highest rank = index 0)
    assert colors["ENG-HIGH"] == PAIRED[0]
    assert colors["ENG-LOW"] == PAIRED[1]


def test_weekly_palette_keeps_red_slot_pastel():
    assert PASTELS[2] == "#F2C6C2"
    assert PAIRED is PASTELS


def test_color_map_stable_regardless_of_week_selection():
    d1 = date(2026, 6, 22)
    d2 = date(2026, 6, 29)
    all_days = [
        _day(d1, [_entry("ENG-A", "", "work", 100)]),
        _day(d2, [_entry("ENG-B", "", "work", 50)]),
    ]
    colors_all = color_map(all_days)
    # The color for ENG-A should be the same whether or not the second week is "selected";
    # color_map always operates on all_days, not the filtered selection.
    colors_week1_only = color_map([_day(d1, [_entry("ENG-A", "", "work", 100)])])
    assert colors_all["ENG-A"] == colors_week1_only["ENG-A"]


def test_color_map_distinct_past_one_palette_cycle():
    d = date(2026, 6, 29)
    palette_size = len(PAIRED)
    entries = [_entry(f"ENG-{i}", "", "work", 100 - i) for i in range(palette_size * 2)]
    days = [_day(d, entries)]
    colors = color_map(days)
    color_list = list(colors.values())
    # Each color in cycle 2 (indices 12-23) must differ from its cycle 1 counterpart.
    for i in range(palette_size):
        assert color_list[i] != color_list[i + palette_size], f"cycle 1 and 2 match at index {i}"


# --- layout_week ---

def test_layout_week_pixel_heights_honor_scale():
    d = date(2026, 6, 29)
    week_data = {d: {("ENG-1", "work"): {"minutes": 60, "entries": [], "display_label": "ENG-1"}}}
    layout = layout_week(week_data, px_per_min=2.0)
    blocks = layout[d]
    assert len(blocks) == 1
    assert blocks[0]["height_px"] == 120.0


def test_layout_week_minimum_height_3px():
    d = date(2026, 6, 29)
    week_data = {d: {("ENG-1", "work"): {"minutes": 1, "entries": [], "display_label": "ENG-1"}}}
    layout = layout_week(week_data, px_per_min=0.1)
    assert layout[d][0]["height_px"] == 3.0


def test_layout_week_block_below_threshold_flagged_label_outside():
    d = date(2026, 6, 29)
    week_data = {d: {("ENG-1", "work"): {"minutes": 3, "entries": [], "display_label": "ENG-1"}}}
    layout = layout_week(week_data, px_per_min=1.0)
    # 3 * 1.0 = 3.0 < LABEL_OUTSIDE_THRESHOLD_PX
    assert layout[d][0]["label_outside"] is True


def test_layout_week_block_at_threshold_not_outside():
    d = date(2026, 6, 29)
    week_data = {d: {
        ("ENG-1", "work"): {"minutes": LABEL_OUTSIDE_THRESHOLD_PX, "entries": [], "display_label": "ENG-1"}
    }}
    layout = layout_week(week_data, px_per_min=1.0)
    assert layout[d][0]["label_outside"] is False


def test_layout_week_blocks_ordered_descending_minutes():
    d = date(2026, 6, 29)
    week_data = {d: {
        ("ENG-LOW", "work"): {"minutes": 10, "entries": [], "display_label": "ENG-LOW"},
        ("ENG-HIGH", "work"): {"minutes": 90, "entries": [], "display_label": "ENG-HIGH"},
    }}
    layout = layout_week(week_data, px_per_min=1.0)
    blocks = layout[d]
    assert blocks[0]["slug"] == "ENG-HIGH"
    assert blocks[1]["slug"] == "ENG-LOW"


def test_layout_week_outside_labels_pushed_apart():
    d = date(2026, 6, 29)
    # Two blocks of 3px each: both below threshold, would overlap at same y position.
    week_data = {d: {
        ("ENG-1", "work"): {"minutes": 3, "entries": [], "display_label": "ENG-1"},
        ("ENG-2", "work"): {"minutes": 2, "entries": [], "display_label": "ENG-2"},
    }}
    layout = layout_week(week_data, px_per_min=1.0)
    blocks = layout[d]
    assert all(b["label_outside"] for b in blocks)
    # The second label must start at or after the first label's bottom.
    first_bottom = blocks[0]["label_top_px"] + LABEL_LINE_HEIGHT_PX
    assert blocks[1]["label_top_px"] >= first_bottom


def test_layout_week_block_positions_unchanged_by_label_push():
    d = date(2026, 6, 29)
    week_data = {d: {
        ("ENG-1", "work"): {"minutes": 3, "entries": [], "display_label": "ENG-1"},
        ("ENG-2", "work"): {"minutes": 2, "entries": [], "display_label": "ENG-2"},
    }}
    layout = layout_week(week_data, px_per_min=1.0)
    blocks = layout[d]
    # Block positions are determined by stacking, not affected by label push.
    assert blocks[0]["top_px"] == 0.0
    assert blocks[1]["top_px"] == pytest.approx(3.0)


# --- sprint_for_date ---

def _sprint(sid, start, end, state="closed"):
    return {"id": sid, "name": f"Sprint {sid}", "start": start, "end": end, "state": state}


def test_sprint_for_date_basic():
    sprints = [_sprint(1, "2026-06-08", "2026-06-22")]
    assert sprint_for_date(date(2026, 6, 10), sprints)["id"] == 1


def test_sprint_for_date_start_inclusive():
    sprints = [_sprint(1, "2026-06-08", "2026-06-22")]
    assert sprint_for_date(date(2026, 6, 8), sprints)["id"] == 1


def test_sprint_for_date_end_exclusive():
    sprints = [
        _sprint(1, "2026-06-08", "2026-06-22"),
        _sprint(2, "2026-06-22", "2026-07-06"),
    ]
    # Boundary Monday goes to the new sprint.
    assert sprint_for_date(date(2026, 6, 22), sprints)["id"] == 2


def test_sprint_for_date_uncovered_returns_none():
    sprints = [_sprint(1, "2026-06-08", "2026-06-22")]
    assert sprint_for_date(date(2026, 5, 1), sprints) is None


def test_sprint_for_date_no_sprint_skipped():
    # no-sprint.json entries have start=None; they should not match any date.
    sprints = [
        {"id": "no-sprint", "name": "no-sprint", "start": None, "end": None, "state": "synthetic"},
        _sprint(1, "2026-06-08", "2026-06-22"),
    ]
    assert sprint_for_date(date(2026, 6, 10), sprints)["id"] == 1


# --- entries_from_day ---

def test_entries_from_day_old_format_passthrough():
    day = {"date": "2026-07-05", "entries": [
        {"start": "09:00", "end": "09:30", "minutes": 30, "kind": "work", "ticket": "ENG-1", "comment": "x"},
    ]}
    result = entries_from_day(day)
    assert result == day["entries"]


def test_entries_from_day_new_format_joins_task_metadata():
    day = {
        "date": "2026-07-01",
        "tasks": [
            {"name": "eng-task", "kind": "work", "ticket": "ENG-6908", "worklog_comment": "fix"},
            {"name": "standup", "kind": "meeting", "ticket": "ENG-6880", "worklog_comment": None},
        ],
        "segments": [
            {"task_name": "eng-task", "start": "08:30", "end": "08:38", "minutes": 7, "note": "sudoers edits"},
            {"task_name": "standup", "start": "09:46", "end": "09:53", "minutes": 8, "note": "ENG standup"},
        ],
    }
    result = entries_from_day(day)
    assert len(result) == 2
    expected0 = {"start": "08:30", "end": "08:38", "minutes": 7, "kind": "work", "ticket": "ENG-6908", "comment": "sudoers edits"}
    expected1 = {"start": "09:46", "end": "09:53", "minutes": 8, "kind": "meeting", "ticket": "ENG-6880", "comment": "ENG standup"}
    assert expected0.items() <= result[0].items()
    assert expected1.items() <= result[1].items()
    assert result[0]["task_name"] == "eng-task"
    assert result[1]["task_name"] == "standup"


def test_entries_from_day_new_format_seconds_converted_to_minutes():
    day = {
        "date": "2026-07-21",
        "tasks": [{"name": "t", "kind": "work", "ticket": "ENG-1", "worklog_comment": None}],
        "segments": [
            {"task_name": "t", "start": "09:00:00", "end": "09:01:30", "seconds": 90, "note": "a"},
            {"task_name": "t", "start": "09:02:00", "end": "09:02:30", "seconds": 30, "note": "b"},
        ],
    }
    result = entries_from_day(day)
    assert result[0]["minutes"] == 1.5
    assert result[1]["minutes"] == 0.5


def test_entries_from_day_new_format_explicit_minutes_wins_over_seconds():
    day = {
        "tasks": [],
        "segments": [{"task_name": "x", "start": "10:00", "end": "10:07", "minutes": 7, "seconds": 999, "note": "n"}],
    }
    result = entries_from_day(day)
    assert result[0]["minutes"] == 7


def test_entries_from_day_new_format_missing_duration_is_zero():
    day = {
        "tasks": [],
        "segments": [{"task_name": "x", "start": "10:00", "end": "10:00", "note": "n"}],
    }
    result = entries_from_day(day)
    assert result[0]["minutes"] == 0


def test_entries_from_day_new_format_unknown_task_defaults_work():
    day = {
        "tasks": [],
        "segments": [{"task_name": "missing", "start": "10:00", "end": "10:10", "minutes": 10, "note": "orphan"}],
    }
    result = entries_from_day(day)
    assert len(result) == 1
    assert result[0]["kind"] == "work"
    assert result[0]["ticket"] is None
    assert result[0]["comment"] == "orphan"


def test_entries_from_day_new_format_missing_entries_key_returns_empty():
    day = {"date": "2026-07-01", "tasks": [], "segments": []}
    assert entries_from_day(day) == []


def test_load_days_handles_new_format(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "2026-07-01.json").write_text(json.dumps({
        "date": "2026-07-01",
        "tasks": [{"name": "t1", "kind": "work", "ticket": "ENG-1", "worklog_comment": None}],
        "segments": [{"task_name": "t1", "start": "09:00", "end": "09:30", "minutes": 30, "note": "impl"}],
    }))
    days = load_days(tmp_path)
    assert len(days) == 1
    assert days[0]["entries"][0]["ticket"] == "ENG-1"
    assert days[0]["entries"][0]["comment"] == "impl"


# --- load_days ---

def test_load_days_sorts_by_date(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "2026-06-30.json").write_text('{"date":"2026-06-30","entries":[]}')
    (year / "2026-06-29.json").write_text('{"date":"2026-06-29","entries":[]}')
    days = load_days(tmp_path)
    assert [d["date"] for d in days] == [date(2026, 6, 29), date(2026, 6, 30)]


def test_load_days_skips_invalid_json(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "bad.json").write_text("not json")
    (year / "2026-06-29.json").write_text('{"date":"2026-06-29","entries":[]}')
    days = load_days(tmp_path)
    assert len(days) == 1


def test_load_days_skips_workstreams_json(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "workstreams.json").write_text('{"some-workstream":{"label":"foo"}}')
    (year / "2026-06-29.json").write_text('{"date":"2026-06-29","entries":[]}')
    days = load_days(tmp_path)
    assert len(days) == 1


def test_load_days_empty_dir_returns_empty(tmp_path):
    assert load_days(tmp_path) == []


# --- load_sprints ---

def test_load_sprints_merges_subjects(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "sprints.json").write_text(json.dumps({
        "year": 2026,
        "sprints": [
            {"id": 1, "name": "S1", "start": "2026-06-08", "end": "2026-06-22",
             "state": "closed", "meeting_ticket": "ENG-100", "tickets": {"ENG-1": "Foo"}},
            {"id": 2, "name": "S2", "start": "2026-06-22", "end": "2026-07-06",
             "state": "active", "meeting_ticket": "ENG-200", "tickets": {"ENG-2": "Bar"}},
        ],
    }))
    result = load_sprints(tmp_path)
    assert result["has_sprint_data"] is True
    assert result["subjects"]["ENG-1"] == "Foo"
    assert result["subjects"]["ENG-2"] == "Bar"
    assert len(result["sprints"]) == 2


def test_load_sprints_merges_across_years(tmp_path):
    for year, ticket in [("2025", "ENG-10"), ("2026", "ENG-20")]:
        d = tmp_path / year
        d.mkdir()
        (d / "sprints.json").write_text(json.dumps({
            "year": int(year),
            "sprints": [
                {"id": ticket, "name": "S", "start": f"{year}-06-01", "end": f"{year}-06-15",
                 "state": "closed", "tickets": {ticket: "Summary"}},
            ],
        }))
    result = load_sprints(tmp_path)
    assert result["has_sprint_data"] is True
    assert "ENG-10" in result["subjects"]
    assert "ENG-20" in result["subjects"]
    assert len(result["sprints"]) == 2


def test_load_sprints_skips_synthetic_no_sprint(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "sprints.json").write_text(json.dumps({
        "year": 2026,
        "sprints": [
            {"id": 1, "name": "S1", "start": "2026-06-08", "end": "2026-06-22",
             "state": "closed", "tickets": {"ENG-1": "Foo"}},
            {"id": "no-sprint", "name": "no-sprint", "start": None, "end": None,
             "state": "synthetic", "tickets": {}},
        ],
    }))
    result = load_sprints(tmp_path)
    assert len(result["sprints"]) == 1
    assert result["sprints"][0]["id"] == 1


def test_load_sprints_no_dir_returns_empty(tmp_path):
    result = load_sprints(tmp_path)
    assert result["has_sprint_data"] is False
    assert result["subjects"] == {}
    assert result["sprints"] == []


# --- load_workstreams ---

def test_load_workstreams_maps_tickets_to_label(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "workstreams.json").write_text(json.dumps({"workstreams": [
        {"id": "eng-1", "label": "Bot DQ (ENG-1)", "tickets": ["ENG-1", "ENG-2"]},
        {"id": "eng-3", "label": "Sync bugs", "tickets": ["ENG-3"]},
    ]}))
    labels = load_workstreams(tmp_path)
    assert labels["ENG-1"] == "Bot DQ (ENG-1)"
    assert labels["ENG-2"] == "Bot DQ (ENG-1)"
    assert labels["ENG-3"] == "Sync bugs"


def test_load_workstreams_joins_distinct_labels_for_shared_ticket(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "workstreams.json").write_text(json.dumps({"workstreams": [
        {"id": "a", "label": "Alpha", "tickets": ["ENG-1"]},
        {"id": "b", "label": "Beta", "tickets": ["ENG-1"]},
        {"id": "c", "label": "Alpha", "tickets": ["ENG-1"]},
    ]}))
    labels = load_workstreams(tmp_path)
    # Distinct labels join; a repeated label is not appended twice.
    assert labels["ENG-1"] == "Alpha / Beta"


def test_load_workstreams_skips_empty_label_and_ticketless(tmp_path):
    year = tmp_path / "2026"
    year.mkdir()
    (year / "workstreams.json").write_text(json.dumps({"workstreams": [
        {"id": "a", "label": "", "tickets": ["ENG-1"]},
        {"id": "b", "label": "Beta", "tickets": []},
    ]}))
    assert load_workstreams(tmp_path) == {}


def test_load_workstreams_no_file_returns_empty(tmp_path):
    assert load_workstreams(tmp_path) == {}
