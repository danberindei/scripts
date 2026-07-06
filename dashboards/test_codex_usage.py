import importlib.util
import json
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location("codex_usage", Path(__file__).with_name("codex-usage.py"))
assert _SPEC and _SPEC.loader
codex_usage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(codex_usage)


def test_load_session_events_counts_reasoning_output_tokens(tmp_path: Path) -> None:
    session_file = tmp_path / "rollout-2026-07-06T12-00-00-12345678-1234-1234-1234-123456789abc.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-06T09:00:00Z",
                        "type": "session_meta",
                        "payload": {"cwd": "/tmp/project"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-06T09:00:01Z",
                        "type": "turn_context",
                        "payload": {"cwd": "/tmp/project", "model": "gpt-5.4"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-06T09:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {"total_tokens": 100},
                                "last_token_usage": {
                                    "input_tokens": 30,
                                    "cached_input_tokens": 10,
                                    "output_tokens": 5,
                                    "reasoning_output_tokens": 7,
                                },
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-06T09:00:03Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {"total_tokens": 100},
                                "last_token_usage": {
                                    "input_tokens": 30,
                                    "cached_input_tokens": 10,
                                    "output_tokens": 5,
                                    "reasoning_output_tokens": 7,
                                },
                            },
                        },
                    }
                ),
            ]
        )
        + "\n"
    )

    events = codex_usage.load_session_events(session_file, None, None, None)

    assert events == [
        {
            "ts": events[0]["ts"],
            "project": "/tmp/project",
            "model": "gpt-5.4",
            "input": 20,
            "output": 12,
            "cache_write": 0,
            "cache_read": 10,
        }
    ]
