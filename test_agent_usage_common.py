import json
from datetime import datetime, timezone

from agent_usage_common import calc_cost_breakdown, write_events


def test_calc_cost_breakdown_returns_per_token_type_costs() -> None:
    pricing_db = {
        "gpt-test": {
            "input_cost_per_token": 0.01,
            "output_cost_per_token": 0.02,
            "cache_creation_input_token_cost": 0.03,
            "cache_read_input_token_cost": 0.004,
        }
    }
    event = {
        "model": "gpt-test",
        "input": 10,
        "output": 5,
        "cache_write": 2,
        "cache_read": 20,
    }

    assert calc_cost_breakdown(event, pricing_db) == {
        "input_cost": 0.1,
        "output_cost": 0.1,
        "cache_write_cost": 0.06,
        "cache_read_cost": 0.08,
    }


def test_write_events_persists_cost_breakdown_fields(tmp_path) -> None:
    pricing_db = {
        "claude-test": {
            "input_cost_per_token": 0.01,
            "output_cost_per_token": 0.02,
            "cache_creation_input_token_cost": 0.03,
            "cache_read_input_token_cost": 0.004,
        }
    }
    events = [
        {
            "ts": datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc),
            "project": "/tmp/demo",
            "model": "claude-test",
            "input": 10,
            "output": 5,
            "cache_write": 2,
            "cache_read": 20,
        }
    ]

    assert write_events(events, tmp_path, "claude", pricing_db) is True

    row = json.loads((tmp_path / "claude-2026-06-17.jsonl").read_text().strip())
    assert row["input_cost"] == 0.1
    assert row["output_cost"] == 0.1
    assert row["cache_write_cost"] == 0.06
    assert row["cache_read_cost"] == 0.08
    assert row["cost"] == 0.34
