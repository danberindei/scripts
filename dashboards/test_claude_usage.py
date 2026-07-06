import importlib.util
import json
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location("claude_usage", Path(__file__).with_name("claude-usage.py"))
assert _SPEC and _SPEC.loader
claude_usage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(claude_usage)


def test_load_events_deduplicates_repeated_assistant_records(tmp_path: Path) -> None:
    config_dir = tmp_path / ".claude"
    project_dir = config_dir / "projects" / "-tmp-project"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-07-06T09:00:00Z",
                        "cwd": "/tmp/project",
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-07-06T09:00:01Z",
                        "requestId": "req_1",
                        "message": {
                            "model": "claude-sonnet-4-6",
                            "usage": {
                                "input_tokens": 3,
                                "output_tokens": 5,
                                "cache_creation_input_tokens": 7,
                                "cache_read_input_tokens": 11,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-07-06T09:00:02Z",
                        "requestId": "req_1",
                        "message": {
                            "model": "claude-sonnet-4-6",
                            "usage": {
                                "input_tokens": 3,
                                "output_tokens": 5,
                                "cache_creation_input_tokens": 7,
                                "cache_read_input_tokens": 11,
                            },
                        },
                    }
                ),
            ]
        )
        + "\n"
    )

    events = claude_usage.load_events(config_dir, None, None, None)

    assert events == [
        {
            "ts": events[0]["ts"],
            "model": "claude-sonnet-4-6",
            "input": 3,
            "output": 5,
            "cache_write": 7,
            "cache_read": 11,
            "project": "/tmp/project",
        }
    ]
