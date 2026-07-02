from pathlib import Path

from streamlit.testing.v1 import AppTest


def write_event(path: Path, ts: str, source: str, cost: float) -> None:
    # Mirror the extractor's output: write_events() always emits the per-token-type
    # cost columns, so fixtures must carry them too (the UI no longer backfills).
    path.write_text(
        "\n".join(
            [
                (
                    '{"ts":"%s","project_short":"demo","model":"%s-model",'
                    '"cost":%s,"input":10,"output":5,"cache_write":0,"cache_read":0,'
                    '"input_cost":%s,"output_cost":0,"cache_write_cost":0,"cache_read_cost":0}'
                )
                % (ts, source, cost, cost)
            ]
        )
        + "\n"
    )


def setup_data(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    data_dir = tmp_path / ".local" / "share" / "agent-usage"
    data_dir.mkdir(parents=True)
    write_event(data_dir / "claude-2026-06-17.jsonl", "2026-06-17T10:00:00Z", "claude", 1.0)
    write_event(data_dir / "codex-2026-06-17.jsonl", "2026-06-17T11:00:00Z", "codex", 2.0)
    return data_dir


def test_stale_source_query_param_does_not_hide_new_sources(tmp_path: Path, monkeypatch) -> None:
    setup_data(tmp_path, monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parent / "agents-dashboard.py"))
    app.query_params["source"] = ["claude"]

    app.run()

    assert app.sidebar.multiselect[0].value == ["claude", "codex"]


def test_deselected_providers_are_persisted_as_provider_off(tmp_path: Path, monkeypatch) -> None:
    setup_data(tmp_path, monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parent / "agents-dashboard.py"))

    app.run()
    app.sidebar.multiselect[0].set_value(["claude"])
    app.run()

    assert app.query_params["a_provider_off"] == ["codex"]
